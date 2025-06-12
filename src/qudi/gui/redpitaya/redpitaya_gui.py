# -*- coding: utf-8 -*-
"""
Red Pitaya GUI module for oscilloscope, signal generation, and PID control.

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

import os
import numpy as np
from PySide2 import QtCore, QtWidgets, QtGui
import pyqtgraph as pg

from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.core.module import GuiBase
from qudi.util.colordefs import QudiPalette as palette


class RedPitayaGui(GuiBase):
    """GUI module for Red Pitaya control and monitoring.
    
    Example config for copy-paste:
    
    redpitaya_gui:
        module.Class: 'redpitaya.redpitaya_gui.RedPitayaGui'
        connect:
            redpitaya_logic: 'redpitaya_logic'
    """
    
    # Connectors
    _redpitaya_logic = Connector(name='redpitaya_logic', interface='RedPitayaLogic')
    
    # Status variables
    _current_tab = StatusVar('current_tab', 0)
    _plot_colors = StatusVar('plot_colors', ['#1f77b4', '#ff7f0e'])
    
    # Signals
    sigStartAcquisition = QtCore.Signal()
    sigStopAcquisition = QtCore.Signal()
    sigConfigurePid = QtCore.Signal(int, str, float, float, float, float)
    sigEnablePid = QtCore.Signal(int, bool)
    sigConfigureAsg = QtCore.Signal(int, str, float, float, float, bool)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Main window
        self._mw = None
        
        # Plot widgets
        self.oscilloscope_plot = None
        self.ch1_curve = None
        self.ch2_curve = None
        
        # Data storage
        self.time_data = np.array([])
        self.ch1_data = np.array([])
        self.ch2_data = np.array([])

    def on_activate(self):
        """Initialize and show the GUI."""
        self._setup_ui()
        self._connect_signals()
        self._restore_window_geometry(self._mw)
        
        # Initialize plots
        self._setup_plots()
        
        # Update initial values
        self._update_device_status()
        
        self.show()

    def on_deactivate(self):
        """Disconnect signals and close GUI."""
        self._disconnect_signals()
        self._save_window_geometry(self._mw)
        self._mw.close()

    def show(self):
        """Show the main window."""
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    def _setup_ui(self):
        """Set up the user interface."""
        # Create main window
        self._mw = RedPitayaMainWindow()
        
        # Set window properties
        self._mw.setWindowTitle('Red Pitaya Control')
        self._mw.setMinimumSize(800, 600)
        
        # Create central widget with tab widget
        central_widget = QtWidgets.QWidget()
        self._mw.setCentralWidget(central_widget)
        
        layout = QtWidgets.QVBoxLayout(central_widget)
        
        # Create tab widget
        self.tab_widget = QtWidgets.QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self._create_oscilloscope_tab()
        self._create_signal_generator_tab()
        self._create_pid_control_tab()
        self._create_device_status_tab()
        
        # Set current tab
        self.tab_widget.setCurrentIndex(self._current_tab)
        
        # Create status bar
        self._mw.statusBar().showMessage('Red Pitaya GUI Ready')

    def _create_oscilloscope_tab(self):
        """Create the oscilloscope control tab."""
        tab = QtWidgets.QWidget()
        self.tab_widget.addTab(tab, 'Oscilloscope')
        
        layout = QtWidgets.QHBoxLayout(tab)
        
        # Control panel
        control_panel = QtWidgets.QGroupBox('Acquisition Control')
        control_layout = QtWidgets.QVBoxLayout(control_panel)
        
        # Duration control
        duration_layout = QtWidgets.QHBoxLayout()
        duration_layout.addWidget(QtWidgets.QLabel('Duration (s):'))
        self.duration_spinbox = QtWidgets.QDoubleSpinBox()
        self.duration_spinbox.setRange(0.001, 10.0)
        self.duration_spinbox.setValue(1.0)
        self.duration_spinbox.setDecimals(3)
        duration_layout.addWidget(self.duration_spinbox)
        control_layout.addLayout(duration_layout)
        
        # Decimation control
        decimation_layout = QtWidgets.QHBoxLayout()
        decimation_layout.addWidget(QtWidgets.QLabel('Decimation:'))
        self.decimation_spinbox = QtWidgets.QSpinBox()
        self.decimation_spinbox.setRange(1, 65536)
        self.decimation_spinbox.setValue(1)
        decimation_layout.addWidget(self.decimation_spinbox)
        control_layout.addLayout(decimation_layout)
        
        # Trigger source
        trigger_layout = QtWidgets.QHBoxLayout()
        trigger_layout.addWidget(QtWidgets.QLabel('Trigger:'))
        self.trigger_combo = QtWidgets.QComboBox()
        self.trigger_combo.addItems(['immediately', 'ch1', 'ch2', 'ext'])
        trigger_layout.addWidget(self.trigger_combo)
        control_layout.addLayout(trigger_layout)
        
        # Acquisition buttons
        self.acquire_button = QtWidgets.QPushButton('Acquire')
        self.acquire_button.setStyleSheet(f'background-color: {palette.c1.name()}')
        control_layout.addWidget(self.acquire_button)
        
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.stop_button.setStyleSheet(f'background-color: {palette.c2.name()}')
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button)
        
        # Statistics display
        stats_group = QtWidgets.QGroupBox('Statistics')
        stats_layout = QtWidgets.QVBoxLayout(stats_group)
        
        self.ch1_stats_label = QtWidgets.QLabel('CH1: No data')
        self.ch2_stats_label = QtWidgets.QLabel('CH2: No data')
        stats_layout.addWidget(self.ch1_stats_label)
        stats_layout.addWidget(self.ch2_stats_label)
        
        control_layout.addWidget(stats_group)
        control_layout.addStretch()
        
        layout.addWidget(control_panel, 1)
        
        # Plot widget
        self.oscilloscope_plot = pg.PlotWidget()
        self.oscilloscope_plot.setLabel('left', 'Amplitude', units='V')
        self.oscilloscope_plot.setLabel('bottom', 'Time', units='s')
        self.oscilloscope_plot.setTitle('Oscilloscope Data')
        layout.addWidget(self.oscilloscope_plot, 3)

    def _create_signal_generator_tab(self):
        """Create the signal generator control tab."""
        tab = QtWidgets.QWidget()
        self.tab_widget.addTab(tab, 'Signal Generator')
        
        layout = QtWidgets.QVBoxLayout(tab)
        
        # ASG0 Control
        asg0_group = QtWidgets.QGroupBox('ASG0 (Output 1)')
        asg0_layout = QtWidgets.QGridLayout(asg0_group)
        
        # Waveform
        asg0_layout.addWidget(QtWidgets.QLabel('Waveform:'), 0, 0)
        self.asg0_waveform_combo = QtWidgets.QComboBox()
        self.asg0_waveform_combo.addItems(['sin', 'square', 'triangle', 'noise'])
        asg0_layout.addWidget(self.asg0_waveform_combo, 0, 1)
        
        # Frequency
        asg0_layout.addWidget(QtWidgets.QLabel('Frequency (Hz):'), 1, 0)
        self.asg0_frequency_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg0_frequency_spinbox.setRange(0.1, 62.5e6)
        self.asg0_frequency_spinbox.setValue(1000)
        self.asg0_frequency_spinbox.setDecimals(1)
        asg0_layout.addWidget(self.asg0_frequency_spinbox, 1, 1)
        
        # Amplitude
        asg0_layout.addWidget(QtWidgets.QLabel('Amplitude (V):'), 2, 0)
        self.asg0_amplitude_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg0_amplitude_spinbox.setRange(0.0, 1.0)
        self.asg0_amplitude_spinbox.setValue(0.1)
        self.asg0_amplitude_spinbox.setDecimals(3)
        asg0_layout.addWidget(self.asg0_amplitude_spinbox, 2, 1)
        
        # Offset
        asg0_layout.addWidget(QtWidgets.QLabel('Offset (V):'), 3, 0)
        self.asg0_offset_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg0_offset_spinbox.setRange(-1.0, 1.0)
        self.asg0_offset_spinbox.setValue(0.0)
        self.asg0_offset_spinbox.setDecimals(3)
        asg0_layout.addWidget(self.asg0_offset_spinbox, 3, 1)
        
        # Enable button
        self.asg0_enable_button = QtWidgets.QPushButton('Enable ASG0')
        self.asg0_enable_button.setCheckable(True)
        asg0_layout.addWidget(self.asg0_enable_button, 4, 0, 1, 2)
        
        layout.addWidget(asg0_group)
        
        # ASG1 Control (similar to ASG0)
        asg1_group = QtWidgets.QGroupBox('ASG1 (Output 2)')
        asg1_layout = QtWidgets.QGridLayout(asg1_group)
        
        # Waveform
        asg1_layout.addWidget(QtWidgets.QLabel('Waveform:'), 0, 0)
        self.asg1_waveform_combo = QtWidgets.QComboBox()
        self.asg1_waveform_combo.addItems(['sin', 'square', 'triangle', 'noise'])
        asg1_layout.addWidget(self.asg1_waveform_combo, 0, 1)
        
        # Frequency
        asg1_layout.addWidget(QtWidgets.QLabel('Frequency (Hz):'), 1, 0)
        self.asg1_frequency_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg1_frequency_spinbox.setRange(0.1, 62.5e6)
        self.asg1_frequency_spinbox.setValue(1000)
        self.asg1_frequency_spinbox.setDecimals(1)
        asg1_layout.addWidget(self.asg1_frequency_spinbox, 1, 1)
        
        # Amplitude
        asg1_layout.addWidget(QtWidgets.QLabel('Amplitude (V):'), 2, 0)
        self.asg1_amplitude_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg1_amplitude_spinbox.setRange(0.0, 1.0)
        self.asg1_amplitude_spinbox.setValue(0.1)
        self.asg1_amplitude_spinbox.setDecimals(3)
        asg1_layout.addWidget(self.asg1_amplitude_spinbox, 2, 1)
        
        # Offset
        asg1_layout.addWidget(QtWidgets.QLabel('Offset (V):'), 3, 0)
        self.asg1_offset_spinbox = QtWidgets.QDoubleSpinBox()
        self.asg1_offset_spinbox.setRange(-1.0, 1.0)
        self.asg1_offset_spinbox.setValue(0.0)
        self.asg1_offset_spinbox.setDecimals(3)
        asg1_layout.addWidget(self.asg1_offset_spinbox, 3, 1)
        
        # Enable button
        self.asg1_enable_button = QtWidgets.QPushButton('Enable ASG1')
        self.asg1_enable_button.setCheckable(True)
        asg1_layout.addWidget(self.asg1_enable_button, 4, 0, 1, 2)
        
        layout.addWidget(asg1_group)
        layout.addStretch()

    def _create_pid_control_tab(self):
        """Create the PID control tab."""
        tab = QtWidgets.QWidget()
        self.tab_widget.addTab(tab, 'PID Control')
        
        layout = QtWidgets.QVBoxLayout(tab)
        
        # Create PID controllers
        self.pid_groups = {}
        self.pid_controls = {}
        
        for pid_id in range(3):
            group = QtWidgets.QGroupBox(f'PID{pid_id}')
            group_layout = QtWidgets.QGridLayout(group)
            
            controls = {}
            
            # Input source
            group_layout.addWidget(QtWidgets.QLabel('Input:'), 0, 0)
            controls['input_combo'] = QtWidgets.QComboBox()
            controls['input_combo'].addItems(['in1', 'in2', 'asg0', 'asg1'])
            group_layout.addWidget(controls['input_combo'], 0, 1)
            
            # Setpoint
            group_layout.addWidget(QtWidgets.QLabel('Setpoint:'), 1, 0)
            controls['setpoint_spinbox'] = QtWidgets.QDoubleSpinBox()
            controls['setpoint_spinbox'].setRange(-1.0, 1.0)
            controls['setpoint_spinbox'].setValue(0.0)
            controls['setpoint_spinbox'].setDecimals(6)
            group_layout.addWidget(controls['setpoint_spinbox'], 1, 1)
            
            # P gain
            group_layout.addWidget(QtWidgets.QLabel('P:'), 2, 0)
            controls['p_spinbox'] = QtWidgets.QDoubleSpinBox()
            controls['p_spinbox'].setRange(-1000.0, 1000.0)
            controls['p_spinbox'].setValue(0.0)
            controls['p_spinbox'].setDecimals(6)
            group_layout.addWidget(controls['p_spinbox'], 2, 1)
            
            # I gain
            group_layout.addWidget(QtWidgets.QLabel('I:'), 3, 0)
            controls['i_spinbox'] = QtWidgets.QDoubleSpinBox()
            controls['i_spinbox'].setRange(-1000.0, 1000.0)
            controls['i_spinbox'].setValue(0.0)
            controls['i_spinbox'].setDecimals(6)
            group_layout.addWidget(controls['i_spinbox'], 3, 1)
            
            # D gain
            group_layout.addWidget(QtWidgets.QLabel('D:'), 4, 0)
            controls['d_spinbox'] = QtWidgets.QDoubleSpinBox()
            controls['d_spinbox'].setRange(-1000.0, 1000.0)
            controls['d_spinbox'].setValue(0.0)
            controls['d_spinbox'].setDecimals(6)
            group_layout.addWidget(controls['d_spinbox'], 4, 1)
            
            # Output display
            group_layout.addWidget(QtWidgets.QLabel('Output:'), 5, 0)
            controls['output_label'] = QtWidgets.QLabel('0.000000')
            group_layout.addWidget(controls['output_label'], 5, 1)
            
            # Enable button
            controls['enable_button'] = QtWidgets.QPushButton(f'Enable PID{pid_id}')
            controls['enable_button'].setCheckable(True)
            group_layout.addWidget(controls['enable_button'], 6, 0, 1, 2)
            
            # Configure button
            controls['configure_button'] = QtWidgets.QPushButton('Configure')
            group_layout.addWidget(controls['configure_button'], 7, 0, 1, 2)
            
            self.pid_groups[pid_id] = group
            self.pid_controls[pid_id] = controls
            layout.addWidget(group)
        
        layout.addStretch()

    def _create_device_status_tab(self):
        """Create the device status tab."""
        tab = QtWidgets.QWidget()
        self.tab_widget.addTab(tab, 'Device Status')
        
        layout = QtWidgets.QVBoxLayout(tab)
        
        # Device info
        info_group = QtWidgets.QGroupBox('Device Information')
        info_layout = QtWidgets.QVBoxLayout(info_group)
        
        self.device_info_text = QtWidgets.QTextEdit()
        self.device_info_text.setReadOnly(True)
        info_layout.addWidget(self.device_info_text)
        
        layout.addWidget(info_group)
        
        # Control buttons
        button_layout = QtWidgets.QHBoxLayout()
        
        self.refresh_button = QtWidgets.QPushButton('Refresh Status')
        button_layout.addWidget(self.refresh_button)
        
        self.reset_button = QtWidgets.QPushButton('Reset Device')
        self.reset_button.setStyleSheet(f'background-color: {palette.c2.name()}')
        button_layout.addWidget(self.reset_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _setup_plots(self):
        """Set up the plot widgets."""
        # Configure oscilloscope plot
        self.oscilloscope_plot.setBackground('w')
        self.oscilloscope_plot.showGrid(x=True, y=True)
        
        # Create curves
        self.ch1_curve = self.oscilloscope_plot.plot(
            pen=pg.mkPen(color=self._plot_colors[0], width=2),
            name='CH1'
        )
        self.ch2_curve = self.oscilloscope_plot.plot(
            pen=pg.mkPen(color=self._plot_colors[1], width=2),
            name='CH2'
        )
        
        # Add legend
        self.oscilloscope_plot.addLegend()

    def _connect_signals(self):
        """Connect GUI signals to logic."""
        # Connect to logic signals
        self._redpitaya_logic().sigDataAcquired.connect(self._update_oscilloscope_data)
        self._redpitaya_logic().sigPidStateChanged.connect(self._update_pid_state)
        self._redpitaya_logic().sigDeviceStatusChanged.connect(self._update_device_info)
        
        # Connect GUI signals
        self.acquire_button.clicked.connect(self._start_acquisition)
        self.stop_button.clicked.connect(self._stop_acquisition)
        
        # ASG signals
        self.asg0_enable_button.toggled.connect(lambda checked: self._configure_asg(0, checked))
        self.asg1_enable_button.toggled.connect(lambda checked: self._configure_asg(1, checked))
        
        # PID signals
        for pid_id in range(3):
            controls = self.pid_controls[pid_id]
            controls['enable_button'].toggled.connect(
                lambda checked, pid=pid_id: self._enable_pid(pid, checked)
            )
            controls['configure_button'].clicked.connect(
                lambda _, pid=pid_id: self._configure_pid(pid)
            )
        
        # Device status signals
        self.refresh_button.clicked.connect(self._update_device_status)
        self.reset_button.clicked.connect(self._reset_device)
        
        # Tab change signal
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def _disconnect_signals(self):
        """Disconnect all signals."""
        try:
            self._redpitaya_logic().sigDataAcquired.disconnect(self._update_oscilloscope_data)
            self._redpitaya_logic().sigPidStateChanged.disconnect(self._update_pid_state)
            self._redpitaya_logic().sigDeviceStatusChanged.disconnect(self._update_device_info)
        except:
            pass

    @QtCore.Slot()
    def _start_acquisition(self):
        """Start data acquisition."""
        duration = self.duration_spinbox.value()
        trigger_source = self.trigger_combo.currentText()
        
        # Update decimation in logic
        decimation = self.decimation_spinbox.value()
        self._redpitaya_logic().decimation = decimation
        
        success = self._redpitaya_logic().start_acquisition(duration, trigger_source)
        
        if success:
            self.acquire_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self._mw.statusBar().showMessage('Acquiring data...')

    @QtCore.Slot()
    def _stop_acquisition(self):
        """Stop data acquisition."""
        self._redpitaya_logic().stop_acquisition()
        self.acquire_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._mw.statusBar().showMessage('Acquisition stopped')

    @QtCore.Slot(object, object, object)
    def _update_oscilloscope_data(self, time_data, ch1_data, ch2_data):
        """Update oscilloscope plot with new data."""
        self.time_data = time_data
        self.ch1_data = ch1_data
        self.ch2_data = ch2_data
        
        # Update curves
        self.ch1_curve.setData(time_data, ch1_data)
        self.ch2_curve.setData(time_data, ch2_data)
        
        # Update statistics
        self._update_statistics()
        
        # Re-enable acquire button
        self.acquire_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._mw.statusBar().showMessage('Data acquired successfully')

    def _update_statistics(self):
        """Update statistics display."""
        if len(self.ch1_data) > 0:
            ch1_stats = self._redpitaya_logic().calculate_statistics(1)
            if 'error' not in ch1_stats:
                self.ch1_stats_label.setText(
                    f"CH1: Mean={ch1_stats['mean']:.3f}V, "
                    f"RMS={ch1_stats['rms']:.3f}V, "
                    f"Samples={ch1_stats['samples']}"
                )
        
        if len(self.ch2_data) > 0:
            ch2_stats = self._redpitaya_logic().calculate_statistics(2)
            if 'error' not in ch2_stats:
                self.ch2_stats_label.setText(
                    f"CH2: Mean={ch2_stats['mean']:.3f}V, "
                    f"RMS={ch2_stats['rms']:.3f}V, "
                    f"Samples={ch2_stats['samples']}"
                )

    def _configure_asg(self, channel, enable):
        """Configure ASG output."""
        if channel == 0:
            waveform = self.asg0_waveform_combo.currentText()
            frequency = self.asg0_frequency_spinbox.value()
            amplitude = self.asg0_amplitude_spinbox.value()
            offset = self.asg0_offset_spinbox.value()
        else:
            waveform = self.asg1_waveform_combo.currentText()
            frequency = self.asg1_frequency_spinbox.value()
            amplitude = self.asg1_amplitude_spinbox.value()
            offset = self.asg1_offset_spinbox.value()
        
        success = self._redpitaya_logic().configure_signal_generator(
            channel, waveform, frequency, amplitude, offset, enable
        )
        
        if success:
            self._mw.statusBar().showMessage(f'ASG{channel} {"enabled" if enable else "disabled"}')
        else:
            # Reset button state on failure
            if channel == 0:
                self.asg0_enable_button.setChecked(False)
            else:
                self.asg1_enable_button.setChecked(False)

    def _configure_pid(self, pid_id):
        """Configure PID controller."""
        controls = self.pid_controls[pid_id]
        
        input_signal = controls['input_combo'].currentText()
        setpoint = controls['setpoint_spinbox'].value()
        p = controls['p_spinbox'].value()
        i = controls['i_spinbox'].value()
        d = controls['d_spinbox'].value()
        
        success = self._redpitaya_logic().configure_pid(
            pid_id, input_signal, setpoint, p, i, d
        )
        
        if success:
            self._mw.statusBar().showMessage(f'PID{pid_id} configured')

    def _enable_pid(self, pid_id, enable):
        """Enable or disable PID controller."""
        success = self._redpitaya_logic().enable_pid(pid_id, enable)
        
        if success:
            self._mw.statusBar().showMessage(f'PID{pid_id} {"enabled" if enable else "disabled"}')
        else:
            # Reset button state on failure
            self.pid_controls[pid_id]['enable_button'].setChecked(False)

    @QtCore.Slot(int, bool)
    def _update_pid_state(self, pid_id, enabled):
        """Update PID state display."""
        controls = self.pid_controls[pid_id]
        controls['enable_button'].setChecked(enabled)
        
        # Update output display if enabled
        if enabled:
            output = self._redpitaya_logic().get_pid_output(pid_id)
            controls['output_label'].setText(f'{output:.6f}')
        else:
            controls['output_label'].setText('0.000000')

    @QtCore.Slot()
    def _update_device_status(self):
        """Update device status display."""
        status = self._redpitaya_logic().get_device_status()
        self._update_device_info(status)

    @QtCore.Slot(dict)
    def _update_device_info(self, info):
        """Update device information display."""
        info_text = "Device Information:\n\n"
        info_text += f"IP Address: {info.get('ip_address', 'N/A')}\n"
        info_text += f"Sampling Rate: {info.get('sampling_rate', 0)/1e6:.1f} MHz\n"
        info_text += f"Decimation: {info.get('decimation', 1)}\n"
        info_text += f"Connected: {info.get('connected', False)}\n"
        info_text += "\nOutput States:\n"
        info_text += f"ASG0: {'Enabled' if info.get('asg_states', {}).get(0, False) else 'Disabled'}\n"
        info_text += f"ASG1: {'Enabled' if info.get('asg_states', {}).get(1, False) else 'Disabled'}\n"
        
        self.device_info_text.setPlainText(info_text)

    @QtCore.Slot()
    def _reset_device(self):
        """Reset the Red Pitaya device."""
        reply = QtWidgets.QMessageBox.question(
            self._mw, 'Reset Device',
            'Are you sure you want to reset the Red Pitaya device?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            success = self._redpitaya_logic().reset_device()
            if success:
                self._mw.statusBar().showMessage('Device reset successfully')
                # Reset GUI state
                self._reset_gui_state()
            else:
                self._mw.statusBar().showMessage('Device reset failed')

    def _reset_gui_state(self):
        """Reset GUI to initial state."""
        # Reset ASG buttons
        self.asg0_enable_button.setChecked(False)
        self.asg1_enable_button.setChecked(False)
        
        # Reset PID buttons
        for pid_id in range(3):
            self.pid_controls[pid_id]['enable_button'].setChecked(False)
            self.pid_controls[pid_id]['output_label'].setText('0.000000')
        
        # Clear plots
        self.ch1_curve.setData([], [])
        self.ch2_curve.setData([], [])
        
        # Clear statistics
        self.ch1_stats_label.setText('CH1: No data')
        self.ch2_stats_label.setText('CH2: No data')

    @QtCore.Slot(int)
    def _on_tab_changed(self, index):
        """Handle tab change."""
        self._current_tab = index


class RedPitayaMainWindow(QtWidgets.QMainWindow):
    """Main window for Red Pitaya GUI."""
    
    def __init__(self):
        # Call parent class constructor properly
        super().__init__()
        
        # Create central widget and layout
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QtWidgets.QVBoxLayout(self.central_widget)
        
        # Create tab widget
        self.tab_widget = QtWidgets.QTabWidget()
        self.layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.oscilloscope_tab = QtWidgets.QWidget()
        self.generator_tab = QtWidgets.QWidget()
        self.pid_tab = QtWidgets.QWidget()
        
        # Add tabs to widget
        self.tab_widget.addTab(self.oscilloscope_tab, "Oscilloscope")
        self.tab_widget.addTab(self.generator_tab, "Signal Generator")
        self.tab_widget.addTab(self.pid_tab, "PID Control")
        
        # Set window properties
        self.setWindowTitle("Red Pitaya Control")
        self.resize(800, 600)