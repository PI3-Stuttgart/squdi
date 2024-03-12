# -*- coding: utf-8 -*-

"""
This file contains a gui to see wavemeter data during laser scanning.

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

import datetime
import wave
import numpy as np
import os
import pyqtgraph as pg
import pyqtgraph.exporters
import time
from qudi.core.connector import Connector
from qudi.util import units
from qudi.core.module import GuiBase
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.util.widgets.fitting import FitConfigurationDialog
from PySide2 import QtCore, QtWidgets, QtGui
from qudi.util.uic import loadUi
from qudi.gui.wavemeter.wavelogger_mw import WavemeterMainWindow


class WavemeterLogGui(GuiBase):
    """
    This GUI is for PLE measurements, reading out a wavemeter

    Todo: Example config for copy-paste:

    """
    # declare connectors
    wavemeterloggerlogic = Connector(interface='WavemeterLoggerLogic')

    sigStartCounter = QtCore.Signal()
    sigStopCounter = QtCore.Signal()
    sigFitChanged = QtCore.Signal(str)
    sigDoFit = QtCore.Signal(str, str)
    # sigUpdateRange = QtCore.Signal()

    def on_activate(self):
        """ Definition and initialisation of the GUI.
        """

        # setting up the window
        self._mw = WavemeterMainWindow()
        self.wavelog_logic = self.wavemeterloggerlogic()
        self._mw.actionStop_resume_scan.triggered.connect(self.stop_resume_clicked)
        # self._mw.actionSave_histogram.triggered.connect(self.save_clicked)
        self._mw.actionReset.triggered.connect(self._reset_scan)
        self._mw.actionStart_scan.triggered.connect(self.start_clicked)
        # self._mw.actionAuto_range.triggered.connect(self.set_auto_range)

        # defining the parameters to edit
        self._mw.binDoubleSpinBox.setValue(self.wavelog_logic._settings['bin_width'])
        self._mw.minDoubleSpinBox.setValue(self.wavelog_logic._settings['start_value'])
        self._mw.maxDoubleSpinBox.setValue(self.wavelog_logic._settings['stop_value'])
        self._mw.countlog_widget.selected_region.setRegion((self.wavelog_logic._settings['start_value'], self.wavelog_logic._settings['stop_value']))
        
        # self.sigUpdateRange.connect(self.update_range)
        
        self._mw.binDoubleSpinBox.editingFinished.connect(
            lambda : (self.wavelog_logic.sigUpdateSettings.emit({'bin_width': self._mw.binDoubleSpinBox.value()}),
            self.update_range())
            )
        self._mw.minDoubleSpinBox.editingFinished.connect(
            lambda : (self.wavelog_logic.sigUpdateSettings.emit({'start_value': self._mw.minDoubleSpinBox.value()}),
            self.update_range())
            )
        self._mw.maxDoubleSpinBox.editingFinished.connect(
            lambda : (self.wavelog_logic.sigUpdateSettings.emit({'stop_value': self._mw.maxDoubleSpinBox.value()}),
            self.update_range())
            )
        self._mw.sweepRangeDoubleSpinBox.editingFinished.connect(self.update_sweep_around_centre)
        self._mw.centreDoubleSpinBox.editingFinished.connect(self.update_sweep_around_centre)

        self._mw.countlog_widget.selected_region.sigRegionChanged.connect(self.sliders_values_are_changing)
        self._mw.countlog_widget.selected_region.sigRegionChangeFinished.connect(
            lambda: self.update_range()
        )
        self.update_range()
        # self.selected_region.setRegion(self._scan_data.scan_range[0])
        self._mw.show()
        self._mw.wavelength_pushButton.clicked.connect(
            lambda : QtWidgets.QApplication.clipboard().setText(self._mw.wavelengthLabel.text()) 
        )
        self._mw.freq_pushButton.clicked.connect(
            lambda : QtWidgets.QApplication.clipboard().setText(self._mw.frequencyLabel.text()) 
        )
        # self.wavelog_logic.sig_new_data_point.connect(self.add_data_point)

        self.wavelog_logic.sig_update_data.connect(self._update_data, QtCore.Qt.QueuedConnection)
        self.wavelog_logic.sig_toggle_log.connect(self.wavelog_logic.toggle_log)

        # Connect signals
        # self._mw.actionFit_settings.triggered.connect(self._fsd.show)
        # self._mw.do_fit_PushButton.clicked.connect(self.doFit)
        # self.sigDoFit.connect(self.wavelog_logic.do_fit)
        # self.sigFitChanged.connect(self.wavelog_logic.fc.set_current_fit)
        # self.wavelog_logic.sig_fit_updated.connect(self.updateFit)

    def on_deactivate(self):
        """ Deactivate the module properly.
        """
        self._mw.close()

    def show(self):
        """Make window visible and put it above all other windows. """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()



    def update_sweep_around_centre(self):
        sweep_range = self._mw.sweepRangeDoubleSpinBox.value()
        central_frequency = self._mw.centreDoubleSpinBox.value()
        self.update_range((central_frequency - sweep_range/2,central_frequency + sweep_range/2))

    @QtCore.Slot()
    def sliders_values_are_changing(self):
        x_range = self._mw.countlog_widget.selected_region.getRegion()
        self._mw.minDoubleSpinBox.setValue(x_range[0])
        self._mw.maxDoubleSpinBox.setValue(x_range[1])
        self._mw.sweepRangeDoubleSpinBox.setValue(abs(x_range[1] - x_range[0] ))
        self._mw.centreDoubleSpinBox.setValue((x_range[0] + x_range[1] )/ 2 )
    
    def _reset_scan(self):
        self.wavelog_logic.empty_buffer()
        self.wavelog_logic._acquisition_start_time = time.time()
        self._mw.countlog_widget._update_scan_data(None)
        self._mw.wavelength_widget._update_scan_data(None)
        

    @QtCore.Slot(object, object)
    def _update_data(self, wavelengths, count_data):
        """
        @param ScanData scan_data:
        
        """
        #We receive wavelengths in THz
        if len(wavelengths) > 1 and wavelengths.wavelength[-1] > 0:
            freq = wavelengths.wavelength[-1]
            wavelength = self.wavelog_logic.wavelength_to_freq(wavelengths.wavelength[-1])/1e12
            wavelength = np.round(wavelength, 6)
            freq = np.round(freq, 6)
            wavelengths.time = wavelengths.time - wavelengths.time[0]
            self._mw.wavelength_widget.set_data(wavelengths)
            if count_data is not None:
                self._mw.countlog_widget.set_data(count_data)
        else:
            wavelength = freq = 0
        self._mw.wavelengthLabel.setText(f"{wavelength} nm")
        self._mw.frequencyLabel.setText(f"{freq} THz")
   


    def stop_resume_clicked(self):
        """ Handling the Start button to stop and restart the counter.
        """
        # If running, then we stop the measurement and enable inputs again
        if self.wavelog_logic.module_state() != 'idle':
            self._mw.actionStop_resume_scan.setText('Resume')
            self.wavelog_logic.sig_toggle_log.emit(False)
            self._mw.actionStop_resume_scan.setEnabled(True)
            self._mw.actionStart_scan.setEnabled(True)
            self._mw.binDoubleSpinBox.setEnabled(True)
        # Otherwise, we start a measurement and disable some inputs.
        else:
            self._mw.actionStop_resume_scan.setText('Stop')
            self.wavelog_logic.sig_toggle_log.emit(True)
            self._mw.actionStart_scan.setEnabled(False)
            self._mw.binDoubleSpinBox.setEnabled(False)
        self._mw.countlog_widget.selected_region.show()

    def start_clicked(self):
        """ Handling resume of the scanning without resetting the data.
        """
        if self.wavelog_logic.module_state() == 'idle':
            # self._scatterplot.clear()
            # self.wavelog_logic.start_scanning()
            self.wavelog_logic.sig_toggle_log.emit(True)
            self._mw.countlog_widget.selected_region.hide()
            # Enable the stop button once a scan starts.
            self._mw.actionStop_resume_scan.setText('Stop')
            self._mw.actionStop_resume_scan.setEnabled(True)
            self._mw.actionStart_scan.setEnabled(False)
            self._mw.binDoubleSpinBox.setEnabled(False)
            # self.recalculate_histogram()
        else:
            self.log.error('Cannot scan, since a scan is already running.')

    def update_range(self, x_range=None):
        x_range = (self._mw.minDoubleSpinBox.value(), self._mw.maxDoubleSpinBox.value()) if x_range is None else x_range
        self._mw.countlog_widget.set_plot_range(x_range=x_range)
        self._mw.wavelength_widget.set_plot_range(x_range=x_range)
        self._mw.countlog_widget.selected_region.setRegion(x_range)
        self._mw.sweepRangeDoubleSpinBox.setValue(abs(x_range[1] - x_range[0] ))
        self._mw.centreDoubleSpinBox.setValue((x_range[0] + x_range[1] )/ 2 )
        self.wavelog_logic.sigUpdateSettings.emit({
                        'start_value': x_range[0],
                        'stop_value': x_range[1]
                        })
