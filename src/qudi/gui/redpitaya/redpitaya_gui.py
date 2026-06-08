import os
import numpy as np
from PySide2 import QtCore, QtWidgets, QtUiTools
import pyqtgraph as pg

from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.module import GuiBase
from qudi.util.colordefs import QudiPalette as palette

class RedPitayaPyrplGui(GuiBase):
    """PyRPL-based GUI for Red Pitaya control."""

    # Connectors
    _redpitaya_logic = Connector(name='redpitaya_logic', interface='RedPitayaPyrplLogic')

    # fixed UI file (not configurable)
    _ui_filename = 'redpitaya_pyrpl.ui'

    # Status variables
    _window_geometry = StatusVar('window_geometry', None)
    _window_state = StatusVar('window_state', None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self.plots = {}
        
        # Setup acquisition timer with reasonable interval
        self._acq_timer = QtCore.QTimer()
        self._acq_timer.setInterval(300)  # 50ms refresh rate (20 Hz)
        self._acq_timer.timeout.connect(self._on_acq_timer)
        self._acq_running = False

    def on_activate(self):
        """Initialize the GUI on activation."""
        # Load UI file (fixed filename in this module)
        ui_file = os.path.join(os.path.dirname(__file__), self._ui_filename)
        if not os.path.isfile(ui_file):
            raise FileNotFoundError(f"UI file not found: {ui_file}")

        qfile = QtCore.QFile(ui_file)
        if not qfile.open(QtCore.QIODevice.ReadOnly):
            raise IOError(f"Could not open UI file: {ui_file}")

        loader = QtUiTools.QUiLoader()
        self._mw = loader.load(qfile)
        qfile.close()

        if self._mw is None:
            raise RuntimeError(f"QUiLoader failed to load UI: {ui_file}")

        # Set up plots
        self._setup_plots()
        
        # Start continuous acquisition immediately
        self._start_acquisition()

        # Add controls
        self._ensure_continuous_controls()   # creates start/stop + integration time
        self._ensure_scope_controls()        # trigger / inputs / apply

        # Connect signals
        self._connect_signals()

        # Restore window geometry
        try:
            if self._window_geometry:
                self._mw.restoreGeometry(self._window_geometry)
            if self._window_state:
                self._mw.restoreState(self._window_state)
        except Exception:
            self.log.warning("Failed to restore window geometry/state")

        # Show window
        self.show()

    def on_deactivate(self):
        """Clean up before deactivating module."""
        self._stop_acquisition()
        if self._mw is None:
            return
        # Save window geometry
        try:
            self._window_geometry = self._mw.saveGeometry()
            self._window_state = self._mw.saveState()
        except Exception:
            pass

        # Disconnect signals and close window
        self._disconnect_signals()
        try:
            self._mw.close()
        except Exception:
            pass

    def show(self):
        """Show the main window."""
        if self._mw is None:
            return
        self._mw.show()
        self._mw.raise_()

    def _ensure_tab_widget(self, object_name):
        """Find a widget by name on the loaded UI and ensure it has a layout.
        If not found, create a QWidget and insert it into central layout as fallback.
        """
        widget = getattr(self._mw, object_name, None)
        if widget is None:
            widget = self._mw.findChild(QtWidgets.QWidget, object_name)
        if widget is None:
            # fallback: try to add to centralwidget layout or create standalone
            central = getattr(self._mw, 'centralwidget', None)
            if central is not None and central.layout() is not None:
                widget = QtWidgets.QWidget()
                widget.setObjectName(object_name)
                central.layout().addWidget(widget)
            else:
                # put into main window as central widget
                widget = QtWidgets.QWidget()
                widget.setObjectName(object_name)
                try:
                    self._mw.setCentralWidget(widget)
                except Exception:
                    pass
        if widget.layout() is None:
            widget.setLayout(QtWidgets.QVBoxLayout())
        return widget

    def _setup_plots(self):
        """Initialize plot widgets."""
        # Time domain plot only
        time_tab = self._ensure_tab_widget('timePlotTab')
        time_plot = pg.PlotWidget()
        time_plot.setLabel('left', 'Voltage', units='V')
        time_plot.setLabel('bottom', 'Time', units='s')
        time_plot.addLegend()
        
        # Create plot curves with clear style
        self.plots['ch1'] = time_plot.plot(
            pen=pg.mkPen(color=palette.c1.name(), width=2),
            name='CH1'
        )
        self.plots['ch2'] = time_plot.plot(
            pen=pg.mkPen(color=palette.c2.name(), width=2),
            name='CH2'
        )
        
        # Store the plot widget for later access
        self.time_plot_widget = time_plot
        time_tab.layout().addWidget(time_plot)

    def _connect_signals(self):
        """Connect all GUI signals safely (check existence first)."""
        if self._mw is None:
            return

        # Start/Stop button and scope apply
        try:
            if hasattr(self._mw, 'startStopButton'):
                self._mw.startStopButton.toggled.connect(self._on_startstop_toggled)
            if hasattr(self._mw, 'integrationSpin'):
                self._mw.integrationSpin.valueChanged.connect(self._on_integration_changed)
            if hasattr(self._mw, 'applyScopeButton'):
                self._mw.applyScopeButton.clicked.connect(self._on_apply_scope)
        except Exception:
            self.log.warning("Failed to connect control signals")

        # Logic connections
        try:
            red_logic = self._redpitaya_logic()
            if hasattr(red_logic, 'sigDataAcquired'):
                red_logic.sigDataAcquired.connect(self._update_plots)
            if hasattr(red_logic, 'sigScopeStateChanged'):
                red_logic.sigScopeStateChanged.connect(self._on_scope_state_changed)
        except Exception:
            self.log.warning("Failed to connect to redpitaya logic signals")

        # Menu actions
        try:
            if hasattr(self._mw, 'actionSave_Data'):
                self._mw.actionSave_Data.triggered.connect(self._save_data)
            if hasattr(self._mw, 'actionLoad_Settings'):
                self._mw.actionLoad_Settings.triggered.connect(self._load_settings)
            if hasattr(self._mw, 'actionSave_Settings'):
                self._mw.actionSave_Settings.triggered.connect(self._save_settings)
            if hasattr(self._mw, 'actionExit'):
                self._mw.actionExit.triggered.connect(self._mw.close)
        except Exception:
            pass

    def _disconnect_signals(self):
        """Disconnect all signals safely."""
        try:
            red_logic = self._redpitaya_logic()
            if hasattr(red_logic, 'sigDataAcquired'):
                red_logic.sigDataAcquired.disconnect(self._update_plots)
            if hasattr(red_logic, 'sigScopeStateChanged'):
                red_logic.sigScopeStateChanged.disconnect(self._on_scope_state_changed)
        except Exception:
            pass
        try:
            if hasattr(self._mw, 'startStopButton'):
                try:
                    self._mw.startStopButton.toggled.disconnect(self._on_startstop_toggled)
                except Exception:
                    pass
            if hasattr(self._mw, 'integrationSpin'):
                try:
                    self._mw.integrationSpin.valueChanged.disconnect(self._on_integration_changed)
                except Exception:
                    pass
            if hasattr(self._mw, 'applyScopeButton'):
                try:
                    self._mw.applyScopeButton.clicked.disconnect(self._on_apply_scope)
                except Exception:
                    pass
        except Exception:
            pass

    def _ensure_continuous_controls(self):
        """Ensure the UI has a single Start/Stop control and an integration time control."""
        # place controls in scopeControlGroup or central layout as fallback
        scope_group = getattr(self._mw, 'scopeControlGroup', None)
        parent_layout = None
        if scope_group is not None and scope_group.layout() is not None:
            parent_layout = scope_group.layout()
        else:
            central = getattr(self._mw, 'centralwidget', None)
            if central is not None and central.layout() is not None:
                parent_layout = central.layout()

        if parent_layout is None:
            return

        # Start/Stop toggle button (single control to start and stop acquisition)
        if not hasattr(self._mw, 'startStopButton'):
            btn = QtWidgets.QPushButton("Start")
            btn.setObjectName('startStopButton')
            btn.setCheckable(True)
            btn.setChecked(False)
            parent_layout.addWidget(btn)
            self._mw.startStopButton = btn

        # Integration time (seconds)
        if not hasattr(self._mw, 'integrationSpin'):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setObjectName('integrationSpin')
            spin.setRange(0.0001, 10.0)
            spin.setDecimals(4)
            spin.setSingleStep(0.001)
            spin.setValue(0.1)  # default integration time
            spin.setSuffix(' s')
            parent_layout.addWidget(QtWidgets.QLabel("Integration time:"))
            parent_layout.addWidget(spin)
            self._mw.integrationSpin = spin

    @QtCore.Slot(bool)
    def _on_startstop_toggled(self, enabled):
        """Handle single acquisition when Acquire button is pressed."""
        if enabled:
            try:
                self._mw.startStopButton.setEnabled(False)  # Disable button during acquisition
                self._mw.startStopButton.setText("Acquiring...")
                # Get duration from spinbox
                duration = self._mw.integrationSpin.value()
                # Trigger single acquisition
                self._redpitaya_logic().get_scope_data(duration)
            except Exception as e:
                self.log.error(f"Acquisition failed: {e}")
                self._mw.startStopButton.setChecked(False)
                self._mw.startStopButton.setText("Acquire")
                self._mw.startStopButton.setEnabled(True)

    @QtCore.Slot(float)
    def _on_integration_changed(self, value):
        """Update integration time used for each acquisition (seconds)."""
        try:
            self._continuous_duration = float(value)
        except Exception:
            pass

    def _start_continuous(self):
        """Start periodic acquisition. Prevent overlapping acquisitions."""
        if self._acq_timer.isActive():
            return
        # Read integration time from UI if available
        duration = 0.1
        try:
            if hasattr(self._mw, 'integrationSpin'):
                duration = float(self._mw.integrationSpin.value())
        except Exception:
            pass
        self._continuous_duration = duration
        self._acq_running = False
        # set timer interval to 0 => refresh as fast as possible (event-loop driven)
        self._acq_timer.setInterval(self._acq_interval_ms)
        self._acq_timer.start()
        try:
            if hasattr(self._mw, 'statusbar'):
                self._mw.statusbar.showMessage('Continuous acquisition started')
        except Exception:
            pass

    def _stop_continuous(self):
        """Stop periodic acquisition."""
        if self._acq_timer.isActive():
            self._acq_timer.stop()
        self._acq_running = False
        try:
            if hasattr(self._mw, 'statusbar'):
                self._mw.statusbar.showMessage('Continuous acquisition stopped')
            if hasattr(self._mw, 'startStopButton'):
                self._mw.startStopButton.setChecked(False)
                self._mw.startStopButton.setText("Start")
        except Exception:
            pass

    def _start_acquisition(self):
        """Start continuous data acquisition."""
        if not self._acq_running:
            self._acq_running = True
            self._acq_timer.setInterval(50)  # 100ms refresh rate
            self._acq_timer.start()

    def _stop_acquisition(self):
        """Stop continuous acquisition."""
        self._acq_timer.stop()
        self._acq_running = False
        self.log.info("Stopped acquisition")

    def _on_acq_timer(self):
        """Timer callback to get new data and update plots."""
        if not self._acq_running:
            return
            
        try:
            # Get 8 seconds of data instead of 1
            times, ch1, ch2 = self._redpitaya_logic().get_scope_data(8.0)
            if all(x is not None for x in (times, ch1, ch2)):
                self._update_plots(times, ch1, ch2)
                
        except Exception as e:
            self.log.error(f"Acquisition failed: {e}")
            self._stop_acquisition()

    @QtCore.Slot(object, object, object)
    def _update_plots(self, time_data, ch1_data, ch2_data):
        """Update plots with new data."""
        if time_data is None or ch1_data is None or ch2_data is None:
            return

        try:
            # Update time domain plots
            self.plots['ch1'].setData(time_data, ch1_data)
            self.plots['ch2'].setData(time_data, ch2_data)
            
            # Set x-axis range to show full 8 seconds
            min_time = min(time_data)
            max_time = max(time_data)
            self.time_plot_widget.setXRange(min_time, max_time, padding=0.02)
            
        except Exception as e:
            self.log.error(f"Plot update failed: {e}")

    def _ensure_scope_controls(self):
        """Setup scope controls and apply initial settings."""
        try:
            # Apply initial scope settings
            self._redpitaya_logic().setup_scope(
                input1='out1',
                input2='out2',
                trigger_source='immediately',
                decimation=64,
                average=False
            )
            # Rolling mode is now started automatically in setup_scope
            
        except Exception as e:
            self.log.error(f"Error setting up scope controls: {e}")

    @QtCore.Slot()
    def _on_apply_scope(self):
        """Apply scope parameters from UI to the hardware via logic."""
        try:
            if self._mw is None:
                return
                
            # Disable apply button during update
            apply_btn = getattr(self._mw, 'applyScopeButton', None)
            if apply_btn is not None:
                apply_btn.setEnabled(False)
                apply_btn.setText("Applying...")
            
            # Get current values from UI
            params = {}
            
            # Input sources
            if hasattr(self._mw, 'input1Combo'):
                params['ch1_input'] = self._mw.input1Combo.currentText()
            if hasattr(self._mw, 'input2Combo'):
                params['ch2_input'] = self._mw.input2Combo.currentText()
                
            # Trigger settings
            if hasattr(self._mw, 'triggerSourceCombo'):
                params['trigger_source'] = self._mw.triggerSourceCombo.currentText()
            if hasattr(self._mw, 'triggerLevelSpin'):
                params['trigger_level'] = self._mw.triggerLevelSpin.value()
            if hasattr(self._mw, 'triggerHystSpin'):
                params['trigger_hysteresis'] = self._mw.triggerHystSpin.value()
            if hasattr(self._mw, 'triggerDelaySpin'):
                params['trigger_delay'] = self._mw.triggerDelaySpin.value()
                
            # Scope settings
            if hasattr(self._mw, 'decimationSpinBox'):
                params['decimation'] = self._mw.decimationSpinBox.value()
            if hasattr(self._mw, 'averageCheckBox'):
                params['average'] = self._mw.averageCheckBox.isChecked()
            
            # Apply settings to hardware
            if params:
                try:
                    self._redpitaya_logic().setup_scope(**params)
                    # Update UI with actual hardware state
                    try:
                        state = self._redpitaya_logic().get_scope_status()
                        self._on_scope_state_changed(state)
                        if hasattr(self._mw, 'statusbar'):
                            self._mw.statusbar.showMessage('Scope settings applied')
                    except Exception as e:
                        self.log.error(f"Failed to update scope state: {e}")
                        if hasattr(self._mw, 'statusbar'):
                            self._mw.statusbar.showMessage('Failed to update scope state')
                except Exception as e:
                    self.log.error(f"Failed to apply scope settings: {e}")
                    if hasattr(self._mw, 'statusbar'):
                        self._mw.statusbar.showMessage('Failed to apply scope settings')
        except Exception as e:
            self.log.error(f"_on_apply_scope: {e}")
            if hasattr(self._mw, 'statusbar'):
                self._mw.statusbar.showMessage('Error applying scope settings')
        finally:
            # Re-enable the apply button
            if apply_btn is not None:
                apply_btn.setEnabled(True)
                apply_btn.setText("Apply Settings")

    @QtCore.Slot(dict)
    def _on_scope_state_changed(self, state):
        """Update UI controls to reflect current hardware scope state."""
        try:
            if not state:
                return
            # Inputs
            if hasattr(self._mw, 'input1Combo') and 'input1' in state:
                i = self._mw.input1Combo.findText(str(state['input1']))
                if i >= 0:
                    self._mw.input1Combo.setCurrentIndex(i)
            if hasattr(self._mw, 'input2Combo') and 'input2' in state:
                i = self._mw.input2Combo.findText(str(state['input2']))
                if i >= 0:
                    self._mw.input2Combo.setCurrentIndex(i)
            # Trigger
            if hasattr(self._mw, 'triggerSourceCombo') and 'trigger_source' in state:
                i = self._mw.triggerSourceCombo.findText(str(state['trigger_source']))
                if i >= 0:
                    self._mw.triggerSourceCombo.setCurrentIndex(i)
            if hasattr(self._mw, 'triggerLevelSpin') and 'trigger_level' in state:
                self._mw.triggerLevelSpin.setValue(float(state['trigger_level']))
            if hasattr(self._mw, 'triggerHystSpin') and 'trigger_hysteresis' in state:
                self._mw.triggerHystSpin.setValue(float(state['trigger_hysteresis']))
            if hasattr(self._mw, 'triggerDelaySpin') and 'trigger_delay' in state:
                self._mw.triggerDelaySpin.setValue(int(state['trigger_delay']))
            # Decimation and averaging
            if hasattr(self._mw, 'decimationSpinBox') and 'decimation' in state:
                self._mw.decimationSpinBox.setValue(int(state['decimation']))
            if hasattr(self._mw, 'averageCheckBox') and 'average' in state:
                self._mw.averageCheckBox.setChecked(bool(state['average']))
        except Exception:
            # Best-effort sync
            pass

    def _update_statistics(self):
        """Update the statistics display."""
        try:
            if self._data['ch1'] is not None and hasattr(self._mw, 'ch1StatsLabel'):
                ch1_stats = f"CH1: Mean={np.mean(self._data['ch1']):.3f}V, "
                ch1_stats += f"RMS={np.sqrt(np.mean(self._data['ch1']**2)):.3f}V, "
                ch1_stats += f"Pk-Pk={np.ptp(self._data['ch1']):.3f}V"
                self._mw.ch1StatsLabel.setText(ch1_stats)
        except Exception:
            pass

        try:
            if self._data['ch2'] is not None and hasattr(self._mw, 'ch2StatsLabel'):
                ch2_stats = f"CH2: Mean={np.mean(self._data['ch2']):.3f}V, "
                ch2_stats += f"RMS={np.sqrt(np.mean(self._data['ch2']**2)):.3f}V, "
                ch2_stats += f"Pk-Pk={np.ptp(self._data['ch2']):.3f}V"
                self._mw.ch2StatsLabel.setText(ch2_stats)
        except Exception:
            pass

    def _save_data(self):
        """Save acquired data to file."""
        if self._data['time'] is None:
            try:
                QtWidgets.QMessageBox.warning(self._mw, 'No Data', 'No data available to save.')
            except Exception:
                pass
            return

        try:
            file_name, _ = QtWidgets.QFileDialog.getSaveFileName(
                self._mw,
                'Save Data',
                '',
                'CSV files (*.csv);;All files (*.*)'
            )

            if file_name:
                data = np.column_stack((
                    self._data['time'],
                    self._data['ch1'],
                    self._data['ch2']
                ))
                np.savetxt(
                    file_name,
                    data,
                    delimiter=',',
                    header='Time (s),CH1 (V),CH2 (V)',
                    comments=''
                )
                if hasattr(self._mw, 'statusbar'):
                    self._mw.statusbar.showMessage(f'Data saved to {file_name}')
        except Exception as e:
            try:
                QtWidgets.QMessageBox.critical(self._mw, 'Error', f'Failed to save data: {str(e)}')
            except Exception:
                pass

    def _load_settings(self):
        """Load settings from file (not implemented)."""
        QtWidgets.QMessageBox.information(self._mw, 'Not implemented', 'Loading settings is not implemented.')

    def _save_settings(self):
        """Save settings to file (not implemented)."""
        QtWidgets.QMessageBox.information(self._mw, 'Not implemented', 'Saving settings is not implemented.')