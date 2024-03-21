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
from qudi.interface.finite_sampling_io_interface import FiniteSamplingIOInterface, FiniteSamplingIOConstraints
from qudi.util.enums import SamplingOutputMode
from qudi.util.mutex import RecursiveMutex
import time
import warnings


class AdwinSamplingIO(FiniteSamplingIOInterface):
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

    # config options
    _timetagger = Connector(name='tt', interface = "TT")
    
    #_timetagger_remote = Connector(name='tt_remote', interface = "TT", optional = True) we dont have any yet.
    _device_name = ConfigOption(name='device_name', default='adwin11', missing='warn') #Here the name is properly send to the BTL
    ### HERE THE ADWIN IS CONNECTING...
    _adwin = Connector(name='adwin', interface = "Adwin_Scanning_Device", optional = True) ##connection to the adwin_Scanner holder.
    _rw_timeout = ConfigOption('read_write_timeout', default=10, missing='nothing')

    # Finite Sampling #TODO What are the frame size hardware limits?
    _frame_size_limits = ConfigOption(name='frame_size_limits', default=(1, 1e9))
    _input_channel_units = ConfigOption(name='input_channel_units',
                                        missing='error')

    _output_channel_units = ConfigOption(name='output_channel_units',
                                         default={'ao{}'.format(channel_index): 'V' for channel_index in range(0, 4)},
                                         missing='error')

    _default_output_mode = ConfigOption(name='default_output_mode', default='JUMP_LIST',
                                        constructor=lambda x: SamplingOutputMode[x.upper()],
                                        missing='nothing')

    _physical_sample_clock_output = ConfigOption(name='sample_clock_output',
                                                 default=None)

    _tt_adwin_clock_input = ConfigOption(name = "tt_adwin_clock_input",
                                                default=None)
    
    _tt_falling_edge_clock_input = ConfigOption(name = "tt_falling_edge_clock_input",
                                                default=None)
    
    _tt_remote_ni_clock_input = ConfigOption(name = "tt_remote_ni_clock_input",
                                                default=None)
    
    _tt_remote_falling_edge_clock_input = ConfigOption(name = "tt_remote_falling_edge_clock_input",
                                                default=None)
    
    _sum_channels = ConfigOption(name='sum_channels', default=[], missing='nothing')

    _adc_voltage_ranges = ConfigOption(name='adc_voltage_ranges',
                                       default={'ai{}'.format(channel_index): [-10, 10]
                                                for channel_index in range(0, 10)},  # TODO max 10 some what arbitrary
                                       missing='nothing')

    _output_voltage_ranges = ConfigOption(name='output_voltage_ranges',
                                          default={'ao{}'.format(channel_index): [0, 1]
                                                   for channel_index in range(0, 3)},
                                          missing='warn')
    _output_voltage_ranges_LT = ConfigOption(name='output_voltage_ranges_LT',
                                          default={'ao{}'.format(channel_index): [0, 1]
                                                   for channel_index in range(0, 3)},
                                          missing='nothing')

    _scanner_ready = False
    # Hardcoded data type
    __data_type = np.float64

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # NIDAQmx device handle
        # self._device_handle = None
        # Task handles for NIDAQmx tasks
        self._di_task_handles = list()

        self._timetagger_cbm_tasks = list()

        self._ai_task_handle = None
        self._clk_task_handle = None
        self._ao_task_handle = None
        self._tasks_started_successfully = False
        # nidaqmx stream reader instances to help with data acquisition
        self._di_readers = list()
        self._ai_reader = None
        self._ao_writer = None

        # Internal settings
        self.__output_mode = None
        self.__sample_rate = -1.0

        # Internal settings
        self.__frame_size = -1
        self.__frame_buffer = -1

        # unread samples buffer
        self.__unread_samples_buffer = None
        self._number_of_pending_samples = 0

        # List of all available counters and terminals for this device
        self.__all_counters = tuple()
        self.__all_digital_terminals = tuple()
        self.__all_analog_in_terminals = tuple()
        self.__all_analog_out_terminals = tuple()

        # currently active channels
        self.__active_channels = dict(di_channels=frozenset(), ai_channels=frozenset(), ao_channels=frozenset())

        # Stored hardware constraints
        self._constraints = None
        self._thread_lock = RecursiveMutex()
        return

    def on_activate(self):
        """
        Starts up the Adwin-CARD and performs sanity checks.
        """
        
        ## This is some stuff for the ADWIN terminals, everythni is only within the python code here.
        self._input_channel_units = {self._extract_terminal(key): value
                                     for key, value in self._input_channel_units.items()}
        self._output_channel_units = {self._extract_terminal(key): value
                                      for key, value in self._output_channel_units.items()}

        # Check if device is connected and set device to use
        self._tt = self._timetagger() #PASST
        
        dev_names = ['adwin11']##ni.system.System().devices.device_names ## Have no NIDAQ.
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
        
        self._adwin_handle =  self._adwin()
        # TODO - more checks similar to reconnections, bla.
        
        # if self._device_handle():
        #     self._device_handle = self._device_handle()
        # else:
        #     self._device_handle = ni.system.Device(self._device_name)



        # WHY???? For now rename and see later if it is needed. Fro now seems not needed.
        
        # ## Maybe later to use for making it smoother for multiple channels, bla
        # self.__all_counters = tuple(
        #     self._extract_terminal(ctr) for ctr in self._adwin_handle.co_physical_chans.channel_names if
        #     'ctr' in ctr.lower())
        self.__all_digital_terminals = tuple(self._extract_terminal(term) for term in self._adwin_handle._digital_outputs.keys() if 'd' in term)
        # self.__all_analog_in_terminals = tuple(
        #     self._extract_terminal(term) for term in self._adwin_handle.ai_physical_chans.channel_names)
        self.__all_analog_out_terminals = tuple(
             self._extract_terminal(term) for term in self._adwin_handle._analog_outputs.keys())

        # Get digital input terminals from _input_channel_units of the Time Tagger
        # The input channels are assumed to be time tagger exclusively
        
        #This is not the case for ADWIN per se, but if multiple inputs will be given, the src will not be starting with the 'tt'
        digital_sources = tuple(src for src in self._input_channel_units if 'tt' in src) #!FIX check maybe regex out tt

        analog_sources = tuple(src for src in self._input_channel_units if 'ai' in src) #We have none for now.

        # Get analog input channels from _input_channel_units
        if analog_sources:
            source_set = set(analog_sources)
            invalid_sources = source_set.difference(set(self.__all_analog_in_terminals))
            if invalid_sources:
                self.log.error('Invalid analog source channels encountered. Following sources will '
                               'be ignored:\n  {0}\nValid analog input channels are:\n  {1}'
                               ''.format(', '.join(natural_sort(invalid_sources)),
                                         ', '.join(self.__all_analog_in_terminals)))
            analog_sources = natural_sort(source_set.difference(invalid_sources))

        # Get analog output channels from _output_channel_units
        analog_outputs = tuple(src for src in self._output_channel_units if 'ao' in src)

        if analog_outputs:
            source_set = set(analog_outputs)
            #print(source_set, self.__all_analog_out_terminals)
            invalid_sources = source_set.difference(set(self.__all_analog_out_terminals))
            if invalid_sources:
                self.log.error('Invalid analog source channels encountered. Following sources will '
                               'be ignored:\n  {0}\nValid analog input channels are:\n  {1}'
                               ''.format(', '.join(natural_sort(invalid_sources)),
                                         ', '.join(self.__all_analog_in_terminals)))
            analog_outputs = natural_sort(source_set.difference(invalid_sources))

        # Check if all input channels fit in the device
        #!TODO FIX with the TimeTagger can be more inputs

        if len(analog_sources) > 16:
            raise ValueError(
                'Too many analog channels specified. Maximum number of analog channels is 16.'
            )

        # If there are any invalid inputs or outputs specified, raise an error
        defined_channel_set = set.union(set(self._input_channel_units), 
                                        set(self._output_channel_units))
        detected_channel_set = set.union(set(analog_sources),
                                         set(digital_sources),
                                         set(analog_outputs))
        invalid_channels = set.difference(defined_channel_set, detected_channel_set)
        
        #print('invalid channels', invalid_channels)
        if invalid_channels:
            raise ValueError(f'The channels "{", ".join(invalid_channels)}", specified in the config, were not recognized.')
        

        self._sum_channels = [ch.lower() for ch in self._sum_channels]
        if len(self._sum_channels) > 1:
            self._input_channel_units["sum"] = self._input_channel_units[self._sum_channels[0]]

        # Check Physical clock output if specified
        if self._physical_sample_clock_output is not None:
            self._physical_sample_clock_output = self._extract_terminal(self._physical_sample_clock_output)
            assert self._physical_sample_clock_output in self.__all_digital_terminals, \
                f'Physical sample clock terminal specified in config is invalid'

        # Get correct sampling frequency limits based on config specified channels
        # if analog_sources and len(analog_sources) > 1:  # Probably "Slowest" case
        #     sample_rate_limits = (
        #         max(self._device_handle.ai_min_rate, self._device_handle.ao_min_rate),
        #         min(self._device_handle.ai_max_multi_chan_rate, self._device_handle.ao_max_rate)
        #     )
        # elif analog_sources and len(analog_sources) == 1:  # Potentially faster than ai multi channel
        #     sample_rate_limits = (
        #         max(self._device_handle.ai_min_rate, self._device_handle.ao_min_rate),
        #         min(self._device_handle.ai_max_single_chan_rate, self._device_handle.ao_max_rate)
        #     )
        # else: 
        # # Only ao and di, therefore probably the fastest possible
        sample_rate_limits = (
                self._adwin_handle.ao_min_rate,
                min(self._adwin_handle.ao_max_rate, self._adwin_handle.ci_max_timebase)
            )

        output_voltage_ranges = {self._extract_terminal(key): value
                                 for key, value in self._output_voltage_ranges.items()}

        input_limits = dict()

        if digital_sources:
            input_limits.update({key: [0, int(1e8)]
                                 for key in digital_sources})  # TODO Real HW constraint?
        if len(self._sum_channels) > 1:
            input_limits["sum"] = [0, int(1e8)]

        if analog_sources:
            adc_voltage_ranges = {self._extract_terminal(key): value
                                  for key, value in self._adc_voltage_ranges.items()}

            input_limits.update(adc_voltage_ranges)

        # Create constraints
        self._constraints = FiniteSamplingIOConstraints(
            supported_output_modes=(SamplingOutputMode.JUMP_LIST, SamplingOutputMode.EQUIDISTANT_SWEEP),
            input_channel_units=self._input_channel_units,
            output_channel_units=self._output_channel_units,
            frame_size_limits=self._frame_size_limits,
            sample_rate_limits=sample_rate_limits,
            output_channel_limits=output_voltage_ranges,
            input_channel_limits=input_limits
        )

        assert self._constraints.output_mode_supported(self._default_output_mode), \
            f'Config output "{self._default_output_mode}" mode not supported'

        self.__output_mode = self._default_output_mode
        self.__frame_size = 0
        return

    def on_deactivate(self):
        """ Shut down the NI card.
        """
        self.terminate_all_tasks()
        # Free memory if possible while module is inactive
        self.__frame_buffer = np.empty(0, dtype=self.__data_type)
        return

    @property
    def constraints(self):
        """
        @return Finite sampling constraints
        """
        return self._constraints

    @property
    def active_channels(self):
        """ Names of all currently active input and output channels.

        @return (frozenset, frozenset): active input channels, active output channels
        """
        return self.__active_channels['di_channels'].union(self.__active_channels['ai_channels']), \
               self.__active_channels['ao_channels']

    def set_active_channels(self, input_channels, output_channels):
        """ Will set the currently active input and output channels.
        All other channels will be deactivated.

        @param iterable(str) input_channels: Iterable of input channel names to set active
        @param iterable(str) output_channels: Iterable of output channel names to set active
        """

        assert hasattr(input_channels, '__iter__') and not isinstance(input_channels, str), \
            f'Given input channels {input_channels} are not iterable'

        assert hasattr(output_channels, '__iter__') and not isinstance(output_channels, str), \
            f'Given output channels {output_channels} are not iterable'

        assert not self.is_running, \
            'Unable to change active channels while IO is running. New settings ignored.'

        input_channels = tuple(self._extract_terminal(channel) for channel in input_channels)
        output_channels = tuple(self._extract_terminal(channel) for channel in output_channels)

        assert set(input_channels).issubset(set(self._constraints.input_channel_names)), \
            f'Trying to set invalid input channels "' \
            f'{set(input_channels).difference(set(self._constraints.input_channel_names))}" not defined in config '

        assert set(output_channels).issubset(set(self._constraints.output_channel_names)), \
            f'Trying to set invalid input channels "' \
            f'{set(output_channels).difference(set(self._constraints.output_channel_names))}" not defined in config '

        di_channels, ai_channels = self._extract_ai_di_from_input_channels(input_channels)

        with self._thread_lock:
            self.__active_channels['di_channels'], self.__active_channels['ai_channels'] \
                = frozenset(di_channels), frozenset(ai_channels)

            self.__active_channels['ao_channels'] = frozenset(output_channels)

    @property
    def sample_rate(self):
        """ The sample rate (in Hz) at which the samples will be emitted.

        @return float: The current sample rate in Hz
        """
        return self.__sample_rate

    def set_sample_rate(self, rate):
        """ Sets the sample rate to a new value.

        @param float rate: The sample rate to set
        """
        assert not self.is_running, \
            'Unable to set sample rate while IO is running. New settings ignored.'
        in_range_flag, rate_val = self._constraints.sample_rate_in_range(rate)
        min_val, max_val = self._constraints.sample_rate_limits
        if not in_range_flag:
            self.log.warning(
                f'Sample rate requested ({rate:.3e}Hz) is out of bounds.'
                f'Please choose a value between {min_val:.3e}Hz and {max_val:.3e}Hz.'
                f'Value will be clipped to {rate_val:.3e}Hz.')
        with self._thread_lock:
            self.__sample_rate = float(rate_val)

    def set_output_mode(self, mode):
        """ Setter for the current output mode.

        @param SamplingOutputMode mode: The output mode to set as SamplingOutputMode Enum
        """
        assert not self.is_running, \
            'Unable to set output mode while IO is running. New settings ignored.'
        assert self._constraints.output_mode_supported(mode), f'Output mode {mode} not supported'
        # TODO: in case of assertion error, set output mode to SamplingOutputMode.INVALID?
        with self._thread_lock:
            self.__output_mode = mode

    @property
    def output_mode(self):
        """ Currently set output mode.

        @return SamplingOutputMode: Enum representing the currently active output mode
        """
        return self.__output_mode

    #TODO
    @property
    def samples_in_buffer(self):
        """ Current number of acquired but unread samples per channel in the input buffer.

        @return int: Unread samples in input buffer
        """
        if not self.is_running:
            return self._number_of_pending_samples

        if self._ai_task_handle is None and self._di_task_handles is not None:
            # data = self._timetagger_cbm_tasks[0].getData()
            return self.frame_size #self._di_task_handles[0].in_stream.avail_samp_per_chan
        elif self._ai_task_handle is not None and self._di_task_handles is None:
            return self._ai_task_handle.in_stream.avail_samp_per_chan
        else:
            return min(self._ai_task_handle.in_stream.avail_samp_per_chan,
                       self.frame_size)

    @property
    def frame_size(self):
        """ Currently set number of samples per channel to emit for each data frame.

        @return int: Number of samples per frame
        """
        return self.__frame_size

    def _set_frame_size(self, size):
        samples_per_channel = int(round(size))  # TODO Warn if not integer
        assert self._constraints.frame_size_in_range(samples_per_channel)[0], f'Frame size "{size}" is out of range'
        assert not self.is_running, f'Module is running. Cannot set frame size'

        with self._thread_lock:
            self.__frame_size = samples_per_channel
            self.__frame_buffer = None

    def set_frame_data(self, data):
        """ Fills the frame buffer for the next data frame to be emitted. Data must be a dict
        containing exactly all active channels as keys with corresponding sample data as values.

        If <output_mode> is SamplingOutputMode.JUMP_LIST, the values must be 1D numpy.ndarrays
        containing the entire data frame.
        If <output_mode> is SamplingOutputMode.EQUIDISTANT_SWEEP, the values must be iterables of
        length 3 representing the entire data frame to be constructed with numpy.linspace(),
        i.e. (start, stop, steps).

        Calling this method will alter read-only property <frame_size>

        @param dict data: The frame data (values) to be set for all active output channels (keys)
        """
        assert data is None or isinstance(data, dict), f'Wrong arguments passed to set_frame_data,' \
                                                       f'expected dict and got {type(data)}'

        assert not self.is_running, f'IO is running. Can not set frame data'

        active_output_channels_set = self.active_channels[1]

        if data is not None:
            # assure dict keys are striped from device name and are lower case
            data = {self._extract_terminal(ch): value for ch, value in data.items()}
            # Check for invalid keys
            assert not set(data).difference(active_output_channels_set), \
                f'Invalid keys in data {*set(data).difference(active_output_channels_set),} '
            # Check if all active channels are in data
            assert set(data) == active_output_channels_set, f'Keys of data {*data,} do not match active' \
                                                            f'channels {*active_output_channels_set,}'

            # set frame size
            if self.output_mode == SamplingOutputMode.JUMP_LIST:
                frame_size = len(next(iter(data.values())))
                assert all(isinstance(d, np.ndarray) and len(d.shape) == 1 for d in data.values()), \
                    f'Data values are no 1D numpy.ndarrays'
                assert all(len(d) == frame_size for d in data.values()), f'Length of data values not the same'

                for output_channel in data:
                    assert not np.any(
                        (min(data[output_channel]) < min(self.constraints.output_channel_limits[output_channel])) |
                        (max(data[output_channel]) > max(self.constraints.output_channel_limits[output_channel]))
                    ), f'Output channel {output_channel} value out of constraints range'

            elif self.output_mode == SamplingOutputMode.EQUIDISTANT_SWEEP:
                assert all(len(tup) == 3 and isinstance(tup, tuple) for tup in data.values()), \
                    f'EQUIDISTANT_SWEEP output mode requires value tuples of length 3 for each output channel'
                assert all(isinstance(tup[-1], int) for tup in data.values()), \
                    f'Linspace number of points not integer'

                assert len(set(tup[-1] for tup in data.values())) == 1, 'Linspace lengths are different'

                for output_channel in data:
                    assert not np.any(
                        (min(data[output_channel][:-1]) < min(self.constraints.output_channel_limits[output_channel])) |
                        (max(data[output_channel][:-1]) > max(self.constraints.output_channel_limits[output_channel]))
                    ), f'Output channel {output_channel} value out of constraints range'
                frame_size = next(iter(data.values()))[-1]
            else:
                frame_size = 0

        with self._thread_lock:
            self._set_frame_size(frame_size)
            # set frame buffer
            if data is not None:
                if self.output_mode == SamplingOutputMode.JUMP_LIST:
                    self.__frame_buffer = {output_ch: jump_list for output_ch, jump_list in data.items()}
                elif self.output_mode == SamplingOutputMode.EQUIDISTANT_SWEEP:
                    self.__frame_buffer = {output_ch: np.linspace(*tup) for output_ch, tup in data.items()}
            if data is None:
                self._set_frame_size(0)  # Sets frame buffer to None

    def start_buffered_frame(self):
        """ Will start the input and output of the previously set data frame in a non-blocking way.
        Must return immediately and not wait for the frame to finish.
        Must raise exception if frame output can not be started.
        """

        assert self._constraints.sample_rate_in_range(self.sample_rate)[0], \
            f'Cannot start frame as sample rate {self.sample_rate:.2g}Hz not valid'
        assert self.frame_size != 0, f'No frame data set, can not start buffered frame'
        assert not self.is_running, f'Frame IO already running. Can not start'

        assert self.active_channels[1] == set(self.__frame_buffer), \
            f'Channels in active channels and frame buffer do not coincide'

        self.module_state.lock()

        with self._thread_lock:
            self._number_of_pending_samples = self.frame_size

            # # set up all tasks
            
            
            if self._init_sample_clock() < 0:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise NiInitError('Sample clock initialization failed; all tasks terminated')
            
            # TT
            
            if self._init_tt_cbm_task() < 0:
                self.terminate_all_tasks() # add the treatment of the TT task termination
                self.module_state.unlock()
                
            # DONE - dummy.
            if self._init_analog_in_task() < 0:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise NiInitError('Analog in task initialization failed; all tasks terminated')


        	# DONE - dummy.
            if self._init_analog_out_task_adwin() < 0:
                self.terminate_all_tasks()
                self.module_state.unlock()
                raise NiInitError('Analog out task initialization failed; all tasks terminated')

            output_data = np.ndarray((len(self.active_channels[1]), self.frame_size)) #basicylly a scan line size..

            for num, output_channel in enumerate(self.active_channels[1]):
                output_data[num] = self.__frame_buffer[output_channel]

            
            ## COMMENTING OUT UNWANTED INTERACTION WITH NIDAQ. but need to start adwin here???
            #Before here we should ask for the counts, or?
            
            # HEre the code from the example of the old scan line...
            
            # lsx = np.linspace(self._current_x, x if x!= None else self._current_x, rs)
            # lsy = np.linspace(self._current_y, y if y!= None else self._current_y, rs)
            # lsz = np.linspace(self._current_z, z if z!= None else self._current_z, rs)

            # n_ch = len(self.get_scanner_axes())
            # if n_ch <= 3:
            #     start_line = np.vstack([lsx, lsy, lsz][0:n_ch])
            # else:
            #     start_line = np.vstack(
            #         [lsx, lsy, lsz, np.ones(lsx.shape) * current_pos[3]])
            # # move to the start position of the scan, counts are thrown away
            
            
            
            self._adwin_handle.scan_line(line_path = output_data, pixel_clock = True)
            
            # try:
            #     self._ao_writer.write_many_sample(output_data) ### Writing some data to the adwin scan line!!!
            # except ni.DaqError:
            #     self.terminate_all_tasks()
            #     self.module_state.unlock()
            #     raise

            # if self._ao_task_handle is not None:
            #     try:
            #         self._ao_task_handle.start() #Start the scan line function?????
            #     except ni.DaqError:
            #         self.terminate_all_tasks()
            #         self.module_state.unlock()
            #         raise

            # if self._ai_task_handle is not None:
            #     try:
            #         self._ai_task_handle.start()
            #     except ni.DaqError:
            #         self.terminate_all_tasks()
            #         self.module_state.unlock()
            #         raise

            # if len(self._di_task_handles) > 0:
            #     try:
            #         for di_task in self._di_task_handles:
            #             di_task.start()
            #     except ni.DaqError:
            #         self.terminate_all_tasks()
            #         self.module_state.unlock()
            #         raise

            # try:
            #     self._clk_task_handle.start()
            # except ni.DaqError:
            #     self.terminate_all_tasks()
            #     self.module_state.unlock()
            #     raise
    ## EXAMPLES from ADWIN CODES from old qudi confocal logic.
    
    
    # def _initialise_scanner(self):
    #     """Initialise the clock and locks for a scan"""
    #     self.module_state.lock()
    #     self._scanning_device.module_state.lock()

    #     returnvalue = self._scanning_device.set_up_scanner_clock(
    #         clock_frequency=self._clock_frequency)
    #     if returnvalue < 0:
    #         self._scanning_device.module_state.unlock()
    #         self.module_state.unlock()
    #         return -1

    #     returnvalue = self._scanning_device.set_up_scanner()
    #     if returnvalue < 0:
    #         self._scanning_device.module_state.unlock()
    #         self.module_state.unlock()
    #         return -1

    #     return 0


    def stop_buffered_frame(self):
        """ Will abort the currently running data frame input and output.
        Will return AFTER the io has been terminated without waiting for the frame to finish
        (if possible).

        After the io operation has been stopped, the output frame buffer will keep its state and
        can be re-run or overwritten by calling <set_frame_data>.
        The input frame buffer will also stay and can be emptied by reading the available samples.

        Must NOT raise exceptions if no frame output is running.
        """
        if self.is_running:
            with self._thread_lock:
                number_of_missing_samples = self.samples_in_buffer
                self.__unread_samples_buffer = self.get_buffered_samples()
                self._number_of_pending_samples = number_of_missing_samples

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.terminate_all_tasks()  # nidaqmx raises a warning when frame is stopped before all samples acq.
            self.module_state.unlock()

    def get_buffered_samples(self, number_of_samples=None):
        """ Returns a chunk of the current data frame for all active input channels read from the
        input frame buffer.
        If parameter <number_of_samples> is omitted, this method will return the currently
        available samples within the input frame buffer (i.e. the value of property
        <samples_in_buffer>).
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

        @return dict: Sample arrays (values) for each active input channel (keys)
        """
        #FIX
        #Since counting with time_tagger only -> buffer is fixed
        #We allow ourselve for now to hardcode it:
        number_of_samples=None
        
        with self._thread_lock:
            if number_of_samples is not None:
                assert isinstance(number_of_samples, (int, np.integer)), f'Number of requested samples not integer'

            samples_to_read = number_of_samples if number_of_samples is not None else self.samples_in_buffer
            pre_stop = not self.is_running

            # if not samples_to_read <= self._number_of_pending_samples:
            #     print(f"Requested {samples_to_read} samples, "
            #                      f"but only {self._number_of_pending_samples} enough pending.")

            if samples_to_read > 0 and self.is_running:
                request_time = time.time()
                # if number_of_samples > self.samples_in_buffer:
                #     self.log.debug(f'Waiting for samples to become available since requested {number_of_samples} are more then '
                #                    f'the {self.samples_in_buffer} in the buffer')
                while samples_to_read > self.samples_in_buffer:
                    if time.time() - request_time < 1.1 * self.frame_size / self.sample_rate:  # TODO Is this timeout ok?
                        time.sleep(0.05)
                    else:
                        raise TimeoutError(f'Acquiring {samples_to_read} samples took longer then the whole frame')

            data = dict()

            if samples_to_read == 0:
                return dict.fromkeys(self.active_channels[0], np.array([]))

            if not self.is_running:
                # When the IO was stopped with samples in buffer, return the ones in
                if number_of_samples is None:
                    data = self.__unread_samples_buffer.copy()
                    self.__unread_samples_buffer = dict.fromkeys(self.active_channels[0], np.array([]))
                    self._number_of_pending_samples = 0
                    return data
                else:
                    for key in self.__unread_samples_buffer:
                        data[key] = self.__unread_samples_buffer[key][:samples_to_read]
                    self._number_of_pending_samples -= samples_to_read
                    self.__unread_samples_buffer = {key: arr[samples_to_read:] for (key, arr)
                                                    in self.__unread_samples_buffer.items()}
                    return data
            else:
                if self._timetagger_cbm_tasks:
                    di_data = np.zeros(len(self.__active_channels['di_channels']) * samples_to_read)

                    di_data = di_data.reshape(len(self.__active_channels['di_channels']), samples_to_read)
                    for num, di_channel in enumerate(self.__active_channels['di_channels']):
                        data_cbm = self._timetagger_cbm_tasks[num].getData()
                        di_data[num] = data_cbm
                        data[di_channel] = di_data[num] * self.sample_rate  # To go to c/s # TODO What if unit not c/s
                        self._scanner_ready = self._timetagger_cbm_tasks[num].ready()
                    
                if self._ai_reader is not None:
                    data_buffer = np.zeros(samples_to_read * len(self.__active_channels['ai_channels']))
                    # self.log.debug(f'Buff shape {data_buffer.shape} and len {len(data_buffer)}')
                    read_samples = self._ai_reader.read_many_sample(
                        data_buffer,
                        number_of_samples_per_channel=samples_to_read,
                        timeout=self._rw_timeout)
                    if read_samples != samples_to_read:
                        return data
                    for num, ai_channel in enumerate(self.__active_channels['ai_channels']):
                        data[ai_channel] = data_buffer[num * samples_to_read:(num + 1) * samples_to_read]

                self._number_of_pending_samples -= samples_to_read
                
                return data

    def get_frame(self, data=None):
        """ Performs io for a single data frame for all active channels.
        This method call is blocking until the entire data frame has been emitted.

        See <start_buffered_output>, <stop_buffered_output> and <set_frame_data> for more details.

        @param dict data: The frame data (values) to be emitted for all active channels (keys)

        @return dict: Frame data (values) for all active input channels (keys)
        """
        with self._thread_lock:
            if data is not None:
                self.set_frame_data(data)
            self.start_buffered_frame()
            return_data = self.get_buffered_samples(self.frame_size)
            self.stop_buffered_frame()

            return return_data

    @property
    def is_running(self):
        """
        Read-only flag indicating if the data acquisition is running.

        @return bool: Finite IO is running (True) or not (False)
        """
        assert self.module_state() in ('locked', 'idle')  # TODO what about other module states?
        if self.module_state() == 'locked':
            return True
        else:
            return False

    # =============================================================================================
    def _init_sample_clock(self):
        """
        Configures a counter to provide the sample clock for all
        channels. # TODO external sample clock?

        @return int: error code (0: OK, -1: Error)
        """
        # # Return if sample clock is externally supplied
        # if self._external_sample_clock_source is not None:
        #     return 0
        print('Hello adwin')
        status = self._adwin_handle.set_up_clock(frequency)
        return status

    def _init_tt_cbm_task(self):
        """
        Set up tasks for digital event counting with the TIMETAGGER
        cbm stnads for count between markers
        @return int: error code (0:OK, -1:error)
        """
        
        channels_tt = [int(ch.split("_")[-1]) for ch in self.__active_channels['di_channels'] if "tt" == ch.split("_")[0]]
        
        
        clock_tt = int(self._tt_adwin_clock_input.split("_")[-1])
        
        
        #Workaround for the old time tagger version at the praktikum
        if self._tt_falling_edge_clock_input:
            clock_fall_tt = int(self._tt_falling_edge_clock_input.split("_")[-1])
        else:
            clock_fall_tt = - clock_tt #Rising or falling edge for the clock...
        

        ## Count between the markers meaurements class of the timetagger.
        self._timetagger_cbm_tasks = [self._tt.count_between_markers(click_channel = channel, 
                                        begin_channel = clock_tt,
                                        end_channel = clock_fall_tt, 
                                        n_values=self.frame_size)  ### It wants to get this ammount of the counts. 
                                        for channel in channels_tt]
        ## IT probably doesnt neet to be started, just waits already all the counts after creation.
        
        if self._timetagger_remote():
            channels_tt_remote = [int(ch.split("_")[-1]) for ch in self.__active_channels['di_channels'] if "ttR".lower() == ch.split("_")[0]]
            clock_tt_remote = int(self._tt_remote_ni_clock_input.split("_")[-1])
            if self._tt_remote_falling_edge_clock_input:
                clock_fall_tt_remote = int(self._tt_remote_falling_edge_clock_input.split("_")[-1])
            else:
                clock_fall_tt_remote = - clock_tt_remote
            
            for channel in channels_tt_remote:
                self._timetagger_cbm_tasks.append(
                    self._timetagger_remote().count_between_markers(click_channel = channel, 
                                            begin_channel = clock_tt_remote,
                                            end_channel = clock_fall_tt_remote, 
                                            n_values=self.frame_size)
                )

        return 0

    def _init_analog_in_task(self):
        """
        Set up task for analog voltage measurement.

        @return int: error code (0:OK, -1:error)
        """
        analog_channels = self.__active_channels['ai_channels']
        self.setup_ai_task()
        return 0
    
    def _init_analog_out_task_adwin(self):
        return self.start_scanner()
        
        
    ### TOOK from old qudi
    def _scan_line(self):
        """scanning an image in either depth or xy

        """
        current_pos = self.get_position()
        # stops scanning
        if self.stopRequested:
            # return the scanner to the crosshair position, counts are thrown away
            crosshair_pos = self.crosshair_posi
            rs = self.return_slowness
            #n_ch = len(self.get_scanner_axes())
            n_ch = 4
            npointsshape = self._return_XL.shape
            if n_ch <= 3: # build return line to posi of crosshair
                return_line = np.vstack([
                    np.linspace(current_pos[0], crosshair_pos[0],rs),
                    np.linspace(current_pos[1], crosshair_pos[1],rs),
                    np.linspace(current_pos[2], crosshair_pos[2],rs)
                ][0:n_ch])
            else: # build return line to posi of crosshair
                return_line = np.vstack([
                    np.linspace(current_pos[0], crosshair_pos[0],rs),
                    np.linspace(current_pos[1], crosshair_pos[1],rs),
                    np.linspace(current_pos[2], crosshair_pos[2],rs),
                    np.ones(npointsshape) * current_pos[3] #no idea what _current_a does, just copied from below
                ])
            return_line_counts = self._scanning_device.scan_line(return_line)
            # now actually stop the scan
            with self.threadlock:
                self.kill_scanner()
                self.stopRequested = False
                self.module_state.unlock()
                self.signal_xy_image_updated.emit()
                self.signal_depth_image_updated.emit()
                time.sleep(0.2) # avoid that the emitted thread sees the scanner locked
                self.set_position('scanner')
                if self._zscan:
                    self._depth_line_pos = self._scan_counter
                else:
                    self._xy_line_pos = self._scan_counter
                # add new history entry
                new_history = ConfocalHistoryEntry(self)
                new_history.snapshot(self)
                self.history.append(new_history)
                if len(self.history) > self.max_history_length:
                    self.history.pop(0)
                self.history_index = len(self.history) - 1
                return

        image = self.depth_image if self._zscan else self.xy_image
        #n_ch = len(self.get_scanner_axes())
        n_ch = 4
        s_ch = len(self.get_scanner_count_channels())

        try:
            if self._scan_counter == 0:
                # make a line from the current cursor position to
                # the starting position of the first scan line of the scan
                rs = self.return_slowness
                lsx = np.linspace(self._current_x, image[self._scan_counter, 0, 0], rs)
                lsy = np.linspace(self._current_y, image[self._scan_counter, 0, 1], rs)
                lsz = np.linspace(self._current_z, image[self._scan_counter, 0, 2], rs)
                if n_ch <= 3:
                    start_line = np.vstack([lsx, lsy, lsz][0:n_ch])
                else:
                    start_line = np.vstack(
                        [lsx, lsy, lsz, np.ones(lsx.shape) * current_pos[3]])
                # move to the start position of the scan, counts are thrown away
                start_line_counts = self._scanning_device.scan_line(start_line)
                if np.any(start_line_counts == -1):
                    self.stopRequested = True
                    self.signal_scan_lines_next.emit()
                    return

            # adjust z of line in image to current z before building the line
            if not self._zscan:
                z_shape = image[self._scan_counter, :, 2].shape
                image[self._scan_counter, :, 2] = self._current_z * np.ones(z_shape)

            # make a line in the scan, _scan_counter says which one it is
            lsx = image[self._scan_counter, :, 0]
            lsy = image[self._scan_counter, :, 1]
            lsz = image[self._scan_counter, :, 2]
            if n_ch <= 3:
                line = np.vstack([lsx, lsy, lsz][0:n_ch])
            else:
                line = np.vstack(
                    [lsx, lsy, lsz, np.ones(lsx.shape) * current_pos[3]])

            # scan the line in the scan
            self._counter_device.setup_count_confocal(len(lsx))
            self.dummy = self._scanning_device.scan_line(line, pixel_clock=True)
            line_counts = self._counter_device.get_confocal_counts()
            if np.any(line_counts == -1):
                self.stopRequested = True
                self.signal_scan_lines_next.emit()
                return

            # make a line to go to the starting position of the next scan line
            # if last line is scanned, make return line to cursor position
            #------------------------------------------------------------------------------------
            #
            # PLAY HERE
            # if we are in the last line
            # if self._scan_counter >= np.size(self._image_vert_axis)-1:
            #     # take x as before, but change y and z
            #     # get current position
            #     current_pos = image[self._scan_counter, 0, :]
            #     #get position of crosshair
            #     crosshair_pos = self.get_position()
            #     npoints = self._return_XL.shape[0]
            #     return_line = np.vstack([
            #         self._return_XL,
            #         np.linspace(current_pos[1], crosshair_pos[1],npoints),
            #         np.linspace(current_pos[2], crosshair_pos[1],npoints)
            #     ][0:n_ch])
            #
            #------------------------------------------------------------------------------------


            if self.depth_img_is_xz or not self._zscan:
                # do as usual if not last line
                if self._scan_counter < np.size(self._image_vert_axis)-1:
                    if n_ch <= 3:
                        return_line = np.vstack([
                            self._return_XL,
                            image[self._scan_counter, 0, 1] * np.ones(self._return_XL.shape),
                            image[self._scan_counter, 0, 2] * np.ones(self._return_XL.shape)
                        ][0:n_ch])
                    else:
                        return_line = np.vstack([
                            self._return_XL,
                            image[self._scan_counter, 0, 1] * np.ones(self._return_XL.shape),
                            image[self._scan_counter, 0, 2] * np.ones(self._return_XL.shape),
                            np.ones(self._return_XL.shape) * current_pos[3]
                        ])
                else: # if in last line
                    # get current position
                    current_pos = image[self._scan_counter, -1, :]
                    crosshair_pos = self.crosshair_posi
                    npointsshape = self._return_XL.shape
                    npoints = npointsshape[0]
                    if n_ch <= 3: # build return line to posi of crosshair
                        return_line = np.vstack([
                            np.linspace(current_pos[0], crosshair_pos[0],npoints),
                            np.linspace(current_pos[1], crosshair_pos[1],npoints),
                            np.linspace(current_pos[2], crosshair_pos[2],npoints)
                        ][0:n_ch])
                    else: # build return line to posi of crosshair
                        return_line = np.vstack([
                            np.linspace(current_pos[0], crosshair_pos[0],npoints),
                            np.linspace(current_pos[1], crosshair_pos[1],npoints),
                            np.linspace(current_pos[2], crosshair_pos[2],npoints),
                            np.ones(npointsshape) * current_pos[3] #no idea what _current_a does, just copied from above
                        ])
            else:
                if n_ch <= 3:
                    return_line = np.vstack([
                            image[self._scan_counter, 0, 1] * np.ones(self._return_YL.shape),
                            self._return_YL,
                            image[self._scan_counter, 0, 2] * np.ones(self._return_YL.shape)
                        ][0:n_ch])
                else:
                    return_line = np.vstack([
                            image[self._scan_counter, 0, 1] * np.ones(self._return_YL.shape),
                            self._return_YL,
                            image[self._scan_counter, 0, 2] * np.ones(self._return_YL.shape),
                            np.ones(self._return_YL.shape) * current_pos[3]
                        ])

            # return the scanner to the start of next line, counts are thrown away
            return_line_counts = self._scanning_device.scan_line(return_line)
            if np.any(return_line_counts == -1):
                self.stopRequested = True
                self.signal_scan_lines_next.emit()
                return

            # update image with counts from the line we just scanned
            if self._zscan:
                if self.depth_img_is_xz:
                    self.depth_image[self._scan_counter, :, 3:3 + s_ch] = line_counts
                else:
                    self.depth_image[self._scan_counter, :, 3:3 + s_ch] = line_counts
                self.signal_depth_image_updated.emit()
            else:
                self.xy_image[self._scan_counter, :, 3:3 + s_ch] = line_counts
                self.signal_xy_image_updated.emit()

            # next line in scan
            self._scan_counter += 1

            # stop scanning when last line scan was performed and makes scan not continuable
            if self._scan_counter >= np.size(self._image_vert_axis):
                if not self.permanent_scan:
                    self.stop_scanning()
                    if self._zscan:
                        self._zscan_continuable = False
                    else:
                        self._xyscan_continuable = False
                else:
                    self._scan_counter = 0

            self.signal_scan_lines_next.emit()
        except:
            self.log.exception('The scan went wrong, killing the scanner.')
            self.stop_scanning()
            self.signal_scan_lines_next.emit()
    
    
    def start_ai_task(self):
        
        #TBD
        pass
    
    def start_scanner(self):
        """Setting up the scanner device and starts the scanning procedure

        @return int: error code (0:OK, -1:error)
        """
        self.module_state.lock()

        self._scanning_device.module_state.lock()
        if self.initialize_image() < 0:
            self._scanning_device.module_state.unlock()
            self.module_state.unlock()
            return -1

        clock_status = self._scanning_device.set_up_scanner_clock(
            clock_frequency=self._clock_frequency)

        if clock_status < 0:
            self._scanning_device.module_state.unlock()
            self.module_state.unlock()
            self.set_position('scanner')
            return -1

        scanner_status = self._scanning_device.set_up_scanner()

        if scanner_status < 0:
            self._scanning_device.close_scanner_clock()
            self._scanning_device.module_state.unlock()
            self.module_state.unlock()
            self.set_position('scanner')
            return -1

        self.signal_scan_lines_next.emit()
        return 0

    def continue_scanner(self):
        """Continue the scanning procedure

        @return int: error code (0:OK, -1:error)
        """
        self.module_state.lock()
        self._scanning_device.module_state.lock()

        clock_status = self._scanning_device.set_up_scanner_clock(
            clock_frequency=self._clock_frequency)

        if clock_status < 0:
            self._scanning_device.module_state.unlock()
            self.module_state.unlock()
            self.set_position('scanner')
            return -1

        scanner_status = self._scanning_device.set_up_scanner()

        if scanner_status < 0:
            self._scanning_device.close_scanner_clock()
            self._scanning_device.module_state.unlock()
            self.module_state.unlock()
            self.set_position('scanner')
            return -1

        self.signal_scan_lines_next.emit()
        return 0
        
                
    ### Continue from new qudi. 

    def _init_analog_out_task_NI_only(self):
        
        """this is what a NIDAQ code looked like...

        Returns:
            _type_: _description_
        """
        
        analog_channels = self.__active_channels['ao_channels']
        if not analog_channels:
            self.log.error('No output channels defined. Can initialize output task')
            return -1

        clock_channel = '/{0}InternalOutput'.format(self._clk_task_handle.channel_names[0])
        sample_freq = float(self._clk_task_handle.co_channels.all.co_pulse_freq)

        # Set up analog input task
        task_name = 'AnalogOut_{0:d}'.format(id(self))

        try:
            ao_task = ni.Task(task_name)
        except ni.DaqError:
            self.log.exception('Unable to create analog-in task with name "{0}".'.format(task_name))
            self.terminate_all_tasks()
            return -1

        try:
            for ao_channel in analog_channels:
                ao_ch_str = '/{0}/{1}'.format(self._device_name, ao_channel)
                ao_task.ao_channels.add_ao_voltage_chan(ao_ch_str,
                                                        min_val=min(self.constraints.output_channel_limits[ao_channel]),
                                                        max_val=max(self.constraints.output_channel_limits[ao_channel])
                                                        )
            ao_task.timing.cfg_samp_clk_timing(sample_freq,
                                               source=clock_channel,
                                               active_edge=ni.constants.Edge.RISING,
                                               sample_mode=ni.constants.AcquisitionType.FINITE,
                                               samps_per_chan=self.frame_size)
        except ni.DaqError:
            self.log.exception(
                'Something went wrong while configuring the analog-in task.')
            try:
                del ao_task
            except NameError:
                pass
            self.terminate_all_tasks()
            return -1

        try:
            ao_task.control(ni.constants.TaskMode.TASK_RESERVE)
        except ni.DaqError:
            try:
                ao_task.close()
            except ni.DaqError:
                self.log.exception('Unable to close task.')
            try:
                del ao_task
            except NameError:
                self.log.exception('Some weird namespace voodoo happened here...')

            self.log.exception('Unable to reserve resources for analog-out task.')
            self.terminate_all_tasks()
            return -1

        try:
            self._ao_writer = AnalogMultiChannelWriter(ao_task.in_stream)
            self._ao_writer.verify_array_shape = False
        except ni.DaqError:
            try:
                ao_task.close()
            except ni.DaqError:
                self.log.exception('Unable to close task.')
            try:
                del ao_task
            except NameError:
                self.log.exception('Some weird namespace voodoo happened here...')
            self.log.exception('Something went wrong while setting up the analog input reader.')
            self.terminate_all_tasks()
            return -1

        self._ao_task_handle = ao_task
        return 0

    def set_new_io_limits(self, is_LT_regime):

        if is_LT_regime:
            limits = self._output_voltage_ranges_LT
        else:
            limits = self._output_voltage_ranges

        digital_sources = tuple(src for src in self._input_channel_units)
        input_limits = dict()

        if digital_sources:
            input_limits.update({self._extract_terminal(key): [0, int(1e8)]
                                for key in digital_sources})  # TODO Real HW constraint?

        sample_rate_limits = (self._device_handle.ao_min_rate, min(self._device_handle.ao_max_rate, self._device_handle.ci_max_timebase))

        # output_voltage_ranges = {self._extract_terminal(key): value
        #                                 for key, value in self._output_voltage_ranges.items()}
        output_voltage_ranges = limits
        output_voltage_ranges = dict(sorted(output_voltage_ranges.items()))
        self._output_channel_units = dict(sorted(self._output_channel_units.items()))

        self._input_channel_units = dict(sorted(self._input_channel_units.items()))
        input_limits = dict(sorted(input_limits.items()))

        self._constraints = FiniteSamplingIOConstraints(
                    supported_output_modes=(SamplingOutputMode.JUMP_LIST, SamplingOutputMode.EQUIDISTANT_SWEEP),
                    input_channel_units=dict(self._input_channel_units),
                    output_channel_units=dict(self._output_channel_units),
                    frame_size_limits=self._frame_size_limits,
                    sample_rate_limits=sample_rate_limits,
                    output_channel_limits=output_voltage_ranges,
                    input_channel_limits=input_limits
                )


    def reset_hardware(self):
        """
        Resets the NI hardware, so the connection is lost and other programs can access it.

        @return int: error code (0:OK, -1:error)
        """
        
        
        # TODO REWIRET USING THE ADWIN BASE RESET HARDWARE
        
        self._device_handle.reset_hardware() #TODO make sure that the magnet is not quenched. 
        
        
        return 0

    def terminate_all_tasks(self):
        
        #TODO properly... in principle remove all the scanner realted tasks from the adwin.
        
        # Terminate the ADWIN process related to scanners, and TT process.
        err = 0
        self._adwin_handle.close_scanner() # this should also keep an eye on processes killing, 
        
        self._di_readers = list()
        self._ai_reader = None

        
        # an attempt to make a quasi stopping of the tasks..
        while len(self._adwin_handle.scanner_processes) > 0:
            try:
                pass
                #TODO stop the processes... Doing nothing now...
            
            except Exception as e:
                self.log.exception('Error while trying to terminate digital counter task.'+e)
                err = -1
            finally:
                pass
                #todo del adwin tasks.
        #self._di_task_handles = list()
        #self._tasks_started_successfully = False
        return err

    @staticmethod
    def _extract_terminal(term_str):
        """
        Helper function to extract the bare terminal name from a string and strip it of the device
        name and dashes.
        Will return the terminal name in lower case.

        @param str term_str: The str to extract the terminal name from
        @return str: The terminal name in lower case
        """
        term = term_str#.strip('/').lower()
        if 'dev' in term:
            term = term.split('/', 1)[-1]
        return term

    def _extract_ai_di_from_input_channels(self, input_channels):
        """
        Takes an iterable with output channels and returns the split up ai and di channels

        @return tuple(di_channels), tuple(ai_channels))
        """
        input_channels = tuple(self._extract_terminal(src) for src in input_channels)

        di_channels = tuple(channel for channel in input_channels if ('pfi' in channel) or ("tt" in channel))
        ai_channels = tuple(channel for channel in input_channels if 'ai' in channel)

        assert (di_channels or ai_channels), f'No channels could be extracted from {*input_channels,}'

        return tuple(di_channels), tuple(ai_channels)


class NiInitError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)
