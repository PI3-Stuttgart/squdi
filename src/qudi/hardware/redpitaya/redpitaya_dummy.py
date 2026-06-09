# -*- coding: utf-8 -*-
"""
Dummy hardware module for Red Pitaya.
"""
from qudi.core.module import Base
import numpy as np
from qudi.interface.redpitaya_interface import RedPitayaInterface

class RedPitayaDummy(RedPitayaInterface):
    """Hardware dummy class for Red Pitaya testing."""

    def on_activate(self):
        self._running = False
        self._sample_rate = 125e6
        self._decimation = 1
        self._asg_config = {0: {'enabled': False}, 1: {'enabled': False}}
        self._pid_config = {i: {'enabled': False} for i in range(3)}

    def on_deactivate(self):
        pass

    def acquire_data(self, duration=1.0, trigger_source='immediately'):
        num_points = int(self._sample_rate * duration / self._decimation)
        time_data = np.linspace(0, duration, num_points)
        ch1_data = np.sin(2 * np.pi * 1e6 * time_data)  # 1 MHz sine
        ch2_data = np.sin(2 * np.pi * 2e6 * time_data)  # 2 MHz sine
        return time_data, ch1_data, ch2_data

    def set_oscilloscope_config(self, decimation=1, trigger_delay=0):
        self._decimation = decimation

    def set_asg_output(self, channel, waveform='sin', frequency=1000, amplitude=0.1, offset=0):
        if channel not in [0, 1]:
            raise ValueError("Channel must be 0 or 1")
        self._asg_config[channel].update({
            'waveform': waveform,
            'frequency': frequency,
            'amplitude': amplitude,
            'offset': offset
        })

    def enable_asg_output(self, channel, enable=True):
        if channel not in [0, 1]:
            raise ValueError("Channel must be 0 or 1")
        self._asg_config[channel]['enabled'] = enable

    def configure_pid(self, pid_id, input_signal, setpoint=0, p=0, i=0, d=0):
        if pid_id not in [0, 1, 2]:
            raise ValueError("PID ID must be 0, 1, or 2")
        self._pid_config[pid_id].update({
            'input': input_signal,
            'setpoint': setpoint,
            'p': p, 'i': i, 'd': d
        })

    def enable_pid(self, pid_id, enable=True):
        if pid_id not in [0, 1, 2]:
            raise ValueError("PID ID must be 0, 1, or 2")
        self._pid_config[pid_id]['enabled'] = enable

    def get_pid_output(self, pid_id):
        if pid_id not in [0, 1, 2]:
            raise ValueError("PID ID must be 0, 1, or 2")
        return 0.0  # Dummy output

    def get_device_info(self):
        return {
            'type': 'Dummy Red Pitaya',
            'version': '1.0',
            'serial': 'DUMMY-001'
        }

    def reset_device(self):
        self.on_activate()  # Reset to initial state

    def get_pyrpl(self):
        """Get the underlying Pyrpl instance."""
        return None