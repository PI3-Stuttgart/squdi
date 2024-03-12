# -*- coding: utf-8 -*-
"""
This file contains the Qudi logic class that captures and processes fluorescence spectra.
Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.
Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

from qtpy import QtCore
from collections import OrderedDict
import numpy as np
import matplotlib.pyplot as plt
from time import sleep
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import Mutex
#from logic.generic_logic import GenericLogic
from qudi.core.module import Base
from qudi.core.module import LogicBase
from qtpy import QtCore


def delay(delay_msec = 100):
    dieTime = QtCore.QTime.currentTime().addMSecs(delay_msec)
    while (QtCore.QTime.currentTime() < dieTime):
        QtCore.QCoreApplication.processEvents(QtCore.QEventLoop.AllEvents, 100)
    
class PowerControllerLogic(LogicBase):

    """This logic module gathers data from the spectrometer.
    Demo config:
    spectrumlogic:
        module.Class: 'spectrum.SpectrumLogic'
        connect:
            spectrometer: 'myspectrometer'
            savelogic: 'savelogic'
            odmrlogic: 'odmrlogic' # optional
            fitlogic: 'fitlogic'
    """
    queryInterval = 1000
    # declare connectors
    powermeter = Connector(interface='PM100D', optional = True)
    motor_pi3 = Connector(interface='Motordriver')
    counter = Connector(interface='TimeTaggerCounter', optional=True)
    # spectrometer = Connector(interface='SpectrometerInterface')
    # spectrometer_fine = Connector(interface='SpectrometerInterface')
    # odmrlogic = Connector(interface='ODMRLogic', optional=True)
    # fitlogic = Connector(interface='FitLogic')
    # nicard = Connector(interface='NationalInstrumentsXSeries', optional=True)
    # ello_devices = Connector(interface='ThorlabsElloDevices', optional=True)
    # cwavelaser = Connector(interface='CwaveLaser')
    calibration_resolution = 180
    # declare status variables
    _saturation_data = StatusVar('saturation_data', np.empty((2, 0)))
    _saturation_background = StatusVar('saturation_background', np.empty((2, 0)))
    _background_correction = StatusVar('background_correction', default = False)
    _power_calibration = StatusVar('power_calibration', default = dict())
    _power_range = StatusVar('power_range', default = dict())
    _rotation_direction = StatusVar('rotation_direction', default = dict())
    fc = StatusVar('fits', None)
    plot_domain = (0, 10000)
    _current_positions = StatusVar("current_positions", default=dict())
    _current_motor = 0
    _motor_position = 0
    # Internal signals
    sig_data_updated = QtCore.Signal()
    sig_run_calibration = QtCore.Signal(int)
    sig_next_diff_loop = QtCore.Signal()
    sig_set_power = QtCore.Signal(float, int, bool)
    

    def __init__(self, **kwargs):
        """ Create SpectrometerLogic object with connectors.
          @param dict kwargs: optional parameters
        """
        super().__init__(**kwargs)
        
        self.stopRequested = False
        # locking for thread safety
        self.threadlock = Mutex()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._saturation_data_corrected = np.array([])
        self._calculate_corrected_spectrum()
        if self.powermeter() is not None:
            self._powermeter = self.powermeter()
        self._motor_pi3 = self.motor_pi3()
        self.channels = self._motor_pi3._active_motor_numbers
        self._rotation_direction.update({ch : 1 for ch in self.channels if ch not in self._rotation_direction.keys()})
        # self._counter = self.counter()
        self._current_positions.update({ch : 0 for ch in self.channels if ch not in self._current_positions.keys()})

        self._power_calibration.update({ch : np.array([]) for ch in self.channels if ch not in self._power_calibration.keys()})
        self.power_calibration = self._power_calibration
        
        
        self.sig_data_updated.emit()
        self.sig_run_calibration.connect(self.calibrate_power_wheel)
        self.sig_set_power.connect(self.set_power, QtCore.Qt.QueuedConnection)

    #     self.queryTimer = QtCore.QTimer()
    #     self.queryTimer.setInterval(self.queryInterval)
    #     self.queryTimer.setSingleShot(True)
    #     self.queryTimer.timeout.connect(self.loop_body)#, QtCore.Qt.QueuedConnection)     
    #     self.queryTimer.start(self.queryInterval)

    # def loop_body(self):
    #     qi = self.queryInterval
    #     self.queryTimer.start(qi)
    #     if self.powermeter() is not None:
    #         self.current_power_1 = self._powermeter.get_power() * self.calibration_factor_1
    #         self.current_power_2 = self._powermeter.get_power() * self.calibration_factor_2
        
    #         self.sig_data_updated.emit()
    

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        for i in range(5):
            QtCore.QCoreApplication.processEvents()
        
        if self.module_state() != 'idle' and self.module_state() != 'deactivated':
            pass
    
    # def constraints!


    @QtCore.Slot(int)
    def calibrate_power_wheel(self, motor=1):
        """ADD WARNING 
        insert powermeter into the path where it is conveneint to measure

        """
        self._motor_pi3.stopAllMovements()
        self._motor_pi3.zeroMotor(motor=motor)
        # delay(10000)
        delay(5000)
        print("Zeroed")
       
        powers = []
        angles = np.linspace(0, 360, self.calibration_resolution).astype(int)
        for angle in angles:
            self._motor_pi3.moveRelative(motor = motor, pos = angle  )
            delay(1000)
            pw = self._powermeter.get_power()
            pw = (self._powermeter.get_power() + pw)/2
            powers.append(pw)
            print(angle, pw)
            if self.stopRequested:
                print("ups")
                self._motor_pi3.stopAllMovements()
                self.stopRequested = False
                return
        delay(3000)
        self._motor_pi3.zeroMotor(motor=motor)
        calib = np.vstack((angles, np.array(powers))).T
        self.power_calibration[motor] = np.roll(calib, np.argmax(calib[:,1]) - len(calib))
        # self._power_range = (min(self._power_calibration[:,1]), max(self._power_calibration[:,1]))

        # self._motor_pi3.stopAllMovements()
    
    @property
    def power_calibration(self):
        return self._power_calibration
    
    @power_calibration.setter
    def power_calibration(self, calibration):
        self._power_calibration = calibration
        self._power_range.update({motor: (min(calibration[motor][:,1]), max(calibration[motor][:,1])) for motor in calibration.keys() if len(calibration[motor]) > 0})
        
        print("range", self._power_range, calibration)
        
    @QtCore.Slot(float, int, bool)
    def set_power(self, power, motor, calibrated):
        current_position = self._motor_pi3.getPosition(motor=motor)
        self._current_motor = motor
        self._current_positions.update({motor: current_position})
        if bool(calibrated) == True:
            if (power > self._power_range[motor][1]) or (power < self._power_range[motor][0]):
                print("Power out of calibrated range")
                return -1
            new_angle = self.power_calibration[motor][:, 0][np.argmin(np.abs(self.power_calibration[motor][:, 1] - power))]
            
            self._motor_pi3.moveRelative(motor = motor, pos = new_angle - current_position )
            delay(5000)
            return 
        else:
            new_angle = power
            self._motor_pi3.moveRelative(motor = motor, pos = new_angle - current_position )
            delay(3000)
       
    @property
    def motor_position(self):
        return self._motor_position
    
    @motor_position.setter
    def motor_position(self, step):
        self._motor_pi3.moveRelative(motor = self._current_motor, pos = step - self._current_positions[self._current_motor] )
        delay(3000)
        self._motor_position = step
        self._current_positions.update({self._current_motor: step})
       

    def run_saturation(self, motor = 0):
        """ Record a single saturation.
        """
        if self._counter is None:
            print("No counter")
            return
        self._motor_pi3.stopAllMovements()
        self._motor_pi3.zeroMotor(motor=motor)
        # delay(10000)
        #self._motor_pi3.moveToAbsolutePosition(motor = motor, pos = self._rotation_direction[motor])
        delay(5000)
        print("Zeroed")
       
        counts = []
        for angle in np.sort(self.power_calibration[motor][:, 0]):
            self._motor_pi3.moveRelative(motor = motor, pos = angle  )
            delay(2000)
            count = self._counter.get_counter()
            counts.append(count)
            if self.stopRequested:
                print("ups")
                self._motor_pi3.stopAllMovements()
                self.stopRequested = False
                return
        delay(2000)
        self._motor_pi3.zeroMotor(motor=motor)
        delay(3000)
        self._saturation_data = np.vstack(( self.power_calibration[motor][:, 1], np.array(counts))).T
        self.sig_data_updated.emit()

    def _calculate_corrected_spectrum(self):
        self._saturation_data_corrected = np.copy(self._saturation_data)
        if len(self._saturation_background) == 2 \
                and len(self._saturation_background[1, :]) == len(self._saturation_data[1, :]):
            self._saturation_data_corrected[1, :] -= self._saturation_background[1, :]
        else:
            self.log.warning('Background saturation has a different dimension then the acquired saturation. '
                             'Returning raw saturation. '
                             'Try acquiring a new background saturation.')

    @property
    def saturation_data(self):
        if self._background_correction:
            self._calculate_corrected_saturation()
            return self._saturation_data_corrected
        else:
            return self._saturation_data

    @property
    def background_correction(self):
        return self._background_correction

    @background_correction.setter
    def background_correction(self, correction=None):
        if correction is None or correction:
            self._background_correction = True
        else:
            self._background_correction = False
        self.sig_data_updated.emit()
