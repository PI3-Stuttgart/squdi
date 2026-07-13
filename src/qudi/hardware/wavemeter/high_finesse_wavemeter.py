# -*- coding: utf-8 -*-

"""
This file contains the qudi hardware module for the HighFinesse wavemeter. It implements the
DataInStreamInterface. Communication with the hardware is done via callback functions such that no new data is missed.
Measurement timestamps provided by the hardware are used for sample timing. As an approximation, the timestamps
corresponding to the first active channel are equally used for all channels. Considering the fixed round-trip time
composing the individual channel exposure times and switching times, this implementation should satisfy all
synchronization needs to an extent that is possible to implement on this software level.

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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from PySide2 import QtCore
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.util.constraints import ScalarConstraint
from qudi.util.mutex import Mutex
from scipy.constants import c, lambda2nu

from qudi.hardware.wavemeter.high_finesse_constants import GetFrequencyError
from qudi.hardware.wavemeter.high_finesse_proxy import HighFinesseProxy
from qudi.interface.data_instream_interface import (
    DataInStreamConstraints,
    DataInStreamInterface,
    SampleTiming,
    StreamingMode,
)


class HighFinesseWavemeter(DataInStreamInterface):
    """
    HighFinesse wavelength meter as an in-streaming device.

    The HighFinesseProxy hardware module is required. It takes care of all communication with the hardware.

    Example config for copy-paste:

    wavemeter:
        module.Class: 'wavemeter.high_finesse_wavemeter.HighFinesseWavemeter'
        connect:
            proxy: wavemeter_proxy
        options:
            channels:
                red_laser:
                    switch_ch: 1    # channel on the wavemeter switch
                    unit: 'm'    # wavelength (m) or frequency (Hz)
                    exposure: 10  # exposure time in ms, optional
                green_laser:
                    switch_ch: 2
                    unit: 'Hz'
                    exposure: 10
    """

    # declare signals
    sigNewWavelength = QtCore.Signal(object)

    _proxy: HighFinesseProxy = Connector(name="proxy", interface="HighFinesseProxy")

    # config options
    _wavemeter_ch_config: Dict[str, Dict[str, Any]] = ConfigOption(
        name="channels",
        default={"default_channel": {"switch_ch": 1, "unit": "m", "exposure": None}},
        missing="info",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = Mutex()

        # internal settings
        # dictionary with switch channel numbers as keys, channel names as values
        self._channel_names: Dict[int, str] = {}
        self._channel_units: Dict[int, str] = {}
        self._channel_buffer_size = 1024**2
        self._active_switch_channels: Optional[List[int]] = (
            None  # list of active switch channel numbers
        )
        self._last_measurement_error: Dict[int, float] = {}

        # data buffer
        self._wm_start_time: Optional[float] = None
        self._data_buffer: Optional[np.ndarray] = None
        self._timestamp_buffer: Optional[np.ndarray] = None
        self._current_buffer_position = 0
        self._buffer_overflow = False
        self._buffer_overflow_logged = False
        self._latest_channel_values: Dict[int, Tuple[float, float]] = {}

        # stored hardware constraints
        self._constraints: Optional[DataInStreamConstraints] = None
        self._measurement_timing: Optional[float] = None
        self._lock_target_frequency_hz: Optional[float] = None
        self._stream_started_by_lock = False

    def on_activate(self) -> None:
        self.reapply_wavemeter_settings()

    def set_dll_set_voltage(channel=1):
        self._proxy().set_laser_piezo_voltage(channel)

    def on_deactivate(self) -> None:
        self.stop_stream()

        # free memory
        self._data_buffer = None
        self._timestamp_buffer = None

    def restart_wavemeter_software(
        self, timeout: float = 100.0, start_silent: bool = False
    ) -> None:
        """Restart the HighFinesse WLM application and leave this module streaming."""
        self._proxy().restart_wlm_application(timeout=timeout, start_silent=start_silent)
        if self.module_state() == "idle":
            time.sleep(5.0)
            self.reapply_wavemeter_settings()
            self.start_stream()

    def reapply_wavemeter_settings(self) -> None:
        """Rebuild activation-time state and reapply settings after a WLM restart."""
        channel_names = {}
        channel_units = {}
        for ch_name, info in self._wavemeter_ch_config.items():
            ch = info["switch_ch"]
            unit = info["unit"]
            channel_names[ch] = ch_name

            if unit == "THz" or unit == "Hz":
                channel_units[ch] = "Hz"
            elif unit == "nm" or unit == "m":
                channel_units[ch] = "m"
            else:
                self.log.warning(
                    f"Invalid unit: {unit}. Valid units are Hz and m. Using m as default."
                )
                channel_units[ch] = "m"

            exp_time = info.get("exposure")
            if exp_time is not None:
                self._proxy().set_exposure_time(info["switch_ch"], exp_time)

        self._channel_names = channel_names
        self._channel_units = channel_units
        self._active_switch_channels = list(self._channel_names)

        sample_rate = self.sample_rate
        self._constraints = DataInStreamConstraints(
            channel_units={
                self._channel_names[ch]: self._channel_units[ch]
                for ch in self._active_switch_channels
            },
            sample_timing=SampleTiming.TIMESTAMP,
            # TODO: implement fixed streaming mode
            streaming_modes=[StreamingMode.CONTINUOUS],
            data_type=np.float64,
            channel_buffer_size=ScalarConstraint(
                default=1024**2, bounds=(128, 1024**3), increment=1, enforce_int=True
            ),  # 8 MB  # max = 8 GB
            sample_rate=ScalarConstraint(default=sample_rate, bounds=(0.01, 1e3)),
        )
        self._measurement_timing = 1 / sample_rate if sample_rate else None
        self._wm_start_time = None
        self.empty_buffer()

    def start_lock(
        self,
        wavelength: Union[float, None] = None,
        use_current_wavelength: bool = False,
        channel: int = 1,
    ) -> None:

        if self.module_state() == "idle":
            self.start_stream()
            self._stream_started_by_lock = True
            time.sleep(0.01)

        if use_current_wavelength:
            wavelength = self.get_current_wavelength(kind="nm")
        else:
            if wavelength == None:
                raise ValueError(
                    "Target wavelength needs to be defined or use_current_wavelength=True"
                )

        self._proxy().set_reference_wavelength(wavelength)
        self._proxy().toggle_locking(True)

    def stop_lock(self, channel: int = 1) -> None:
        self._proxy().toggle_locking(False)
        if self._stream_started_by_lock and self.module_state() == "locked":
            self.stop_stream()
        self._stream_started_by_lock = False

    # Compatibility helpers for older wavemeter logic modules expecting the
    # legacy WavemeterInterface API.
    def _compat_ensure_running(self) -> None:
        if self.module_state() == "idle":
            self.start_stream()

    def _compat_wait_for_samples(self, min_samples: int = 1, timeout: float = 2.0) -> None:
        self._compat_ensure_running()
        deadline = time.time() + timeout
        while self.available_samples < min_samples:
            if time.time() >= deadline:
                raise TimeoutError("Timed out while waiting for wavemeter data.")
            time.sleep(0.01)

    def _compat_get_latest_channel_value(self, channel_index: int = 0) -> Tuple[float, float, int]:
        self._compat_ensure_running()
        deadline = time.time() + 2.0
        while True:
            with self._lock:
                number_of_channels = len(self.active_channels)
                if channel_index >= number_of_channels:
                    raise IndexError("Requested wavemeter channel index is not available.")
                switch_channel = self._active_switch_channels[channel_index]
                if switch_channel in self._latest_channel_values or self.available_samples > 0:
                    break
            if time.time() >= deadline:
                return self._compat_read_direct_channel_value(switch_channel)
            time.sleep(0.01)

        with self._lock:
            number_of_channels = len(self.active_channels)
            switch_channel = self._active_switch_channels[channel_index]
            try:
                value, timestamp = self._latest_channel_values[switch_channel]
            except KeyError:
                available_samples = self.available_samples
                buffer_index = number_of_channels * (available_samples - 1)
                value = float(self._data_buffer[buffer_index + channel_index])
                timestamp = float(self._timestamp_buffer[available_samples - 1])
        return value, timestamp, switch_channel

    def _compat_read_direct_channel_value(self, switch_channel: int) -> Tuple[float, float, int]:
        wavelength_m = self._proxy().get_wavelength_m(switch_channel)
        if wavelength_m <= 0:
            try:
                error_name = GetFrequencyError(wavelength_m).name
            except ValueError:
                error_name = f"error code {wavelength_m}"
            raise TimeoutError(
                "Timed out while waiting for wavemeter callback data, and direct "
                f"readout of channel {switch_channel} returned {error_name}."
            )

        if self._channel_units[switch_channel] == "Hz":
            value = float(lambda2nu(wavelength_m))
        else:
            value = float(wavelength_m)

        timestamp = time.time()
        with self._lock:
            self._latest_channel_values[switch_channel] = (value, timestamp)
        return value, timestamp, switch_channel

    def _compat_value_to_frequency_hz(self, value: float, switch_channel: int) -> float:
        if self._channel_units[switch_channel] == "Hz":
            return float(value)
        return float(lambda2nu(value))

    def _compat_value_to_wavelength_m(self, value: float, switch_channel: int) -> float:
        if self._channel_units[switch_channel] == "Hz":
            return float(c / value)
        return float(value)

    def start_acquisition(self) -> int:
        try:
            self._compat_ensure_running()
        except Exception:
            self.log.exception("Failed to start wavemeter acquisition.")
            return -1
        return 0

    def stop_acquisition(self) -> int:
        try:
            if self.module_state() == "locked":
                self.stop_stream()
        except Exception:
            self.log.exception("Failed to stop wavemeter acquisition.")
            return -1
        return 0

    def get_current_wavelength(self, kind: str = "nm") -> float:
        value, _, switch_channel = self._compat_get_latest_channel_value(0)
        frequency_hz = self._compat_value_to_frequency_hz(value, switch_channel)
        wavelength_m = self._compat_value_to_wavelength_m(value, switch_channel)

        mode = kind.lower()
        if mode in {"freq", "hz"}:
            return float(frequency_hz)
        if mode == "thz":
            return float(frequency_hz / 1e12)
        if mode == "m":
            return float(wavelength_m)
        if mode == "nm":
            return float(wavelength_m * 1e9)

    def get_current_wavelength2(self, kind: str = "air") -> float:
        try:
            value, _, switch_channel = self._compat_get_latest_channel_value(1)
        except (IndexError, TimeoutError):
            return -2.0

        frequency_hz = self._compat_value_to_frequency_hz(value, switch_channel)
        wavelength_m = self._compat_value_to_wavelength_m(value, switch_channel)
        mode = kind.lower()
        if mode in {"freq", "hz"}:
            return float(frequency_hz)
        if mode == "thz":
            return float(frequency_hz / 1e12)
        if mode == "m":
            return float(wavelength_m)
        return float(wavelength_m * 1e9)

    def get_current_frequency(self) -> float:
        return self.get_current_wavelength(kind="freq")

    def set_lock_frequency(self, frequency: float) -> None:
        self._lock_target_frequency_hz = float(frequency)

    def lock_frequency(self) -> None:
        if self._lock_target_frequency_hz is None:
            self._lock_target_frequency_hz = self.get_current_frequency()
        wavelength_nm = c / self._lock_target_frequency_hz * 1e9
        self.start_lock(wavelength=wavelength_nm)

    def unlock_frequency(self) -> None:
        self.stop_lock()

    def get_timing(self) -> float:
        if self._measurement_timing is not None:
            return float(self._measurement_timing)
        sample_rate = self.sample_rate
        return float(1 / sample_rate) if sample_rate else 0.0

    def set_timing(self, timing: float) -> int:
        self._measurement_timing = float(timing)
        return 0

    def empty_buffer(self) -> None:
        with self._lock:
            if self._data_buffer is not None:
                self._data_buffer.fill(0)
            if self._timestamp_buffer is not None:
                self._timestamp_buffer.fill(0)
            self._current_buffer_position = 0
            self._buffer_overflow = False
            self._buffer_overflow_logged = False
            self._latest_channel_values = {}

    def get_wavelength_buffer(self) -> np.ndarray:
        try:
            self._compat_wait_for_samples()
        except TimeoutError:
            return np.array([[self.get_current_wavelength(kind="THz"), 0.0]])

        with self._lock:
            available_samples = self.available_samples
            if available_samples < 1:
                return np.array([[self.get_current_wavelength(kind="THz"), 0.0]])

            number_of_channels = len(self.active_channels)
            switch_channel = self._active_switch_channels[0]
            values = self._data_buffer[
                : available_samples * number_of_channels : number_of_channels
            ].copy()
            timestamps = self._timestamp_buffer[:available_samples].copy()
            self._remove_samples_from_buffer(available_samples)

        if self._channel_units[switch_channel] == "Hz":
            wavelengths_thz = values / 1e12
        else:
            wavelengths_thz = lambda2nu(values) / 1e12
        return np.column_stack((wavelengths_thz, timestamps))

    @property
    def constraints(self) -> DataInStreamConstraints:
        """Read-only property returning the constraints on the settings for this data streamer."""
        return self._constraints

    def start_stream(self) -> None:
        """Start the data acquisition/streaming"""
        with self._lock:
            if self.module_state() == "idle":
                self.module_state.lock()
                self._init_buffers()
                self._last_measurement_error = {ch: 0 for ch in self._active_switch_channels}
                self._proxy().connect_instreamer(self, self._active_switch_channels)
            else:
                self.log.warning("Unable to start input stream. It is already running.")

    def stop_stream(self) -> None:
        """Stop the data acquisition/streaming"""
        with self._lock:
            if self.module_state() == "locked":
                self._proxy().disconnect_instreamer(self)
                self._wm_start_time = None
                self.module_state.unlock()
            else:
                self.log.warning("Unable to stop wavemeter input stream as nothing is running.")

    def stop_stream_watchdog(self) -> None:
        """Meant to be called from proxy watchdog only. Skips the disconnecting."""
        with self._lock:
            if self.module_state() == "locked":
                self._wm_start_time = None
                self.module_state.unlock()
            else:
                self.log.warning("Unable to stop wavemeter input stream as nothing is running.")

    def read_data_into_buffer(
        self,
        data_buffer: np.ndarray,
        samples_per_channel: int,
        timestamp_buffer: Optional[np.ndarray] = None,
    ) -> None:
        """Read data from the stream buffer into a 1D numpy array given as parameter.
        Samples of all channels are stored interleaved in contiguous memory.
        In case of a multidimensional buffer array, this buffer will be flattened before written
        into.
        The 1D data_buffer can be unraveled into channel and sample indexing with:

            data_buffer.reshape([<samples_per_channel>, <channel_count>])

        The data_buffer array must have the same data type as self.constraints.data_type.

        In case of SampleTiming.TIMESTAMP a 1D numpy.float64 timestamp_buffer array has to be
        provided to be filled with timestamps corresponding to the data_buffer array. It must be
        able to hold at least <samples_per_channel> items:

        This function is blocking until the required number of samples has been acquired.
        """
        self._validate_buffers(data_buffer, timestamp_buffer)

        # wait until requested number of samples is available
        while self.available_samples < samples_per_channel:
            if self.module_state() != "locked":
                break
            # wait for 10 ms
            time.sleep(0.01)

        with self._lock:
            if self.module_state() != "locked":
                raise RuntimeError("Unable to read data. Stream is not running.")

            total_samples = samples_per_channel * len(self.active_channels)
            data_buffer[:total_samples] = self._data_buffer[:total_samples]
            timestamp_buffer[:samples_per_channel] = self._timestamp_buffer[:samples_per_channel]
            self._remove_samples_from_buffer(samples_per_channel)

    def read_available_data_into_buffer(
        self, data_buffer: np.ndarray, timestamp_buffer: Optional[np.ndarray] = None
    ) -> int:
        """Read data from the stream buffer into a 1D numpy array given as parameter.
        All samples for each channel are stored in consecutive blocks one after the other.
        The number of samples read per channel is returned and can be used to slice out valid data
        from the buffer arrays like:

            valid_data = data_buffer[:<channel_count> * <return_value>]
            valid_timestamps = timestamp_buffer[:<return_value>]

        See "read_data_into_buffer" documentation for more details.

        This method will read all currently available samples into buffer. If number of available
        samples exceeds buffer size, read only as many samples as fit into the buffer.
        """
        with self._lock:
            if self.module_state() != "locked":
                raise RuntimeError("Unable to read data. Stream is not running.")

            req_samples_per_channel = self._validate_buffers(data_buffer, timestamp_buffer)
            number_of_channels = len(self.active_channels)
            samples_per_channel = min(req_samples_per_channel, self.available_samples)
            total_samples = number_of_channels * samples_per_channel

            data_buffer[:total_samples] = self._data_buffer[:total_samples]
            timestamp_buffer[:samples_per_channel] = self._timestamp_buffer[:samples_per_channel]
            self._remove_samples_from_buffer(samples_per_channel)

        return samples_per_channel

    def read_data(
        self, samples_per_channel: Optional[int] = None
    ) -> Tuple[np.ndarray, Union[np.ndarray, None]]:
        """Read data from the stream buffer into a 1D numpy array and return it.
        All samples for each channel are stored in consecutive blocks one after the other.
        The returned data_buffer can be unraveled into channel samples with:

            data_buffer.reshape([<channel_count>, samples_per_channel])

        The numpy array data type is the one defined in self.constraints.data_type.

        In case of SampleTiming.TIMESTAMP a 1D numpy.float64 timestamp_buffer array will be
        returned as well with timestamps corresponding to the data_buffer array.

        If samples_per_channel is omitted all currently available samples are read from buffer.
        This method will not return until all requested samples have been read or a timeout occurs.
        """
        samples_per_channel = (
            samples_per_channel if samples_per_channel is not None else self.available_samples
        )
        total_samples = len(self.active_channels) * samples_per_channel

        data_buffer = np.empty(total_samples, dtype=self.constraints.data_type)
        timestamp_buffer = np.empty(samples_per_channel, dtype=np.float64)
        self.read_data_into_buffer(data_buffer, samples_per_channel, timestamp_buffer)

        return data_buffer, timestamp_buffer

    def read_single_point(self) -> Tuple[np.ndarray, Union[None, np.float64]]:
        """This method will initiate a single sample read on each configured data channel.
        In general this sample may not be acquired simultaneous for all channels and timing in
        general can not be assured. Us this method if you want to have a non-timing-critical
        snapshot of your current data channel input.
        May not be available for all devices.
        The returned 1D numpy array will contain one sample for each channel.

        In case of SampleTiming.TIMESTAMP a single numpy.float64 timestamp value will be returned
        as well.
        """
        if self.module_state() != "locked":
            raise RuntimeError("Unable to read data. Device is not running.")

        with self._lock:
            n = len(self.active_channels)
            if all(ch in self._latest_channel_values for ch in self._active_switch_channels):
                data = np.array(
                    [self._latest_channel_values[ch][0] for ch in self._active_switch_channels],
                    dtype=self.constraints.data_type,
                )
                timestamp = self._latest_channel_values[self._active_switch_channels[0]][1]
                return data, timestamp

            available_samples = self.available_samples
            # get the most recent samples for each channel
            if available_samples < 1:
                raise RuntimeError("Unable to read data. No samples are available.")
            data = self._data_buffer[n * (available_samples - 1) : n * available_samples].copy()
            timestamp = self._timestamp_buffer[available_samples - 1]

        return data, timestamp

    @property
    def sample_rate(self) -> float:
        """Read-only property returning the currently set sample rate in Hz.
        For SampleTiming.CONSTANT this is the sample rate of the hardware, for any other timing mode
        this property represents only a hint to the actual hardware timebase and can not be
        considered accurate.

        For the wavemeter, it is estimated by the exposure times per channel and switching times if
        more than one channel is active.
        """
        return self._proxy().sample_rate()

    @property
    def streaming_mode(self) -> StreamingMode:
        """Read-only property returning the currently configured StreamingMode Enum"""
        return StreamingMode.CONTINUOUS

    @property
    def active_channels(self) -> List[str]:
        """Read-only property returning the currently configured active channel names"""
        ch_names = [self._channel_names[ch] for ch in self._active_switch_channels]
        return ch_names

    @property
    def available_samples(self) -> int:
        """
        Read-only property to return the currently available number of samples per channel ready
        to read from buffer.
        """
        if self.module_state() != "locked":
            return 0

        # all channels must have been read out in order to count as an available sample
        return self._current_buffer_position // len(self.active_channels)

    @property
    def channel_buffer_size(self) -> int:
        """Read-only property returning the currently set buffer size in samples per channel.
        The total buffer size in bytes can be estimated by:
            <buffer_size> * <channel_count> * numpy.nbytes[<data_type>]

        For StreamingMode.FINITE this will also be the total number of samples to acquire per
        channel.
        """
        return self._channel_buffer_size

    def configure(
        self,
        active_channels: Sequence[str],
        streaming_mode: Union[StreamingMode, int],
        channel_buffer_size: int,
        sample_rate: float,
    ) -> None:
        """Configure a data stream. See read-only properties for information on each parameter."""
        if self.module_state() == "locked":
            raise RuntimeError("Unable to configure data stream while it is already running")

        if active_channels is not None:
            self._active_switch_channels = []
            for ch in active_channels:
                if ch in self._wavemeter_ch_config:
                    self._active_switch_channels.append(self._wavemeter_ch_config[ch]["switch_ch"])
                else:
                    raise ValueError(
                        f"Channel {ch} is not set up in the config file. Available channels "
                        f"are {list(self._channel_names.keys())}."
                    )

        if streaming_mode is not None and streaming_mode.value != StreamingMode.CONTINUOUS.value:
            self.log.warning("Only continuous streaming is supported, ignoring this setting.")

        if channel_buffer_size is not None:
            self.constraints.channel_buffer_size.is_valid(channel_buffer_size)
            self._channel_buffer_size = channel_buffer_size

    def process_new_wavelength(self, ch, wavelength, timestamp):
        with self._lock:
            if (
                self.module_state() != "locked"
                or self._data_buffer is None
                or self._timestamp_buffer is None
                or self._active_switch_channels is None
            ):
                return
            try:
                i = self._active_switch_channels.index(ch)
            except ValueError:
                # channel is not active on this instreamer
                return

        if self._last_measurement_error.get(ch, 0) != 0:
            if wavelength > 0:
                # reset error flag
                self._last_measurement_error[ch] = 0

        if wavelength <= 0:
            # negative values indicate an error
            if self._last_measurement_error.get(ch, 0) != wavelength:
                # error is new
                self._last_measurement_error[ch] = wavelength
                try:
                    error_name = GetFrequencyError(wavelength).name
                except ValueError:
                    error_name = f"error code {wavelength}"
                self.log.warning(
                    f"The last wavemeter measurement of channel {ch} was unsuccessful "
                    f"due to {error_name}."
                )
            wavelength = np.nan

        with self._lock:
            number_of_channels = len(self.active_channels)
            current_timestamp_buffer_position = self._current_buffer_position // number_of_channels
            if current_timestamp_buffer_position >= self.channel_buffer_size:
                self._buffer_overflow = True
                if not self._buffer_overflow_logged:
                    self.log.warning(
                        "Wavemeter streaming buffer is full. Dropping the oldest sample "
                        "to keep the latest wavelength available."
                    )
                    self._buffer_overflow_logged = True
                self._remove_samples_from_buffer(1)
                current_timestamp_buffer_position = (
                    self._current_buffer_position // number_of_channels
                )

            # unit conversion
            if self._channel_units[ch] == "Hz":
                converted_value = lambda2nu(wavelength)
            else:
                converted_value = wavelength

            # check if this is the first time this callback runs during a stream
            if self._wm_start_time is None:
                # set the timing offset to the start of the stream
                self._wm_start_time = timestamp

            relative_timestamp = timestamp - self._wm_start_time
            self._latest_channel_values[ch] = (float(converted_value), float(relative_timestamp))

            if i != self._current_buffer_position % number_of_channels:
                # discard the sample if a sample was missed before and the buffer position is off
                return

            # insert the new data into the buffers
            self._data_buffer[self._current_buffer_position] = converted_value
            if i == 0:
                # only record the timestamp of the first active channel
                self._timestamp_buffer[current_timestamp_buffer_position] = relative_timestamp
            self._current_buffer_position += 1

        self.sigNewWavelength.emit(converted_value)

    def _init_buffers(self) -> None:
        """Initialize buffers and the current buffer position marker."""
        n = len(self._active_switch_channels)
        self._data_buffer = np.zeros(
            n * self._channel_buffer_size, dtype=self.constraints.data_type
        )
        self._timestamp_buffer = np.zeros(self._channel_buffer_size, dtype=np.float64)
        self._current_buffer_position = 0
        self._buffer_overflow = False
        self._buffer_overflow_logged = False
        self._latest_channel_values = {}

    def _remove_samples_from_buffer(self, samples_per_channel: int) -> None:
        """
        Remove samples that have been read from buffer to make space for new samples.
        :param samples_per_channel: number of samples per channel to clear off the buffer
        :return: None
        """
        if samples_per_channel <= 0 or self._data_buffer is None or self._timestamp_buffer is None:
            return

        samples_per_channel = min(samples_per_channel, self.available_samples)
        total_samples = len(self.active_channels) * samples_per_channel
        self._data_buffer = np.roll(self._data_buffer, -total_samples)
        self._timestamp_buffer = np.roll(self._timestamp_buffer, -samples_per_channel)
        self._current_buffer_position = max(0, self._current_buffer_position - total_samples)

    def _validate_buffers(
        self, data_buffer: np.ndarray, timestamp_buffer: np.ndarray
    ) -> Tuple[int, Union[int, Any]]:
        """Validate arguments for read_[available]_data_into_buffer methods."""
        if (
            not isinstance(data_buffer, np.ndarray)
            or data_buffer.dtype != self.constraints.data_type
        ):
            raise TypeError(
                f"data_buffer must be numpy.ndarray with dtype {self.constraints.data_type}."
            )

        if not isinstance(timestamp_buffer, np.ndarray) or timestamp_buffer.dtype != np.float64:
            raise TypeError(
                "timestamp_buffer must be provided for the wavemeter and "
                "it must be a numpy.ndarray with dtype np.float64."
            )

        number_of_channels = len(self.active_channels)
        samples_per_channel = data_buffer.size // number_of_channels

        if timestamp_buffer.size != samples_per_channel:
            raise ValueError(
                "timestamp_buffer must be exactly of length data_buffer // <channel_count>"
            )

        return samples_per_channel
