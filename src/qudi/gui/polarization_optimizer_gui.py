"""Control panel for MPC320 polarization optimization and stabilization."""

from collections import deque
import time

import pyqtgraph as pg
from PySide2 import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.core.statusvariable import StatusVar


class PolarizationOptimizerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Polarization stabilization')
        self.resize(960, 760)
        self.setStyleSheet('''
            QGroupBox { font-weight: 600; margin-top: 8px; padding-top: 10px; }
            QPushButton { min-height: 36px; padding: 4px 14px; }
            QPushButton#lockButton { font-weight: 600; }
            QLabel#powerLabel { font-size: 20px; font-weight: 700; }
            QLabel#polarizationStatus {
                font-size: 17px;
                font-weight: 700;
                padding: 9px 14px;
                border-radius: 6px;
            }
            QLabel#actionLabel {
                padding: 6px 9px;
                background: palette(alternate-base);
                border-radius: 4px;
            }
            QLabel#paddleValue {
                font-size: 16px;
                font-weight: 700;
                padding: 7px 14px;
                border: 1px solid palette(mid);
                border-radius: 5px;
                background: palette(base);
            }
        ''')

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        self.power_label = QtWidgets.QLabel('Power: -- nW')
        self.power_label.setObjectName('powerLabel')
        self.best_power_label = QtWidgets.QLabel('Best found: -- nW')
        self.recording_label = QtWidgets.QLabel('Recording: off')
        header.addWidget(self.power_label)
        header.addWidget(self.best_power_label)
        header.addStretch()
        header.addWidget(self.recording_label)
        layout.addLayout(header)

        paddle_group = QtWidgets.QGroupBox('Current paddle positions')
        paddle_layout = QtWidgets.QHBoxLayout(paddle_group)
        self.paddle_labels = []
        for paddle in range(1, 4):
            column = QtWidgets.QVBoxLayout()
            title = QtWidgets.QLabel(f'Paddle {paddle}')
            title.setAlignment(QtCore.Qt.AlignCenter)
            value = QtWidgets.QLabel('--.--°')
            value.setObjectName('paddleValue')
            value.setAlignment(QtCore.Qt.AlignCenter)
            column.addWidget(title)
            column.addWidget(value)
            paddle_layout.addLayout(column)
            self.paddle_labels.append(value)
        layout.addWidget(paddle_group)

        process_group = QtWidgets.QGroupBox('Polarization process')
        process_layout = QtWidgets.QVBoxLayout(process_group)
        self.polarization_status = QtWidgets.QLabel('Waiting for power')
        self.polarization_status.setObjectName('polarizationStatus')
        self.polarization_status.setAlignment(QtCore.Qt.AlignCenter)
        process_layout.addWidget(self.polarization_status)
        action_row = QtWidgets.QHBoxLayout()
        action_title = QtWidgets.QLabel('Current action:')
        action_title.setStyleSheet('font-weight: 600;')
        self.action_label = QtWidgets.QLabel('Waiting')
        self.action_label.setObjectName('actionLabel')
        action_row.addWidget(action_title)
        action_row.addWidget(self.action_label, stretch=1)
        process_layout.addLayout(action_row)
        priority_row = QtWidgets.QHBoxLayout()
        priority_title = QtWidgets.QLabel('Active priority:')
        priority_title.setStyleSheet('font-weight: 600;')
        self.priority_light = QtWidgets.QLabel()
        self.priority_light.setFixedSize(14, 14)
        self.priority_light.setToolTip('The control policy currently taking precedence')
        self.priority_label = QtWidgets.QLabel('Idle')
        priority_row.addWidget(priority_title)
        priority_row.addWidget(self.priority_light)
        priority_row.addWidget(self.priority_label, stretch=1)
        process_layout.addLayout(priority_row)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat('Idle')
        self.progress.setVisible(False)
        process_layout.addWidget(self.progress)
        self.elapsed_label = QtWidgets.QLabel('')
        self.elapsed_label.setAlignment(QtCore.Qt.AlignRight)
        self.elapsed_label.setVisible(False)
        process_layout.addWidget(self.elapsed_label)
        layout.addWidget(process_group)

        plot_header = QtWidgets.QHBoxLayout()
        plot_title = QtWidgets.QLabel('Power history')
        plot_title.setStyleSheet('font-weight: 600;')
        state_key = QtWidgets.QLabel(
            '<span style="color:#2e7d32">● okay</span> &nbsp; '
            '<span style="color:#b3261e">● drifting</span> &nbsp; '
            '<span style="color:#d89b00">● optimizing</span>'
        )
        self.log_button = QtWidgets.QPushButton('Start log')
        self.log_button.setToolTip('Logging is independent and also starts automatically with any operation')
        plot_header.addWidget(plot_title)
        plot_header.addWidget(state_key)
        plot_header.addStretch()
        plot_header.addWidget(self.log_button)
        layout.addLayout(plot_header)

        self.plot = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(orientation='bottom')}
        )
        self.plot.setLabel('left', 'Power', units='nW')
        self.plot.setLabel('bottom', 'Timestamp')
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot(pen=pg.mkPen('#3daee9', width=2))
        self.state_points = pg.ScatterPlotItem(size=7, pen=None)
        self.plot.addItem(self.state_points)
        self.threshold_line = pg.InfiniteLine(
            angle=0, pen=pg.mkPen('#e85d75', style=QtCore.Qt.DashLine)
        )
        self.plot.addItem(self.threshold_line)
        layout.addWidget(self.plot, stretch=1)

        self.position_plot = pg.PlotWidget(
            axisItems={'bottom': pg.DateAxisItem(orientation='bottom')}
        )
        self.position_plot.setLabel('left', 'Paddle angle', units='°')
        self.position_plot.setLabel('bottom', 'Timestamp')
        self.position_plot.setYRange(0, 160)
        self.position_plot.setXLink(self.plot)
        self.position_plot.showGrid(x=True, y=True, alpha=0.25)
        self.position_plot.addLegend(offset=(10, 10))
        self.paddle_curves = [
            self.position_plot.plot(pen=pg.mkPen(color, width=2), name=f'Paddle {index}')
            for index, color in enumerate(('#f59e0b', '#8b5cf6', '#10b981'), start=1)
        ]
        edge_pen = pg.mkPen('#e85d75', style=QtCore.Qt.DashLine)
        self.edge_lower_line = pg.InfiniteLine(angle=0, pen=edge_pen)
        self.edge_upper_line = pg.InfiniteLine(angle=0, pen=edge_pen)
        self.position_plot.addItem(self.edge_lower_line)
        self.position_plot.addItem(self.edge_upper_line)
        layout.addWidget(self.position_plot, stretch=1)

        settings_group = QtWidgets.QGroupBox('Settings')
        settings = QtWidgets.QFormLayout(settings_group)
        self.threshold_spin = QtWidgets.QDoubleSpinBox()
        self.threshold_spin.setRange(0.01, 1e9)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSuffix(' nW')
        self.hold_threshold_spin = QtWidgets.QDoubleSpinBox()
        self.hold_threshold_spin.setRange(0.0, 1e9)
        self.hold_threshold_spin.setDecimals(2)
        self.hold_threshold_spin.setSuffix(' nW')
        self.edge_margin_spin = QtWidgets.QDoubleSpinBox()
        self.edge_margin_spin.setRange(0.0, 79.9)
        self.edge_margin_spin.setDecimals(2)
        self.edge_margin_spin.setSuffix(' °')
        self.fine_initial_spin = QtWidgets.QDoubleSpinBox()
        self.fine_initial_spin.setRange(0.01, 20.0)
        self.fine_initial_spin.setDecimals(3)
        self.fine_initial_spin.setSuffix(' °')
        self.fine_final_spin = QtWidgets.QDoubleSpinBox()
        self.fine_final_spin.setRange(0.01, 20.0)
        self.fine_final_spin.setDecimals(3)
        self.fine_final_spin.setSuffix(' °')
        self.fine_levels_spin = QtWidgets.QSpinBox()
        self.fine_levels_spin.setRange(2, 12)
        self.log_duration_spin = QtWidgets.QDoubleSpinBox()
        self.log_duration_spin.setRange(1.0, 24 * 3600.0)
        self.log_duration_spin.setSuffix(' s')
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.05, 3600.0)
        self.interval_spin.setDecimals(2)
        self.interval_spin.setSuffix(' s')
        self.continuous_log = QtWidgets.QCheckBox('Continuous logging')
        settings.addRow('Master power threshold:', self.threshold_spin)
        settings.addRow('Hold threshold:', self.hold_threshold_spin)
        settings.addRow('Forbidden edge margin:', self.edge_margin_spin)
        settings.addRow('Fine initial step:', self.fine_initial_spin)
        settings.addRow('Fine final step:', self.fine_final_spin)
        settings.addRow('Logarithmic step levels:', self.fine_levels_spin)
        settings.addRow('Log duration:', self.log_duration_spin)
        settings.addRow('Log / lock interval:', self.interval_spin)
        settings.addRow(self.continuous_log)
        layout.addWidget(settings_group)

        operations = QtWidgets.QGroupBox('Polarization operations')
        operation_layout = QtWidgets.QGridLayout(operations)
        self.coarse_button = QtWidgets.QPushButton('Coarse optimisation')
        self.fine_button = QtWidgets.QPushButton('Fine optimisation')
        self.coarse_fine_button = QtWidgets.QPushButton('Coarse + fine optimisation')
        self.lock_button = QtWidgets.QPushButton('Lock polarisation')
        self.lock_button.setObjectName('lockButton')
        operation_layout.addWidget(self.coarse_button, 0, 0)
        operation_layout.addWidget(self.fine_button, 0, 1)
        operation_layout.addWidget(self.coarse_fine_button, 1, 0)
        operation_layout.addWidget(self.lock_button, 1, 1)
        layout.addWidget(operations)

        # Keep the graph central and expose controls as standard movable Qudi
        # dock widgets. Each panel can be moved, floated, hidden, or restored
        # from the View menu.
        for panel in (paddle_group, process_group, settings_group, operations):
            layout.removeWidget(panel)
        self.setDockOptions(
            QtWidgets.QMainWindow.AnimatedDocks |
            QtWidgets.QMainWindow.AllowNestedDocks |
            QtWidgets.QMainWindow.AllowTabbedDocks
        )
        self._docks = []
        paddle_dock = self._add_dock('Paddle positions', paddle_group, QtCore.Qt.TopDockWidgetArea)
        settings_dock = self._add_dock('Parameters', settings_group, QtCore.Qt.TopDockWidgetArea)
        process_dock = self._add_dock('Process', process_group, QtCore.Qt.TopDockWidgetArea)
        operations_dock = self._add_dock(
            'Operations', operations, QtCore.Qt.BottomDockWidgetArea
        )
        self.splitDockWidget(paddle_dock, settings_dock, QtCore.Qt.Horizontal)
        self.splitDockWidget(settings_dock, process_dock, QtCore.Qt.Horizontal)

        view_menu = self.menuBar().addMenu('View')
        for dock in self._docks:
            view_menu.addAction(dock.toggleViewAction())

    def _add_dock(self, title, widget, area):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(f'polarization_{title.lower().replace(" ", "_")}_dock')
        dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable |
            QtWidgets.QDockWidget.DockWidgetClosable
        )
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        self._docks.append(dock)
        return dock


