"""Live control panel for the MPC320 polarization optimizer."""

from collections import deque

import pyqtgraph as pg
from PySide2 import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase


class PolarizationOptimizerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Polarization stabilization')
        self.resize(900, 650)
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        self.power_label = QtWidgets.QLabel('Power: -- nW')
        self.power_label.setStyleSheet('font-size: 18px; font-weight: bold;')
        self.state_label = QtWidgets.QLabel('Log: stopped   |   Lock: stopped')
        self.activity_label = QtWidgets.QLabel('Activity: idle')
        layout.addWidget(self.power_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.activity_label)

        self.plot = pg.PlotWidget()
        self.plot.setLabel('left', 'Power', units='nW')
        self.plot.setLabel('bottom', 'Time', units='s')
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot(pen=pg.mkPen('#3daee9', width=2))
        self.threshold_line = pg.InfiniteLine(angle=0, pen=pg.mkPen('#e85d75', style=QtCore.Qt.DashLine))
        self.plot.addItem(self.threshold_line)
        layout.addWidget(self.plot, stretch=1)

        settings = QtWidgets.QGroupBox('Run settings')
        form = QtWidgets.QFormLayout(settings)
        self.threshold_spin = QtWidgets.QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1e9)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSuffix(' nW')
        self.log_duration_spin = QtWidgets.QDoubleSpinBox()
        self.log_duration_spin.setRange(1.0, 24 * 3600.0)
        self.log_duration_spin.setSuffix(' s')
        self.lock_duration_spin = QtWidgets.QDoubleSpinBox()
        self.lock_duration_spin.setRange(1.0, 24 * 3600.0)
        self.lock_duration_spin.setSuffix(' s')
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.05, 3600.0)
        self.interval_spin.setDecimals(2)
        self.interval_spin.setSuffix(' s')
        self.continuous_log = QtWidgets.QCheckBox('Continuous logging')
        self.continuous_lock = QtWidgets.QCheckBox('Continuous locking')
        form.addRow('Power threshold:', self.threshold_spin)
        form.addRow('Log length:', self.log_duration_spin)
        form.addRow('Lock length:', self.lock_duration_spin)
        form.addRow('Sample / lock interval:', self.interval_spin)
        form.addRow(self.continuous_log)
        form.addRow(self.continuous_lock)
        layout.addWidget(settings)

        controls = QtWidgets.QGridLayout()
        self.minimize_button = QtWidgets.QPushButton('Minimize once')
        self.start_log_button = QtWidgets.QPushButton('Start log')
        self.run_all_button = QtWidgets.QPushButton('Minimize + lock + log')
        self.stop_lock_button = QtWidgets.QPushButton('Stop locking')
        self.stop_log_button = QtWidgets.QPushButton('Stop log')
        controls.addWidget(self.minimize_button, 0, 0)
        controls.addWidget(self.start_log_button, 0, 1)
        controls.addWidget(self.run_all_button, 0, 2)
        controls.addWidget(self.stop_lock_button, 1, 0)
        controls.addWidget(self.stop_log_button, 1, 1)
        layout.addLayout(controls)


class PolarizationOptimizerGui(GuiBase):
    """Qudi GUI for live plotting, logging, and polarization locking."""

    optimizer = Connector(interface='PolarizationOptimizerLogic')

    def on_activate(self):
        self._logic = self.optimizer()
        self._mw = PolarizationOptimizerWindow()
        self._times = deque(maxlen=10000)
        self._powers = deque(maxlen=10000)
        self._logging = False
        self._locking = False

        self._mw.threshold_spin.setValue(float(self._logic._lock_threshold_nw))
        self._mw.log_duration_spin.setValue(300.0)
        self._mw.lock_duration_spin.setValue(300.0)
        self._mw.interval_spin.setValue(float(self._logic._lock_interval_s))
        self._mw.threshold_line.setValue(self._mw.threshold_spin.value())

        self._mw.threshold_spin.valueChanged.connect(self._mw.threshold_line.setValue)
        self._mw.minimize_button.clicked.connect(self._start_minimize)
        self._mw.start_log_button.clicked.connect(self._start_log)
        self._mw.run_all_button.clicked.connect(self._start_all)
        self._mw.stop_lock_button.clicked.connect(self._logic.stop_lock)
        self._mw.stop_log_button.clicked.connect(self._logic.stop_log)
        self._logic.sigLogSample.connect(self._append_sample, QtCore.Qt.QueuedConnection)
        self._logic.sigPowerUpdated.connect(self._show_power, QtCore.Qt.QueuedConnection)
        self._logic.sigLogStateChanged.connect(self._set_log_state, QtCore.Qt.QueuedConnection)
        self._logic.sigLockStateChanged.connect(self._set_lock_state, QtCore.Qt.QueuedConnection)
        self._logic.sigOperationStatusChanged.connect(self._set_activity, QtCore.Qt.QueuedConnection)
        self._restore_window_geometry(self._mw)
        self._mw.show()

    def on_deactivate(self):
        self._logic.stop_log()
        self._logic.stop_lock()
        self._save_window_geometry(self._mw)
        self._mw.close()

    def show(self):
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _settings(self):
        return {
            'log_duration_s': self._mw.log_duration_spin.value(),
            'lock_duration_s': self._mw.lock_duration_spin.value(),
            'interval_s': self._mw.interval_spin.value(),
            'continuous_log': self._mw.continuous_log.isChecked(),
            'continuous_lock': self._mw.continuous_lock.isChecked(),
            'threshold_nw': self._mw.threshold_spin.value(),
        }

    def _start_log(self):
        if not self._logging:
            self._reset_plot()
        values = self._settings()
        self._logic.start_log(values['log_duration_s'], values['interval_s'], values['continuous_log'])

    def _start_minimize(self):
        """Run the full coarse-plus-fine search using the displayed threshold."""
        self._logic.start_minimize(self._mw.threshold_spin.value())

    def _start_all(self):
        if not self._logging:
            self._reset_plot()
        self._logic.start_minimize_lock_log(**self._settings())

    def _reset_plot(self):
        """Discard a completed run before plotting samples from the next one."""
        self._times.clear()
        self._powers.clear()
        self._mw.curve.setData([], [])

    @QtCore.Slot(float, float)
    def _append_sample(self, elapsed, power):
        self._times.append(elapsed)
        self._powers.append(power)
        self._mw.curve.setData(list(self._times), list(self._powers))
        self._show_power(power)

    @QtCore.Slot(float)
    def _show_power(self, power):
        self._mw.power_label.setText(f'Power: {power:.2f} nW')

    @QtCore.Slot(bool)
    def _set_log_state(self, active):
        self._logging = bool(active)
        self._update_state()

    @QtCore.Slot(bool)
    def _set_lock_state(self, active):
        self._locking = bool(active)
        self._update_state()

    @QtCore.Slot(str)
    def _set_activity(self, status):
        self._mw.activity_label.setText(f'Activity: {status}')

    def _update_state(self):
        log_state = 'running' if self._logging else 'stopped'
        lock_state = 'running' if self._locking else 'stopped'
        self._mw.state_label.setText(f'Log: {log_state}   |   Lock: {lock_state}')
