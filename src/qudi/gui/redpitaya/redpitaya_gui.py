from PySide2 import QtCore, QtWidgets
from qudi.core.connector import Connector
from qudi.core.module import GuiBase

class RedPitayaPyrplGui(GuiBase):
    """Qudi GUI wrapper for PyRPL main widget."""

    # Connectors
    _redpitaya_logic = Connector(name='redpitaya_logic', interface='RedPitayaPyrplLogic')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._logic = None
        self._bias_wrapper_dock = None
        self._bias_wrapper_controls = {}

    def on_activate(self):
        """Initialize the GUI on activation."""
        logic = self._redpitaya_logic()
        if logic is None:
            raise RuntimeError("RedPitaya logic connector is not available.")
        self._logic = logic
            
        pyrpl_instance = logic.get_pyrpl()
        if pyrpl_instance is None:
            raise RuntimeError("PyRPL instance is not available from logic module.")

        # Check if the pyrpl_instance is a remote proxy (using rpyc)
        is_remote = hasattr(pyrpl_instance, '___conn___') or type(pyrpl_instance).__name__ in ('netref', 'BaseNetref')

        if is_remote:
            # We are running on a remote client PC. 
            # We must instantiate the PyrplWidget locally, but passing the remote pyrpl proxy.
            # We must ensure the sub-widgets are also created locally.
            from pyrpl.widgets.pyrpl_widget import PyrplWidget
            import pyrpl.widgets.module_widgets
            
            # Subclass PyrplWidget to override dock widget creation for remote compatibility
            class RemotePyrplWidget(PyrplWidget):
                def __init__(self, pyrpl_instance):
                    # Call QMainWindow constructor and initialize local state
                    QtWidgets.QMainWindow.__init__(self)
                    self.parent = pyrpl_instance
                    self.logger = self.parent.logger
                    
                    self.setDockNestingEnabled(True)
                    self.setAnimated(True)
                    self.dock_widgets = {}
                    self.last_docked = None
                    
                    self.menu_modules = self.menuBar().addMenu("Modules")
                    self.module_actions = []
                    
                    # For each software module, get its local widget class and instantiate it locally
                    for module in self.parent.software_modules:
                        widget_class_name = module._widget_class.__name__
                        local_widget_class = getattr(pyrpl.widgets.module_widgets, widget_class_name)
                        
                        def make_create_widget_func(m, cls):
                            return lambda: cls(m.name, m)
                            
                        local_create_fn = make_create_widget_func(module, local_widget_class)
                        self.add_dock_widget(local_create_fn, module.name)
                        
                    self.centralwidget = QtWidgets.QFrame()
                    self.setCentralWidget(self.centralwidget)
                    self.centrallayout = QtWidgets.QVBoxLayout()
                    self.centrallayout.setAlignment(QtCore.Qt.AlignCenter)
                    self.centralwidget.setLayout(self.centrallayout)
                    self.centralbutton = QtWidgets.QPushButton(
                        'Click on "Modules" in the upper left corner to load a specific PyRPL module!'
                    )
                    self.centralbutton.clicked.connect(self.click_menu_modules)
                    self.centrallayout.addWidget(self.centralbutton)
                    
                    self.timer_save_pos = QtCore.QTimer()
                    self.timer_toolbar = QtCore.QTimer()
                    self.status_bar = self.statusBar()
                    self.setWindowTitle(f"{self.parent.c.pyrpl.name} (Remote)")
            
            self._mw = RemotePyrplWidget(pyrpl_instance)
        else:
            # We are running locally on the server PC. 
            if len(pyrpl_instance.widgets) == 0:
                self._mw = pyrpl_instance._create_widget()
            else:
                self._mw = pyrpl_instance.widgets[0]

        self._create_bias_wrapper_dock()
        self._logic.sigPidBiasWrapperStatus.connect(
            self._update_bias_wrapper_status,
            QtCore.Qt.QueuedConnection,
        )
        self._update_bias_wrapper_status(
            self._logic.get_pid_bias_wrapper_status()
        )

        # Show the main window
        self.show()

    def on_deactivate(self):
        """Clean up before deactivating module."""
        if self._logic is not None:
            self._logic.stop_pid_bias_wrapper()
            try:
                self._logic.sigPidBiasWrapperStatus.disconnect(
                    self._update_bias_wrapper_status
                )
            except (RuntimeError, TypeError):
                pass
        if self._bias_wrapper_dock is not None:
            try:
                self._mw.removeDockWidget(self._bias_wrapper_dock)
                self._bias_wrapper_dock.deleteLater()
            except (AttributeError, RuntimeError):
                pass
            self._bias_wrapper_dock = None
            self._bias_wrapper_controls = {}
        if self._mw is not None:
            try:
                self._mw.close()
            except Exception:
                pass
            self._mw = None
        self._logic = None

    def _create_bias_wrapper_dock(self):
        """Add a non-intrusive bias-wrapper panel to the PyRPL window."""
        dock = QtWidgets.QDockWidget("EOM Bias Wrapper", self._mw)
        dock.setObjectName("eom_bias_wrapper_dock")
        panel = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(panel)
        form = QtWidgets.QFormLayout()

        pid_channel = QtWidgets.QSpinBox(panel)
        pid_channel.setRange(0, 2)
        pid_channel.setValue(0)

        vpi = self._make_double_spinbox(
            panel, 0.001, 4.0, 0.36, 4, 0.01
        )
        minimum = self._make_double_spinbox(
            panel, -4.0, 4.0, -0.6, 3, 0.05
        )
        maximum = self._make_double_spinbox(
            panel, -4.0, 4.0, 0.6, 3, 0.05
        )
        margin = self._make_double_spinbox(
            panel, 0.0, 2.0, 0.05, 3, 0.01
        )
        interval = self._make_double_spinbox(
            panel, 0.2, 60.0, 1.0, 1, 0.5
        )
        recovery = QtWidgets.QCheckBox("erlauben", panel)
        recovery.setChecked(True)

        form.addRow("PID-Kanal", pid_channel)
        form.addRow("Vpi", vpi)
        form.addRow("Minimum", minimum)
        form.addRow("Maximum", maximum)
        form.addRow("Sicherheitsabstand", margin)
        form.addRow("Pruefintervall (s)", interval)
        form.addRow("Windup-Recovery", recovery)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        preview_button = QtWidgets.QPushButton("Preview", panel)
        start_button = QtWidgets.QPushButton("Start", panel)
        stop_button = QtWidgets.QPushButton("Stop", panel)
        buttons.addWidget(preview_button)
        buttons.addWidget(start_button)
        buttons.addWidget(stop_button)
        layout.addLayout(buttons)

        status = QtWidgets.QLabel("Gestoppt", panel)
        status.setWordWrap(True)
        status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(status)
        layout.addStretch(1)

        self._bias_wrapper_controls = {
            'pid_channel': pid_channel,
            'vpi': vpi,
            'minimum': minimum,
            'maximum': maximum,
            'margin': margin,
            'interval': interval,
            'recovery': recovery,
            'preview_button': preview_button,
            'start_button': start_button,
            'stop_button': stop_button,
            'status': status,
        }
        preview_button.clicked.connect(self._preview_bias_wrapper)
        start_button.clicked.connect(self._start_bias_wrapper)
        stop_button.clicked.connect(self._stop_bias_wrapper)

        dock.setWidget(panel)
        self._mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self._bias_wrapper_dock = dock

    @staticmethod
    def _make_double_spinbox(parent, minimum, maximum, value, decimals, step):
        widget = QtWidgets.QDoubleSpinBox(parent)
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setValue(value)
        return widget

    def _bias_wrapper_settings(self):
        controls = self._bias_wrapper_controls
        return {
            'pid_channel': controls['pid_channel'].value(),
            'vpi': controls['vpi'].value(),
            'min_value': controls['minimum'].value(),
            'max_value': controls['maximum'].value(),
            'margin': controls['margin'].value(),
        }

    @QtCore.Slot()
    def _preview_bias_wrapper(self):
        try:
            preview = self._logic.get_pid_wrap_preview(
                **self._bias_wrapper_settings()
            )
            preview.update(
                enabled=self._logic.get_pid_bias_wrapper_status().get(
                    'enabled', False
                ),
                state='preview',
            )
            self._update_bias_wrapper_status(preview)
        except Exception as error:
            self._show_bias_wrapper_error(error)

    @QtCore.Slot()
    def _start_bias_wrapper(self):
        try:
            settings = self._bias_wrapper_settings()
            settings.update(
                interval_seconds=(
                    self._bias_wrapper_controls['interval'].value()
                ),
                allow_windup_recovery=(
                    self._bias_wrapper_controls['recovery'].isChecked()
                ),
            )
            self._logic.start_pid_bias_wrapper(**settings)
        except Exception as error:
            self._show_bias_wrapper_error(error)

    @QtCore.Slot()
    def _stop_bias_wrapper(self):
        if self._logic is not None:
            self._logic.stop_pid_bias_wrapper()

    @QtCore.Slot(object)
    def _update_bias_wrapper_status(self, status):
        if not self._bias_wrapper_controls:
            return
        state = status.get('state', 'stopped')
        enabled = bool(status.get('enabled', False))
        output = status.get('output')
        integrator = status.get('integrator_after')
        write_result = status.get('write_result', {})
        wrap_count = status.get('wrap_count', 0)
        details = [
            f"Status: {state}",
            f"aktiv: {'ja' if enabled else 'nein'}",
            f"Wraps: {wrap_count}",
        ]
        if output is not None:
            details.append(f"PID-Ausgang: {float(output):+.6f}")
        if integrator is not None:
            details.append(f"Integrator: {float(integrator):+.6f}")
        if write_result.get('written_output') is not None:
            details.append(
                "PID-Ausgang nach Wrap: "
                f"{float(write_result['written_output']):+.6f}"
            )
        if status.get('should_wrap'):
            target = status.get('target_output')
            if target is not None:
                details.append(f"Ziel-Ausgang: {float(target):+.6f}")
        error = status.get('error')
        if error:
            details.append(f"Grund: {error}")

        label = self._bias_wrapper_controls['status']
        label.setText("\n".join(details))
        if state in ('error', 'blocked'):
            label.setStyleSheet("color: #ff6666;")
        elif enabled:
            label.setStyleSheet("color: #66cc66;")
        else:
            label.setStyleSheet("")
        for name in (
            'pid_channel',
            'vpi',
            'minimum',
            'maximum',
            'margin',
            'interval',
            'recovery',
        ):
            self._bias_wrapper_controls[name].setEnabled(not enabled)
        self._bias_wrapper_controls['start_button'].setEnabled(not enabled)
        self._bias_wrapper_controls['stop_button'].setEnabled(enabled)

    def _show_bias_wrapper_error(self, error):
        self._update_bias_wrapper_status({
            'enabled': False,
            'state': 'error',
            'error': str(error),
            'wrap_count': 0,
        })

    def show(self):
        """Show the main window."""
        if self._mw is not None:
            self._mw.show()
            self._mw.raise_()
