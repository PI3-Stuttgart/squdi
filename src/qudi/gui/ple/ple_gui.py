# -*- coding: utf-8 -*-
"""
This file contains the Qudi GUI module to operate the voltage (laser) scanner.
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

#TODO carefull disconnection
from email.policy import default
import os
import numpy as np
import copy as cp
from typing import Union, Tuple
from functools import partial
from PySide2 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

import qudi.util.uic as uic
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption
from qudi.interface.scanning_probe_interface import ScanData
from qudi.core.module import GuiBase
from qudi.logic.ple.optimize_logic import OptimizerScanSequence
from qudi.util.widgets.fitting import FitConfigurationDialog
from .fit_dockwidget import PleFitDockWidget
from qudi.gui.ple.ple_ui_window import PLEScanMainWindow
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox, ScienSpinBox
from qudi.gui.ple.optimizer_setting_dialog import OptimizerSettingDialog
from qudi.gui.ple.ple_settings_dialog import PleSettingDialog
from qudi.gui.ple.optimizer_dockwidget import OptimizerDockWidget


class SaveDialog(QtWidgets.QDialog):
    """ Dialog to provide feedback and block GUI while saving """
    def __init__(self, parent, title="Please wait", text="Saving..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)

        # Dialog layout
        self.text = QtWidgets.QLabel("<font size='16'>" + text + "</font>")
        self.hbox = QtWidgets.QHBoxLayout()
        self.hbox.addSpacerItem(QtWidgets.QSpacerItem(50, 0))
        self.hbox.addWidget(self.text)
        self.hbox.addSpacerItem(QtWidgets.QSpacerItem(50, 0))
        self.setLayout(self.hbox)

class PLEScanGui(GuiBase):
    """
    """
    
    # declare connectors
    _scanning_logic = Connector(name='scannerlogic', interface='PLEScannerLogic')
    _optimize_logic = Connector(name='optimizerlogic', interface='PLEOptimizeScannerLogic')
    _data_logic = Connector(name='data_logic', interface='PleDataLogic')
    _microwave_logic = Connector(name='microwave', interface= 'OdmrLogic', optional=True)
    _repump_logic = Connector(name='repump', interface= 'RepumpInterfuseLogic', optional=True)
    _controller_logic = Connector(name='controller', interface= 'ControllerInterfuseLogic', optional=True)

    # status vars
    _window_state = StatusVar(name='window_state', default=None)
    _window_geometry = StatusVar(name='window_geometry', default=None)
    _save_display_view = StatusVar(name='save_display_view', default=None)
    _save_folderpath = StatusVar('save_folderpath', default=None)
    _optimizer_plot_dims = ConfigOption(name='optimizer_plot_dimensions', default=[1])
    _optimizer_state = {'is_running': False}
    _accumulated_data = None
    _optimizer_id = 0
    # signals
    sigScannerTargetChanged = QtCore.Signal(dict)#, object)
    sigScanSettingsChanged = QtCore.Signal(dict)
    # sigToggleScan = QtCore.Signal(bool, tuple, object)
    sigOptimizerSettingsChanged = QtCore.Signal(dict)
    sigToggleOptimize = QtCore.Signal(bool)
    sigSaveScan = QtCore.Signal(object, object, object, object, object, object, object)
    sigSaveFinished = QtCore.Signal()
    sigShowSaveDialog = QtCore.Signal(bool)

    _n_save_tasks = 0
    scan_data = None
    sigDoFit = QtCore.Signal(str, str, bool)
    _fit_averaged = False
    fit_result = None

    

    def on_activate(self):
        """ 
        """
        self._scanning_logic = self._scanning_logic()
        self._optimizer_id = self._optimize_logic().module_uuid
        self._scanning_logic._scan_id = self.module_uuid
        self.scan_axis = self._scanning_logic._scan_axis
        self.axis = self._scanning_logic.scanner_axes[self.scan_axis]
        channel = self._scanning_logic.scanner_channels[self._scanning_logic._channel]


        self._mw = PLEScanMainWindow(self.axis, channel)
        
        self._save_dialog = SaveDialog(self._mw)
        # self._mw.show()
        self.scan_state_updated(self._scanning_logic.module_state() != 'idle')
        # Connect signals
        self.sigScannerTargetChanged.connect(
            self._scanning_logic.set_target_position, QtCore.Qt.QueuedConnection
        )
        self._scanning_logic.sigScannerTargetChanged.connect(
            self.scanner_target_updated, QtCore.Qt.QueuedConnection
        )
        self.sigScanSettingsChanged.connect(
            self._scanning_logic.set_scan_settings, QtCore.Qt.QueuedConnection
        )
        self._scanning_logic.sigUpdateAccumulated.connect(self._update_accumulated_scan, QtCore.Qt.QueuedConnection)
        self._scanning_logic.sigToggleScan.connect(self._scanning_logic.toggle_scan, QtCore.Qt.QueuedConnection)
        self._mw.actionToggle_scan.triggered.connect(self.toggle_scan, QtCore.Qt.QueuedConnection)
        self._scanning_logic.sigRepeatScan.connect(self.scan_repeated, QtCore.Qt.QueuedConnection)
        
        self._scanning_logic.sigScanStateChanged.connect(
            self.scan_state_updated, QtCore.Qt.QueuedConnection
        )
        #self._scanning_logic.sigScannerTargetChanged.connect(
        #    self.scanner_target_updated, QtCore.Qt.QueuedConnection
        #)
        self._scanning_logic.sigScanSettingsChanged.connect(
            self.scanner_settings_updated, QtCore.Qt.QueuedConnection
        )
        self.sigToggleOptimize.connect(
            self._optimize_logic().toggle_optimize, QtCore.Qt.QueuedConnection
        )
        self.sigOptimizerSettingsChanged.connect(
            self._optimize_logic().set_optimize_settings, QtCore.Qt.QueuedConnection)

        self._mw.action_optimize_position.triggered[bool].connect(self.toggle_optimize, QtCore.Qt.QueuedConnection)
        #self._mw.ple_widget.target_point.sigPositionChanged.connect(self.sliders_values_are_changing)
        # self._mw.ple_widget.selected_region.sigRegionChanged.connect(self.sliders_values_are_changing)
        # self._mw.ple_averaged_widget.selected_region.sigRegionChanged.connect(self.sliders_values_are_changing_averaged_data)
        self._optimize_logic().sigOptimizeStateChanged.connect(
            self.optimize_state_updated, QtCore.Qt.QueuedConnection
        )
        self._mw.ple_widget.target_point.sigPositionChanged.connect(self.sliders_values_are_changing) #set_scanner_target_position
        self._mw.ple_widget.target_point.sigPositionChangeFinished.connect(self.set_scanner_target_position)
        self._mw.ple_widget.selected_region.sigRegionChangeFinished.connect(self.region_value_changed) 
        

        self._mw.ple_averaged_widget.target_point.sigPositionChanged.connect(self.sliders_values_are_changing_averaged_data)
        self._mw.ple_averaged_widget.selected_region.sigRegionChangeFinished.connect(self.region_value_changed_averaged_data) 
        self._mw.ple_averaged_widget.target_point.sigPositionChangeFinished.connect(self.set_scanner_target_position)
        
        
        # x_range = settings['range'][self.scan_axis]
        # dec_places = decimal_places = np.abs(int(f'{x_range[0]:e}'.split('e')[-1])) + 3
        self._mw.startDoubleSpinBox.setSuffix(self.axis.unit)
        self._mw.stopDoubleSpinBox.setSuffix(self.axis.unit)
        self._mw.constDoubleSpinBox.setSuffix(self.axis.unit)

        self._mw.channel_comboBox.addItems(self._scanning_logic.scanner_channels.keys())
        self._mw.channel_comboBox.currentTextChanged.connect(self._set_channel)
        self._mw.channel_comboBox.setCurrentText(self._scanning_logic._channel)
        #create microwave control window if microwave is set
        if self._microwave_logic() is not None:
            self._microwave_logic = self._microwave_logic()
            self._mw.add_dock_widget('Microwave')
            self._init_microwave()
        self._repump_logic = self._repump_logic()
        if self._repump_logic is not None:
            
            self._scanning_logic.sigRepeatScan.connect(self. _repump_logic.repump_before_scan, 
                                                         QtCore.Qt.QueuedConnection)
            
            self._mw.add_dock_widget('Pulsed')
            self._mw.Pulsed_widget.sig_pulser_params_updated.connect(self._repump_logic.pulser_updated, QtCore.Qt.QueuedConnection)
            self._repump_logic.sigGuiParamsUpdated.connect(self._mw.Pulsed_widget.update_gui, QtCore.Qt.QueuedConnection)
            self._mw.Pulsed_widget.sig_prescan_repump.connect(self.setup_repump_before_scan)
            self._repump_logic.sigGuiParamsUpdated.emit(self._repump_logic.parameters)

        self._controller_logic = self._controller_logic()
        if self._controller_logic is not None:
            
            
            self._mw.add_dock_widget('Controller')
            self._mw.Controller_widget.sig_controller_params_updated.connect(self._controller_logic.params_updated, QtCore.Qt.QueuedConnection)
            self._controller_logic.sigGuiParamsUpdated.connect(self._mw.Controller_widget.update_gui, QtCore.Qt.QueuedConnection)
            self._controller_logic.sigGuiParamsUpdated.emit(self._controller_logic.parameters)
        
        #PLE tracking
        self._mw.actionTrackPLE.triggered.connect(
            lambda: self._optimize_logic().toggle_ple_tracking(self._mw.actionTrackPLE.isChecked()), 
            QtCore.Qt.QueuedConnection)
        self.scanner_target_updated()
        # self.scan_state_updated(
        #     self._scanning_logic.module_state() != 'idle'
        #     )
        # self.scan_state_updated(
        #     self._scanning_logic.module_state() != 'idle', 
        #     caller_id=self._optimizer_id
        #                         )

        self.restore_scanner_settings()
        self._init_ui_connectors()
        self._init_static_widgets()
        self._init_optimizer_settings()
        self._init_scanner_settings()
        self.setup_fit_widget()
        self.__connect_fit_control_signals()

        self.sigSaveScan.connect(self._data_logic().save_scan, QtCore.Qt.QueuedConnection)
        self.sigSaveFinished.connect(self._save_dialog.hide, QtCore.Qt.QueuedConnection)
        self._data_logic().sigSaveStateChanged.connect(self._track_save_status)
        


        self.sigShowSaveDialog.connect(lambda x: self._save_dialog.show() if x else self._save_dialog.hide(),
                                       QtCore.Qt.DirectConnection)
        self.save_path_widget.currPathLabel.setText('Default' if self._save_folderpath is None else self._save_folderpath)
        self.save_path_widget.DailyPathCheckBox.clicked.connect(lambda: self.save_path_widget.newPathCheckBox.setEnabled(not self.save_path_widget.DailyPathCheckBox.isChecked()))
        
        if self._save_folderpath is None:
            self.save_path_widget.DailyPathCheckBox.setChecked(True)
            self.save_path_widget.DailyPathCheckBox.clicked.emit()


        self._mw.action_Save.triggered.connect(lambda x: self.save_scan_data(scan_axes=None))
        self._mw.actionSave.triggered.connect(lambda x: self.save_scan_data(scan_axes=None))
        self._restore_window_geometry(self._mw)
        # self.load_view()

    def on_deactivate(self):
        """ Reverse steps of activation
        @return int: error code (0:OK, -1:error)
        """
        # Connect signals
        self.sigScannerTargetChanged.disconnect()
        self._scanning_logic.sigScannerTargetChanged.disconnect(self.scanner_target_updated)

        self.sigScanSettingsChanged.disconnect()
        self._scanning_logic.sigUpdateAccumulated.disconnect()
        self._scanning_logic.sigToggleScan.disconnect()
        self._mw.actionToggle_scan.triggered.disconnect()
        self._scanning_logic.sigRepeatScan.disconnect()
        self._scanning_logic.sigScanStateChanged.disconnect(self.scan_state_updated)
        self._scanning_logic.sigScanSettingsChanged.disconnect(self.scanner_settings_updated)
        
        self.sigToggleOptimize.disconnect()
        self.sigOptimizerSettingsChanged.disconnect()
        self._mw.action_optimize_position.triggered[bool].disconnect()
        self._optimize_logic().sigOptimizeStateChanged.disconnect()
       
        if self._microwave_logic() is not None:
            self._microwave_logic().sigCwParametersUpdated.disconnect()
            self._microwave_logic().sigCwStateUpdated.disconnect()
        

        # if self._repump_logic is not None:
        #     self._scanning_logic.sigRepeatScan.disconnect()
        #     self._repump_logic().sigGuiParamsUpdated.disconnect()

        if self._controller_logic is not None:
            self._controller_logic.sigGuiParamsUpdated.disconnect()



        self.sigSaveScan.disconnect()
        self.sigSaveFinished.disconnect()
        self._data_logic().sigSaveStateChanged.disconnect()
        
        self.sigShowSaveDialog.disconnect()

        self._mw.action_Save.triggered.disconnect()
        self._mw.actionSave.triggered.disconnect()

        self._save_window_geometry(self._mw)
        self._mw.close()

        return 0
    
    @QtCore.Slot(bool)
    def setup_repump_before_scan(self, do_repump):
        #here we can measure the start frequency!
        self._repump_logic.do_prescan_repump = do_repump
        
    def _init_optimizer_settings(self):
        """ Configuration and initialisation of the optimizer settings dialog.
        """
        # Create the Settings window
        self._osd = OptimizerSettingDialog(tuple(self._scanning_logic.scanner_axes.values()),
                                           tuple(self._scanning_logic.scanner_channels.values()),
                                           self._optimizer_plot_dims)

        # Connect MainWindow actions
        self._mw.action_optimizer_settings.triggered.connect(lambda x: self._osd.exec_())

        # Connect the action of the settings window with the code:
        self._osd.accepted.connect(self.change_optimizer_settings)
        self._osd.rejected.connect(self.update_optimizer_settings)
        self._osd.button_box.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.change_optimizer_settings)
        # pull in data
        self.update_optimizer_settings()
        return

    def _init_scanner_settings(self):
        """
        """
        # Create the Settings dialog
        self._psd = PleSettingDialog(tuple(self._scanning_logic.scanner_axes.values()),
                                         self._scanning_logic.scanner_constraints)

        # Connect MainWindow actions
        self._mw.action_ple_settings.triggered.connect(lambda x: self._psd.exec_())

        # Connect the action of the settings dialog with the GUI module:
        self._psd.accepted.connect(self.apply_scanner_settings)
        self._psd.rejected.connect(self.restore_scanner_settings)
        self._psd.button_box.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply_scanner_settings
        )
    
    @QtCore.Slot()
    def apply_scanner_settings(self):
        """ ToDo: Document
        """
        # ToDo: Implement backwards scanning functionality
        forward_freq = {ax: freq[0] for ax, freq in self._psd.settings_widget.frequency.items()}
        self.sigScanSettingsChanged.emit({'frequency': forward_freq})

        shift = {ax: shift for ax, shift in self._psd.settings_widget.shift.items()}
        self.sigScanSettingsChanged.emit({'shift': shift})

    @QtCore.Slot()
    def change_optimizer_settings(self):
        self.sigOptimizerSettingsChanged.emit(self._osd.settings)
        self.optimizer_dockwidget.scan_sequence = self._osd.settings['scan_sequence']
        #TODO!!!
        # self.update_crosshair_sizes()

    @QtCore.Slot(dict)
    def update_optimizer_settings(self, settings=None):
        if not isinstance(settings, dict):
            settings = self._optimize_logic().optimize_settings

        # Update optimizer settings QDialog
        self._osd.change_settings(settings)

        # Adjust optimizer settings
        if 'scan_sequence' in settings:
            new_settings = self._optimize_logic().check_sanity_optimizer_settings(settings)
            if settings['scan_sequence'] != new_settings['scan_sequence']:
                new_seq = new_settings['scan_sequence']
                self.log.warning(f"Tried to update gui with illegal optimizer sequence= {settings['scan_sequence']}."
                                 f" Defaulted optimizer to= {new_seq}")
                self._optimize_logic().scan_sequence = new_seq
            settings = new_settings

            axes_constr = self._scanning_logic.scanner_axes
            self.optimizer_dockwidget.scan_sequence = settings['scan_sequence']

            for seq_step in settings['scan_sequence']:
                if len(seq_step) == 1:
                    axis = seq_step[0]
                    self.optimizer_dockwidget.set_plot_label(axis='bottom',
                                                             axs=seq_step,
                                                             text=axis,
                                                             units=axes_constr[axis].unit)
                    self.optimizer_dockwidget.set_plot_data(axs=seq_step)
                    self.optimizer_dockwidget.set_fit_data(axs=seq_step)
                elif len(seq_step) == 2:
                    x_axis, y_axis = seq_step
                    self.optimizer_dockwidget.set_image_label(axis='bottom',
                                                              axs=seq_step,
                                                              text=x_axis,
                                                              units=axes_constr[x_axis].unit)
                    self.optimizer_dockwidget.set_image_label(axis='left',
                                                              axs=seq_step,
                                                              text=y_axis,
                                                              units=axes_constr[y_axis].unit)
                    self.optimizer_dockwidget.set_image(None, axs=seq_step,
                                                        extent=((-0.5, 0.5), (-0.5, 0.5)))

                # Adjust 1D plot y-axis label
                if 'data_channel' in settings and len(seq_step)==1:
                    channel_constr = self._scanning_logic.scanner_channels
                    channel = settings['data_channel']
                    self.optimizer_dockwidget.set_plot_label(axs=seq_step, axis='left',
                                                             text=channel,
                                                             units=channel_constr[channel].unit)

                # Adjust crosshair size according to optimizer range
                # self.update_crosshair_sizes()

    def _init_microwave(self):
        
        mw_constraints = self._microwave_logic.microwave_constraints
        self._mw.Microwave_widget.set_constraints(mw_constraints)
        self._mw.Microwave_widget.sig_microwave_params_updated.connect(
            self._microwave_logic.set_cw_parameters
            )
        self._mw.Microwave_widget.sig_microwave_enabled.connect(
            self._microwave_logic.toggle_cw_output
        )
        self._microwave_logic.sigCwParametersUpdated.connect(
            self._mw.Microwave_widget.update_params
        )
        self._microwave_logic.sigCwStateUpdated.connect(
            self._mw.Microwave_widget.enable_microwave
        )
        self._microwave_logic.sigCwParametersUpdated.emit(self._microwave_logic.cw_parameters)
    
    def _init_static_widgets(self):
        self.optimizer_dockwidget = OptimizerDockWidget(axes=self._scanning_logic.scanner_axes,
                                                        plot_dims=self._optimizer_plot_dims,
                                                        sequence=self._optimize_logic().scan_sequence)
        self.optimizer_dockwidget.setAllowedAreas(QtCore.Qt.TopDockWidgetArea)
        self._mw.addDockWidget(QtCore.Qt.TopDockWidgetArea, self.optimizer_dockwidget)
        # self.optimizer_dockwidget.visibilityChanged.connect(
        #     self._mw.action_view_optimizer.setChecked)
        # self._mw.action_view_optimizer.triggered[bool].connect(
        #     self.optimizer_dockwidget.setVisible)

        # self._mw.util_toolBar.visibilityChanged.connect(
        #     self._mw.action_view_toolbar.setChecked)
        # self._mw.action_view_toolbar.triggered[bool].connect(self._mw.util_toolBar.setVisible)

        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'save_path_widget.ui')
        self.save_path_widget = QtWidgets.QDockWidget()
        uic.loadUi(ui_file, self.save_path_widget)
        
        self._mw.addDockWidget(QtCore.Qt.TopDockWidgetArea, self.save_path_widget)

    def _track_save_status(self, in_progress):
        if in_progress:
            self._n_save_tasks += 1
        else:
            self._n_save_tasks -= 1

        if self._n_save_tasks == 0:
            self.sigSaveFinished.emit()


    def setup_fit_widget(self):
        self._fit_dockwidget = PleFitDockWidget(parent=self._mw, fit_container=self._scanning_logic._fit_container)
        self._fit_config_dialog = FitConfigurationDialog(parent=self._mw,
                                                         fit_config_model=self._scanning_logic._fit_config_model)
        self._mw.action_show_fit_settings.triggered.connect(self._fit_config_dialog.show)
        self._mw.addDockWidget(QtCore.Qt.TopDockWidgetArea, self._fit_dockwidget)
        self.sigDoFit.connect(self._scanning_logic.do_fit, QtCore.Qt.QueuedConnection)
        self._scanning_logic.sigFitUpdated.connect(self._update_fit_result, QtCore.Qt.QueuedConnection)

    def __connect_fit_control_signals(self):
        self._fit_dockwidget.fit_widget.sigDoFit.connect(self._fit_clicked)
        
    def __disconnect_fit_control_signals(self):
        self._fit_dockwidget.fit_widget.sigDoFit.disconnect()

    def _set_channel(self, value):
        self._scanning_logic._channel = value
        
        ch = self._scanning_logic.scanner_channels[value]
        self._mw.ple_widget.channel = ch
        self._mw.ple_retrace_widget.channel = ch
        self._mw.ple_averaged_widget.channel = ch
        self._mw.matrix_widget.channel = ch
        # self.optimizer_dockwidget.

    def _fit_clicked(self, fit_config):
        channel = self._scanning_logic.scanner_channels[self._scanning_logic._channel]#self._scan_control_dockwidget.selected_channel
        # range_index = #self._scan_control_dockwidget.selected_range
        self.sigDoFit.emit(fit_config, channel, self._fit_averaged)

    def _update_fit_result(self, fit_cfg_result, channel):
        current_channel = channel#self._scan_control_dockwidget.selected_channel
        # current_range_index = self._scan_control_dockwidget.selected_range
        self.fit_result = fit_cfg_result
        if current_channel == channel:# and current_range_index == range_index:
            if fit_cfg_result is None:
                self._fit_dockwidget.fit_widget.update_fit_result('No Fit', None)
                self._mw.ple_widget.set_fit_data(None, None)
            else:
                self._fit_dockwidget.fit_widget.update_fit_result(*fit_cfg_result)
                self._mw.ple_widget.set_fit_data(*fit_cfg_result[1].high_res_best_fit)
            
            if self._fit_averaged:
                if fit_cfg_result is None:
                    self._fit_dockwidget.fit_widget.update_fit_result('No Fit', None)
                    self._mw.ple_averaged_widget.set_fit_data(None, None)
                else:
                    self._fit_dockwidget.fit_widget.update_fit_result(*fit_cfg_result)
                    self._mw.ple_averaged_widget.set_fit_data(*fit_cfg_result[1].high_res_best_fit)


    @QtCore.Slot(bool)
    def toggle_optimize(self, enabled):
        """
        """
        #! TODO: uncomment by implemebnting
        #self._toggle_enable_actions(not enabled, exclude_action=self._mw.action_optimize_position)
        # self._toggle_enable_scan_buttons(not enabled)
        # self._toggle_enable_scan_crosshairs(not enabled)
        self.sigToggleOptimize.emit(enabled)



    def _init_ui_connectors(self):
        new_scan_range = lambda: self.sigScanSettingsChanged.emit({'range': {self.scan_axis: (int(self._mw.startDoubleSpinBox.value()), int(self._mw.stopDoubleSpinBox.value()))}})
        self._mw.startDoubleSpinBox.editingFinished.connect(new_scan_range)
        self._mw.stopDoubleSpinBox.editingFinished.connect(new_scan_range)
        self._mw.frequencyDoubleSpinBox.editingFinished.connect(
            lambda: self.sigScanSettingsChanged.emit({'frequency': {self.scan_axis: self._mw.frequencyDoubleSpinBox.value()}})
        )
        self._mw.resolutionDoubleSpinBox.editingFinished.connect(
            lambda: self.sigScanSettingsChanged.emit({'resolution': {self.scan_axis: self._mw.resolutionDoubleSpinBox.value()}})
            ) 
        self._mw.actionFull_range.triggered.connect(
            self._scanning_logic.set_full_scan_ranges, QtCore.Qt.QueuedConnection
        )
        # !ValueError: all the input array dimensions for the concatenation axis must match exactly, but along dimension 1, the array at index 0 has size 50 and the array at index 1 has size 100
        self._mw.number_of_repeats_SpinBox.editingFinished.connect(
            lambda: self._scanning_logic.update_number_of_repeats(self._mw.number_of_repeats_SpinBox.value())
        )
        
        self._mw.constDoubleSpinBox.valueChanged.connect(self.const_changed) 

        self._mw.constDoubleSpinBox.editingFinished.connect(
            self.set_scanner_target_position
        )

    def toggle_scan(self):

        self._mw.elapsed_lines_DisplayWidget.display(self._scanning_logic._repeated)
        self._mw.constDoubleSpinBox.setValue(self._mw.startDoubleSpinBox.value())
        self._mw.constDoubleSpinBox.editingFinished.emit()
        self._scanning_logic.sigToggleScan.emit(self._mw.actionToggle_scan.isChecked(), [self.scan_axis], self.module_uuid)

    def show(self):
        """Make window visible and put it above all other windows. """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    @QtCore.Slot()
    def region_value_changed_averaged_data(self):
        region = self._mw.ple_averaged_widget.selected_region.getRegion()
        

        self._mw.startDoubleSpinBox.setValue(region[0])
        self._mw.stopDoubleSpinBox.setValue(region[1])
        self._mw.ple_widget.selected_region.setRegion(region)

        region = (int(region[0]), int(region[1]))
        self.sigScanSettingsChanged.emit({'range': {self.scan_axis: region}})


    @QtCore.Slot()
    def region_value_changed(self):
        region = self._mw.ple_widget.selected_region.getRegion()
        

        self._mw.startDoubleSpinBox.setValue(region[0])
        self._mw.stopDoubleSpinBox.setValue(region[1])
        self._mw.ple_averaged_widget.selected_region.setRegion(region)
        self._mw.ple_widget.target_point.setValue(region[0])

        region = (int(region[0]), int(region[1]))
        self.sigScanSettingsChanged.emit({'range': {self.scan_axis: region}})

    @QtCore.Slot()
    def sliders_values_are_changing_averaged_data(self):
        value = self._mw.ple_averaged_widget.target_point.value()
        self._mw.constDoubleSpinBox.setValue(value)
        self._mw.ple_widget.target_point.setValue(value)

    @QtCore.Slot()
    def sliders_values_are_changing(self):
        value = self._mw.ple_widget.target_point.value()
        self._mw.constDoubleSpinBox.setValue(value)
        self._mw.ple_averaged_widget.target_point.setValue(value)

    @QtCore.Slot()
    def const_changed(self):
        value = self._mw.constDoubleSpinBox.value()
        self._mw.ple_widget.target_point.setValue(value)
        self._mw.ple_averaged_widget.target_point.setValue(value)

    @QtCore.Slot()
    def restore_scanner_settings(self):
        """ ToDo: Document
        """
        self.scanner_settings_updated({'frequency': self._scanning_logic.scan_frequency,
        'resolution': self._scanning_logic.scan_resolution,
        'range': self._scanning_logic.scan_ranges})


    @QtCore.Slot(dict)
    def scanner_settings_updated(self, settings=None, caller_id=None):
        """
        Update scanner settings from logic and set widgets accordingly.

        @param dict settings: Settings dict containing the scanner settings to update.
                              If None (default) read the scanner setting from logic and update.
        """
        if self._mw.action_optimize_position.isChecked():#self.module_uuid:
            return 

        if not isinstance(settings, dict):
            settings = self._scanning_logic.scan_settings

        # if self._scanner_settings_locked:
        #     return
        # ToDo: Handle all remaining settings
        # ToDo: Implement backwards scanning functionality
        
        if 'resolution' in settings:
            self._mw.resolutionDoubleSpinBox.setValue(settings['resolution'][self.scan_axis])
        if 'range' in settings:
            x_range = settings['range'][self.scan_axis]
  
            self._mw.startDoubleSpinBox.setValue(x_range[0])
            self._mw.stopDoubleSpinBox.setValue(x_range[1])
            self._mw.constDoubleSpinBox.setRange(*x_range)
            
            # self._mw.startDoubleSpinBox.update_value()


            y_range =  (0, self._scanning_logic._number_of_repeats)
            self._mw.matrix_widget.set_plot_range(x_range = x_range)#, y_range = y_range)
            
            self._mw.ple_widget.selected_region.setRegion(x_range)
            self._mw.ple_widget.target_point.setValue(self._scanning_logic.scanner_target[self._scanning_logic._scan_axis])
            self._mw.ple_widget.plot_widget.setRange(xRange = x_range)
            
            self._mw.ple_averaged_widget.selected_region.setRegion(x_range)
            self._mw.ple_averaged_widget.target_point.setValue(self._scanning_logic.scanner_target[self._scanning_logic._scan_axis])
            self._mw.ple_averaged_widget.plot_widget.setRange(xRange = x_range)

        if 'frequency' in settings:
            self._mw.frequencyDoubleSpinBox.setValue(settings['frequency'][self.scan_axis])
        
        self._scanning_logic.reset_accumulated()
        self._mw.number_of_repeats_SpinBox.setValue(self._scanning_logic._number_of_repeats)
        

    @QtCore.Slot(bool, tuple)
    def scan_repeated(self, start, scan_axes):
        self._mw.elapsed_lines_DisplayWidget.display(self._scanning_logic.display_repeated)

    def set_scanner_target_position(self):
        """
        Issues new target to logic and updates gui.

        @param dict target_pos:
        """
        target = self.sender().value()
        
        # target = self._mw.ple_widget.target_point.value()
        
        target_pos = {self._scanning_logic._scan_axis: int(target)}
        
        # self.scanner_target_updated(pos_dict=target_pos, caller_id=None)

        self.sigScannerTargetChanged.emit(target_pos)

    def scanner_target_updated(self, pos_dict=None, caller_id=None):
        """
        Updates the scanner target and set widgets accordingly.

        @param dict pos_dict: The scanner position dict to update each axis position.
                              If None (default) read the scanner position from logic and update.
        @param int caller_id: The qudi module object id responsible for triggering this update
        """

        # If this update has been issued by this module, do not update display.
        # This has already been done before notifying the logic.
        if caller_id is self.module_uuid:
            return
        if not isinstance(pos_dict, dict):
            pos_dict = self._scanning_logic.scanner_target
        
        #FIX update the crosshairs here
        # self._mw.ple_widget.target_point.blockSignals(True)
        # self._mw.constDoubleSpinBox.blockSignals(True)

        # self._mw.ple_widget.target_point.setValue(pos_dict[self._scanning_logic._scan_axis])
        # self._mw.ple_averaged_widget.target_point.setValue(pos_dict[self._scanning_logic._scan_axis])
        # self._mw.constDoubleSpinBox.setValue(pos_dict[self._scanning_logic._scan_axis])

        # self._mw.constDoubleSpinBox.blockSignals(False)
        # self._mw.ple_widget.target_point.blockSignals(False)
        # self.scanner_control_dockwidget.set_target(pos_dict)

    @QtCore.Slot(bool, object, object)
    def scan_state_updated(self, is_running, scan_data=None, caller_id=None):
        scan_axes = scan_data.scan_axes if scan_data is not None else None
        if scan_data is not None:
            self._mw.actionToggle_scan.setChecked(is_running)

            if caller_id is self._optimizer_id:
                channel = self._osd.settings['data_channel']
                if scan_data.scan_dimension == 2:
                    x_ax, y_ax = scan_data.scan_axes
                    self.optimizer_dockwidget.set_image(image=scan_data.data[channel],
                                                        extent=scan_data.scan_range,
                                                        axs=scan_data.scan_axes)
                    self.optimizer_dockwidget.set_image_label(axis='bottom',
                                                                text=x_ax,
                                                                units=scan_data.axes_units[x_ax],
                                                                axs=scan_data.scan_axes)
                    self.optimizer_dockwidget.set_image_label(axis='left',
                                                                text=y_ax,
                                                                units=scan_data.axes_units[y_ax],
                                                                axs=scan_data.scan_axes)
                elif scan_data.scan_dimension == 1:
                    x_ax = scan_data.scan_axes[0]
                    self.optimizer_dockwidget.set_plot_data(
                        x=np.linspace(*scan_data.scan_range[0], scan_data.scan_resolution[0]),
                        y=scan_data.data[channel],
                        axs=scan_data.scan_axes
                    )
                    self.optimizer_dockwidget.set_plot_label(axis='bottom',
                                                                text=x_ax,
                                                                units=scan_data.axes_units[x_ax],
                                                                axs=scan_data.scan_axes)
                    self.optimizer_dockwidget.set_plot_label(axis='left',
                                                                text=channel,
                                                                units=scan_data.channel_units[channel],
                                                                axs=scan_data.scan_axes)
            else:
                self._update_scan_data(scan_data)
            self.scan_data = scan_data
        if not self._optimizer_state['is_running']:
            self._toggle_enable_actions(not is_running, exclude_action=self._mw.action_optimize_position)
        else:
            self._toggle_enable_actions(not is_running, exclude_action=self._mw.action_optimize_position)
        # self._toggle_enable_scan_crosshairs(not is_running)
        # self.scanner_settings_toggle_gui_lock(is_running)
     

        return

    def _toggle_enable_actions(self, enable, exclude_action=None):
        # self._mw.action_optimize_position.setChecked(enable)
        pass
        # if exclude_action is not self._mw.action_optimize_position:
        #     self._mw.action_optimize_position.setEnabled(enable)
        # if exclude_action is not self._mw.actionToggle_scan:
        #     self._mw.actionToggle_scan.setEnabled(enable)
    
    @QtCore.Slot(bool, dict, object)
    def optimize_state_updated(self, is_running, optimal_position=None, fit_data=None):
       
        self._optimizer_state['is_running'] = is_running
        _is_optimizer_valid_1d = not is_running
        _is_optimizer_valid_2d = not is_running

        # self._toggle_enable_scan_buttons(not is_running)
        self._toggle_enable_actions(not is_running,
                                    exclude_action=self._mw.actionToggle_scan)
        # self._toggle_enable_scan_crosshairs(not is_running)
        self._mw.action_optimize_position.setChecked(is_running)
        # self.scanner_settings_toggle_gui_lock(is_running)

        if fit_data is not None and optimal_position is None:
            raise ValueError("Can't understand fit_data without optimal position")

        # Update optimal position crosshair and marker
        if isinstance(optimal_position, dict):
            scan_axs = list(optimal_position.keys())
            if len(optimal_position) == 2:
                _is_optimizer_valid_2d = True
                self.optimizer_dockwidget.set_2d_position(tuple(optimal_position.values()),
                                                          scan_axs)

            elif len(optimal_position) == 1:
                _is_optimizer_valid_1d = True
                self.optimizer_dockwidget.set_1d_position(next(iter(optimal_position.values())),
                                                          scan_axs)
                
                #FIX!! not general AT ALL
                self._mw.ple_widget.target_point.setValue(optimal_position[self._scanning_logic._scan_axis])
                self._mw.ple_averaged_widget.target_point.setValue(optimal_position[self._scanning_logic._scan_axis])
                self._mw.constDoubleSpinBox.setValue(optimal_position[self._scanning_logic._scan_axis])

        if (fit_data is not None and
            np.any('full_fit_res' in fit_data) and
            np.any('fit_data' in fit_data) 
            and isinstance(optimal_position, dict)):
            data = fit_data['fit_data']
            fit_res = fit_data['full_fit_res']
            if data.ndim == 1:
                self.optimizer_dockwidget.set_fit_data(scan_axs, y=data)
                sig_z = fit_res.params['sigma'].value
                self.optimizer_dockwidget.set_1d_position(next(iter(optimal_position.values())),
                                                          scan_axs, sigma=sig_z)
            elif data.ndim == 2:
                sig_x, sig_y = fit_res.params['sigma_x'].value, fit_res.params['sigma_y'].value
                self.optimizer_dockwidget.set_2d_position(tuple(optimal_position.values()),
                                                          scan_axs, sigma=[sig_x, sig_y])

        # Hide crosshair and 1d marker when scanning
        if len(scan_axs) == 2:
            self.optimizer_dockwidget.toogle_crosshair(scan_axs, _is_optimizer_valid_2d)
        else:
            self.optimizer_dockwidget.toogle_crosshair(None, _is_optimizer_valid_2d)
        if len(scan_axs) == 1:
            self.optimizer_dockwidget.toogle_marker(scan_axs, _is_optimizer_valid_1d)
        else:
            self.optimizer_dockwidget.toogle_marker(None, _is_optimizer_valid_1d)
       
            
    @QtCore.Slot(object)
    def _update_scan_data(self, scan_data):
        """
        @param ScanData scan_data:
        """
    
        self._mw.ple_widget.set_scan_data(scan_data.data, scan_data)
        

        if scan_data.accumulated is not None:
            self._mw.matrix_widget.set_scan_data(scan_data.accumulated, scan_data)
            averaged_data = {channel: data.mean(axis=0)  for channel, data in scan_data.accumulated.items()}
            # averaged_retrace_data = {channel: data.mean(axis=0)  for channel, data in scan_data.accumulated.items()}
            self._mw.ple_averaged_widget.set_scan_data(averaged_data, scan_data)

    @QtCore.Slot(object)
    def _update_accumulated_scan(self, accumulated_data, scan_data):
         if accumulated_data is not None:
            # self._mw.matrix_widget.set_scan_data(accumulated_data, scan_data)
            # self._mw.ple_averaged_widget.set_scan_data(accumulated_data, scan_data)
            self._accumulated_data = accumulated_data
           

    @QtCore.Slot(tuple)
    def save_scan_data(self, scan_axes=None):
        """
        Save data for a given (or all) scan axis.
        @param tuple: Axis to save. Save all currently displayed if None.
        """
        
        name_tag = self.save_path_widget.saveTagLineEdit.text()
        if self.save_path_widget.newPathCheckBox.isChecked() and self.save_path_widget.newPathCheckBox.isEnabled():
            new_path = QtWidgets.QFileDialog.getExistingDirectory(self._mw, 'Select Folder')
            if new_path:
                self._save_folderpath = new_path
                self.save_path_widget.currPathLabel.setText(self._save_folderpath)
                self.save_path_widget.newPathCheckBox.setChecked(False)
            else:
                return

        self.sigShowSaveDialog.emit(True)

        if self.save_path_widget.DailyPathCheckBox.isChecked():
            self._save_folderpath = None
            self.save_path_widget.currPathLabel.setText('Default')

        try:
            #data_logic = self._data_logic()
            #scans = data_logic.get_all_current_scan_data()

            # if scan_axes is None:
            #     scan_axes = [scan.scan_axes for scan in data_logic.get_all_current_scan_data()]
            # else:
            #     scan_axes = [scan_axes]
            cbar_range = self._mw.matrix_widget.image_widget.levels
            if self._controller_logic is not None:
                meta_params = self._mw.Controller_widget.params
            else:
                meta_params = dict()

            self.sigSaveScan.emit(self.scan_data, 
                                  self._scanning_logic._channel,
                                  self._scanning_logic._fit_container,
                                  cbar_range, 
                                  name_tag, 
                                  self._save_folderpath, 
                                  meta_params)

        finally:
            pass

    # def save_view(self):
    #     """Saves the current GUI state as a QbyteArray.
    #        The .data() function will transform it to a bytearray, 
    #        which can be saved as a StatusVar and read by the load_view method. 
    #     """
    #     self._save_display_view = self._mw.saveState().data() 
        
    # def load_view(self):
    #     """Loads the saved state from the GUI and can read a QbyteArray
    #         or a simple byteArray aswell.
    #     """
    #     if self._save_display_view is None:
    #         pass
    #     else:
    #         self._mw.restoreState(self._save_display_view)

