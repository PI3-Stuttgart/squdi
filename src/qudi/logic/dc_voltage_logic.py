# -*- coding: utf-8 -*-
"""
Logic module for manual DC-voltage control and optional synchronized PLE sweeps.

This module keeps the first iteration intentionally simple:
- Manual set/read/toggle output for a ProcessControlInterface DC source.
- Optional voltage-point sweep where each point triggers exactly one PLE scan.
"""

from __future__ import annotations

import datetime as dt
import time

import numpy as np
from PySide2 import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar


class DCVoltageLogic(LogicBase):
    """Manual DC voltage control plus optional synchronized PLE sweep execution."""

    _dc_source = Connector(name="dc_source", interface="ProcessControlInterface")
    _ple_scanner = Connector(
        name="ple_scanner", interface="PLEScannerLogic", optional=True
    )

    _setpoint_channel = ConfigOption(
        name="setpoint_channel", default="voltage", missing="warn"
    )
    _measured_voltage_channel = ConfigOption(
        name="measured_voltage_channel", default="measured_voltage", missing="warn"
    )
    _measured_current_channel = ConfigOption(
        name="measured_current_channel", default="current", missing="warn"
    )
    _default_scan_axis = ConfigOption(name="default_scan_axis", default="", missing="nothing")
    _default_ple_repeats = ConfigOption(
        name="default_ple_repeats", default=1, missing="warn"
    )
    _default_settle_time_s = ConfigOption(
        name="default_settle_time_s", default=0.2, missing="warn"
    )

    voltage_setpoint = StatusVar(name="voltage_setpoint", default=0.0)
    output_enabled = StatusVar(name="output_enabled", default=False)
    last_measured_voltage = StatusVar(name="last_measured_voltage", default=float("nan"))
    last_measured_current = StatusVar(name="last_measured_current", default=float("nan"))
    _last_sweep_settings = StatusVar(name="last_sweep_settings", default=None)

    sigStateChanged = QtCore.Signal(object)
    sigMeasurementChanged = QtCore.Signal(float, float)
    sigOutputStateChanged = QtCore.Signal(bool)
    sigMessage = QtCore.Signal(str)

    sigSweepStateChanged = QtCore.Signal(bool)
    sigSweepProgressChanged = QtCore.Signal(object)
    sigSweepResultsChanged = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dc_hw = None
        self._ple_scan_logic = None

        self._running = False
        self._abort_requested = False
        self._pending_ple_scan = False
        self._last_scan_data = None

        self._sweep_voltages = np.array([], dtype=float)
        self._sweep_index = -1
        self._sweep_results = []
        self._sweep_started_at = None
        self._sweep_settle_time_s = float(self._default_settle_time_s)
        self._scan_axes = tuple()
        self._desired_ple_repeats = int(max(1, self._default_ple_repeats))
        self._ple_repeats_backup = None

    def on_activate(self):
        self._dc_hw = self._dc_source()
        self._ple_scan_logic = self._ple_scanner()

        if self._ple_scan_logic is not None:
            self._ple_scan_logic.sigScanStateChanged.connect(
                self._on_ple_scan_state_changed, QtCore.Qt.QueuedConnection
            )

        try:
            self.set_voltage(float(self.voltage_setpoint), settle=False)
        except Exception:
            self.log.exception("Failed to restore DC voltage setpoint on activation.")

        try:
            self.set_output_enabled(bool(self.output_enabled))
        except Exception:
            self.log.exception("Failed to restore DC output state on activation.")

        self.refresh_measurements()
        self._emit_state()

    def on_deactivate(self):
        self.stop_ple_voltage_sweep()
        if self._ple_scan_logic is not None:
            try:
                self._ple_scan_logic.sigScanStateChanged.disconnect(
                    self._on_ple_scan_state_changed
                )
            except RuntimeError:
                pass

    @QtCore.Slot(result=object)
    def get_voltage_limits(self):
        try:
            return tuple(self._dc_hw.constraints.channel_limits[self._setpoint_channel])
        except Exception:
            return (-np.inf, np.inf)

    @QtCore.Slot(result=object)
    def get_available_scan_axes(self):
        if self._ple_scan_logic is None:
            return tuple()
        try:
            return tuple(self._ple_scan_logic.scan_ranges.keys())
        except Exception:
            return tuple()

    @QtCore.Slot(result=object)
    def get_default_sweep_settings(self):
        if isinstance(self._last_sweep_settings, dict):
            defaults = dict(self._last_sweep_settings)
        else:
            defaults = {
                "start_v": -10.0,
                "stop_v": 10.0,
                "steps": 21,
                "settle_time_s": float(self._default_settle_time_s),
                "ple_repeats": int(max(1, self._default_ple_repeats)),
            }
        available_axes = self.get_available_scan_axes()
        default_axis = str(defaults.get("scan_axis", "")).strip()
        if not default_axis:
            default_axis = str(self._default_scan_axis).strip()
        if not default_axis and len(available_axes) > 0:
            default_axis = available_axes[0]
        if default_axis and default_axis in available_axes:
            defaults["scan_axis"] = default_axis
        elif len(available_axes) > 0:
            defaults["scan_axis"] = available_axes[0]
        else:
            defaults["scan_axis"] = ""
        return defaults

    @QtCore.Slot(float)
    def set_voltage(self, value: float, settle: bool = False):
        self._set_voltage_internal(value, settle=settle)
        self._emit_state()

    def _set_voltage_internal(self, value: float, settle: bool):
        value = float(value)
        self._dc_hw.set_setpoint(self._setpoint_channel, value)
        self.voltage_setpoint = value
        if settle and self._sweep_settle_time_s > 0:
            time.sleep(self._sweep_settle_time_s)

    @QtCore.Slot()
    def refresh_measurements(self):
        v_val = self.last_measured_voltage
        i_val = self.last_measured_current
        try:
            v_val = float(self._dc_hw.get_process_value(self._measured_voltage_channel))
        except Exception:
            self.log.exception("Failed reading measured voltage channel.")
        try:
            i_val = float(self._dc_hw.get_process_value(self._measured_current_channel))
        except Exception:
            self.log.exception("Failed reading measured current channel.")

        self.last_measured_voltage = v_val
        self.last_measured_current = i_val
        self.sigMeasurementChanged.emit(float(v_val), float(i_val))

    @QtCore.Slot(bool)
    def set_output_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._dc_hw.set_activity_state(self._setpoint_channel, enabled)
        self.output_enabled = enabled
        self.sigOutputStateChanged.emit(enabled)
        self._emit_state()

    @QtCore.Slot(object)
    def start_ple_voltage_sweep(self, settings):
        if self._running or self.module_state() != "idle":
            self.sigMessage.emit("Voltage sweep is already running.")
            return
        if self._ple_scan_logic is None:
            self.sigMessage.emit(
                "No PLE scanner connected. Configure connector 'ple_scanner' first."
            )
            return
        if self._ple_scan_logic.module_state() != "idle":
            self.sigMessage.emit("PLE scanner is busy. Stop current scan first.")
            return

        try:
            cfg = self._sanitize_sweep_settings(settings)
            voltages = np.linspace(cfg["start_v"], cfg["stop_v"], cfg["steps"], dtype=float)
            if voltages.size == 0:
                self.sigMessage.emit("No voltage points generated.")
                return
        except Exception:
            self.log.exception("Failed to prepare voltage sweep settings.")
            self.sigMessage.emit("Invalid voltage sweep settings.")
            return

        self._last_sweep_settings = dict(cfg)
        self._sweep_voltages = voltages
        self._sweep_settle_time_s = float(cfg["settle_time_s"])
        self._desired_ple_repeats = int(max(1, cfg["ple_repeats"]))
        self._scan_axes = (cfg["scan_axis"],)
        self._sweep_index = -1
        self._sweep_results = []
        self._sweep_started_at = dt.datetime.now()
        self._last_scan_data = None
        self._abort_requested = False
        self._pending_ple_scan = False

        try:
            self._ple_repeats_backup = int(
                getattr(self._ple_scan_logic, "_number_of_repeats", 1)
            )
        except Exception:
            self._ple_repeats_backup = None

        try:
            self._ple_scan_logic.update_number_of_repeats(self._desired_ple_repeats)
            if hasattr(self._ple_scan_logic, "_repeated"):
                self._ple_scan_logic._repeated = 0
            if hasattr(self._ple_scan_logic, "display_repeated"):
                self._ple_scan_logic.display_repeated = 0
        except Exception:
            self.log.exception("Could not update PLE repeats.")

        self._running = True
        self.module_state.lock()
        self.sigSweepStateChanged.emit(True)
        self.sigSweepResultsChanged.emit(self._result_payload())
        self.sigMessage.emit(
            f"Starting voltage sweep with {len(self._sweep_voltages)} points."
        )
        QtCore.QTimer.singleShot(0, self._advance_to_next_voltage)

    @QtCore.Slot()
    def stop_ple_voltage_sweep(self):
        if not self._running:
            return
        self._abort_requested = True

        if self._pending_ple_scan:
            try:
                self._ple_scan_logic.toggle_scan(False, self._scan_axes, self.module_uuid)
            except Exception:
                self.log.exception("Failed to stop running PLE scan during abort.")
            return

        self._finish_sweep(aborted=True)

    @QtCore.Slot(bool, object, object)
    def _on_ple_scan_state_changed(self, is_running, scan_data, caller_id):
        if caller_id != self.module_uuid:
            return
        if not self._running:
            return

        if scan_data is not None:
            self._last_scan_data = scan_data

        if is_running:
            self.sigSweepProgressChanged.emit(self._progress_payload(stage="scanning"))
            return

        if not self._pending_ple_scan:
            return

        self._pending_ple_scan = False
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return

        self._consume_scan_result(self._last_scan_data)
        QtCore.QTimer.singleShot(0, self._advance_to_next_voltage)

    def _advance_to_next_voltage(self):
        if not self._running:
            return
        if self._abort_requested:
            self._finish_sweep(aborted=True)
            return

        self._sweep_index += 1
        if self._sweep_index >= len(self._sweep_voltages):
            self._finish_sweep(aborted=False)
            return

        target_voltage = float(self._sweep_voltages[self._sweep_index])
        try:
            self._set_voltage_internal(target_voltage, settle=True)
            self.refresh_measurements()
        except Exception:
            self.log.exception("Failed setting voltage during sweep.")
            self._finish_sweep(
                aborted=True, error_message="Setting voltage failed. Sweep aborted."
            )
            return

        try:
            self._ple_scan_logic.update_number_of_repeats(self._desired_ple_repeats)
            if hasattr(self._ple_scan_logic, "_repeated"):
                self._ple_scan_logic._repeated = 0
            if hasattr(self._ple_scan_logic, "display_repeated"):
                self._ple_scan_logic.display_repeated = 0
            self._pending_ple_scan = True
            self._ple_scan_logic.toggle_scan(True, self._scan_axes, self.module_uuid)
        except Exception:
            self.log.exception("Failed to start synchronized PLE scan.")
            self._pending_ple_scan = False
            self._finish_sweep(
                aborted=True, error_message="Could not start PLE scan. Sweep aborted."
            )
            return

        self.sigSweepProgressChanged.emit(self._progress_payload(stage="scanning"))

    def _consume_scan_result(self, scan_data):
        channel = self._resolve_channel(scan_data)
        peak_counts = np.nan
        if scan_data is not None and channel is not None:
            try:
                signal = np.asarray(scan_data.data[channel], dtype=float).ravel()
                if signal.size > 0:
                    peak_counts = float(np.nanmax(signal))
            except Exception:
                peak_counts = np.nan

        result = {
            "index": int(self._sweep_index),
            "voltage_setpoint": float(self.voltage_setpoint),
            "measured_voltage": float(self.last_measured_voltage),
            "measured_current": float(self.last_measured_current),
            "peak_counts": float(peak_counts),
            "timestamp": dt.datetime.now().isoformat(),
        }
        self._sweep_results.append(result)
        self.sigSweepResultsChanged.emit(self._result_payload())
        self.sigSweepProgressChanged.emit(self._progress_payload(stage="point_done"))

    def _finish_sweep(self, aborted=False, error_message=None):
        if not self._running and self.module_state() == "idle":
            return

        self._running = False
        self._abort_requested = False
        self._pending_ple_scan = False

        if self._ple_repeats_backup is not None and self._ple_scan_logic is not None:
            try:
                self._ple_scan_logic.update_number_of_repeats(self._ple_repeats_backup)
            except Exception:
                self.log.exception("Failed to restore previous PLE repeat setting.")
        self._ple_repeats_backup = None

        if self.module_state() != "idle":
            self.module_state.unlock()

        stage = "aborted" if aborted else "finished"
        self.sigSweepProgressChanged.emit(self._progress_payload(stage=stage))
        self.sigSweepResultsChanged.emit(self._result_payload())
        self.sigSweepStateChanged.emit(False)
        self._emit_state()

        if error_message:
            self.sigMessage.emit(error_message)
        elif aborted:
            self.sigMessage.emit("Voltage PLE sweep aborted.")
        else:
            self.sigMessage.emit("Voltage PLE sweep finished.")

    def _resolve_channel(self, scan_data):
        if scan_data is None:
            return None
        try:
            channels = list(scan_data.data.keys())
            return channels[0] if len(channels) > 0 else None
        except Exception:
            return None

    def _sanitize_sweep_settings(self, settings):
        defaults = self.get_default_sweep_settings()
        merged = defaults if not isinstance(settings, dict) else {**defaults, **settings}

        scan_axis = str(merged.get("scan_axis", "")).strip()
        available = self.get_available_scan_axes()
        if not scan_axis and len(available) > 0:
            scan_axis = available[0]
        if scan_axis and scan_axis not in available:
            raise ValueError(f'Unknown scan axis "{scan_axis}". Available: {available}')
        if not scan_axis:
            raise ValueError("No PLE scan axis available.")

        out = {
            "scan_axis": scan_axis,
            "start_v": float(merged.get("start_v", -10.0)),
            "stop_v": float(merged.get("stop_v", 10.0)),
            "steps": int(max(1, merged.get("steps", 21))),
            "settle_time_s": float(max(0.0, merged.get("settle_time_s", 0.0))),
            "ple_repeats": int(max(1, merged.get("ple_repeats", self._default_ple_repeats))),
        }
        return out

    def _progress_payload(self, stage):
        total = int(len(self._sweep_voltages))
        index = int(min(max(self._sweep_index, 0), total - 1)) if total > 0 else 0
        voltage = (
            float(self._sweep_voltages[self._sweep_index])
            if 0 <= self._sweep_index < total
            else float("nan")
        )
        return {
            "stage": stage,
            "index": index,
            "total": total,
            "voltage": voltage,
            "scan_axis": self._scan_axes[0] if len(self._scan_axes) else "",
        }

    def _result_payload(self):
        return {
            "running": bool(self._running),
            "scan_axis": self._scan_axes[0] if len(self._scan_axes) else "",
            "results": [dict(item) for item in self._sweep_results],
            "current_index": int(self._sweep_index),
            "total_points": int(len(self._sweep_voltages)),
            "started_at": None
            if self._sweep_started_at is None
            else self._sweep_started_at.isoformat(),
        }

    def _emit_state(self):
        self.sigStateChanged.emit(
            {
                "voltage_setpoint": float(self.voltage_setpoint),
                "output_enabled": bool(self.output_enabled),
                "measured_voltage": float(self.last_measured_voltage),
                "measured_current": float(self.last_measured_current),
                "sweep_running": bool(self._running),
            }
        )
