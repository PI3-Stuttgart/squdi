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
import time
import threading
from PySide2 import QtCore


class _PidReadRequest:
    """Container used to return one queued PyRPL register read."""

    def __init__(self, pid_channel):
        self.pid_channel = pid_channel
        self.completed = threading.Event()
        self.value = None
        self.error = None


class _PyrplIoBridge(QtCore.QObject):
    """Execute PyRPL accesses in the thread that created the PyRPL GUI."""

    sigReadPidIntegrator = QtCore.Signal(object)
    sigReadPidWrapState = QtCore.Signal(object)

    def __init__(self, pids):
        super().__init__()
        self._pids = tuple(pids)
        self.sigReadPidIntegrator.connect(
            self._read_pid_integrator,
            QtCore.Qt.QueuedConnection,
        )
        self.sigReadPidWrapState.connect(
            self._read_pid_wrap_state,
            QtCore.Qt.QueuedConnection,
        )

    @QtCore.Slot(object)
    def _read_pid_integrator(self, request):
        try:
            request.value = float(self._pids[request.pid_channel].ival)
        except Exception as error:
            request.error = error
        finally:
            request.completed.set()

    @QtCore.Slot(object)
    def _read_pid_wrap_state(self, request):
        try:
            pid = self._pids[request.pid_channel]
            request.value = {
                'proportional_gain': float(pid.p),
                'pid_minimum': float(pid.min_voltage),
                'pid_maximum': float(pid.max_voltage),
                'integrator': float(pid.ival),
            }
        except Exception as error:
            request.error = error
        finally:
            request.completed.set()

    def read_pid_integrator(self, pid_channel, timeout=2.0):
        request = _PidReadRequest(pid_channel)
        if self.thread() is QtCore.QThread.currentThread():
            self._read_pid_integrator(request)
        else:
            self.sigReadPidIntegrator.emit(request)
            if not request.completed.wait(timeout):
                raise TimeoutError("Timed out while reading the PID integrator.")

        if request.error is not None:
            raise request.error
        return request.value

    def read_pid_wrap_state(self, pid_channel, timeout=2.0):
        request = _PidReadRequest(pid_channel)
        if self.thread() is QtCore.QThread.currentThread():
            self._read_pid_wrap_state(request)
        else:
            self.sigReadPidWrapState.emit(request)
            if not request.completed.wait(timeout):
                raise TimeoutError("Timed out while reading the PID wrap state.")

        if request.error is not None:
            raise request.error
        return request.value


