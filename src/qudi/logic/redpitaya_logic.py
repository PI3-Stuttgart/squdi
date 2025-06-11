# -*- coding: utf-8 -*-
"""
Red Pitaya logic module for high-level control and data processing.

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

import numpy as np
import time
from collections import OrderedDict
from PySide2 import QtCore

from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex


class RedPitayaLogic(LogicBase):
    """Logic module for Red Pitaya control and data processing."""
    
    # Connectors
    redpitaya = Connector(interface='RedPitayaInterface')
    
    # Status variables
    _acquisition_running = StatusVar('acquisition_running', False)
    _current_data = StatusVar('current_data', None)
    _pid_states = StatusVar('pid_states', {0: False, 1: False, 2: False})
    
    # Config options
    _default_duration = ConfigOption('default_duration', 1.0, missing='nothing')
    _default_decimation = ConfigOption('default_decimation', 1, missing='nothing')
    _auto_save = ConfigOption('auto_save', False, missing='nothing')
    
    # Signals
    sigDataAcquired = QtCore.Signal(object, object, object)  # time, ch1, ch2
    sigPidStateChanged = QtCore.Signal(int, bool)  # pid_id, enabled
    sigDeviceStatusChanged = QtCore.Signal(dict)  # device info
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mutex = RecursiveMutex()
        
        # Data storage
        self.time_data = np.array([])
        self.ch1_data = np.array([])
        self.ch2_data = np.array([])
        
        # Acquisition parameters
        self.acquisition_duration = self._default_duration
        self.decimation = self._default_decimation
        self.trigger_source = 'immediately'
        
        # PID parameters
        self.pid_configs = {
            0: {'input': 'in1', 'setpoint': 0, 'p': 0, 'i': 0, 'd': 0},
            1: {'input': 'in2', 'setpoint': 0, 'p': 0, 'i': 0, 'd': 0},
            2: {'input': 'in1', 'setpoint': 0, 'p': 0, 'i': 0, 'd': 0}
        }

    def on_activate(self):
        """Activate the logic module."""
        # Configure oscilloscope with default settings
        self.redpitaya().set_oscilloscope_config(
            decimation=self.decimation,
            trigger_delay=0
        )
        
        # Get initial device status
        device_info = self.redpitaya().get_device_info()
        self.sigDeviceStatusChanged.emit(device_info)
        
        self.log.info('Red Pitaya logic activated')

    def on_deactivate(self):
        """Deactivate the logic module."""
        # Stop any running acquisition
        if self._acquisition_running:
            self.stop_acquisition()
        
        # Disable all PIDs
        for pid_id in range(3):
            if self._pid_states.get(pid_id, False):
                self.disable_pid(pid_id)
        
        self.log.info('Red Pitaya logic deactivated')

    # Data acquisition methods
    def start_acquisition(self, duration=None, trigger_source=None):
        """
        Start data acquisition.
        
        Args:
            duration (float): Acquisition duration in seconds
            trigger_source (str): Trigger source
        """
        with self._mutex:
            if self._acquisition_running:
                self.log.warning('Acquisition already running')
                return False
            
            try:
                # Update parameters if provided
                if duration is not None:
                    self.acquisition_duration = duration
                if trigger_source is not None:
                    self.trigger_source = trigger_source
                
                # Configure oscilloscope
                self.redpitaya().set_oscilloscope_config(
                    decimation=self.decimation,
                    trigger_delay=0
                )
                
                # Acquire data
                time_data, ch1_data, ch2_data = self.redpitaya().acquire_data(
                    duration=self.acquisition_duration,
                    trigger_source=self.trigger_source
                )
                
                # Store data
                self.time_data = time_data
                self.ch1_data = ch1_data
                self.ch2_data = ch2_data
                
                # Emit signal
                self.sigDataAcquired.emit(time_data, ch1_data, ch2_data)
                
                self.log.info(f'Data acquired: {len(time_data)} samples over {self.acquisition_duration}s')
                return True
                
            except Exception as e:
                self.log.error(f'Failed to acquire data: {e}')
                return False

    def stop_acquisition(self):
        """Stop data acquisition."""
        with self._mutex:
            self._acquisition_running = False
            self.log.info('Data acquisition stopped')

    def get_current_data(self):
        """
        Get the current acquired data.
        
        Returns:
            tuple: (time_array, ch1_data, ch2_data)
        """
        return self.time_data, self.ch1_data, self.ch2_data

    # Signal generation methods
    def configure_signal_generator(self, channel, waveform='sin', frequency=1000, 
                                 amplitude=0.1, offset=0, enable=True):
        """
        Configure and optionally enable signal generator.
        
        Args:
            channel (int): ASG channel (0 or 1)
            waveform (str): Waveform type
            frequency (float): Frequency in Hz
            amplitude (float): Amplitude in V
            offset (float): DC offset in V
            enable (bool): Enable output after configuration
        """
        try:
            self.redpitaya().set_asg_output(
                channel=channel,
                waveform=waveform,
                frequency=frequency,
                amplitude=amplitude,
                offset=offset
            )
            
            if enable:
                self.redpitaya().enable_asg_output(channel, True)
            
            self.log.info(f'ASG{channel} configured: {waveform}, {frequency}Hz, {amplitude}V')
            return True
            
        except Exception as e:
            self.log.error(f'Failed to configure ASG{channel}: {e}')
            return False

    def enable_signal_generator(self, channel, enable=True):
        """
        Enable or disable signal generator output.
        
        Args:
            channel (int): ASG channel (0 or 1)
            enable (bool): Enable/disable output
        """
        try:
            self.redpitaya().enable_asg_output(channel, enable)
            self.log.info(f'ASG{channel} {"enabled" if enable else "disabled"}')
            return True
        except Exception as e:
            self.log.error(f'Failed to {"enable" if enable else "disable"} ASG{channel}: {e}')
            return False

    # PID control methods
    def configure_pid(self, pid_id, input_signal='in1', setpoint=0, p=0, i=0, d=0):
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
            self.redpitaya().configure_pid(
                pid_id=pid_id,
                input_signal=input_signal,
                setpoint=setpoint,
                p=p, i=i, d=d
            )
            
            # Store configuration
            self.pid_configs[pid_id] = {
                'input': input_signal,
                'setpoint': setpoint,
                'p': p, 'i': i, 'd': d
            }
            
            self.log.info(f'PID{pid_id} configured: P={p}, I={i}, D={d}, setpoint={setpoint}')
            return True
            
        except Exception as e:
            self.log.error(f'Failed to configure PID{pid_id}: {e}')
            return False

    def enable_pid(self, pid_id, enable=True):
        """
        Enable or disable PID controller.
        
        Args:
            pid_id (int): PID controller ID
            enable (bool): Enable/disable PID
        """
        try:
            self.redpitaya().enable_pid(pid_id, enable)
            self._pid_states[pid_id] = enable
            self.sigPidStateChanged.emit(pid_id, enable)
            
            self.log.info(f'PID{pid_id} {"enabled" if enable else "disabled"}')
            return True
            
        except Exception as e:
            self.log.error(f'Failed to {"enable" if enable else "disable"} PID{pid_id}: {e}')
            return False

    def get_pid_output(self, pid_id):
        """
        Get current PID output value.
        
        Args:
            pid_id (int): PID controller ID
            
        Returns:
            float: Current PID output
        """
        try:
            return self.redpitaya().get_pid_output(pid_id)
        except Exception as e:
            self.log.error(f'Failed to get PID{pid_id} output: {e}')
            return 0.0

    def get_all_pid_outputs(self):
        """
        Get all PID output values.
        
        Returns:
            dict: PID outputs {pid_id: output_value}
        """
        outputs = {}
        for pid_id in range(3):
            if self._pid_states.get(pid_id, False):
                outputs[pid_id] = self.get_pid_output(pid_id)
            else:
                outputs[pid_id] = 0.0
        return outputs

    # Utility methods
    def reset_device(self):
        """Reset the Red Pitaya device."""
        try:
            self.redpitaya().reset_device()
            
            # Reset internal state
            self._acquisition_running = False
            self._pid_states = {0: False, 1: False, 2: False}
            
            # Get updated device status
            device_info = self.redpitaya().get_device_info()
            self.sigDeviceStatusChanged.emit(device_info)
            
            self.log.info('Red Pitaya device reset successfully')
            return True
            
        except Exception as e:
            self.log.error(f'Failed to reset device: {e}')
            return False

    def get_device_status(self):
        """
        Get current device status.
        
        Returns:
            dict: Device status information
        """
        try:
            device_info = self.redpitaya().get_device_info()
            device_info.update({
                'acquisition_running': self._acquisition_running,
                'pid_states': self._pid_states.copy(),
                'last_acquisition_samples': len(self.time_data)
            })
            return device_info
        except Exception as e:
            self.log.error(f'Failed to get device status: {e}')
            return {'error': str(e)}

    # Data analysis methods
    def calculate_statistics(self, channel=1):
        """
        Calculate basic statistics for acquired data.
        
        Args:
            channel (int): Channel to analyze (1 or 2)
            
        Returns:
            dict: Statistics (mean, std, min, max, rms)
        """
        try:
            if channel == 1:
                data = self.ch1_data
            elif channel == 2:
                data = self.ch2_data
            else:
                raise ValueError(f'Invalid channel: {channel}')
            
            if len(data) == 0:
                return {'error': 'No data available'}
            
            stats = {
                'mean': float(np.mean(data)),
                'std': float(np.std(data)),
                'min': float(np.min(data)),
                'max': float(np.max(data)),
                'rms': float(np.sqrt(np.mean(data**2))),
                'samples': len(data)
            }
            
            return stats
            
        except Exception as e:
            self.log.error(f'Failed to calculate statistics: {e}')
            return {'error': str(e)}