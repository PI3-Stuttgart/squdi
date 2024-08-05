# -*- coding: utf-8 -*-

"""
Combine two hardware switches into one.

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

from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector


class ProcessSetpointCombinerInterfuse(ProcessSetpointInterface):
    """Methods to control slow ao devices.
    This interfuse in particular combines two ao devices into one.

    Example config for copy-paste:

    process_setpoint_combiner:
        module.Class: 'interfuse.process_setpoint_combiner_interfuse.ProcessSetpointCombinerInterfuse'
        connect:
            ao_device1: OPX
            ao_device2: Adwin
        options:
            name: combined_aos  # optional name of the combined hardware

            # if True the switch names will be extended by the hardware name of the individual switches in front.
            extend_hardware_name: False

    """

    # connectors for the switches to be combined
    ao_device1 = Connector(interface="ProcessSetpointInterface")
    ao_device2 = Connector(interface="ProcessSetpointInterface")

    # optional name of the combined hardware
    _hardware_name = ConfigOption(name="name", default=None, missing="nothing")

    # if extend_hardware_name is True the switch names will be extended by the hardware name
    # of the individual switches in front.
    _extend_hardware_name = ConfigOption(
        name="extend_hardware_name", default=False, missing="nothing"
    )

    def on_activate(self):
        """Activate the module and fill status variables."""
        if self._hardware_name is None:
            self._hardware_name = self.module_name

    def on_deactivate(self):
        """TODO: Deactivate the module and clean up."""

    @property
    def constraints(self) -> ProcessControlConstraints:
        """Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self.ao_device1().constraints.update(self.ao_device2().constraints)

    def set_activity_state(self, channel: str, active: bool) -> None:
        """TODO: Documentation"""
        if channel in self.ao_device1().constraints:
            self.ao_device1().set_activity_state(channel, active)
        elif channel in self.ao_device2().constraints:
            self.ao_device2().set_activity_state(channel, active)
        else:
            self.log.warning("no such channel")

    def get_activity_state(self, channel: str) -> bool:
        """Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        if channel in self.ao_device1().constraints:
            return self.ao_device1().get_activity_state(channel)
        elif channel in self.ao_device2().constraints:
            return self.ao_device2().get_activity_state(channel)
        else:
            self.log.warning("no such channel")
            return False

    def set_setpoint(self, channel: str, value: float) -> None:
        """Set new setpoint for a single channel"""
        if channel in self.ao_device1().constraints:
            self.ao_device1().set_setpoint(channel, value)
        elif channel in self.ao_device2().constraints:
            self.ao_device2().set_setpoint(channel, value)
        else:
            self.log.warning("no such channel")

    def get_setpoint(self, channel: str) -> float:
        """Get current setpoint for a single channel"""
        if channel in self.ao_device1().constraints:
            return self.ao_device1().get_setpoint(channel)
        elif channel in self.ao_device2().constraints:
            return self.ao_device2().get_setpoint(channel)
        else:
            self.log.warning("no such channel")
            return 0
