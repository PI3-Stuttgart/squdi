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



class RedPitayaInterface:
    """Interface class for Red Pitaya hardware control."""

    @abstractmethod
    def setup_scope(self, input1=None, input2=None, trigger_source='ch1_positive_edge',
                   trigger_level=0.0, trigger_hysteresis=0.01, trigger_delay=0,
                   decimation=64, average=False):
        """Configure the oscilloscope settings."""
        pass

    @abstractmethod
    def get_last_seconds(self, seconds):
        """Get the last N seconds of scope data."""
        pass

    @abstractmethod
    def setup_asg(self, channel, freq=0, amp=0, start_p=0, wf='sin', trig_source='immediately'):
        """Configure arbitrary signal generator."""
        pass

    @abstractmethod
    def activate_asg(self, channel, outputchannel):
        """Activate ASG output on specified channel."""
        pass

    @abstractmethod
    def get_scope_status(self):
        """Get current scope status."""
        pass

    @abstractmethod
    def setup_pid(self, pid_channel, input_signal, output_direct='out1',
                 p=0.0, i=0.0, d=0.0, ival=0.0, input_filter=None,
                 invert_signal=False, max_voltage=1, min_voltage=-1, setpoint=0):
        """Configure PID controller."""
        pass

    @abstractmethod
    def get_pid_status(self, pid_channel):
        """Get PID controller status."""
        pass

    @abstractmethod
    def reset_pid_integrator(self, pid_channel, value=0.0):
        """Reset PID integrator."""
        pass

    @abstractmethod
    def setup_iq(self, iq_channel, frequency, bandwidth, input_signal,
                output_direct='off', output_signal='quadrature', phase=0.0,
                gain=0.0, acbandwidth=50000, amplitude=0.1, quadrature_factor=20):
        """Configure IQ demodulator."""
        pass

    @abstractmethod
    def get_iq_data(self, iq_channel, num_samples=1, timeout=1.0):
        """Get IQ demodulator data."""
        pass

    @abstractmethod
    def get_iq_status(self, iq_channel):
        """Get IQ demodulator status."""
        pass

    @abstractmethod
    def get_pyrpl(self):
        """Get the underlying Pyrpl instance."""
        pass