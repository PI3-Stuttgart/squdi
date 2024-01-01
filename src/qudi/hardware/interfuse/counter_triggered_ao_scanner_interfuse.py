import numpy as np
import time

from PySide2 import QtCore
from PySide2.QtGui import QGuiApplication

from qudi.interface.scanning_probe_interface import ScanningProbeInterface, ScanConstraints, \
    ScannerAxis, ScannerChannel, ScanData
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.util.mutex import RecursiveMutex, Mutex
from qudi.util.enums import SamplingOutputMode
from qudi.util.helpers import in_range

class CounterTriggeredAOScanner(ScanningProbeInterface):
    """
    The interfuse to connect a time tagger and an analog scanning device.

    """
    _timetagger = Connector(name='tagger', interface = "TT")
    _triggered_ao = Connector(name='triggered_ao', interface='TriggeredAOInterface')

    _channel_mapping = ConfigOption(name='channel_mapping', missing='error')
    _sum_channels = ConfigOption(name='sum_channels', default=[], missing='nothing')
    _input_channel_units = ConfigOption(name='input_channel_units', missing='error')
    _scan_units = ConfigOption(name='scan_units', missing='error')

    _position_ranges = ConfigOption(name='position_ranges', missing='error')
    _frequency_ranges = ConfigOption(name='frequency_ranges', missing='error')
    _resolution_ranges = ConfigOption(name='resolution_ranges', missing='error')
    
    _backwards_line_resolution = ConfigOption(name='backwards_line_resolution', default=50)
    __max_move_velocity = ConfigOption(name='maximum_move_velocity', default=400e-6)
    _ao_trigger_channel = ConfigOption(name="ao_trigger_channel", missing='error') #trigger from AO to timetagger
    
    _threaded = True  # Interfuse is by default not threaded.
    _scanned_lines = 0
    _max_rollovers = 1
    lines_to_scan = 1

    sigNextDataChunk = QtCore.Signal()
    sigStartScanner = QtCore.Signal()


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._current_scan_frequency = -1
        self._current_scan_ranges = [tuple(), tuple()]
        self._current_scan_axes = tuple()
        self._current_scan_resolution = tuple()

        self._scan_data = None
        self.raw_data_container = None

        self._constraints = None
        
        self._target_pos = dict()
        self._stored_target_pos = dict()

        self._min_step_interval = 1e-3
        self._scanner_distance_atol = 1e-9

        self._ao_trigger_channel = int(self._ao_trigger_channel[2:])

        self._thread_lock_cursor = Mutex()
        self._thread_lock_data = Mutex()

        self.movement_manager = MovementManager(self)
        self.scan_manager = ScanManager(self)
        self.data_manager = DataManager(self)
        # Initialize other necessary components here

    def on_activate(self):
        
        self._validate_channel_configuration()

        self._configure_scanner_constraints()

        self._initialize_scanner_state()
        
        self._setup_signals()

    def _validate_channel_configuration(self):
        """ Validate that the channel configurations are correctly set. """
        assert set(self._position_ranges) == set(self._frequency_ranges) == set(self._resolution_ranges), \
            'Channels in position ranges, frequency ranges, and resolution ranges do not coincide'

        assert set(self._input_channel_units).union(self._position_ranges) == set(self._channel_mapping), \
            'Not all specified channels are mapped to the physical channel'

    def _configure_scanner_constraints(self):
        """ Configure scanner constraints based on the channel settings. """
        self._normalize_channel_names()
        self._create_axes_constraints()
        self._create_channel_constraints()
        self._assign_active_channels()

    def _normalize_channel_names(self):
        """ Normalize the names of the channels for consistency. """
        self._sum_channels = [ch.lower() for ch in self._sum_channels]
        if len(self._sum_channels) > 1:
            self._input_channel_units["sum"] = list(self._input_channel_units.values())[1]

    def _create_axes_constraints(self):
        """ Create constraints for each axis. """
        self._constraints_axes = [
            ScannerAxis(
                name=axis,
                unit=self._scan_units,
                value_range=self._position_ranges[axis],
                step_range=(0, abs(np.diff(self._position_ranges[axis]))),
                resolution_range=self._resolution_ranges[axis],
                frequency_range=self._frequency_ranges[axis]
            )
            for axis in self._position_ranges
        ]

    def _create_channel_constraints(self):
        """ Create constraints for each channel. """
        self._constraints_channels = [
            ScannerChannel(name=channel, unit=unit, dtype=np.float64)
            for channel, unit in self._input_channel_units.items()
        ]

    def _assign_active_channels(self):
        """ Assign active channels based on channel mapping. """
        self.__active_channels = {
            'di_channels': [value for key, value in self._channel_mapping.items() if "APD" in key]
        }
        self._constraints = ScanConstraints(
            axes=self._constraints_axes,
            channels=self._constraints_channels,
            backscan_configurable=False,
            has_position_feedback=False,
            square_px_only=False
        )

    def _initialize_scanner_state(self):
        """ Initialize the state of the scanner. """
        self._target_pos = self.get_position()  # get voltages/positions from ni_ao
        self._toggle_ao_setpoint_channels(False)  # Free ao resources
        self._t_last_move = time.perf_counter()
        self.__t_last_follow = None

    def _setup_signals(self):
        """ Setup signals for data fetching and scanner start. """
        self.sigNextDataChunk.connect(self._fetch_data_chunk, QtCore.Qt.QueuedConnection)
        self.sigStartScanner.connect(lambda: self._triggered_ao().start_scan(), QtCore.Qt.QueuedConnection)


    def on_deactivate(self):
        # Deactivation logic here

    # Other high-level methods...

class MovementManager:
    def __init__(self, parent):
        self.parent = parent

    def move_absolute(self, position, velocity=None, blocking=False):
        # Movement logic

    def move_relative(self, distance, velocity=None, blocking=False):
        # Relative movement logic

    # Other movement-related methods...
class ScanManager:
    def __init__(self, parent):
        self.parent = parent

    def configure_scan(self, scan_settings):
        # Configuration logic

    def start_scan(self):
        # Start scan logic

    def stop_scan(self):
        # Stop scan logic

    # Other scan-related methods...

class DataManager:
    def __init__(self, parent):
        self.parent = parent

    def get_scan_data(self):
        # Logic to retrieve scan data

    def process_data_chunk(self, data_chunk):
        # Data processing logic

    # Other data-related methods...
        

def position_to_voltage(position):
    # Conversion logic

# Other utility functions...
