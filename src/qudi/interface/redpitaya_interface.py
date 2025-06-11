# -*- coding: utf-8 -*-
"""
Interface for Red Pitaya devices using PyRPL.

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

from abc import abstractmethod
from qudi.core.module import Base
import numpy as np


class RedPitayaInterface(Base):
    """Interface for Red Pitaya devices using PyRPL."""

    # Oscilloscope methods
    @abstractmethod
    def acquire_data(self, duration=1.0, trigger_source='immediately'):
        """
        Acquire oscilloscope data.
        
        Args:
            duration (float): Acquisition duration in seconds
            trigger_source (str): Trigger source ('immediately', 'ch1', 'ch2', etc.)
            
        Returns:
            tuple: (time_array, ch1_data, ch2_data)
        """
        pass

    @abstractmethod
    def set_oscilloscope_config(self, decimation=1, trigger_delay=0):
        """
        Configure oscilloscope settings.
        
        Args:
            decimation (int): Decimation factor
            trigger_delay (int): Trigger delay in samples
        """
        pass

    # Signal generator methods
    @abstractmethod
    def set_asg_output(self, channel, waveform='sin', frequency=1000, amplitude=0.1, offset=0):
        """
        Configure arbitrary signal generator output.
        
        Args:
            channel (int): ASG channel (0 or 1)
            waveform (str): Waveform type ('sin', 'square', 'triangle', 'noise')
            frequency (float): Frequency in Hz
            amplitude (float): Amplitude in V
            offset (float): DC offset in V
        """
        pass

    @abstractmethod
    def enable_asg_output(self, channel, enable=True):
        """
        Enable or disable ASG output.
        
        Args:
            channel (int): ASG channel (0 or 1)
            enable (bool): Enable/disable output
        """
        pass

    # PID controller methods
    @abstractmethod
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
        pass

    @abstractmethod
    def enable_pid(self, pid_id, enable=True):
        """
        Enable or disable PID controller.
        
        Args:
            pid_id (int): PID controller ID
            enable (bool): Enable/disable PID
        """
        pass

    @abstractmethod
    def get_pid_output(self, pid_id):
        """
        Get current PID output value.
        
        Args:
            pid_id (int): PID controller ID
            
        Returns:
            float: Current PID output
        """
        pass

    # General methods
    @abstractmethod
    def get_device_info(self):
        """
        Get device information.
        
        Returns:
            dict: Device information
        """
        pass

    @abstractmethod
    def reset_device(self):
        """Reset the Red Pitaya device."""
        pass