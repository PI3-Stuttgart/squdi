# -*- coding: utf-8 -*-

"""
This module contains a POI Manager core class which gives capability to mark
points of interest, re-optimise their position, and keep track of sample drift
over time.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

from qtpy import QtCore
import ctypes   # is a foreign function library for Python. It provides C
                # compatible data types, and allows calling functions in DLLs
                # or shared libraries. It can be used to wrap these libraries
                # in pure Python.
from qudi.hardware.wavemeter import high_finesse_api
from qudi.interface.wavemeter_interface import WavemeterInterface
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import Mutex
import time
import numpy as np

class HardwarePull(QtCore.QObject):
    """ Helper class for running the hardware communication in a separate thread. """

    # signal to deliver the wavelength to the parent class
    sig_wavelength = QtCore.Signal(dict)

    def __init__(self, parentclass):
        super().__init__()

        # remember the reference to the parent class to access functions ad settings
        self._parentclass = parentclass


    def handle_timer(self, state_change):
        """ Threaded method that can be called by a signal from outside to start the timer.

        @param bool state: (True) starts timer, (False) stops it.
        """

        if state_change:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._measure_thread)
            self.timer.start(self._parentclass._measurement_timing)
        else:
            if hasattr(self, 'timer'):
                self.timer.stop()

    def _measure_thread(self):
        """ The threaded method querying the data from the wavemeter.
        """

        # update as long as the state is busy
        # if self._parentclass.module_state() == 'running':
        # get the current wavelength from the wavemeter
        wavelengths = {ch: self._parentclass._wavemeter.get_wavelength(channel=ch) for ch in self._parentclass._active_channels}
      
        # send the data to the parent via a signal
        self.sig_wavelength.emit(wavelengths)



class HighFinesseWavemeter(WavemeterInterface):
    """ Hardware class to controls a High Finesse Wavemeter.

    Example config for copy-paste:

    high_finesse_wavemeter:
        module.Class: 'high_finesse_wavemeter.HighFinesseWavemeter'
            options:
                measurement_timing: 10.0 # in seconds
                active_channels: [0, 1]

    """

    # config options
    _measurement_timing = ConfigOption('measurement_timing', default=0.2)
    _active_channels = ConfigOption('active_channels', default=[0])
    _selected_channels = ConfigOption('selected_channels', default=[2,4])
    _default_channel = ConfigOption('default_channel', default=0)
    _buffer_size = 3000
    # signals
    sig_handle_timer = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        
        super().__init__(*args, **kwargs)
        # self.log.warning("This module has not been tested on the new qudi core."
        #                  "Use with caution and contribute bug fixed back, please.")
        #locking for thread safety
        self.threadlock = Mutex()

        # the current wavelength read by the wavemeter in nm (vac)
        self._current_wavelengths = {ch: 0 for ch in self._active_channels}
        
        self._wavelength_buffer = np.array([])
      


    def on_activate(self):
        

        self._wavemeter = high_finesse_api.WLM()

        # create an indepentent thread for the hardware communication
        self.hardware_thread = QtCore.QThread()

        # create an object for the hardware communication and let it live on the new thread
        self._hardware_pull = HardwarePull(self)
        self._hardware_pull.moveToThread(self.hardware_thread)

        # connect the signals in and out of the threaded object
        self.sig_handle_timer.connect(self._hardware_pull.handle_timer)
        self._hardware_pull.sig_wavelength.connect(self.handle_wavelength)

        # start the event loop for the hardware
        self.hardware_thread.start()


    def on_deactivate(self):
        if self.module_state() != 'idle' and self.module_state() != 'deactivated':
            self.stop_acquisition()
        self.hardware_thread.quit()
        self.sig_handle_timer.disconnect()
        self._hardware_pull.sig_wavelength.disconnect()

        try:
            # clean up by removing reference to the ctypes library object
            del self._wavemeterdll
            return 0
        except:
            self.log.error('Could not unload the wlmData.dll of the '
                    'wavemeter.')


    #############################################
    # Methods of the main class
    #############################################

    def handle_wavelength(self, wavelengths):
        """ Function to save the wavelength, when it comes in with a signal.
        """
        elapsed_time = time.time() - self.start_time
        row = [wavelengths[ch] for ch in self._selected_channels]
        row.append(elapsed_time)
        if len(self._wavelength_buffer) < 1:
            
            self._wavelength_buffer = np.array(
                row
                )
        elif len(self._wavelength_buffer) > 2:
            if (np.abs(np.round(wavelengths[self._default_channel], 5) - np.round(self._wavelength_buffer[-1][0], 5))) > 0:
                self._wavelength_buffer = np.vstack((self._wavelength_buffer, row))
            else:
                pass
        else:
            self._wavelength_buffer = np.vstack((self._wavelength_buffer, row))

        self._wavelength_buffer = self._wavelength_buffer[-self._buffer_size:]
        self._current_wavelengths = wavelengths
    def empty_buffer(self):
        self._wavelength_buffer = np.array([])

    def start_acquisition(self):
        """ Method to start the wavemeter software.

        @return int: error code (0:OK, -1:error)

        Also the actual threaded method for getting the current wavemeter reading is started.
        """

        # first check its status
        if self.module_state() == 'running':
            self.log.error('Wavemeter busy')
            return -1


        # self.module_state.run()
        self._wavemeter.start_measurements()
        self.start_time = time.time()
        # start the measuring thread
        self.sig_handle_timer.emit(True)

        return 0

    def stop_acquisition(self):
        """ Stops the Wavemeter from measuring and kills the thread that queries the data.

        @return int: error code (0:OK, -1:error)
        """
        # check status just for a sanity check
        if self.module_state() == 'idle':
            self.log.warning('Wavemeter was already stopped, stopping it '
                    'anyway!')
        else:
            # stop the measurement thread
            self.sig_handle_timer.emit(True)
            # set status to idle again
            self.module_state.stop()

        # Stop the actual wavemeter measurement
        self._wavemeter.stop_measurements()

        return 0

    def get_wavelength_buffer(self):
      
        if len(self._wavelength_buffer) > 0:
            return np.array(self._wavelength_buffer)
        else:
            return np.array([self.get_current_wavelength(), 0])

    def get_current_wavelengths(self):
        """ This method returns the current wavelength.

        """

        return self._current_wavelengths
    def get_selected_channels(self):
        return self._selected_channels
    
    def get_current_wavelength(self):
    
        return self._current_wavelengths[self._default_channel]
        

    def get_timing(self):
        """ Get the timing of the internal measurement thread.

        @return float: clock length in second
        """
        return self._measurement_timing

    def set_timing(self, timing):
        """ Set the timing of the internal measurement thread.

        @param float timing: clock length in second

        @return int: error code (0:OK, -1:error)
        """
        self._measurement_timing=float(timing)
        return 0

