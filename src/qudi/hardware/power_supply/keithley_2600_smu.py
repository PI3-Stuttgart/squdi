# -*- coding: utf-8 -*-
"""
Keithley 2600 SourceMeter wrapper exposing ProcessControlInterface channels.

This module is intentionally small and focused on DC voltage sourcing with
current readback, mirroring the usage pattern from IV_x.ipynb.

Example config:

keithley_2600:
    module.Class: 'power_supply.keithley_2600_smu.Keithley2600SMU'
    options:
        visa_resource_name: 'USB0::0x05E6::0x2636::4365643::INSTR'
        channel: 'a'
        voltage_limits: [-200, 200]
        current_limits: [-0.01, 0.01]
        timeout_ms: 3000
        command_retries: 8
        retry_sleep_s: 0.25
        measurement_retries: 8
        enable_output_on_activate: False
        disable_output_on_deactivate: True
        initial_voltage: 0.0
        current_range: 0.001
        source_current_limit: 0.001
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Tuple, Union

from qudi.core.configoption import ConfigOption
from qudi.core.module import Base
from qudi.interface.process_control_interface import (
    ProcessControlConstraints,
    ProcessControlInterface,
)

try:
    from qudi.jupyternotebooks.keithley2600 import SMU26xx
except Exception:  # pragma: no cover - import fallback for local path variants
    SMU26xx = None


class Keithley2600SMU(Base, ProcessControlInterface):
    """Process-control style hardware module for Keithley 2600 SMUs."""

    _visa_resource_name = ConfigOption(name="visa_resource_name", missing="error")
    _channel = ConfigOption(name="channel", default="a", missing="warn")

    _setpoint_channel_name = ConfigOption(
        name="setpoint_channel_name", default="voltage", missing="nothing"
    )
    _measured_voltage_channel_name = ConfigOption(
        name="measured_voltage_channel_name", default="measured_voltage", missing="nothing"
    )
    _measured_current_channel_name = ConfigOption(
        name="measured_current_channel_name", default="current", missing="nothing"
    )

    _voltage_limits = ConfigOption(name="voltage_limits", default=(-200.0, 200.0))
    _current_limits = ConfigOption(name="current_limits", default=(-1.5, 1.5))

    _timeout_ms = ConfigOption(name="timeout_ms", default=3000, missing="warn")
    _command_retries = ConfigOption(name="command_retries", default=5, missing="warn")
    _measurement_retries = ConfigOption(
        name="measurement_retries", default=5, missing="warn"
    )
    _retry_sleep_s = ConfigOption(name="retry_sleep_s", default=0.25, missing="warn")

    _enable_output_on_activate = ConfigOption(
        name="enable_output_on_activate", default=False, missing="nothing"
    )
    _disable_output_on_deactivate = ConfigOption(
        name="disable_output_on_deactivate", default=True, missing="nothing"
    )
    _initial_voltage = ConfigOption(name="initial_voltage", default=0.0, missing="nothing")

    _voltage_range = ConfigOption(name="voltage_range", default=None, missing="nothing")
    _current_range = ConfigOption(name="current_range", default=None, missing="nothing")
    _source_current_limit = ConfigOption(
        name="source_current_limit", default=None, missing="nothing"
    )

    _smu = None
    _smu_channel = None
    _constraints: Optional[ProcessControlConstraints] = None
    _setpoint_value = 0.0
    _output_enabled = False
    _activity_states = None

    @staticmethod
    @_voltage_limits.constructor
    @_current_limits.constructor
    def _construct_limits(value) -> Tuple[float, float]:
        if isinstance(value, (tuple, list)) and len(value) == 2:
            v0 = float(value[0])
            v1 = float(value[1])
            return (min(v0, v1), max(v0, v1))
        raise ValueError("Limits must be provided as two numeric values.")

    def on_activate(self):
        if SMU26xx is None:
            raise RuntimeError(
                "Could not import qudi.jupyternotebooks.keithley2600.SMU26xx."
            )

        self._smu = SMU26xx(self._visa_resource_name, timeout=int(self._timeout_ms))
        self._smu_channel = self._smu.get_channel(str(self._channel).lower())

        self._call_with_retries(
            lambda: self._smu_channel.set_mode_voltage_source(),
            "set voltage source mode",
        )

        if self._voltage_range is not None:
            self._call_with_retries(
                lambda: self._smu_channel.set_voltage_range(float(self._voltage_range)),
                "set voltage range",
            )

        if self._current_range is not None:
            self._call_with_retries(
                lambda: self._smu_channel.set_current_range(float(self._current_range)),
                "set current range",
            )

        if self._source_current_limit is not None:
            if self._current_range is None:
                self.log.warning(
                    'Config option "source_current_limit" was set without "current_range". '
                    "Skipping current limit setup."
                )
            else:
                self._call_with_retries(
                    lambda: self._smu_channel.set_current_limit(
                        float(self._source_current_limit)
                    ),
                    "set source current limit",
                )

        self._constraints = ProcessControlConstraints(
            setpoint_channels=(self._setpoint_channel_name,),
            process_channels=(
                self._measured_voltage_channel_name,
                self._measured_current_channel_name,
            ),
            units={
                self._setpoint_channel_name: "V",
                self._measured_voltage_channel_name: "V",
                self._measured_current_channel_name: "A",
            },
            limits={
                self._setpoint_channel_name: self._voltage_limits,
                self._measured_voltage_channel_name: self._voltage_limits,
                self._measured_current_channel_name: self._current_limits,
            },
            dtypes={
                self._setpoint_channel_name: float,
                self._measured_voltage_channel_name: float,
                self._measured_current_channel_name: float,
            },
        )

        self._setpoint_value = float(self._initial_voltage)
        self.set_setpoint(self._setpoint_channel_name, self._setpoint_value)
        self._set_output_state_internal(bool(self._enable_output_on_activate))

        self._activity_states = {
            ch: self._output_enabled for ch in self._constraints.all_channels
        }

    def on_deactivate(self):
        try:
            if self._smu_channel is not None and self._disable_output_on_deactivate:
                self._set_output_state_internal(False)
        except Exception:
            self.log.exception("Disabling Keithley output during deactivation failed.")

        try:
            if self._smu is not None:
                self._smu.disconnect()
        except Exception:
            self.log.exception("Closing Keithley connection failed.")
        finally:
            self._smu_channel = None
            self._smu = None

    @property
    def constraints(self) -> ProcessControlConstraints:
        return self._constraints

    def set_activity_state(self, channel: str, active: bool) -> None:
        if channel not in self.constraints.all_channels:
            raise ValueError(
                f'Invalid channel "{channel}". Valid channels: {self.constraints.all_channels}'
            )
        self._set_output_state_internal(bool(active))
        for ch in self.constraints.all_channels:
            self._activity_states[ch] = self._output_enabled

    def get_activity_state(self, channel: str) -> bool:
        if channel not in self.constraints.all_channels:
            raise ValueError(
                f'Invalid channel "{channel}". Valid channels: {self.constraints.all_channels}'
            )
        return bool(self._activity_states.get(channel, False))

    def set_setpoint(self, channel: str, value: Union[int, float]) -> None:
        if channel != self._setpoint_channel_name:
            raise ValueError(
                f'Invalid setpoint channel "{channel}". '
                f'Valid setpoint channels: {self.constraints.setpoint_channels}'
            )
        value = float(value)
        if not self.constraints.channel_value_in_range(channel, value)[0]:
            raise ValueError(
                f"Setpoint {value} V out of range {self.constraints.channel_limits[channel]} for channel '{channel}'."
            )
        self._call_with_retries(
            lambda: self._smu_channel.set_voltage(value), "set source voltage"
        )
        self._setpoint_value = value

    def get_setpoint(self, channel: str) -> float:
        if channel != self._setpoint_channel_name:
            raise ValueError(
                f'Invalid setpoint channel "{channel}". '
                f'Valid setpoint channels: {self.constraints.setpoint_channels}'
            )
        return float(self._setpoint_value)

    def get_process_value(self, channel: str) -> float:
        if channel == self._measured_voltage_channel_name:
            return float(
                self._call_with_retries(
                    lambda: self._smu_channel.measure_voltage(),
                    "measure voltage",
                    retries=int(self._measurement_retries),
                )
            )
        if channel == self._measured_current_channel_name:
            return float(
                self._call_with_retries(
                    lambda: self._smu_channel.measure_current(),
                    "measure current",
                    retries=int(self._measurement_retries),
                )
            )
        raise ValueError(
            f'Invalid process channel "{channel}". '
            f'Valid process channels: {self.constraints.process_channels}'
        )

    def _set_output_state_internal(self, active: bool) -> None:
        if self._smu_channel is None:
            raise RuntimeError("Keithley channel is not initialized.")
        if active:
            self._call_with_retries(lambda: self._smu_channel.enable_output(), "enable output")
        else:
            self._call_with_retries(lambda: self._smu_channel.disable_output(), "disable output")
        self._output_enabled = bool(active)

    def _call_with_retries(
        self,
        operation: Callable[[], object],
        description: str,
        retries: Optional[int] = None,
    ):
        n_tries = max(1, int(self._command_retries if retries is None else retries))
        delay_s = max(0.0, float(self._retry_sleep_s))
        last_exc = None
        for idx in range(n_tries):
            try:
                return operation()
            except Exception as exc:
                last_exc = exc
                if idx < n_tries - 1 and delay_s > 0:
                    time.sleep(delay_s * (1.0 + 0.25 * idx))
        raise RuntimeError(
            f"Keithley command failed ({description}) after {n_tries} tries: {last_exc}"
        ) from last_exc

