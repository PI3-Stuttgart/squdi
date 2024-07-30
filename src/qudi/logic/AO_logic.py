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

from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex


class AOLogic(LogicBase):
    """ Logic module for interacting with the aonalog outputs of hardware.

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

    # connector for one switch, if multiple switches are needed use the SwitchCombinerInterfuse
    ao_hardware = Connector(interface='ProcessSetpointInterface')

    _watchdog_interval = ConfigOption(name='watchdog_interval', default=1.0, missing='nothing')
    _autostart_watchdog = ConfigOption(name='autostart_watchdog', default=False, missing='nothing')
    
    _hardware_bounds_V = (-0.5, 0.5) # V

    sigSetpointsChanged = QtCore.Signal(dict)
    sigWatchdogToggled = QtCore.Signal(bool)

    # directly wrapped attributes from hardware module
    __wrapped_hw_attributes = frozenset({'ao_names', 'number_of_aos'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._thread_lock = RecursiveMutex()

        self._watchdog_active = False
        self._watchdog_interval_ms = 500
        self._old_states = dict()

    def on_activate(self):
        """ Activate module
        """
        self._old_setpoints = self.setpoints
        self._watchdog_interval_ms = int(round(self._watchdog_interval * 1000))

        if self._autostart_watchdog:
            self._watchdog_active = True
            QtCore.QMetaObject.invokeMethod(self, '_watchdog_body', QtCore.Qt.QueuedConnection)
        else:
            self._watchdog_active = False

    def on_deactivate(self):
        """ Deactivate module
        """
        self._watchdog_active = False

    def __getattr__(self, item):
        if item in self.__wrapped_hw_attributes:
            return getattr(self.ao_hardware(), item)
        raise AttributeError(f'SwitchLogic has no attribute with name "{item}"')
    

    @property
    def watchdog_active(self):
        return self._watchdog_active

    @property
    def setpoints(self):
        """ The current states the hardware is in as state dictionary with switch names as keys and
        state names as values.

        @return dict: All the current states of the switches in the form {"switch": "state"}
        """
        with self._thread_lock:
            try:
                setpoints = self.ao_hardware().setpoints
            except:
                if self._watchdog_active:
                    self.toggle_watchdog(False)
                    self.log.exception(f'Error during query of all switch states. '
                                       f'Deactivating watchdog to avoid constant errors.')
                else:
                    self.log.exception(f'Error during query of all setpoints.')
                setpoints = dict()
            return setpoints

    @setpoints.setter
    def setpoints(self, setpoints_dict: dict[str, float], use_hardware_values: bool = False):
        """ The setter for the states of the hardware.

        The setpoint of the system can be set by specifying a dict that has the setpoint_channel names as keys
        and the setpoints as values.

        @param dict setpoints_dict: state dict of the form {"channel": "setpoint"}
        """
        with self._thread_lock:
            try:
                if use_hardware_values:
                    self.ao_hardware().setpoints = setpoints_dict
                else:
                    self.ao_hardware().setpoint(self._convert_setpoints(setpoints_dict))
            except:
                self.log.exception('Error while trying to set setpoints.')

            setpoints = self.setpoints
            if setpoints:
                self.sigSetpointsChanged.emit({channel: setpoints[channel] for channel in setpoints_dict})

    def get_setpoint(self, channel: str, get_hardware_value = False):
        """ Query state of single switch by name

        @param str channel: name of the channel to query the setpoint for
        @return str: The current switch state
        """
        with self._thread_lock:
            try:
                setpoint_hw = self.ao_hardware().get_setpoint(channel)
                if get_hardware_value:
                    setpoint = setpoint_hw.copy()
                else:
                    setpoint = self.conv_setpoint_to_hw(channel, setpoint_hw, invert=True)
            except:
                self.log.exception(f'Error while trying to query setpoint of channel "{channel}".')
                setpoint = None
            return setpoint

    @QtCore.Slot(str, str)
    def set_setpoint(self, channel: str, value: float, use_hardware_value: bool = False):
        """ Query state of single channel

        @param str switch: name of the channel to change
        @param str state: name of the setpoint to set
        """
        with self._thread_lock:
            try:
                #
                if use_hardware_value:
                    self.ao_hardware().set_setpoint(channel, value)
                    # self.sigSetpointsChanged.emit(self.setpoints)
                else:
                    self.ao_hardware().set_setpoint(channel, self.conv_setpoint_to_hw(channel, value))
            except:
                self.log.exception(
                    f'Error while trying to set channel "{channel}" to setpoint "{value}".'
                )
            
    def conv_setpoint_to_hw(self, channel: str, value: float, invert: bool = False):

        # check if convertion is defined, otherwise just returns input value as output
        if channel in self._hw_params:
            if 'conv_bounds' in self._hw_params[channel]:
                source_min, source_max = self._hw_params[channel]['conv_bounds'] if not invert else \
                    self._hardware_bounds
                target_min, target_max = self._hardware_bounds if not invert else \
                    self._hw_params[channel]['conv_bounds']
        # returns input value if no convartion bounds are define in qudi config file
        else:
            return value
                
        # normalize value
        normalized_value = (value - source_min) / (source_max - source_min)
        # Scale the normalized value to the target bounds
        converted_value = normalized_value * (target_max - target_min) + target_min
    
        return converted_value
        
        
    def convert_setpoints_dict_to_hw(self, setpoints_dict, invert: bool = False):
        return {channel: self.convert_setpoint(channel, value, invert=invert) \
            for channel, value in setpoints_dict.items()}
    
  

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
                    QtCore.QMetaObject.invokeMethod(self,
                                                    '_watchdog_body',
                                                    QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def _watchdog_body(self):
        """ Helper function to regularly query the states from the hardware.

        This function is called by an internal signal and queries the hardware regularly to fire
        the signal sig_switch_updated, if the hardware changed its state without notifying the logic.
        The timing of the watchdog is set by the ConfigOption watchdog_interval in seconds.
        """
        with self._thread_lock:
            if self._watchdog_active:
                curr_setpoints = self.setpoints
                diff_setpoints = {channel: setpoint for channel, setpoint in curr_setpoints.items() if
                              setpoint != self._old_setpoints[channel]}
                self._old_states = curr_setpoints
                if diff_setpoints:
                    self.sigSetpointsChanged.emit(diff_setpoints)
                QtCore.QTimer.singleShot(self._watchdog_interval_ms, self._watchdog_body)
