# -*- coding: utf-8 -*-
"""
This module contains a GUI for operating the spectrum logic module.

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

import os
import pyqtgraph as pg
import numpy as np

from qudi.core.connector import Connector
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.core.module import GuiBase
from qudi.util.widgets.plotting import colorbar
from qudi.util.colordefs import ColorScaleInferno
from qudi.util.colordefs import QudiPalette as palette
from qudi.core.statusvariable import StatusVar
from qudi.util.units import ScaledFloat
from qudi.util.mutex import Mutex
from qudi.util.widgets.fitting import FitWidget, FitConfigurationDialog
from qtpy import QtCore
from qtpy import QtWidgets
from qtpy import uic


class PowerControllerWindow(QtWidgets.QMainWindow):

    def __init__(self):
        """ Create the laser scanner window.
        """
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_powercontroller.ui')

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)
        self.show()


class PowerControllerGui(GuiBase):
    """
    """
    
    # declare connectors
    powercontrollerlogic = Connector(interface='PowerControllerLogic')
    sigRecordSaturation = QtCore.Signal(bool)
    _use_calibration = False
    _slider_max = StatusVar('slider_max', 360)
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Definition and initialisation of the GUI.
        """

        self._powercontrollerlogic = self.powercontrollerlogic()

        # setting up the window
        self._mw = PowerControllerWindow()
        self._restore_window_geometry(self._mw)
        
        self._mw.centralwidget.hide()
        self._mw.setDockNestingEnabled(True)
        
        #Vlad updates


        
        self._mw.channel_comboBox.addItems(np.array(self._powercontrollerlogic.channels).astype(str))
        self._mw.channel_comboBox.currentIndexChanged.connect(self.channel_changed)
        self.sigRecordSaturation.connect(self._powercontrollerlogic.run_saturation)
        # self._powercontrollerlogic.sig_data_updated.connect(self.update_data)
        self._mw.actionSet_current_as_zero.triggered.connect(self.set_new_zero)
        self._mw.use_calibration_Button.toggled.connect(self.use_calibration)

        self._mw.calibrate_Button.clicked.connect(self.calibrate_power)
        # .setChecked(len(self._powercontrollerlogic.power_calibrationrationration) > 0)
        # self._mw.calibrate_power_1_Action.triggered.connect(self.calibrate_power)

        self._mw.powerHorizontalSlider.sliderReleased.connect(self.set_power_slider)
        # self._mw.p2HorizontalSlider
        self._mw.show()

        self._save_PNG = True

    def set_slider_max(self, slider_maximum):
        self._slider_max = slider_maximum
        self._mw.powerHorizontalSlider.setMaximum(slider_maximum)


    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # disconnect signals
        self._save_window_geometry(self._mw)
        self._mw.close()

    def use_calibration(self, is_toggled):
        self._use_calibration = is_toggled

    def show(self):
        """Make window visible and put it above all other windows.
        """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()

    def channel_changed(self):
        motor = int(self._mw.channel_comboBox.currentText())
        self._mw.powerHorizontalSlider.setValue(self._powercontrollerlogic._current_positions[motor])

    def set_power_slider(self):
        slider_val = float(self._mw.powerHorizontalSlider.value())
        motor = int(self._mw.channel_comboBox.currentText())
        if self._use_calibration and (len(self._powercontrollerlogic.power_calibration[motor]) > 0):
            powers_cal = self._powercontrollerlogic.power_calibration[motor][:, 1]
            vals = np.linspace(0, 360, powers_cal.shape[0])
            power = powers_cal[np.argmin(np.abs(vals - slider_val))]
          
            self._powercontrollerlogic.sig_set_power.emit(power, motor, True)
            if (power < 1e-6):
                display_power = np.round(power * 1e9, 2)
                self._mw.power_doubleSpinBox.setValue(display_power)
                self._mw.power_doubleSpinBox.setSuffix(" nW")
            elif (power < 1e-3):
                display_power = np.round(power * 1e6, 2)
                self._mw.power_doubleSpinBox.setValue(display_power)
                self._mw.power_doubleSpinBox.setSuffix(" muW")
            else:
                display_power = np.round(power * 1e3, 2)
                self._mw.power_doubleSpinBox.setValue(display_power)
                self._mw.power_doubleSpinBox.setSuffix(" mW")

        else:
            # vals = np.linspace(0, 360, powers_cal.shape[0])
            # power = vals[np.argmin(np.abs(vals - slider_val))]
            self._mw.power_doubleSpinBox.setValue(slider_val)
            self._mw.power_doubleSpinBox.setSuffix(" deg")
            self._powercontrollerlogic.sig_set_power.emit(slider_val, motor, False)

    def calibrate_power(self, is_checked):

        # self._mw.calibrate_Button.setChecked(True)
        self._powercontrollerlogic.stopRequested = False
        self._powercontrollerlogic.sig_run_calibration.emit(int(self._mw.channel_comboBox.currentText()))

        # self._powercontrollerlogic.stopRequested = True
    
    def set_new_zero(self):
        slider_val = float(self._mw.powerHorizontalSlider.value())
        motor = int(self._mw.channel_comboBox.currentText())
        self._powercontrollerlogic._zero_index.update({motor
            : slider_val
        })
        self._mw.powerHorizontalSlider.setValue(0)

    def record_saturation(self):
        """ Handle resume of the scanning without resetting the data.
        """
        #FIX TIMING

        self.sigRecordSaturation.emit(False)
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.updateProgress)
        self.update_time = 500
        self.timer.start(self.update_time)
    
    def updateProgress(self):
        # int_time = self._mw.integration_time_doubleSpinBox.value()
        int_time = 1 #THIS IS WHAT?? fix

        self.time_passed += self.update_time/1000
        if self.time_passed >= int_time:
            self.timer.stop()
            self._mw.progressBar.setValue(int_time)
            return
        self._mw.progressBar.setValue(self.time_passed)

   
    # def save_spectrum_data(self):
    #     self._powercontrollerlogic.save_saturation_data()

    def correct_background(self):
        self._powercontrollerlogic.background_correction = self._mw.correct_background_Action.isChecked()

    def acquire_background(self):
        self.sigRecordSaturation.emit(True)
        # self._spectrum_logic.get_single_spectrum(background=True)

    # def save_background_data(self):
    #     self._powercontrollerlogic.save_saturation_data(background=True)

    
    def restore_default_view(self):
        """ Restore the arrangement of DockWidgets to the default
        """
      

        # Set the toolbar to its initial top area
        self._mw.addToolBar(QtCore.Qt.TopToolBarArea,
                            self._mw.measure_ToolBar)
        self._mw.addToolBar(QtCore.Qt.TopToolBarArea,
                            self._mw.background_ToolBar)

        return 0