class RedPitayaPyrpl(Base, RedPitayaInterface):
    """Hardware module for controlling Red Pitaya using PyRPL library."""

    # Config options - simplified to just IP address
    _config_file = ConfigOption('config_file', missing='warn')
    
    def __init__(self, config_file=None, **kwargs):
        if config_file :
            self._config_file = config_file
        super().__init__(**kwargs)

    def on_activate(self):
        """Initialize parameters without connecting to device to ensure thread-affinity with GUI thread."""
        self._pyrpl = None
        self._rp = None
        self._scope = None
        self._asg0 = None
        self._asg1 = None
        self._pid0 = None
        self._pid1 = None
        self._pid2 = None
        self._iq0 = None 
        self._iq1 = None
        self._iq2 = None
        self._pyrpl_io_bridge = None

    def on_deactivate(self):
        self._pyrpl = None 
        self._rp = None
        self._scope = None
        self._asg0 = None
        self._asg1 = None
        self._pid0 = None
        self._pid1 = None
        self._pid2 = None
        self._iq0 = None 
        self._iq1 = None
        self._iq2 = None
        self._pyrpl_io_bridge = None

    def setup_asg(self, channel , freq = 0 , amp = 0, start_p= 0 , wf= 'sin'  , trig_source = 'immediately'):
        self.get_pyrpl()
        if channel == 0:
            self._asg0.setup(frequency=freq, amplitude=amp, offset=0, start_phase=start_p, waveform=wf, trigger_source=trig_source)
        elif channel == 1:
            self._asg1.setup(frequency=freq, amplitude=amp, offset=0, start_phase=start_p, waveform=wf, trigger_source=trig_source)
        else:
            raise ValueError("Invalid channel")

    def activate_asg(self, channel, outputchannel):
        """Activate ASG output on specified channel.
        
        Args:
            channel (int): ASG channel (0 or 1)
            outputchannel (str): Output channel ('off', 'out1', 'out2')
        """
        self.get_pyrpl()
        if channel == 0:
            self._asg0.output_direct = outputchannel
        elif channel == 1:
            self._asg1.output_direct = outputchannel
        else:
            raise ValueError("Invalid channel. Must be 0 or 1.")

    # Scope-related methods
    def setup_scope(self, input1=None, input2=None, trigger_source='ch1_positive_edge', 
                   trigger_level=0.0, trigger_hysteresis=0.01, trigger_delay=0,
                   decimation=64, average=False):
        """Configure the oscilloscope settings.
        
        Args:
            input1 (str, optional): Input for channel 1 ('in1', 'in2', 'asg1', 'pid0', etc.)
            input2 (str, optional): Input for channel 2
            trigger_source (str): Trigger source ('ch1_positive_edge', 'ch1_negative_edge',
                                'ch2_positive_edge', 'ch2_negative_edge', 'immediately')
            trigger_level (float): Trigger level in volts
            trigger_hysteresis (float): Hysteresis around trigger level in volts
            trigger_delay (int): Trigger delay in samples
            decimation (int): Decimation factor (1-2^17)
            average (bool): Whether to enable averaging
        """
        self.get_pyrpl()
        if input1 is not None:
            self._scope.input1 = input1
        if input2 is not None:
            self._scope.input2 = input2
            
        self._scope.trigger_source = trigger_source
        self._scope.threshold = trigger_level
        self._scope.hysteresis = trigger_hysteresis
        self._scope.trigger_delay = trigger_delay
        self._scope.decimation = decimation
        self._scope.average = average

    def start_rolling_mode(self, seconds):
        """Setup and start rolling mode acquisition.
        
        Args:
            seconds (float): Duration of data buffer in seconds
        """
        self.get_pyrpl()
        # Ensure rolling mode buffer is large enough
        target_duration = max(0.1, float(seconds))
        self._scope.duration = target_duration
        self._scope.rolling_mode = True

        # Start rolling acquisition mode
        try:
            self._scope._start_acquisition_rolling_mode()
        except Exception as e:
            self.log.error(f"Failed to start rolling mode: {e}")

    def get_last_seconds(self, seconds):
        """Get the last N seconds of scope data in rolling mode."""
        self.get_pyrpl()
        try:
            # Grab rolling curve (times in seconds, datas shape: (2, N))
            times, datas = self._scope._get_rolling_curve()

            # Times are shifted so that last sample is ~0; slice last `seconds`
            mask_time = times >= -seconds
            t = times[mask_time]
            ch1 = datas[0][mask_time]
            ch2 = datas[1][mask_time]

            # Remove NaNs injected during acquisition transitions
            finite_mask = np.isfinite(ch1) & np.isfinite(ch2)
            return t[finite_mask], ch1[finite_mask], ch2[finite_mask]

        except Exception as e:
            self.log.error(f"Error getting scope data: {e}")
            return None, None, None

        
    def get_voltage(self, channel):
        """Get current voltage on a channel.
        
        Args:
            channel (int): Channel number (1 or 2)
            
        Returns:
            float: Current voltage in volts
        """
        self.get_pyrpl()
        if channel == 1:
            return self._scope.voltage_in1
        elif channel == 2:
            return self._scope.voltage_in2
        else:
            raise ValueError("Invalid channel. Must be 1 or 2.")
            
    def get_scope_status(self):
        """Get current scope status.
        
        Returns:
            dict: Dictionary containing scope status information
        """
        self.get_pyrpl()
        return {
            'trigger_source': self._scope.trigger_source,
            'trigger_level': self._scope.threshold,
            'trigger_hysteresis': self._scope.hysteresis,
            'trigger_delay': self._scope.trigger_delay,
            'decimation': self._scope.decimation,
            'average': self._scope.average,
            'input1': self._scope.input1,
            'input2': self._scope.input2,
            'curve_ready': self._scope.curve_ready(),
            'duration': self._scope.duration,
            'current_timestamp': self._scope.current_timestamp,
            'trigger_timestamp': self._scope.trigger_timestamp
        }
        
    # PID controller methods
    def setup_pid(self, pid_channel, input_signal, output_direct='out1', 
                 p=0.0, i=0.0, d=0.0, ival=0.0, 
                 input_filter=None, invert_signal=False,max_voltage=1 , min_voltage = -1, setpoint= 0):
        """Configure a PID controller.
        
        Args:
            pid_channel (int): PID controller number (0, 1, or 2)
            input_signal (str): Input signal source ('in1', 'in2', 'asg0', etc.)
            output_direct (str): Output destination ('out1', 'out2', or 'off')
            p (float): Proportional gain (0.0 to 1.0)
            i (float): Integral unity-gain frequency in Hz
            d (float): Derivative time constant in seconds
            ival (float): Initial integrator value (-4.0 to 4.0 V)
            input_filter (list): List of 4 filter coefficients [f1, f2, f3, f4]
            invert_signal (bool): Whether to invert the input signal
        """
        self.get_pyrpl()
        # Get the PID module
        if pid_channel == 0:
            pid = self._pid0
        elif pid_channel == 1:
            pid = self._pid1
        elif pid_channel == 2:
            pid = self._pid2
        else:
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")
            
        # Configure the PID
        pid.input = input_signal
        pid.output_direct = output_direct
        pid.p = p
        pid.i = i
        pid.d = d
        pid.ival = ival
        pid.max_voltage = max_voltage
        pid.min_voltage = min_voltage 
        pid.setpoint = setpoint
        
        # Apply input filter if provided
        if input_filter is not None:
            if len(input_filter) > 4:
                raise ValueError("Input filter must be a list of up to 4 coefficients")
            pid.inputfilter = input_filter
            
        # Invert signal if needed
        if invert_signal:
            pid.sign = -1
        else:
            pid.sign = 1
            
    def get_pid_status(self, pid_channel):
        """Get the current status of a PID controller.
        
        Args:
            pid_channel (int): PID controller number (0, 1, or 2)
            
        Returns:
            dict: Dictionary containing PID status information
        """
        self.get_pyrpl()
        # Get the PID module
        if pid_channel == 0:
            pid = self._pid0
        elif pid_channel == 1:
            pid = self._pid1
        elif pid_channel == 2:
            pid = self._pid2
        else:
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")
            
        return {
            'input': pid.input,
            'output_direct': pid.output_direct,
            'p': pid.p,
            'i': pid.i,
            'd': pid.d,
            'ival': pid.ival,
            'input_filter': pid.inputfilter,
            'sign': 'inverted' if pid.sign < 0 else 'normal',
            'output_min': pid.output_min,
            'output_max': pid.output_max,
            'setpoint': pid.setpoint
        }
        
    def reset_pid_integrator(self, pid_channel, value=0.0):
        """Reset the integrator of a PID controller.
        
        Args:
            pid_channel (int): PID controller number (0, 1, or 2)
            value (float): Value to set the integrator to (default: 0.0)
        """
        self.get_pyrpl()
        if pid_channel == 0:
            self._pid0.ival = value
        elif pid_channel == 1:
            self._pid1.ival = value
        elif pid_channel == 2:
            self._pid2.ival = value
        else:
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")

    def get_pid_integrator(self, pid_channel=0):
        """Return the current PID integrator value without modifying it."""
        channel = int(pid_channel)
        if channel not in (0, 1, 2):
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")
        if self.get_pyrpl() is None:
            raise RuntimeError("PyRPL is not connected.")
        bridge = getattr(self, '_pyrpl_io_bridge', None)
        if bridge is None:
            bridge = _PyrplIoBridge((self._pid0, self._pid1, self._pid2))
            self._pyrpl_io_bridge = bridge
        return bridge.read_pid_integrator(channel)

    def get_pid_wrap_state(self, pid_channel=0):
        """Return the live PID values needed for a safe wrap decision."""
        channel = int(pid_channel)
        if channel not in (0, 1, 2):
            raise ValueError("Invalid PID channel. Must be 0, 1, or 2.")
        if self.get_pyrpl() is None:
            raise RuntimeError("PyRPL is not connected.")
        bridge = getattr(self, '_pyrpl_io_bridge', None)
        if bridge is None:
            bridge = _PyrplIoBridge((self._pid0, self._pid1, self._pid2))
            self._pyrpl_io_bridge = bridge
        return bridge.read_pid_wrap_state(channel)
            
    # IQ module methods
    def setup_iq(self, iq_channel, frequency, bandwidth, input_signal, output_direct='off',
                output_signal='quadrature', phase=0.0, gain=0.0, acbandwidth=50000, amplitude=0.1,quadrature_factor= 20):
        """Configure an IQ module for lock-in detection or signal processing.
        
        Args:
            iq_channel (int): IQ module number (0, 1, or 2)
            frequency (float): Demodulation frequency in Hz
            bandwidth (float or list): Bandwidth of low-pass filter(s) in Hz. Can be a single value or a list of two values.
            input_signal (str): Input signal source ('in1', 'in2', 'asg0', etc.)
            output_direct (str): Output destination ('out1', 'out2', or 'off')
            output_signal (str): Output signal type ('quadrature', 'input', 'quadrature_demod', 'i_demod', 'q_demod')
            phase (float): Phase offset in degrees
            gain (float): Gain factor for the output signal
            acbandwidth (float): AC coupling cutoff frequency in Hz (0 for DC coupling)
            amplitude (float): Amplitude of the internal oscillator (0.0 to 1.0)
        """
        self.get_pyrpl()
        # Get the IQ module
        if iq_channel == 0:
            iq = self._iq0
        elif iq_channel == 1:
            iq = self._iq1
        elif iq_channel == 2:
            iq = self._iq2
        else:
            raise ValueError("Invalid IQ channel. Must be 0, 1, or 2.")
            
        # Convert single bandwidth to list if needed
        if not hasattr(bandwidth, '__len__'):
            bandwidth = [bandwidth, bandwidth]
            
        # Configure the IQ module
        iq.setup(frequency=frequency,
                bandwidth=bandwidth,
                gain=gain,
                phase= phase, 
                acbandwidth=acbandwidth, 
                amplitude=amplitude,
                input=input_signal,
                output_direct=output_direct,
                output_signal=output_signal,
                quadrature_factor=quadrature_factor)
        
    def get_iq_data(self, iq_channel, num_samples=1, timeout=1.0):
        """Get demodulated I and Q data from an IQ module.
        
        Args:
            iq_channel (int): IQ module number (0, 1, or 2)
            num_samples (int): Number of samples to acquire
            timeout (float): Maximum time to wait for data in seconds
            
        Returns:
            tuple: (I_data, Q_data) arrays of demodulated data
        """
        self.get_pyrpl()
        # Get the IQ module
        if iq_channel == 0:
            iq = self._iq0
        elif iq_channel == 1:
            iq = self._iq1
        elif iq_channel == 2:
            iq = self._iq2
        else:
            raise ValueError("Invalid IQ channel. Must be 0, 1, or 2.")
            
        # Start data acquisition
        future = iq.acquire_async(num_samples)
        
        # Wait for data to be ready
        start_time = time.time()
        while not future.done():
            if time.time() - start_time > timeout:
                raise TimeoutError("IQ data acquisition timed out")
            time.sleep(0.001)
            
        # Return the data
        return future.result()
        
    def get_iq_status(self, iq_channel):
        """Get the current status of an IQ module.
        
        Args:
            iq_channel (int): IQ module number (0, 1, or 2)
            
        Returns:
            dict: Dictionary containing IQ module status information
        """
        self.get_pyrpl()
        # Get the IQ module
        if iq_channel == 0:
            iq = self._iq0
        elif iq_channel == 1:
            iq = self._iq1
        elif iq_channel == 2:
            iq = self._iq2
        else:
            raise ValueError("Invalid IQ channel. Must be 0, 1, or 2.")
            
        return {
            'frequency': iq.frequency,
            'bandwidth': iq.bandwidth,
            'input': iq.input,
            'output_direct': iq.output_direct,
            'output_signal': iq.output_signal,
            'phase': iq.phase,
            'gain': iq.gain,
            'acbandwidth': iq.acbandwidth,
            'amplitude': iq.amplitude,
            'i': iq.i,
            'q': iq.q,
            'r': iq.r,
            'phi': iq.phi
        }
        
    def setup_network_analyzer(self, start_freq, stop_freq, points=1001, rbw=1000, 
                             amplitude=0.1, input_signal='in1', output_direct='out1'):
        """Configure the network analyzer for frequency response measurements.
        
        Args:
            start_freq (float): Start frequency in Hz
            stop_freq (float): Stop frequency in Hz
            points (int): Number of frequency points
            rbw (float): Resolution bandwidth in Hz
            amplitude (float): Output amplitude (0.0 to 1.0)
            input_signal (str): Input signal source
            output_direct (str): Output destination
            
        Returns:
            tuple: (frequencies, magnitude, phase) arrays
        """
        self.get_pyrpl()
        na = self._pyrpl.networkanalyzer
        na.setup(
            start=start_freq,
            stop=stop_freq,
            points=points,
            rbw=rbw,
            amplitude=amplitude,
            input=input_signal,
            output_direct=output_direct,
            acbandwidth=0  # DC coupling
        )
        
        # Start the measurement
        na.start()
        
        # Wait for completion
        while na.running():
            time.sleep(0.1)
            
        # Return the data
        return na.frequencies, na.magnitude, na.phase

    def get_pyrpl(self):
        """Get the underlying Pyrpl instance (lazily initialized)."""
        if getattr(self, '_pyrpl', None) is None:
            try:
                self.log.info("Connecting to Red Pitaya via PyRPL...")
                self._pyrpl = Pyrpl(config=self._config_file, reloadserver=False, gui=False)
                self._rp = self._pyrpl.rp
                self._scope = self._rp.scope
                self._asg0 = self._rp.asg0
                self._asg1 = self._rp.asg1
                self._pid0 = self._rp.pid0
                self._pid1 = self._rp.pid1
                self._pid2 = self._rp.pid2

                self._iq0 = self._rp.iq0 
                self._iq1 = self._rp.iq1
                self._iq2 = self._rp.iq2
                self._pyrpl_io_bridge = _PyrplIoBridge(
                    (self._pid0, self._pid1, self._pid2)
                )
                print("y")
            except Exception as e:
                self.log.error(f'Failed to connect to Red Pitaya: {str(e)}')
                self._pyrpl = None
        return self._pyrpl
