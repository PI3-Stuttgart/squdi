# filepath: c:\Users\yy3\GIT\squdi\src\qudi\hardware\redpitaya\redpitaya_pyrpl.py
# -*- coding: utf-8 -*-
"""
Red Pitaya hardware driver using PyRPL.

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

from qudi.core.module import Base
import numpy as np
from pyrpl import Pyrpl
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.interface.redpitaya_interface import RedPitayaInterface


class RedPitayaPyrpl(RedPitayaInterface):
    """Hardware module for controlling Red Pitaya using PyRPL library."""

    # Config options - simplified to just IP address
    _ip_address = ConfigOption('ip_address', '192.168.1.100')
    _sampling_rate = ConfigOption('sampling_rate', 125e6)  # Base sampling rate in Hz
    _decimation = ConfigOption('decimation', 8)  # Default decimation factor

    # Status variables
    _asg_states = StatusVar('asg_states', {0: False, 1: False})
    _pid_states = StatusVar('pid_states', {0: False, 1: False, 2: False})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pyrpl = None
        self._rp = None
        self._is_connected = False

    def on_activate(self):
        """Initialize and connect to Red Pitaya device."""
        try:
            # Initialize PyRPL with IP address and custom config
            config = {
                'hostname': self._ip_address,
                'modules': {
                    'scope': {'decimation': self._decimation},
                    'asg0': {'output_direct': 'off'},
                    'asg1': {'output_direct': 'off'},
                    'pid0': {'input_direct': 'off', 'output_direct': 'off'},
                    'pid1': {'input_direct': 'off', 'output_direct': 'off'},
                    'pid2': {'input_direct': 'off', 'output_direct': 'off'}
                }
            }
            
            self._pyrpl = Pyrpl(hostname=self._ip_address,
                               config=config,
                               autostart=True,
                               load_default_profile=False)
            self._rp = self._pyrpl.rp
            self._is_connected = True
            
            # Configure default settings
            self._setup_device()
            
            self.log.info(f'Successfully connected to Red Pitaya at {self._ip_address}')
            return 0  # Qudi expects 0 for success
            
        except Exception as e:
            self.log.error(f'Failed to connect to Red Pitaya: {str(e)}')
            return -1  # Qudi expects non-zero for failure

    def on_deactivate(self):
        """Clean up and disconnect from device."""
        try:
            # Disable all outputs
            for channel in range(2):
                self.enable_asg_output(channel, False)
            
            # Disable all PIDs
            for pid_id in range(3):
                self.enable_pid(pid_id, False)
            
            self._rp = None
            self._pyrpl = None
            self._is_connected = False
            
        except Exception as e:
            self.log.error(f'Error during deactivation: {str(e)}')

    def _setup_device(self):
        """Configure initial device settings."""
        # Set sampling rate and decimation
        self._rp.scope.decimation = self._decimation
        
        # Configure default scope settings
        self._rp.scope.trigger_source = 'immediately'
        self._rp.scope.trigger_delay = 0
        
        # Initialize ASGs
        for channel in range(2):
            self._rp.asgs[channel].output_direct = 'off'
            self._asg_states[channel] = False
        
        # Initialize PIDs
        for pid_id in range(3):
            pid = self._rp.pids[pid_id]
            pid.input_direct = 'off'
            pid.output_direct = 'off'
            self._pid_states[pid_id] = False

    def acquire_data(self, duration=1.0, trigger_source='immediately'):
        """Acquire oscilloscope data."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")
        
            # Configure scope
            self._rp.scope.decimation = self._decimation
            self._rp.scope.trigger_source = trigger_source
            
            # Calculate number of samples
            samples = int(duration * self._sampling_rate / self._decimation)
            self._rp.scope.data_length = samples
            
            # Acquire data
            data = self._rp.scope.curve()
            time_array = np.linspace(0, duration, len(data[0]))
            
            return time_array, data[0], data[1]
            
        except Exception as e:
            self.log.error(f'Error acquiring data: {str(e)}')
            return np.array([]), np.array([]), np.array([])

    def set_oscilloscope_config(self, decimation=1, trigger_delay=0):
        """Configure oscilloscope settings."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")
        
            self._rp.scope.decimation = decimation
            self._rp.scope.trigger_delay = trigger_delay
            self._decimation = decimation
            return True
            
        except Exception as e:
            self.log.error(f'Error configuring oscilloscope: {str(e)}')
            return False

    def set_asg_output(self, channel, waveform='sin', frequency=1000, amplitude=0.1, offset=0):
        """Configure arbitrary signal generator output."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            asg = self._rp.asgs[channel]
            
            # Configure waveform
            if waveform == 'sin':
                asg.setup(waveform='sin',
                         frequency=frequency,
                         amplitude=amplitude,
                         offset=offset)
            elif waveform == 'square':
                asg.setup(waveform='square',
                         frequency=frequency,
                         amplitude=amplitude,
                         offset=offset)
            elif waveform == 'triangle':
                asg.setup(waveform='ramp',
                         frequency=frequency,
                         amplitude=amplitude,
                         offset=offset)
            elif waveform == 'noise':
                asg.setup(waveform='noise',
                         amplitude=amplitude,
                         offset=offset)
            else:
                raise ValueError(f"Unsupported waveform type: {waveform}")
                
            return True
            
        except Exception as e:
            self.log.error(f'Error configuring ASG{channel}: {str(e)}')
            return False

    def enable_asg_output(self, channel, enable=True):
        """Enable or disable ASG output."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            asg = self._rp.asgs[channel]
            if enable:
                asg.output_direct = 'out{}'.format(channel + 1)
            else:
                asg.output_direct = 'off'
                
            self._asg_states[channel] = enable
            return True
            
        except Exception as e:
            self.log.error(f'Error {"enabling" if enable else "disabling"} ASG{channel}: {str(e)}')
            return False

    def configure_pid(self, pid_id, input_signal, setpoint=0, p=0, i=0, d=0):
        """Configure PID controller."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            pid = self._rp.pids[pid_id]
            
            # Configure input
            pid.input_direct = input_signal
            pid.setpoint = setpoint
            pid.p = p
            pid.i = i
            pid.d = d
            
            return True
            
        except Exception as e:
            self.log.error(f'Error configuring PID{pid_id}: {str(e)}')
            return False

    def enable_pid(self, pid_id, enable=True):
        """Enable or disable PID controller."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            pid = self._rp.pids[pid_id]
            if enable:
                pid.output_direct = f'out{pid_id + 1}'
            else:
                pid.output_direct = 'off'
                
            self._pid_states[pid_id] = enable
            return True
            
        except Exception as e:
            self.log.error(f'Error {"enabling" if enable else "disabling"} PID{pid_id}: {str(e)}')
            return False

    def get_pid_output(self, pid_id):
        """Get current PID output value."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            pid = self._rp.pids[pid_id]
            return float(pid.output)
            
        except Exception as e:
            self.log.error(f'Error getting PID{pid_id} output: {str(e)}')
            return 0.0

    def get_device_info(self):
        """Get device information."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            info = {
                'ip_address': self._ip_address,
                'sampling_rate': self._sampling_rate,
                'decimation': self._decimation,
                'asg_states': self._asg_states.copy(),
                'pid_states': self._pid_states.copy(),
                'connected': self._is_connected
            }
            return info
            
        except Exception as e:
            self.log.error(f'Error getting device info: {str(e)}')
            return {'error': str(e)}

    def reset_device(self):
        """Reset device to default state."""
        try:
            if not self._is_connected:
                raise RuntimeError("Device not connected")

            # Disable all outputs
            for channel in range(2):
                self.enable_asg_output(channel, False)
            
            # Disable all PIDs
            for pid_id in range(3):
                self.enable_pid(pid_id, False)
            
            # Reset scope settings
            self.set_oscilloscope_config(self._decimation, 0)
            
            # Re-initialize device settings
            self._setup_device()
            
            return True
            
        except Exception as e:
            self.log.error(f'Error resetting device: {str(e)}')
            return False