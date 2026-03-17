# -*- coding: utf-8 -*-
"""
Simple GUI for DC voltage control and basic PLE-synchronized voltage sweeps.
"""

from __future__ import annotations

import numpy as np
from PySide2 import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase


class DCVoltageMainWindow(QtWidgets.QMainWindow):
    """Main window for manual DC voltage control and PLE sweep controls."""

    def __init__(self):
        super().__init__()
        self.setObjectName("DCVoltageMainWindow")
        self.setWindowTitle("DC Voltage Control")
        self.resize(520, 520)
        self._build_actions()
        self._build_ui()

    def _build_actions(self):
        self.action_close = QtWidgets.QAction("Close", self)
        self.action_close.triggered.connect(self.close)

        menu = self.menuBar().addMenu("File")
        menu.addAction(self.action_close)

    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.manual_group = QtWidgets.QGroupBox("Manual Control", central)
        manual_form = QtWidgets.QFormLayout(self.manual_group)
        manual_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.setpoint_spin = QtWidgets.QDoubleSpinBox(self.manual_group)
        self.setpoint_spin.setDecimals(6)
        self.setpoint_spin.setRange(-1.0e6, 1.0e6)
        self.setpoint_spin.setSuffix(" V")
        self.setpoint_spin.setSingleStep(0.1)

        self.apply_button = QtWidgets.QPushButton("Apply Voltage", self.manual_group)
        self.output_checkbox = QtWidgets.QCheckBox("Output Enabled", self.manual_group)
        self.refresh_button = QtWidgets.QPushButton("Refresh Readback", self.manual_group)

        self.measured_voltage_label = QtWidgets.QLabel("nan V", self.manual_group)
        self.measured_current_label = QtWidgets.QLabel("nan A", self.manual_group)

        manual_form.addRow("Setpoint", self.setpoint_spin)
        manual_form.addRow(self.apply_button)
        manual_form.addRow(self.output_checkbox)
        manual_form.addRow(self.refresh_button)
        manual_form.addRow("Measured Voltage", self.measured_voltage_label)
        manual_form.addRow("Measured Current", self.measured_current_label)

        self.sweep_group = QtWidgets.QGroupBox("PLE Voltage Sweep", central)
        sweep_form = QtWidgets.QFormLayout(self.sweep_group)
        sweep_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.scan_axis_combo = QtWidgets.QComboBox(self.sweep_group)

        self.start_spin = QtWidgets.QDoubleSpinBox(self.sweep_group)
        self.start_spin.setDecimals(6)
        self.start_spin.setRange(-1.0e6, 1.0e6)
        self.start_spin.setSuffix(" V")

        self.stop_spin = QtWidgets.QDoubleSpinBox(self.sweep_group)
        self.stop_spin.setDecimals(6)
        self.stop_spin.setRange(-1.0e6, 1.0e6)
        self.stop_spin.setSuffix(" V")

        self.steps_spin = QtWidgets.QSpinBox(self.sweep_group)
        self.steps_spin.setRange(1, 100000)

        self.settle_time_spin = QtWidgets.QDoubleSpinBox(self.sweep_group)
        self.settle_time_spin.setDecimals(3)
        self.settle_time_spin.setRange(0.0, 60.0)
        self.settle_time_spin.setSingleStep(0.05)
        self.settle_time_spin.setSuffix(" s")

        self.ple_repeats_spin = QtWidgets.QSpinBox(self.sweep_group)
        self.ple_repeats_spin.setRange(1, 100000)

        self.start_sweep_button = QtWidgets.QPushButton("Start Sweep", self.sweep_group)
        self.stop_sweep_button = QtWidgets.QPushButton("Stop Sweep", self.sweep_group)
        self.stop_sweep_button.setEnabled(False)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.start_sweep_button)
        buttons.addWidget(self.stop_sweep_button)

        self.progress_bar = QtWidgets.QProgressBar(self.sweep_group)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label = QtWidgets.QLabel("idle", self.sweep_group)
        self.result_label = QtWidgets.QLabel("No sweep results yet.", self.sweep_group)
        self.result_label.setWordWrap(True)

        sweep_form.addRow("PLE Scan Axis", self.scan_axis_combo)
        sweep_form.addRow("Start Voltage", self.start_spin)
        sweep_form.addRow("Stop Voltage", self.stop_spin)
        sweep_form.addRow("Steps", self.steps_spin)
        sweep_form.addRow("Settle Time", self.settle_time_spin)
        sweep_form.addRow("PLE Repeats / Point", self.ple_repeats_spin)
        sweep_form.addRow(buttons)
        sweep_form.addRow("Progress", self.progress_bar)
        sweep_form.addRow("Stage", self.progress_label)
        sweep_form.addRow("Last Point", self.result_label)

        root.addWidget(self.manual_group)
        root.addWidget(self.sweep_group)
        root.addStretch(1)

        self.statusBar().showMessage("Ready")


