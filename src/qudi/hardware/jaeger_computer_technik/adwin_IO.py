"""
This file contains the Qudi dummy module for the confocal scanner.

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
import numpy as np
from PySide2 import QtCore
from fysom import FysomError
from qudi.util.mutex import Mutex
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.anolog_and_digital_io import AnalogAndDigitalIO 
from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase
from qudi.interface.process_control_interface import ProcessControlConstraints
from qudi.interface.process_control_interface import ProcessSetpointInterface
from qudi.interface.mixins.process_control_switch import ProcessControlSwitchMixin
from qudi.core.statusvariable import StatusVar

from qudi.util.helpers import natural_sort, in_range
from qudi.hardware.jaeger_computer_technik.helpers_adwin import sanitize_device_name, normalize_channel_name
from qudi.hardware.jaeger_computer_technik.helpers_adwin import ao_channel_names, ao_voltage_range

import os
import ADwin


## This needs to be compatible with the NI_AO, which is 
## hardware\ni_x_series\ni_x_series_analog_output.py
class Adwin_AO(AdwinBase, ProcessControlSwitchMixin, 
               ProcessSetpointInterface):   #TODO see towards - ProcessSetpointInterface
    _device_name = ConfigOption(name='device_name',
                                default='adwin11',
                                missing='warn',
                                constructor=sanitize_device_name)
    _channels_config = ConfigOption(
        name='channels',
        default={
            'ao0': {'limits': (-10.0, 10.0), 'keep_value': True},
            'ao1': {'limits': (-10.0, 10.0), 'keep_value': True},
            'ao2': {'limits': (-10.0, 10.0), 'keep_value': True}},
        missing='warn')
    
    _setpoints = StatusVar(name='current_setpoints', default=dict())
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._thread_lock = Mutex()

        self._constraints = None
        self._device_channel_mapping = dict()
        self._ao_task_handles = dict()
        self._keep_values = dict()
        
        
    def on_activate(self):
        # Check if device is connected and set device to use
        self.boot_adwin()
        #self.start_adwin_processes(['control_analog_out.TB9'])  
        #self.start_adwin_processes(['control_digout.TB0'])
       
        self._device_channel_mapping = dict()
        self._ao_task_handles = dict()
        self._keep_values = dict()

        # Sanitize channel configuration
        ao_limits = ao_voltage_range(self._device_name)
        valid_channels = ao_channel_names(self._device_name)
        valid_channels_lower = [name.lower() for name in valid_channels]
        limits = dict()
        for ch_name in natural_sort(self._channels_config):
            ch_cfg = self._channels_config[ch_name]
            norm_name = normalize_channel_name(ch_name).lower()
            try:
                device_name = valid_channels[valid_channels_lower.index(norm_name)]
            except (ValueError, IndexError):
                self.log.error(f'Invalid analog output channel "{ch_name}" configured. Channel '
                               f'will be ignored.\nValid analog output channels are: '
                               f'{valid_channels}')
                continue
            try:
                ch_limits = ch_cfg['limits']
            except KeyError:
                ch_limits = ao_limits
            else:
                if not all(in_range(lim, *ao_limits)[0] for lim in ch_limits):
                    self.log.error(
                        f'Invalid analog output voltage limits {ch_limits} configured for channel '
                        f'"{ch_name}". Channel will be ignored.\nValid analog output limits must '
                        f'lie in range {ao_limits}'
                    )
                    continue
            self._device_channel_mapping[ch_name] = device_name
            self._keep_values[ch_name] = bool(ch_cfg.get('keep_value', True))
            limits[ch_name] = ch_limits

        # Initialization of hardware constraints defined in the config file
        self._constraints = ProcessControlConstraints(
            setpoint_channels=self._device_channel_mapping,
            units={ch: 'V' for ch in self._device_channel_mapping},
            limits=limits,
            dtypes={ch: float for ch in self._device_channel_mapping}
        )

        # Sanitize status variables
        self._sanitize_setpoint_status()
        
        
        
    def on_deactivate(self):
        """Stops all adwin process needed for the script
        """
        # TODO
        
        
        self.stop_all()
        pass
    
    ## THIS FOLLOWING FUNCTIONS HAVE TO BE WRITTEN TO MAP TO NI_AO class from Bluefors.cfg
    def get_activity_state(self):
        pass
    @property
    def constraints(self) -> ProcessControlConstraints:
        """ Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self._constraints
    
    def set_activity_state(self, channel: str, active: bool) -> None:
        """ Set activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        try:
            active = bool(active)
        except Exception as err:
            raise TypeError('Unable to convert activity state to bool') from err
        with self._thread_lock:
            try:
                current_state = self._get_activity_state(channel)
            except KeyError as err:
                raise ValueError(f'Invalid channel specifier "{channel}". Valid channels are:\n'
                                 f'{self.constraints.all_channels}') from err
            if active != current_state:
                try:
                    if active:
                        self._create_ao_task(channel) #obsolete
                        self._write_ao_value(channel, self._setpoints.get(channel, 0))
                    else:
                        self._terminate_ao_task(channel)
                finally:
                    self._update_module_state()
    def get_activity_state(self, channel: str) -> bool:
        """ Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        with self._thread_lock:
            return self._get_activity_state(channel)

    def _get_activity_state(self, channel: str) -> bool:
        if channel not in self.constraints.all_channels:
            raise ValueError(f'Invalid channel specifier "{channel}". Valid channels are:\n'
                             f'{self.constraints.all_channels}')
        return channel in self._ao_task_handles                
    
    def _update_module_state(self) -> None:
        busy = len(self._ao_task_handles) > 0
        if busy and self.module_state() != 'locked':
            self.module_state.lock()
        elif not busy and self.module_state() == 'locked':
            self.module_state.unlock()

    def set_setpoint(self, channel: str, value: float) -> None:
        """ Set new setpoint for a single channel """
        value = float(value)
        with self._thread_lock:
            if not self._get_activity_state(channel):
                raise RuntimeError(f'Please activate channel "{channel}" before setting setpoint')
            if not self.constraints.channel_value_in_range(channel, value)[0]:
                raise ValueError(f'Setpoint {value} for channel "{channel}" out of allowed '
                                 f'value bounds {self.constraints.channel_limits[channel]}')
            self._write_ao_value(channel, value)
            self._setpoints[channel] = value

    def get_setpoint(self, channel: str) -> float:
        """ Get current setpoint for a single channel """
        with self._thread_lock:
            if not self._get_activity_state(channel):
                raise RuntimeError(f'Please activate channel "{channel}" before getting setpoint')
            return self._setpoints[channel]

    def set_new_ao_limits(self, is_LT_regime):
        #lim = {'ao2': [0, lim], 'ao1': [0, lim], 'ao3': [0, lim]}
        if is_LT_regime:
            limits = {ch_name:ch_params["limits_LT"]  for ch_name, ch_params in self._channels_config.items()}
        else:
            limits = {ch_name:ch_params["limits"]  for ch_name, ch_params in self._channels_config.items()}
        if self._constraints:
            self._constraints._channel_limits = limits

    def _terminate_ao_task(self, channel: str) -> None:
        """ Reset analog output to 0 if keep_values flag is not set """
        try:
            if not self._keep_values[channel]:
                self._write_ao_value(0)
            task = self._ao_task_handles.pop(channel)
        except KeyError:
            return
        try:
            if not task.is_task_done():
                task.stop()
        finally:
            task.close()

    def _create_ao_task(self, channel: str) -> None:
        if channel in self._ao_task_handles:
            raise ValueError(f'AO task with name "{channel}" already present.')
        try:
            ao_task = ni.Task(channel)
        except ni.DaqError as err:
            raise RuntimeError(f'Unable to create NI task "{channel}"') from err
        try:
            ao_phys_ch = f'/{self._device_name}/{self._device_channel_mapping[channel]}'
            min_val, max_val = self.constraints.channel_limits[channel]
            ao_task.ao_channels.add_ao_voltage_chan(physical_channel=ao_phys_ch,
                                                    min_val=min_val,
                                                    max_val=max_val)
        except Exception as err:
            try:
                ao_task.close()
            except ni.DaqError:
                pass
            raise RuntimeError('Error while configuring NI analog out task') from err
        self._ao_task_handles[channel] = ao_task

    def _write_ao_value(self, channel: str, value: float) -> None:
        self._ao_task_handles[channel].write(value)

    def _sanitize_setpoint_status(self) -> None:
        # Remove obsolete channels and out-of-bounds values
        for channel, value in list(self._setpoints.items()):
            try:
                if not self.constraints.channel_value_in_range(channel, value)[0]:
                    del self._setpoints[channel]
            except KeyError:
                del self._setpoints[channel]
        # Add missing setpoint channels and set initial value to zero
        self._setpoints.update(
            {ch: 0 for ch in self.constraints.setpoint_channels if ch not in self._setpoints}
        )
    
    def set_setpoint(self):
        pass
    def get_setpoint(self):
        pass
    def set_activity_state(self):
        pass

