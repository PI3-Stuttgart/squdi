# -*- coding: utf-8 -*-

"""
This file contains the qudi hardware module to use a National Instruments X-series card as finite sampled
signal input and output device.

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

import ctypes
import numpy as np
import nidaqmx as ni
from nidaqmx._lib import lib_importer  # Due to NIDAQmx C-API bug needed to bypass property getter
from nidaqmx.stream_readers import AnalogMultiChannelReader, CounterReader
from nidaqmx.stream_writers import AnalogMultiChannelWriter

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.util.helpers import natural_sort
from qudi.interface.finite_sampling_input_interface import FiniteSamplingInputInterface, FiniteSamplingInputConstraints
from qudi.util.enums import SamplingOutputMode
from qudi.util.mutex import RecursiveMutex
from qudi.hardware.jaeger_computer_technik.adwin_IO import AdwinTrigger
import time
import warnings


class AdwinSamplingInput(FiniteSamplingInputInterface):
    """
    A module for a National Instrument device that outputs voltages and records input from digital channels and/or
    analog channels in a hardware timed fashion. Either as an equidistant sweep or with a list of values to write
    depending on the output mode.

    !!!!!!Tested and developed for NI USB 63XX, NI PCIe 63XX and NI PXIe 63XX DEVICES ONLY !!!!!!

    See [National Instruments X Series Documentation](@ref nidaq-x-series) for details.

    Example config for copy-paste:

    ni_finite_sampling_io:
        module.Class: 'ni_x_series.ni_x_series_finite_sampling_io.NIXSeriesFiniteSamplingIO'
        options:
            device_name: 'Dev1'
            input_channel_units:
                PFI8: 'c/s'
                PFI9: 'c/s'
                ai0: 'V'
                ai1: 'V'
            output_channel_units: # Specify used output channels
                'ao0': 'V'
                'ao1': 'V'
                'ao2': 'V'
                'ao3': 'V'
            adc_voltage_ranges:
                ai0: [-10, 10]  # optional
                ai1: [-10, 10]  # optional
            output_voltage_ranges:
                ao0: [-1.5, 1.5]
                ao1: [-1.5, 1.5]
                ao2: [0, 10.0]
                ao3: [-10.0, 10.0]
            frame_size_limits: [1, 1e9]  # optional #TODO actual HW constraint?
            default_output_mode: 'JUMP_LIST' # optional, must be name of SamplingOutputMode
            read_write_timeout: 10  # optional
            sample_clock_output: '/Dev1/PFI11' # optional: routing of sample clock to a physical connection

    """

    # connectors
    _timetagger = Connector(name='tt', interface = "TT")
    _timetagger_remote = Connector(name='tt_remote', interface = "TT", optional = True) #we dont have any yet.
    adwin_trigger = Connector(name='adwin_trigger', interface = "Base")
    
    _device_name = ConfigOption(name='device_name', default='adwin11', missing='warn') #Here the name is properly send to the BTL  
    # Config options
    _tt_ni_clock_input = ConfigOption(name = "tt_ni_clock_input",
                                                default=None)
    _tt_falling_edge_clock_input = ConfigOption(name = "tt_falling_edge_clock_input",
                                                default=None)
    _scanner_ready = False
    _sum_channels = ConfigOption(name='sum_channels', default=list(), missing='info')
    _device_name = ConfigOption(name='device_name', default='Dev1', missing='warn')
    _digital_channel_units = ConfigOption(name='digital_channel_units', default=dict(), missing='info')
    _analog_channel_units = ConfigOption(name='analog_channel_units', default=dict(), missing='info')
    _external_sample_clock_source = ConfigOption(
        name='external_sample_clock_source', default=None, missing='nothing')
    _external_sample_clock_frequency = ConfigOption(
        name='external_sample_clock_frequency', default=None, missing='nothing')

    _physical_sample_clock_output = ConfigOption(name='sample_clock_output', default=None)
    _physical_counter_sample_clock_output = ConfigOption(name='counter_sample_clock_output', default=None)

    _adc_voltage_range = ConfigOption('adc_voltage_range', default=(-10, 10), missing='info')
    _max_channel_samples_buffer = ConfigOption(
        'max_channel_samples_buffer', default=25e6, missing='info')

    # TODO: check limits
    _sample_rate_limits = ConfigOption(name='sample_rate_limits', default=(1e-3, 1e6))
    _frame_size_limits = ConfigOption(name='frame_size_limits', default=(1, 1e9))

    _rw_timeout = ConfigOption('read_write_timeout', default=10, missing='nothing')

    # Hardcoded data type
    __data_type = np.float64
    
    frame_size = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # NIDAQmx device handle
        self._device_handle = None
        # Task handles for NIDAQmx tasks
        self._di_task_handles = list()
        
        self._timetagger_cbm_tasks = list()
        self._ai_task_handle = None
        # nidaqmx stream reader instances to help with data acquisition
        self._di_readers = list()
        self._ai_reader = None

        # List of all available counters and terminals for this device
        self.__all_counters = tuple()
        self.__all_digital_terminals = tuple()
        self.__all_analog_terminals = tuple()

        # currently active channels
        self.__active_channels = dict(di_channels=frozenset(), ai_channels=frozenset())

        self._thread_lock = RecursiveMutex()
        self._sample_rate = -1
        self._frame_size = -1
        self._constraints = None

    def on_activate(self):
        """
        Starts up the Adwin and Time Tagger and performs sanity checks.
        """
  
        # Check connection and connect to adwin and Time Tagger
        self.module_state() == 'idle'
        self._tt = self._timetagger()
        dev_names = ['adwin11']
        
        #TODO check here for multiple adwin systems?
        
        if self._device_name.lower() not in set(dev.lower() for dev in dev_names):
            raise ValueError(
                f'Device name "{self._device_name}" not found in list of connected devices: '
                f'{dev_names}\nActivation of AdwinFiniteSamplingIO failed!'
            )
        for dev in dev_names:
            if dev.lower() == self._device_name.lower():
                self._device_name = dev
                break
        
        self._adwin_trigger: AdwinTrigger = self.adwin_trigger()
        # TODO - more checks similar to reconnections, bla.
    

        digital_sources = set(src for src in self._digital_channel_units if 'tt' in src)
        analog_sources = set(src for src in self._analog_channel_units)

        if analog_sources:
            source_set = set(self._extract_terminal(src) for src in analog_sources)
            invalid_sources = source_set.difference(set(self.__all_analog_terminals))
            if invalid_sources:
                self.log.error('Invalid analog source channels encountered. Following sources will '
                               'be ignored:\n  {0}\nValid analog input channels are:\n  {1}'
                               ''.format(', '.join(natural_sort(invalid_sources)),
                                         ', '.join(self.__all_analog_terminals)))
            analog_sources = set(natural_sort(source_set.difference(invalid_sources)))

        # Check if all input channels fit in the device
        # if len(digital_sources) > 3:
        #     raise ValueError(
        #         'Too many digital channels specified. Maximum number of digital channels is 3.'
        #     )
        if len(analog_sources) > 16:
            raise ValueError(
                'Too many analog channels specified. Maximum number of analog channels is 16.'
            )

        # Check if there are any valid input channels left
        if not analog_sources and not digital_sources:
            raise ValueError(
                'No valid analog or digital sources defined in config. Activation of '
                'Adwin has failed!'
            )

        # Check Physical clock output if specified
        if self._physical_sample_clock_output is not None:
            self._physical_sample_clock_output = self._extract_terminal(self._physical_sample_clock_output)
        if self._physical_counter_sample_clock_output is not None:
            self._physical_counter_sample_clock_output = self._extract_terminal(self._physical_counter_sample_clock_output)
        
        self._sum_channels = [ch.lower() for ch in self._sum_channels]
        if len(self._sum_channels)>1:
            self._digital_channel_units["sum"] = self._digital_channel_units[self._sum_channels[0]]
        # Create constraints object and perform sanity/type checking
        self._channel_units = self._digital_channel_units.copy()
        self._channel_units.update(self._analog_channel_units)
        
        self._constraints = FiniteSamplingInputConstraints(
            channel_units=self._channel_units,
            frame_size_limits=self._frame_size_limits,
            sample_rate_limits=self._sample_rate_limits
        )
        # Make sure the ConfigOptions have correct values and types
        # (ensured by FiniteSamplingInputConstraints)
        self._sample_rate_limits = self._constraints.sample_rate_limits
        self._frame_size_limits = self._constraints.frame_size_limits
        self._channel_units = self._constraints.channel_units

        # initialize default settings
        self._sample_rate = self._constraints.max_sample_rate
        self._frame_size = 0

        self.set_active_channels(digital_sources.union(analog_sources))
        

    def on_deactivate(self):
        """ Shut down the NI card.
        """
        self.terminate_all_tasks()
        # Free memory if possible while module is inactive
        self.__frame_buffer = np.empty(0, dtype=self.__data_type)
        return

    @property
    def constraints(self):
        return self._constraints

    @property
    def active_channels(self):
        return self.__active_channels['di_channels'].union(self.__active_channels['ai_channels'])

    @property
    def sample_rate(self):
        """
        The currently set sample rate

        @return float: current sample rate in Hz
        """
        return self._sample_rate

    @property
    def frame_size(self):
        return self._frame_size

    @property
    def samples_in_buffer(self):
        """ Currently available samples per channel being held in the input buffer.
        This is the current minimum number of samples to be read with "get_buffered_samples()"
        without blocking.

        @return int: Number of unread samples per channel
        """
        with self._thread_lock:
            if self.module_state() == 'locked':
                if self._ai_task_handle is None:
                    return self.frame_size#self._di_task_handles[0].in_stream.avail_samp_per_chan
                else:
                    return self._ai_task_handle.in_stream.avail_samp_per_chan
            return 0

    def set_sample_rate(self, rate):
        sample_rate = float(rate)
        assert self._constraints.sample_rate_in_range(sample_rate)[0], \
            f'Sample rate "{sample_rate}Hz" to set is out of ' \
            f'bounds {self._constraints.sample_rate_limits}'
        with self._thread_lock:
            assert self.module_state() == 'idle', \
                'Unable to set sample rate. Data acquisition in progress.'
            self._sample_rate = sample_rate
            self.log.debug(f'set sample_rate to {self._sample_rate}')
        return

    def set_active_channels(self, channels):
        """ Will set the currently active channels. All other channels will be deactivated.

        @param iterable(str) channels: Iterable of channel names to set active.
        """
        assert hasattr(channels, '__iter__') and not isinstance(channels, str), \
            f'Given input channels {channels} are not iterable'

        assert self.module_state() != 'locked', \
            'Unable to change active channels while finite sampling is running. New settings ignored.'

        channels = tuple(self._extract_terminal(channel) for channel in channels)

        assert set(channels).issubset(set(self._constraints.channel_names)), \
            f'Trying to set invalid input channels "' \
            f'{set(channels).difference(set(self._constraints.channel_names))}" not defined in config.'

        di_channels, ai_channels = self._extract_ai_di_from_input_channels(channels)

        with self._thread_lock:
            self.__active_channels['di_channels'], self.__active_channels['ai_channels'] \
                = frozenset(di_channels), frozenset(ai_channels)

    def set_frame_size(self, size):
        """ Will set the number of samples per channel to acquire within one frame.

        @param int size: The sample rate to set
        """
        samples = int(round(size))
        assert self._constraints.frame_size_in_range(samples)[0], \
            f'frame size "{samples}" to set is out of bounds {self._constraints.frame_size_limits}'
        with self._thread_lock:
            assert self.module_state() == 'idle', \
                'Unable to set frame size. Data acquisition in progress.'
            self._frame_size = samples
            self.log.debug(f'set frame_size to {self._frame_size}')
            

    def _init_tt_cbm_task(self):
        """
        Set up tasks for digital event counting with the TIMETAGGER
        cbm stnads for count between markers
        @return int: error code (0:OK, -1:error)
        """
        channels_tt = [int(ch[2:]) for ch in self.__active_channels['di_channels'] if "tt" in ch]
        clock_tt = int(self._tt_ni_clock_input[2:])
        #Workaround for the old time tagger version at the praktikum
        if self._tt_falling_edge_clock_input:
            clock_fall_tt = int(self._tt_falling_edge_clock_input[2:])
        else:
            clock_fall_tt = - clock_tt
        self._timetagger_cbm_tasks = [self._tt.count_between_markers(click_channel = channel, 
                                        begin_channel = clock_tt,
                                        end_channel = clock_fall_tt, 
                                        n_values=self.frame_size) if channel != 111 else self._tt.count_between_markers(
                                                        click_channel = self._tt._combined_channels.getChannel(), 
                                                        begin_channel = clock_tt,
                                                        end_channel = clock_fall_tt, 
                                                        n_values=self.frame_size) 
                                        for channel in channels_tt]
        return 0

    def start_buffered_acquisition(self):
        """ Will start the acquisition of a data frame in a non-blocking way.
        Must return immediately and not wait for the data acquisition to finish.

        Must raise exception if data acquisition can not be started.
        """
        assert self.module_state() == 'idle', \
            'Unable to start data acquisition. Data acquisition already in progress.'
        self.module_state.lock()

        # set up tasks
        if self._init_sample_clock() < 0:
            self.terminate_all_tasks()
            self.module_state.unlock()
        if self._init_tt_cbm_task() < 0:
                self.terminate_all_tasks() # add the treatment of the TT task termination
                self.module_state.unlock()
        # if self._init_digital_tasks() < 0:
        #     self.terminate_all_tasks()
        #     self.module_state.unlock()
        #     raise NiInitError('Counter task initialization failed; all tasks terminated')
        if self._init_analog_task() < 0:
            self.terminate_all_tasks()
            self.module_state.unlock()

        # start tasks
        # if len(self._di_task_handles) > 0:
        #     try:
        #         for task in self._di_task_handles:
        #             task.start()
        #     except ni.DaqError:
        #         self.terminate_all_tasks()
        #         self.module_state.unlock()
        #         raise

        if self._ai_task_handle is not None:
            try:
                self._ai_task_handle.start()
            except ni.DaqError:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise

        try:
            self._adwin_trigger.start()
        except:
            self.terminate_all_tasks()
            self.module_state.unlock()
            raise

    def stop_buffered_acquisition(self):
        """ Will abort the currently running data frame acquisition.
        Will return AFTER the data acquisition has been terminated without waiting for all samples
        to be acquired (if possible).

        Must NOT raise exceptions if no data acquisition is running.
        """
        if self.module_state() == 'locked':
            self.terminate_all_tasks()
            self.module_state.unlock()

    def get_buffered_samples(self, number_of_samples=None):
        """ Returns a chunk of the current data frame for all active channels read from the frame
        buffer.
        If parameter <number_of_samples> is omitted, this method will return the currently
        available samples within the frame buffer (i.e. the value of property <samples_in_buffer>).
        If <number_of_samples> is exceeding the currently available samples in the frame buffer,
        this method will block until the requested number of samples is available.
        If the explicitly requested number of samples is exceeding the number of samples pending
        for acquisition in the rest of this frame, raise an exception.

        Samples that have been already returned from an earlier call to this method are not
        available anymore and can be considered discarded by the hardware. So this method is
        effectively decreasing the value of property <samples_in_buffer> (until new samples have
        been read).

        If the data acquisition has been stopped before the frame has been acquired completely,
        this method must still return all available samples already read into buffer.

        @param int number_of_samples: optional, the number of samples to read from buffer

        @return dict: Sample arrays (values) for each active channel (keys)
        """
        data = dict()
        if self.module_state() == 'idle' and self.samples_in_buffer < 1:
            self.log.error('Unable to read data. Device is not running and no data in buffer.')
            return data

        number_of_samples = self.samples_in_buffer if number_of_samples is None else number_of_samples

        if number_of_samples > self._frame_size:
            raise ValueError(
                f'Number of requested samples ({number_of_samples}) exceeds number of samples '
                f'pending for acquisition ({self._frame_size}).'
            )

        try:
            # TODO: What if counter stops while waiting for samples?
            if self._timetagger_cbm_tasks:
                di_data = np.zeros(len(self.__active_channels['di_channels']) * number_of_samples)

                di_data = di_data.reshape(len(self.__active_channels['di_channels']), number_of_samples)
                for num, di_channel in enumerate(self.__active_channels['di_channels']):
                    data_cbm = self._timetagger_cbm_tasks[num].getData()
                    di_data[num] = data_cbm
                    data[di_channel] = di_data[num] * self.sample_rate  # To go to c/s # TODO What if unit not c/s
                self._scanner_ready = self._timetagger_cbm_tasks[-1].ready()

        except:
            self.log.exception('Getting samples from streamer failed.')
            return data
        if len(self._sum_channels)>1:
            data["sum"] = np.sum([samples for ch, samples in data.items() if ch in self._sum_channels], axis=0)
        return data

    def acquire_frame(self, frame_size=None):
        """ Acquire a single data frame for all active channels.
        This method call is blocking until the entire data frame has been acquired.

        If an explicit frame_size is given as parameter, it will not overwrite the property
        <frame_size> but just be valid for this single frame.

        See <start_buffered_acquisition>, <stop_buffered_acquisition> and <get_buffered_samples>
        for more details.

        @param int frame_size: optional, the number of samples to acquire in this frame

        @return dict: Sample arrays (values) for each active channel (keys)
        """
        with self._thread_lock:
            if frame_size is None:
                buffered_frame_size = None
            else:
                buffered_frame_size = self._frame_size
                self.set_frame_size(frame_size)

            self.start_buffered_acquisition()
            # self._scanner_ready = False
            data = self.get_buffered_samples(self._frame_size)
            while not self._scanner_ready:
                data = self.get_buffered_samples(self._frame_size)
            data = self.get_buffered_samples(self._frame_size)
            self.stop_buffered_acquisition()
            if buffered_frame_size is not None:
                self._frame_size = buffered_frame_size
            return data

    # =============================================================================================
    def _init_sample_clock(self):
        """
        If no external clock is given, configures a counter to provide the sample clock for all
        channels.

        @return int: error code (0: OK, -1: Error)
        """
        self._adwin_trigger.sample_rate = self._sample_rate
        self._adwin_trigger.number_of_pulses = self._frame_size
        self._adwin_trigger.digi_out_port = 3 # TODO
        
        return 0

    # TODO
    def _init_analog_task(self):
        """
        Set up task for analog voltage measurement.

        @return int: error code (0:OK, -1:error)
        """

        return 0


    # TODO
    def reset_hardware(self):
        """
        Resets the Adwin, so the connection is lost and other programs can access it.
        @return int: error code (0:OK, -1:error)
        """
        return 0

    # TODO
    def terminate_all_tasks(self):
        self._adwin_trigger.stop()
        

    @staticmethod
    def _extract_terminal(term_str):
        """
        Helper function to extract the bare terminal name from a string and strip it of the device
        name and dashes.
        Will return the terminal name in lower case.

        @param str term_str: The str to extract the terminal name from
        @return str: The terminal name in lower case
        """
        term = term_str.strip('/').lower()
        if 'dev' in term:
            term = term.split('/', 1)[-1]
        return term

    def _extract_ai_di_from_input_channels(self, input_channels):
        """
        Takes an iterable and returns the split up ai and di channels
        @return tuple(di_channels), tuple(ai_channels))
        """
        input_channels = tuple(self._extract_terminal(src) for src in input_channels)

        di_channels = tuple(channel for channel in input_channels if ('pfi' in channel) or ("tt" in channel))
        ai_channels = tuple(channel for channel in input_channels if 'ai' in channel)

        assert (di_channels or ai_channels), f'No channels could be extracted from {*input_channels,}'

        return tuple(di_channels), tuple(ai_channels)