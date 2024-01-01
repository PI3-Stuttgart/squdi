import ctypes
import numpy as np
import nidaqmx as ni
from nidaqmx._lib import lib_importer  # Due to NIDAQmx C-API bug needed to bypass property getter
from nidaqmx.stream_readers import AnalogMultiChannelReader, CounterReader
from nidaqmx.stream_writers import AnalogMultiChannelWriter

from qudi.core.configoption import ConfigOption
from qudi.core.module import Base
from qudi.core.connector import Connector
from qudi.util.helpers import natural_sort
from qudi.interface.finite_sampling_io_interface import FiniteSamplingIOInterface, FiniteSamplingIOConstraints
from qudi.util.enums import SamplingOutputMode
from qudi.util.mutex import RecursiveMutex
import time
import warnings

class NI_IO_TT_Interfuse(FiniteSamplingIOInterface):
    _timetagger = Connector(name='tt', interface = "TT")
    _ni_finite_sampling_io = Connector(name='scan_hardware', interface='FiniteSamplingIOInterface')

    _device_name = ConfigOption(name='device_name', default='Dev1', missing='warn')
    
    _rw_timeout = ConfigOption('read_write_timeout', default=10, missing='nothing')
    _delay_buffered_frame = ConfigOption('delay_buffered_frame', default=0.0, missing='nothing')
    # Finite Sampling #TODO What are the frame size hardware limits?
    _frame_size_limits = ConfigOption(name='frame_size_limits', default=(1, 1e9))
   
    input_channel_units = ConfigOption(name='input_channel_units',
                                        missing='error')
    
    _tt_ni_clock_input = ConfigOption(name = "tt_ni_clock_input",
                                                default=None, missing='warn')
    
    _tt_falling_edge_clock_input = ConfigOption(name = "tt_falling_edge_clock_input",
                                                default=None, missing='warn')
    _sum_channels = ConfigOption(name='sum_channels', default=[], missing='nothing')
    _scanner_ready = False
    # Hardcoded data type
    __data_type = np.float64

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._di_task_handles = list()

        self._timetagger_cbm_tasks = list()

        # Internal settings
        self.__output_mode = None
        self.__sample_rate = -1.0

        # Internal settings
        self.__frame_size = -1
        self.__frame_buffer = -1

        # unread samples buffer
        self.__unread_samples_buffer = None
        self._number_of_pending_samples = 0

        # currently active channels
        self.__active_channels = dict(di_channels=frozenset(), ai_channels=frozenset(), ao_channels=frozenset())

        # Stored hardware constraints
        self._constraints = None
        self._thread_lock = RecursiveMutex()
        return
    
    
    def on_activate(self):
        """
        Starts up the NI-card and performs sanity checks.
        """

        # Check if device is connected and set device to use
        self._tt = self._timetagger()
        
        self._ni_finite_sampling_io = self._ni_finite_sampling_io()
        self._device_handle = self._ni_finite_sampling_io._device_handle

        self._sum_channels = [ch.lower() for ch in self._sum_channels]
        # SOLVE THE ISSUE WITH _input channel units USING ORDERERD DICT
        self._input_channel_units = self._ni_finite_sampling_io._input_channel_units
        self._input_channel_units.update({self._extract_terminal(key): value
                                     for key, value in self.input_channel_units.items()})
        if len(self._sum_channels) > 1:
            self._input_channel_units["sum"] = self._input_channel_units[self._sum_channels[0]]
        
        output_voltage_ranges = {self._extract_terminal(key): value
                                 for key, value in self._ni_finite_sampling_io._output_voltage_ranges.items()}

        digital_sources = tuple(src for src in self._input_channel_units if 'tt' in src) #!FIX check maybe regex out tt
        self.input_limits = self._ni_finite_sampling_io._constraints.input_channel_limits
        if digital_sources:
            self.input_limits.update({key: [0, int(1e8)]
                                 for key in digital_sources})  # TODO Real HW constraint?
        if len(self._sum_channels) > 1:
            self.input_limits["sum"] = [0, int(1e8)]
        self.__active_channels["di_channels"] = [int(ch[2:]) for ch in self._input_channel_units.keys() if "tt" in ch]
        
        # Create constraints
        # output_units = self._ni_finite_sampling_io._output_channel_units
        # print("Output ranges", output_voltage_ranges.keys())
        # output_units = {"ao1": "V"}
        # self._constraints = self._ni_finite_sampling_io._constraints
        # self._constraints._input_channel_units

        self._constraints = FiniteSamplingIOConstraints(
            supported_output_modes=(SamplingOutputMode.JUMP_LIST, SamplingOutputMode.EQUIDISTANT_SWEEP),
            input_channel_units=self._input_channel_units,
            output_channel_units=self._ni_finite_sampling_io._constraints._output_channel_units,
            frame_size_limits=self._ni_finite_sampling_io._constraints._frame_size_limits,
            sample_rate_limits=self._ni_finite_sampling_io._constraints.sample_rate_limits,
            output_channel_limits=self._ni_finite_sampling_io._output_voltage_ranges,
            input_channel_limits=self.input_limits,
        )
        # assert self._constraints.output_mode_supported(self._ni_finite_sampling_io._default_output_mode), \
        #     f'Config output "{self._ni_finite_sampling_io._default_output_mode}" mode not supported'

        self.__output_mode = self._ni_finite_sampling_io._default_output_mode
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

    def set_active_channels(self, input_channels, output_channels):
        """ Will set the currently active input and output channels.
        All other channels will be deactivated.

        @param iterable(str) input_channels: Iterable of input channel names to set active
        @param iterable(str) output_channels: Iterable of output channel names to set active
        """
        assert not self.is_running, \
            'Unable to change active channels while IO is running. New settings ignored.'

        #start all input and output channels of the remote NI card
        input_channels = [input_ch for input_ch in list(self._ni_finite_sampling_io._constraints.input_channel_names)]
        output_channels = [output_ch for output_ch in list(self._ni_finite_sampling_io._constraints.output_channel_names)]
        
        self._ni_finite_sampling_io.set_active_channels(input_channels, output_channels)

        #set active the lockal channels (the time tagger channels for readout!)

        di_channels, ai_channels = self._extract_ai_di_from_input_channels(input_channels)
        di_channels = [int(ch[2:]) for ch in self._input_channel_units.keys() if "tt" in ch]
        
        with self._thread_lock:
            self.__active_channels['di_channels'], self.__active_channels['ai_channels'] \
                = frozenset(di_channels), frozenset(ai_channels)

            self.__active_channels['ao_channels'] = frozenset(output_channels)
        self.__active_channels["di_channels"] = frozenset([ch for ch in self._input_channel_units.keys() if "tt" in ch])
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
        in_range_flag, rate_val = self._ni_finite_sampling_io._constraints.sample_rate_in_range(rate)
        min_val, max_val = self._ni_finite_sampling_io._constraints.sample_rate_limits
        if not in_range_flag:
            self.log.warning(
                f'Sample rate requested ({rate:.3e}Hz) is out of bounds.'
                f'Please choose a value between {min_val:.3e}Hz and {max_val:.3e}Hz.'
                f'Value will be clipped to {rate_val:.3e}Hz.')
        with self._thread_lock:
            self.__sample_rate = float(rate_val)
            self._ni_finite_sampling_io.set_sample_rate(self.__sample_rate)

    def set_output_mode(self, mode):
        """ Setter for the current output mode.

        @param SamplingOutputMode mode: The output mode to set as SamplingOutputMode Enum
        """
        self._ni_finite_sampling_io.set_output_mode(mode)
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

    @property
    def samples_in_buffer(self):
        """ Current number of acquired but unread samples per channel in the input buffer.

        @return int: Unread samples in input buffer
        """
        if not self.is_running:
            return self._number_of_pending_samples
        else:
            return self.frame_size #self._di_task_handles[0].in_stream.avail_samp_per_chan

    @property
    def frame_size(self):
        """ Currently set number of samples per channel to emit for each data frame.

        @return int: Number of samples per frame
        """
        return self.__frame_size

    def _set_frame_size(self, size):
        
        samples_per_channel = int(round(size))
        with self._thread_lock:
            self.__frame_size = samples_per_channel
            self.__frame_buffer = None
        #self._ni_finite_sampling_io._set_frame_size(size)#

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

        active_output_channels_set = self._ni_finite_sampling_io.active_channels[1]
        self._ni_finite_sampling_io.set_frame_data(data)
        self._set_frame_size(self._ni_finite_sampling_io.frame_size)

    def start_buffered_frame(self):
        """ Will start the input and output of the previously set data frame in a non-blocking way.
        Must return immediately and not wait for the frame to finish.

        Must raise exception if frame output can not be started.
        """
        # I need to check if the frame size is set and active channels are set
        
        self.module_state.lock()
        with self._thread_lock:
            

            if self._init_tt_cbm_task() < 0:
                self.terminate_all_tasks() # add the treatment of the TT task termination
                self.module_state.unlock()
            
            time.sleep(self._delay_buffered_frame)
            self._ni_finite_sampling_io.start_buffered_frame()
            # output_data = np.ndarray((len(self.active_channels[1]), self.frame_size))

            # for num, output_channel in enumerate(self.active_channels[1]):
            #     output_data[num] = self.__frame_buffer[output_channel]

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
            with self._thread_lock:
                self._ni_finite_sampling_io.stop_buffered_frame()
            

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
                        self._scanner_ready = self._timetagger_cbm_tasks[0].ready()
              
                self._number_of_pending_samples -= samples_to_read
                
                return data
    @property
    def active_channels(self):
        """ Names of all currently active input and output channels.

        @return (frozenset, frozenset): active input channels, active output channels
        """
        return self.__active_channels['di_channels'].union(self.__active_channels['ai_channels']), \
               self.__active_channels['ao_channels']
    

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

    def _init_tt_cbm_task(self):
        """
        Set up tasks for digital event counting with the TIMETAGGER
        cbm stnads for count between markers
        @return int: error code (0:OK, -1:error)
        """
        
        # channels_tt =[int(ch[2:]) for ch in self.__active_channels['di_channels'] if "tt" in ch]
        channels_tt = [int(ch[2:]) for ch in self.__active_channels['di_channels'] if "tt" in ch and "remote" not in ch]
        remote_channels_tt = [int(ch[2:].split("_remote")[0]) for ch in self.__active_channels['di_channels'] if "tt" in ch and "remote" in ch]
        clock_tt = int(self._tt_ni_clock_input[2:])
        #Workaround for the old time tagger version at the praktikum
        if self._tt_falling_edge_clock_input:
            clock_fall_tt = int(self._tt_falling_edge_clock_input[2:])
        else:
            clock_fall_tt = - clock_tt
        self._timetagger_cbm_tasks = [self._tt.count_between_markers(click_channel = channel, 
                                        begin_channel = clock_tt,
                                        end_channel = clock_tt,#clock_fall_tt, 
                                        n_values=self.frame_size) 
                                        for channel in channels_tt]
        
        for ch in remote_channels_tt:
            self._timetagger_cbm_tasks.append(
                self._tt.count_between_markers(
                    is_remote=True,
                    click_channel = ch, 
                    begin_channel = clock_tt,
                    end_channel = clock_tt,#clock_fall_tt, 
                    n_values=self.frame_size
                    )
            )

        return 0

    def reset_hardware(self):
        """
        Resets the NI hardware, so the connection is lost and other programs can access it.

        @return int: error code (0:OK, -1:error)
        """
        
        return self._ni_finite_sampling_io.reset_hardware()

    def terminate_all_tasks(self):
        err = 0

        err = self._ni_finite_sampling_io.terminate_all_tasks()
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
        term = term_str.strip('/').lower()
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