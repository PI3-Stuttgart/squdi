# -*- coding: utf-8 -*-
"""
Interact with switches.

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

import time
from typing import Any

from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)
from qudi.logic.aom_power_calibration import AomPowerCalibration


class AOLogic(LogicBase):
    """Logic module for interacting with the aonalog outputs of hardware.

    AOLogic:
        module.Class: 'AO_logic.AOLogic'
        options:
            watchdog_interval: 1  # optional
            autostart_watchdog: True  # optional
            AO_parameters: # optional
                AOM_575:
                    conv_bounds: [0, 20]
                    unit: 'mW'

        connect:
            ao_hardware: <hardware name>
    """

    ao_hardware: ProcessSetpointInterface = Connector(interface="ProcessSetpointInterface")
    power_conversion: AomPowerCalibration = Connector(interface="LogicBase")
    _power_conversion: AomPowerCalibration
    _ao_hardware: ProcessSetpointInterface

    ao_parameters: dict[str, dict[str, Any]] = ConfigOption(name="AO_parameters", missing="nothing")  # type: ignore

    _watchdog_interval: float = ConfigOption(name="watchdog_interval", default=1.0, missing="nothing")  # type: ignore
    _autostart_watchdog: bool = ConfigOption(name="autostart_watchdog", default=False, missing="nothing")  # type: ignore
    # Defines the max and min values of the hardware AO output. used in the convertion function
    _hardware_bounds_V: tuple[float, float] = (-1, 1)  # V
    # If True, ignores the converstion of the setpoints and instead uses the direct hardware values
    use_hardware_setpoints = False

    _old_setpoints: dict[str, float] = {}

    sigSetpointsChanged = QtCore.Signal(dict)
    sigWatchdogToggled = QtCore.Signal(bool)

    # directly wrapped attributes from hardware module
    __wrapped_hw_attributes = frozenset({""})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._thread_lock = RecursiveMutex()

        self._watchdog_active = False
        self._watchdog_interval_ms = 500

    def on_activate(self):
        """Activate module"""
        self._power_conversion = self.power_conversion()
        self._ao_hardware = self.ao_hardware()
        self._old_setpoints = self.setpoints
        self._set_constraints()
        self._watchdog_interval_ms = int(round(self._watchdog_interval * 1000))
        self._curr_conversion_channels = self._power_conversion.channels_w_conversion
        if self._autostart_watchdog:
            self._watchdog_active = True
            QtCore.QMetaObject.invokeMethod(self, "_watchdog_body", QtCore.Qt.QueuedConnection)
        else:
            self._watchdog_active = False

    def on_deactivate(self):
        """Deactivate module"""
        self._watchdog_active = False

    # def __getattr__(self, item):
    #     if item in self.__wrapped_hw_attributes:
    #         return getattr(self._ao_hardware, item)
    #     # raise AttributeError(f'AOLogic has no attribute with name "{item}"')

    def use_conversion(self, channel: str) -> bool:
        """Checks if conversion is used"""
        return channel in self._power_conversion.channels_w_conversion

    @property
    def watchdog_active(self) -> bool:
        """Returns a bool indicating if the watchdog is active"""
        return self._watchdog_active

    def _set_constraints(self) -> None:
        channels = list(self._ao_hardware.constraints.setpoint_channels)
        units = {}
        limits = {}
        for channel in channels:
            if channel in self._power_conversion.channels_w_conversion and self.use_conversion:
                units[channel] = "W"  # TODO: Needs to be generalized

                limits[channel] = tuple(
                    [self._power_conversion.convert_voltage_to_power(v, channel) for v in self._ao_hardware.constraints.channel_limits[channel]]
                )

            else:
                units[channel] = self._ao_hardware.constraints.channel_units[channel]
                limits[channel] = self._ao_hardware.constraints.channel_limits[channel]

        print(limits)
        print(units)
        self._constraints = ProcessControlConstraints(
            setpoint_channels=channels,
            units=units,
            limits=limits,
            dtypes={ch: float for ch in channels},
        )

    @property
    def constraints(self) -> ProcessControlConstraints:
        if self._curr_conversion_channels == self._power_conversion.channels_w_conversion:

            return self._constraints
        else:
            self._set_constraints()
            return self._constraints

    @property
    def setpoints(self) -> dict[str, float]:
        """The current states the hardware is in as state dictionary with switch names as keys and
        state names as values. Returns the converted setpoints if not self.use_hardware_setpoints = True.

        @return dict: All the current states of the switches in the form {"switch": "state"}
        """
        with self._thread_lock:
            try:
                setpoints_dict = self.convert_setpoints_dict(self._ao_hardware.setpoints, reverse=True)
            except BaseException:
                if self._watchdog_active:
                    self.toggle_watchdog(False)
                    self.log.exception(msg="Error during query of all switch states. " "Deactivating watchdog to avoid constant errors.")
                else:
                    self.log.exception(msg="Error during query of all setpoints.")
                setpoints_dict: dict[str, float] = {}
            return setpoints_dict

    @setpoints.setter
    def setpoints(self, setpoints_dict: dict[str, float]):
        """The setter for the states of the hardware.

        The setpoint of the system can be set by specifying a dict that has the setpoint_channel names as keys
        and the setpoints as values.

        @param dict setpoints_dict: state dict of the form {"channel": "setpoint"}
        """
        with self._thread_lock:
            try:
                self._ao_hardware.setpoint(self.convert_setpoints_dict(setpoints_dict))
            except BaseException:
                self.log.exception("Error while trying to set setpoints.")

            setpoints = self.setpoints
            if setpoints:
                self.sigSetpointsChanged.emit({channel: setpoints[channel] for channel in setpoints_dict})

    def get_setpoint(self, channel: str, get_hardware_value=False):
        """Query state of single switch by name

        @param str channel: name of the channel to query the setpoint for
        @return str: The current switch state
        """
        with self._thread_lock:
            try:
                setpoint_hw = self._ao_hardware.get_setpoint(channel)
                if get_hardware_value:
                    setpoint = setpoint_hw.copy()
                else:
                    setpoint = self.convert_setpoint(channel, setpoint_hw, reverse=True)
            except BaseException:
                self.log.exception(f'Error while trying to query setpoint of channel "{channel}".')
                setpoint = None
            return setpoint

    @QtCore.Slot(str, str)
    def set_setpoint(self, channel: str, value: float, use_hardware_value: bool = False):
        """Query state of single channel

        @param str switch: name of the channel to change
        @param str state: name of the setpoint to set
        """
        with self._thread_lock:
            try:
                self._ao_hardware.set_setpoint(channel, self.convert_setpoint(channel, value))
            except BaseException:
                self.log.exception(f'Error while trying to set channel "{channel}" to setpoint "{value}".')

    def convert_setpoint(self, channel: str, value: float, reverse: bool = False):
        """Converts setpoint value in arbitrary value to hardware value"""

        # check if convertion is defined, otherwise just returns input value as output
        if self.use_conversion(channel):
            if reverse:
                return self._power_conversion.convert_voltage_to_power(value, channel)
            else:
                return self._power_conversion.convert_power_to_voltage(value, channel)
        else:
            return value

    def convert_setpoints_dict(self, setpoints_dict: dict[str, float], reverse: bool = False) -> dict[str, float]:
        """converts setpoints_dict from arbitrary value to hardware values."""

        return {channel: self.convert_setpoint(channel, value, reverse) for channel, value in setpoints_dict.items()}

    def calibrate_power(self, aom_channel: str, get_meas_data=False) -> None:
        self._power_conversion.calibrate_power(aom_channel, get_meas_data)
        self._set_constraints()

    @QtCore.Slot(bool)
    def toggle_watchdog(self, enable):
        """

        @param bool enable:
        """
        enable = bool(enable)
        with self._thread_lock:
            if enable != self._watchdog_active:
                self._watchdog_active = enable
                self.sigWatchdogToggled.emit(enable)
                if enable:
                    QtCore.QMetaObject.invokeMethod(self, "_watchdog_body", QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def _watchdog_body(self):
        """Helper function to regularly query the states from the hardware.

        This function is called by an internal signal and queries the hardware regularly to fire
        the signal sig_switch_updated, if the hardware changed its state without notifying the logic.
        The timing of the watchdog is set by the ConfigOption watchdog_interval in seconds.
        """
        with self._thread_lock:
            if self._watchdog_active:
                curr_setpoints: dict[str, float] = self.setpoints
                diff_setpoints: dict[str, float] = {
                    channel: setpoint for channel, setpoint in curr_setpoints.items() if setpoint != self._old_setpoints[channel]
                }
                self._old_setpoints: dict[str, float] = curr_setpoints
                if diff_setpoints:
                    self.sigSetpointsChanged.emit(diff_setpoints)
                QtCore.QTimer.singleShot(self._watchdog_interval_ms, self._watchdog_body)
