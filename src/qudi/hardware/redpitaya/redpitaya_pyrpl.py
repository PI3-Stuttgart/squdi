# -*- coding: utf-8 -*-
"""
Red Pitaya hardware module using PyRPL.

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
from qudi.core.configoption import ConfigOption
from qudi.interface.redpitaya_interface import RedPitayaInterface
from pyrpl import Pyrpl


class RedPitayaPyRPL(RedPitayaInterface):
    """Red Pitaya hardware implementation using PyRPL."""
    
    _hostname = ConfigOption('hostname', '192.168.202.72', missing='nothing')
    _config = ConfigOption('config', missing='warn')
    _gui = ConfigOption('gui', False, missing='nothing')
    
    def on_activate(self):
        """Initialize the Red Pitaya connection."""
        try:
            if self._config:
                self.rpl = Pyrpl(self._config, gui=self._gui)
            else:
                self.rpl = Pyrpl(self._hostname, gui=self._gui)
            self.rp = self.rpl.rp
            self.log.info(f'Red Pitaya connected at {self._hostname}')
        except Exception as e:
            self.log.error(f'Failed to connect to Red Pitaya: {e}')
            raise

    def on_deactivate(self):
        """Close the Red Pitaya connection."""
        if hasattr(self, 'rpl'):
            self.rpl.close()
            self.log.info('Red Pitaya connection closed')

    def acquire_data(self, duration=1.0, trigger_source='immediately'):
        """
        Acquire oscilloscope data.
        
        Args:
            duration (float): Acquisition duration in seconds
            trigger_source (str): Trigger source
            
        Returns:
            tuple: (time_array, ch1_data, ch2_data)
        """
        try:
            scope = self.rp.scope
            
            # Configure scope
            scope.setup(duration=duration, trigger_source=trigger_source)
            
            # Acquire data
            ch1_data, ch2_data = scope.curve()
            
            # Create time array
            dt = duration / len(ch1_data)
            time_array = np.arange(len(ch1_data)) * dt
            
            return time_array, ch1_data, ch2_data
            
        except Exception as e:
            self.log.error(f'Failed to acquire data: {e}')
            raise

    def set_oscilloscope_config(self, decimation=1, trigger_delay=0):
        """
        Configure oscilloscope settings.
        
        Args:
            decimation (int): Decimation factor
            trigger_delay (int): Trigger delay in samples
        """
        try:
            scope = self.rp.scope
            scope.decimation = decimation
            scope.trigger_delay = trigger_delay
            self.log.debug(f'Oscilloscope configured: decimation={decimation}, trigger_delay={trigger_delay}')
        except Exception as e:
            self.log.error(f'Failed to configure oscilloscope: {e}')
            raise

    def set_asg_output(self, channel, waveform='sin', frequency=1000, amplitude=0.1, offset=0):
        """
        Configure arbitrary signal generator output.
        
        Args:
            channel (int): ASG channel (0 or 1)
            waveform (str): Waveform type
            frequency (float): Frequency in Hz
            amplitude (float): Amplitude in V
            offset (float): DC offset in V
        """
        try:
            if channel == 0:
                asg = self.rp.asg0
            elif channel == 1:
                asg = self.rp.asg1
            else:
                raise ValueError(f'Invalid ASG channel: {channel}')
            
            asg.setup(waveform=waveform, frequency=frequency, amplitude=amplitude, offset=offset)
            self.log.debug(f'ASG{channel} configured: {waveform}, {frequency}Hz, {amplitude}V, {offset}V offset')
            
        except Exception as e:
            self.log.error(f'Failed to configure ASG{channel}: {e}')
            raise

    def enable_asg_output(self, channel, enable=True):
        """
        Enable or disable ASG output.
        
        Args:
            channel (int): ASG channel (0 or 1)
            enable (bool): Enable/disable output
        """
        try:
            if channel == 0:
                asg = self.rp.asg0
            elif channel == 1:
                asg = self.rp.asg1
            else:
                raise ValueError(f'Invalid ASG channel: {channel}')
            
            if enable:
                asg.output_direct = 'out1' if channel == 0 else 'out2'
            else:
                asg.output_direct = 'off'
                
            self.log.debug(f'ASG{channel} output {"enabled" if enable else "disabled"}')
            
        except Exception as e:
            self.log.error(f'Failed to {"enable" if enable else "disable"} ASG{channel}: {e}')
            raise

    def configure_pid(self, pid_id, input_signal, setpoint=0, p=0, i=0, d=0):
        """
        Configure PID controller.
        
        Args:
            pid_id (int): PID controller ID (0, 1, or 2)
            input_signal (str): Input signal source
            setpoint (float): PID setpoint
            p (float): Proportional gain
            i (float): Integral gain
            d (float): Derivative gain
        """
        try:
            if pid_id == 0:
                pid = self.rp.pid0
            elif pid_id == 1:
                pid = self.rp.pid1
            elif pid_id == 2:
                pid = self.rp.pid2
            else:
                raise ValueError(f'Invalid PID ID: {pid_id}')
            
            pid.input = input_signal
            pid.setpoint = setpoint
            pid.p = p
            pid.i = i
            pid.d = d
            
            self.log.debug(f'PID{pid_id} configured: input={input_signal}, setpoint={setpoint}, P={p}, I={i}, D={d}')
            
        except Exception as e:
            self.log.error(f'Failed to configure PID{pid_id}: {e}')
            raise

    def enable_pid(self, pid_id, enable=True):
        """
        Enable or disable PID controller.
        
        Args:
            pid_id (int): PID controller ID
            enable (bool): Enable/disable PID
        """
        try:
            if pid_id == 0:
                pid = self.rp.pid0
            elif pid_id == 1:
                pid = self.rp.pid1
            elif pid_id == 2:
                pid = self.rp.pid2
            else:
                raise ValueError(f'Invalid PID ID: {pid_id}')
            
            if enable:
                pid.output_direct = 'out1'  # or 'out2' depending on your setup
            else:
                pid.output_direct = 'off'
                
            self.log.debug(f'PID{pid_id} {"enabled" if enable else "disabled"}')
            
        except Exception as e:
            self.log.error(f'Failed to {"enable" if enable else "disable"} PID{pid_id}: {e}')
            raise

    def get_pid_output(self, pid_id):
        """
        Get current PID output value.
        
        Args:
            pid_id (int): PID controller ID
            
        Returns:
            float: Current PID output
        """
        try:
            if pid_id == 0:
                pid = self.rp.pid0
            elif pid_id == 1:
                pid = self.rp.pid1
            elif pid_id == 2:
                pid = self.rp.pid2
            else:
                raise ValueError(f'Invalid PID ID: {pid_id}')
            
            return float(pid.output)
            
        except Exception as e:
            self.log.error(f'Failed to get PID{pid_id} output: {e}')
            raise

    def get_device_info(self):
        """
        Get device information.
        
        Returns:
            dict: Device information
        """
        try:
            info = {
                'hostname': self._hostname,
                'pyrpl_version': self.rpl.version if hasattr(self.rpl, 'version') else 'unknown',
                'connected': hasattr(self, 'rp') and self.rp is not None,
                'config_file': self._config if self._config else 'hostname-based'
            }
            return info
        except Exception as e:
            self.log.error(f'Failed to get device info: {e}')
            return {'error': str(e)}

    def reset_device(self):
        """Reset the Red Pitaya device."""
        try:
            # Close current connection
            if hasattr(self, 'rpl'):
                self.rpl.close()
            
            # Reinitialize
            time.sleep(1)  # Wait a moment
            self.on_activate()
            
            self.log.info('Red Pitaya device reset successfully')
            
        except Exception as e:
            self.log.error(f'Failed to reset device: {e}')
            raise