class PolarizationOptimizerGui(GuiBase):
    optimizer = Connector(interface='PolarizationOptimizerLogic')
    _saved_dock_layout = StatusVar(name='saved_dock_layout', default=None)

    _manual_operations = {
        'Coarse optimisation',
        'Fine optimisation',
        'Coarse + fine optimisation',
    }

    def on_activate(self):
        self._logic = self.optimizer()
        self._mw = PolarizationOptimizerWindow()
        self._times = deque(maxlen=10000)
        self._powers = deque(maxlen=10000)
        self._logged_positions = [deque(maxlen=10000) for _ in range(3)]
        self._logged_states = deque(maxlen=10000)
        self._plot_started = time.monotonic()
        self._logging = False
        self._operation = 'Idle'
        self._current_action = 'Waiting'
        self._last_power = None
        self._progress_started = None
        self._progress_budget = 0.0
        self._progress_timer = QtCore.QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._refresh_progress)
        self._progress_timer.start()

        self._mw.threshold_spin.setValue(float(self._logic.threshold))
        self._mw.hold_threshold_spin.setMaximum(max(0.0, self._mw.threshold_spin.value() - 0.01))
        self._mw.hold_threshold_spin.setValue(min(float(self._logic.hold_threshold), self._mw.hold_threshold_spin.maximum()))
        self._mw.log_duration_spin.setValue(300.0)
        self._mw.interval_spin.setValue(float(self._logic._lock_interval_s))
        self._mw.threshold_line.setValue(self._mw.threshold_spin.value())
        self._mw.edge_margin_spin.setValue(self._logic._edge_margin())
        self._mw.fine_initial_spin.setValue(float(self._logic._fine_initial_step_deg))
        self._mw.fine_final_spin.setValue(float(self._logic._fine_final_step_deg))
        self._mw.fine_levels_spin.setValue(int(self._logic._fine_step_levels))
        self._update_edge_lines(self._mw.edge_margin_spin.value())
        self._mw.continuous_log.toggled.connect(
            lambda checked: self._mw.log_duration_spin.setEnabled(not checked)
        )
        self._mw.threshold_spin.valueChanged.connect(self._threshold_changed)
        self._mw.hold_threshold_spin.valueChanged.connect(self._hold_threshold_changed)
        self._mw.edge_margin_spin.valueChanged.connect(self._edge_margin_changed)
        self._mw.fine_initial_spin.valueChanged.connect(self._fine_steps_changed)
        self._mw.fine_final_spin.valueChanged.connect(self._fine_steps_changed)
        self._mw.fine_levels_spin.valueChanged.connect(self._fine_steps_changed)
        self._mw.log_button.clicked.connect(self._toggle_log)
        self._mw.coarse_button.clicked.connect(
            lambda: self._toggle_manual('Coarse optimisation', self._logic.start_coarse_optimization)
        )
        self._mw.fine_button.clicked.connect(
            lambda: self._toggle_manual('Fine optimisation', self._logic.start_fine_optimization)
        )
        self._mw.coarse_fine_button.clicked.connect(
            lambda: self._toggle_manual(
                'Coarse + fine optimisation', self._logic.start_coarse_fine_optimization
            )
        )
        self._mw.lock_button.clicked.connect(self._toggle_lock)

        self._logic.sigPowerUpdated.connect(self._show_power, QtCore.Qt.QueuedConnection)
        self._logic.sigLogSample.connect(self._append_log_sample, QtCore.Qt.QueuedConnection)
        self._logic.sigBestPowerUpdated.connect(self._show_best_power, QtCore.Qt.QueuedConnection)
        self._logic.sigPaddlePositionsUpdated.connect(
            self._show_paddle_positions, QtCore.Qt.QueuedConnection
        )
        self._logic.sigLogStateChanged.connect(self._set_log_state, QtCore.Qt.QueuedConnection)
        self._logic.sigLockStateChanged.connect(self._set_lock_state, QtCore.Qt.QueuedConnection)
        self._logic.sigProcessStateChanged.connect(self._set_operation, QtCore.Qt.QueuedConnection)
        self._logic.sigCurrentActionChanged.connect(self._set_action, QtCore.Qt.QueuedConnection)
        self._logic.sigLockPriorityChanged.connect(self._set_lock_priority, QtCore.Qt.QueuedConnection)
        self._logic.sigActivePaddlesChanged.connect(self._set_active_paddles, QtCore.Qt.QueuedConnection)
        self._logic.sigElapsedProgress.connect(self._set_progress, QtCore.Qt.QueuedConnection)
        self._logic.sigError.connect(self._show_error, QtCore.Qt.QueuedConnection)
        self._set_lock_priority('idle')
        self._set_active_paddles(())
        self._update_controls()
        self._update_polarization_status()
        self._show_paddle_positions(*self._logic.current_angles())
        self._restore_window_geometry(self._mw)
        if self._saved_dock_layout is not None:
            self._mw.restoreState(self._saved_dock_layout)
        self._mw.show()

    def on_deactivate(self):
        self._logic.stop_optimization()
        self._logic.stop_lock()
        self._logic.stop_log()
        self._save_window_geometry(self._mw)
        self._saved_dock_layout = self._mw.saveState().data()
        self._mw.close()

    def show(self):
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _ensure_log_running(self):
        if self._logging or (self._logic._log_thread and self._logic._log_thread.is_alive()):
            return
        self._reset_plot()
        duration = self._mw.log_duration_spin.value()
        interval = self._mw.interval_spin.value()
        self._logic.start_log(duration, interval, self._mw.continuous_log.isChecked())

    def _toggle_log(self):
        if self._logging:
            self._logic.request_stop_log()
        else:
            self._ensure_log_running()

    def _toggle_manual(self, name, starter):
        if self._operation == name:
            self._logic.stop_optimization()
            return
        self._ensure_log_running()
        starter(self._mw.threshold_spin.value())

    def _toggle_lock(self):
        if self._operation == 'Polarisation lock':
            self._logic.request_stop_lock()
            return
        self._ensure_log_running()
        self._logic.start_lock(
            threshold=self._mw.threshold_spin.value(),
            interval=self._mw.interval_spin.value(),
        )

    def _reset_plot(self):
        self._times.clear()
        self._powers.clear()
        for positions in self._logged_positions:
            positions.clear()
        self._logged_states.clear()
        self._plot_started = time.monotonic()
        self._mw.curve.setData([], [])
        self._mw.state_points.setData([], [])
        for curve in self._mw.paddle_curves:
            curve.setData([], [])

    @QtCore.Slot(float)
    def _show_power(self, power):
        self._last_power = float(power)
        self._mw.power_label.setText(f'Power: {power:.2f} nW')
        self._update_polarization_status()

    @QtCore.Slot(float, float, object, str)
    def _append_log_sample(self, timestamp, power, positions, state):
        self._times.append(timestamp)
        self._powers.append(power)
        self._logged_states.append(state)
        for values, position in zip(self._logged_positions, positions):
            values.append(float(position))

        times = list(self._times)
        powers = list(self._powers)
        self._mw.curve.setData(times, powers)
        brushes = {
            'Polarisation okay': pg.mkBrush('#2e7d32'),
            'Polarisation drifting': pg.mkBrush('#b3261e'),
            'Polarisation optimizing': pg.mkBrush('#d89b00'),
        }
        self._mw.state_points.setData(
            times,
            powers,
            brush=[brushes.get(value, pg.mkBrush('#6b7280')) for value in self._logged_states],
        )
        for curve, values in zip(self._mw.paddle_curves, self._logged_positions):
            curve.setData(times, list(values))

    @QtCore.Slot(float)
    def _threshold_changed(self, threshold):
        self._logic.set_threshold(threshold)
        max_hold = max(0.0, float(threshold) - 0.01)
        self._mw.hold_threshold_spin.setMaximum(max_hold)
        if self._mw.hold_threshold_spin.value() >= threshold:
            self._mw.hold_threshold_spin.setValue(max_hold)
        self._logic.set_hold_threshold(self._mw.hold_threshold_spin.value())
        self._mw.threshold_line.setValue(threshold)
        self._update_polarization_status()

    @QtCore.Slot(float)
    def _hold_threshold_changed(self, threshold):
        try:
            self._logic.set_hold_threshold(threshold)
        except ValueError:
            max_hold = max(0.0, self._mw.threshold_spin.value() - 0.01)
            self._mw.hold_threshold_spin.setValue(max_hold)
        self._update_polarization_status()

    @QtCore.Slot(float)
    def _edge_margin_changed(self, margin):
        self._logic.set_edge_margin(margin)
        self._update_edge_lines(margin)

    def _fine_steps_changed(self, _value):
        self._logic.set_fine_step_settings(
            self._mw.fine_initial_spin.value(),
            self._mw.fine_final_spin.value(),
            self._mw.fine_levels_spin.value(),
        )

    def _update_edge_lines(self, margin):
        self._mw.edge_lower_line.setValue(float(margin))
        self._mw.edge_upper_line.setValue(160.0 - float(margin))

    @QtCore.Slot(float)
    def _show_best_power(self, power):
        self._mw.best_power_label.setText(f'Best found: {power:.2f} nW')

    @QtCore.Slot(float, float, float)
    def _show_paddle_positions(self, paddle1, paddle2, paddle3):
        for label, position in zip(
            self._mw.paddle_labels, (paddle1, paddle2, paddle3)
        ):
            label.setText(f'{position:.2f}°')

    @QtCore.Slot(bool)
    def _set_log_state(self, active):
        self._logging = bool(active)
        self._mw.recording_label.setText('Recording: active' if active else 'Recording: off')
        self._mw.log_button.setText('Stop log' if active else 'Start log')

    @QtCore.Slot(bool)
    def _set_lock_state(self, active):
        """Provide a GUI-safe fallback if a lock worker exits unexpectedly."""
        if not active and self._operation == 'Polarisation lock':
            self._operation = 'Idle'
            self._current_action = 'Waiting'
            self._mw.action_label.setText('Waiting')
            self._set_lock_priority('idle')
            self._update_polarization_status()
            self._update_controls()

    @QtCore.Slot(str)
    def _set_lock_priority(self, priority):
        states = {
            'idle': ('Idle', '#6b7280'),
            'monitoring': ('Monitoring', '#2e7d32'),
            'hold_trim': ('Hold-threshold trim', '#d89b00'),
            'master_debounce': ('Master threshold confirmation', '#e87516'),
            'master_recovery': ('Master-threshold recovery', '#b3261e'),
            'equivalent_relocation': ('Equivalent lambda/2 minimum relocation', '#7c3aed'),
            'edge_recovery': ('Edge recovery (highest priority)', '#a21caf'),
            'stopping': ('Stopping lock', '#6b7280'),
        }
        text, color = states.get(str(priority), ('Unknown', '#6b7280'))
        self._mw.priority_label.setText(text)
        self._mw.priority_light.setStyleSheet(
            f'background-color: {color}; border: 1px solid #374151; border-radius: 7px;'
        )

    @QtCore.Slot(object)
    def _set_active_paddles(self, active_axes):
        try:
            active = {int(axis) for axis in active_axes}
        except (TypeError, ValueError):
            active = set()
        for index, label in enumerate(self._mw.paddle_labels):
            if index in active:
                label.setStyleSheet('color: #d97706; font-weight: 800;')
            else:
                label.setStyleSheet('')
    @QtCore.Slot(str)
    def _set_operation(self, operation):
        self._operation = operation
        show_progress = operation in self._manual_operations
        self._mw.progress.setVisible(show_progress)
        self._mw.elapsed_label.setVisible(show_progress)
        if operation in self._manual_operations:
            self._mw.best_power_label.setText('Best found: -- nW')
        if operation == 'Idle':
            self._progress_started = None
            self._progress_budget = 0.0
            self._mw.progress.setValue(0)
            self._mw.progress.setFormat('Idle')
            self._mw.elapsed_label.clear()
        self._update_polarization_status()
        self._update_controls()

    @QtCore.Slot(str)
    def _set_action(self, action):
        self._current_action = action
        self._mw.action_label.setText(action)
        self._update_polarization_status()

    @QtCore.Slot(int, float, float)
    def _set_progress(self, percent, elapsed, budget):
        if self._operation == 'Polarisation lock' or budget <= 0:
            self._progress_started = None
            self._progress_budget = 0.0
            self._mw.progress.setRange(0, 100)
            self._mw.progress.setValue(0)
            self._mw.progress.setFormat('Continuous')
            self._mw.elapsed_label.setText(f'Lock active for {elapsed:.0f} s')
            return
        self._progress_started = time.monotonic() - elapsed
        self._progress_budget = budget
        self._mw.progress.setRange(0, 100)
        self._mw.progress.setValue(percent)
        self._mw.progress.setFormat('%p% of time budget')
        self._mw.elapsed_label.setText(f'{elapsed:.1f} s elapsed / {budget:.0f} s maximum')

    @QtCore.Slot()
    def _refresh_progress(self):
        if self._progress_started is None or self._progress_budget <= 0:
            return
        elapsed = time.monotonic() - self._progress_started
        percent = min(99, round(100 * elapsed / self._progress_budget))
        self._mw.progress.setValue(percent)
        self._mw.elapsed_label.setText(
            f'{elapsed:.1f} s elapsed / {self._progress_budget:.0f} s maximum'
        )

    @QtCore.Slot(str)
    def _show_error(self, message):
        self._set_status_style('Polarisation error', '#b3261e', '#ffffff')
        self._mw.action_label.setText(f'Error: {message}')
        QtWidgets.QMessageBox.critical(self._mw, 'Polarization optimizer error', message)

    def _update_polarization_status(self):
        correcting_lock = (
            self._operation == 'Polarisation lock' and
            self._current_action not in {'Waiting', 'Monitoring optical power for drift'}
        )
        if self._operation in self._manual_operations or correcting_lock:
            self._set_status_style('Polarisation optimizing', '#d89b00', '#1f1f1f')
        elif self._last_power is None:
            self._set_status_style('Waiting for power', '#6b7280', '#ffffff')
        elif self._last_power <= self._mw.hold_threshold_spin.value():
            self._set_status_style('Polarisation okay', '#2e7d32', '#ffffff')
        elif self._last_power < self._mw.threshold_spin.value():
            self._set_status_style('Fine trim zone', '#d89b00', '#1f1f1f')
        else:
            self._set_status_style('Polarisation drifting', '#b3261e', '#ffffff')

    def _set_status_style(self, text, background, foreground):
        self._mw.polarization_status.setText(text)
        self._mw.polarization_status.setStyleSheet(
            f'background-color: {background}; color: {foreground};'
        )

    def _update_controls(self):
        active = self._operation != 'Idle'
        mapping = (
            (self._mw.coarse_button, 'Coarse optimisation'),
            (self._mw.fine_button, 'Fine optimisation'),
            (self._mw.coarse_fine_button, 'Coarse + fine optimisation'),
            (self._mw.lock_button, 'Polarisation lock'),
        )
        for button, operation in mapping:
            is_current = self._operation == operation
            button.setEnabled(not active or is_current)
            if operation == 'Polarisation lock':
                base_text = 'Lock polarisation'
                stop_text = 'Stop lock'
            else:
                base_text = operation
                stop_text = f'Stop {operation.lower()}'
            button.setText(stop_text if is_current else base_text)