class Adwin_IO(AnalogAndDigitalIO, AdwinBase): #TODO see towards - ProcessSetpointInterface
    
    # Imports the conifg for all available ports
    _ports = ConfigOption(name='ports', missing='warn')
    
        

    def on_activate(self):
        self.boot_adwin()
        self.start_adwin_processes(['control_analog_out.TB9'])  
        self.start_adwin_processes(['control_digout.TB0'])
        
        
    def on_deactivate(self):
        """Stops all adwin process needed for the script
        """
        # TODO
        pass
    
    
    ## THIS FOLLOWING FUNCTIONS HAVE TO BE WRITTEN TO MAP TO NI_AO class from Bluefors.cfg
    def get_activity_state(self):
        pass
    def constraints(self):
        pass
    def set_setpoint(self):
        pass
    def get_setpoint(self):
        pass
    def set_activity_state(self):
        pass
    
    
    def init_analog_outputs(self):
        pass

    
    def set_digi_out(self, port: int, active: bool):
        
        if self.available_ports()['digital'][port]['IO'] == 'in':
            par_idx = 8 if port == 0 else port
        
            if active:
                self.adwin.Set_Par(par_idx, 1)
            if not active:
                self.adwin.Set_Par(par_idx, 0)
        else:
            raise ValueError('Port is not defined')
    
    def get_digi_out(self, port: int) -> bool:
        pass
    
    
    def set_analog_out(self, port: int, voltage: float):
        
        if self.available_ports()['analog'][port] is not None:
            par_idx = 8 if port == 0 else port

            self.adwin.Set_FPar(par_idx, voltage)
    
    
    def get_analog_out(self, port: int) -> float:
        pass
    
    def available_ports(self) -> dict:
        return self._ports