class DCVoltageGui(GuiBase):
    """GUI module wrapping DCVoltageLogic."""

    _logic = Connector(name="dc_voltage_logic", interface="DCVoltageLogic")

    sigSetVoltage = QtCore.Signal(float)
    sigSetOutputEnabled = QtCore.Signal(bool)
    sigRefreshMeasurements = QtCore.Signal()
    sigStartSweep = QtCore.Signal(object)
    sigStopSweep = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._dc_logic = None

    def on_activate(self):
        self._dc_logic = self._logic()
        self._mw = DCVoltageMainWindow()
        self._restore_window_geometry(self._mw)

        v_limits = self._dc_logic.get_voltage_limits()
        if isinstance(v_limits, (tuple, list)) and len(v_limits) == 2:
            self._mw.setpoint_spin.setRange(float(v_limits[0]), float(v_limits[1]))
            self._mw.start_spin.setRange(float(v_limits[0]), float(v_limits[1]))
            self._mw.stop_spin.setRange(float(v_limits[0]), float(v_limits[1]))

        defaults = self._dc_logic.get_default_sweep_settings()
        self._apply_sweep_defaults(defaults)
        self._refresh_scan_axes(defaults.get("scan_axis", ""))

        self._mw.apply_button.clicked.connect(self._apply_voltage_clicked)
        self._mw.output_checkbox.toggled.connect(self.sigSetOutputEnabled.emit)
        self._mw.refresh_button.clicked.connect(self.sigRefreshMeasurements.emit)
        self._mw.start_sweep_button.clicked.connect(self._start_sweep_clicked)
        self._mw.stop_sweep_button.clicked.connect(self.sigStopSweep.emit)

        self.sigSetVoltage.connect(self._dc_logic.set_voltage, QtCore.Qt.QueuedConnection)
        self.sigSetOutputEnabled.connect(
            self._dc_logic.set_output_enabled, QtCore.Qt.QueuedConnection
        )
        self.sigRefreshMeasurements.connect(
            self._dc_logic.refresh_measurements, QtCore.Qt.QueuedConnection
        )
        self.sigStartSweep.connect(
            self._dc_logic.start_ple_voltage_sweep, QtCore.Qt.QueuedConnection
        )
        self.sigStopSweep.connect(
            self._dc_logic.stop_ple_voltage_sweep, QtCore.Qt.QueuedConnection
        )

        self._dc_logic.sigStateChanged.connect(
            self._on_state_changed, QtCore.Qt.QueuedConnection
        )
        self._dc_logic.sigMeasurementChanged.connect(
            self._on_measurements_changed, QtCore.Qt.QueuedConnection
        )
        self._dc_logic.sigSweepStateChanged.connect(
            self._on_sweep_state_changed, QtCore.Qt.QueuedConnection
        )
        self._dc_logic.sigSweepProgressChanged.connect(
            self._on_sweep_progress, QtCore.Qt.QueuedConnection
        )
        self._dc_logic.sigSweepResultsChanged.connect(
            self._on_sweep_results, QtCore.Qt.QueuedConnection
        )
        self._dc_logic.sigMessage.connect(self._on_message, QtCore.Qt.QueuedConnection)

        self.show()
        self.sigRefreshMeasurements.emit()

    def on_deactivate(self):
        if self._mw is None:
            return

        for signal in (
            self._mw.apply_button.clicked,
            self._mw.output_checkbox.toggled,
            self._mw.refresh_button.clicked,
            self._mw.start_sweep_button.clicked,
            self._mw.stop_sweep_button.clicked,
        ):
            try:
                signal.disconnect()
            except RuntimeError:
                pass

        for signal in (
            self.sigSetVoltage,
            self.sigSetOutputEnabled,
            self.sigRefreshMeasurements,
            self.sigStartSweep,
            self.sigStopSweep,
        ):
            try:
                signal.disconnect()
            except RuntimeError:
                pass

        if self._dc_logic is not None:
            for signal, slot in (
                (self._dc_logic.sigStateChanged, self._on_state_changed),
                (self._dc_logic.sigMeasurementChanged, self._on_measurements_changed),
                (self._dc_logic.sigSweepStateChanged, self._on_sweep_state_changed),
                (self._dc_logic.sigSweepProgressChanged, self._on_sweep_progress),
                (self._dc_logic.sigSweepResultsChanged, self._on_sweep_results),
                (self._dc_logic.sigMessage, self._on_message),
            ):
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass

        self._save_window_geometry(self._mw)
        self._mw.close()
        self._mw = None
        self._dc_logic = None

    def show(self):
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _apply_sweep_defaults(self, defaults: dict):
        self._mw.start_spin.setValue(float(defaults.get("start_v", -10.0)))
        self._mw.stop_spin.setValue(float(defaults.get("stop_v", 10.0)))
        self._mw.steps_spin.setValue(int(defaults.get("steps", 21)))
        self._mw.settle_time_spin.setValue(float(defaults.get("settle_time_s", 0.2)))
        self._mw.ple_repeats_spin.setValue(int(defaults.get("ple_repeats", 1)))

    def _refresh_scan_axes(self, preferred_axis: str):
        axes = self._dc_logic.get_available_scan_axes()
        self._mw.scan_axis_combo.blockSignals(True)
        self._mw.scan_axis_combo.clear()
        self._mw.scan_axis_combo.addItems(list(axes) if len(axes) else [""])
        if preferred_axis and preferred_axis in axes:
            self._mw.scan_axis_combo.setCurrentText(preferred_axis)
        self._mw.scan_axis_combo.blockSignals(False)

    def _apply_voltage_clicked(self):
        self.sigSetVoltage.emit(float(self._mw.setpoint_spin.value()))

    def _start_sweep_clicked(self):
        settings = {
            "scan_axis": self._mw.scan_axis_combo.currentText().strip(),
            "start_v": float(self._mw.start_spin.value()),
            "stop_v": float(self._mw.stop_spin.value()),
            "steps": int(self._mw.steps_spin.value()),
            "settle_time_s": float(self._mw.settle_time_spin.value()),
            "ple_repeats": int(self._mw.ple_repeats_spin.value()),
        }
        self.sigStartSweep.emit(settings)

    @QtCore.Slot(object)
    def _on_state_changed(self, payload):
        if not isinstance(payload, dict):
            return
        setpoint = float(payload.get("voltage_setpoint", np.nan))
        output_enabled = bool(payload.get("output_enabled", False))
        if np.isfinite(setpoint):
            self._mw.setpoint_spin.blockSignals(True)
            self._mw.setpoint_spin.setValue(setpoint)
            self._mw.setpoint_spin.blockSignals(False)
        self._mw.output_checkbox.blockSignals(True)
        self._mw.output_checkbox.setChecked(output_enabled)
        self._mw.output_checkbox.blockSignals(False)

    @QtCore.Slot(float, float)
    def _on_measurements_changed(self, voltage: float, current: float):
        self._mw.measured_voltage_label.setText(self._fmt(voltage, "V"))
        self._mw.measured_current_label.setText(self._fmt(current, "A"))

    @QtCore.Slot(bool)
    def _on_sweep_state_changed(self, running: bool):
        self._mw.start_sweep_button.setEnabled(not running)
        self._mw.stop_sweep_button.setEnabled(running)

    @QtCore.Slot(object)
    def _on_sweep_progress(self, payload):
        if not isinstance(payload, dict):
            return
        stage = str(payload.get("stage", ""))
        index = int(payload.get("index", 0))
        total = int(payload.get("total", 0))
        voltage = float(payload.get("voltage", np.nan))

        if total > 0:
            self._mw.progress_bar.setRange(0, total)
            self._mw.progress_bar.setValue(min(max(index + 1, 0), total))
        else:
            self._mw.progress_bar.setRange(0, 1)
            self._mw.progress_bar.setValue(0)

        label = f"{stage} | point {index + 1 if total else 0}/{total} | V={self._fmt(voltage, 'V')}"
        self._mw.progress_label.setText(label)

    @QtCore.Slot(object)
    def _on_sweep_results(self, payload):
        if not isinstance(payload, dict):
            return
        results = payload.get("results", [])
        if len(results) < 1:
            self._mw.result_label.setText("No sweep results yet.")
            return
        last = results[-1]
        txt = (
            f"idx={last.get('index', 'n/a')}, "
            f"set={self._fmt(last.get('voltage_setpoint', np.nan), 'V')}, "
            f"meas={self._fmt(last.get('measured_current', np.nan), 'A')}, "
            f"peak={self._fmt(last.get('peak_counts', np.nan), '')}"
        )
        self._mw.result_label.setText(txt)

    @QtCore.Slot(str)
    def _on_message(self, text: str):
        self._mw.statusBar().showMessage(str(text), 7000)

    @staticmethod
    def _fmt(value, unit):
        try:
            value = float(value)
            if np.isnan(value):
                return f"nan {unit}".strip()
            if unit:
                return f"{value:.6g} {unit}"
            return f"{value:.6g}"
        except Exception:
            return f"nan {unit}".strip()
