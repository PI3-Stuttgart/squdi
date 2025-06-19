from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
import numpy as np
import pulsestreamer as pstreamer
from pulsestreamer import Sequence, OutputState

import os

class PulseStreamer(Base):
    """
    Wrapper for the Swabian Instruments Pulse Streamer.
    """

    _ip_address = ConfigOption('ip_address', '192.168.1.100', missing='info')
    _trigger_mode = ConfigOption('trigger_mode', 'software', missing='warn')
    _pulse_schemes_directory = ConfigOption('pulse_schemes_directory', 'pulse_schemes', missing='info')
    _seq = None
    def __init__(self, **kwargs):
        """
        Initializes the Pulse Streamer module.
        """
        super().__init__(**kwargs)
        self.ps = None
        self.sequence_data = None # To hold the sequence list
        if not os.path.exists(self._pulse_schemes_directory):
            try:
                os.makedirs(self._pulse_schemes_directory)
                self.log.info(f"Created pulse schemes directory: {self._pulse_schemes_directory}")
            except OSError as e:
                self.log.error(f"Failed to create pulse schemes directory {self._pulse_schemes_directory}: {e}")

    def on_activate(self):
        """
        Called when the module is activated. Connects to the device.
        """
        self.connect()

    def on_deactivate(self):
        """
        Called when the module is deactivated. Disconnects from the device.
        """
        self.disconnect()

    def connect(self):
        """
        Connect to the Pulse Streamer device.
        """
        try:
            # The constructor accepts an IP address or hostname 
            self.ps = pstreamer.PulseStreamer(self._ip_address)
            self.log.info(f"Connected to Pulse Streamer at {self._ip_address}")
            # Resetting the device to a known default state is good practice 
            self.ps.reset()
        except Exception as e:
            self.log.error(f"Failed to connect to Pulse Streamer: {e}")
            self.ps = None

    def disconnect(self):
        """
        Disconnects from the Pulse Streamer.
        """
        if self.ps:
            try:
                # Set outputs to 0V before closing for safety
                self.ps.constant(OutputState.ZERO)
                self.ps.close()
                self.log.info("Disconnected from Pulse Streamer.")
                self.ps = None
            except Exception as e:
                self.log.error(f"Error during disconnection: {e}")

    def upload_sequence(self, sequence_data):
        """
        Stores the sequence data locally, ready for streaming.
        The data should be in the Run-Length Encoded (RLE) list format.
        
        :param sequence_data: A list of tuples in the format:
                              (duration_ns, [HIGH_channels], analog_V0, analog_V1)
        """
        self.sequence_data = sequence_data
       

    def load_sequence_from_file(self, filename):
        """
        Loads sequence data from a .npy file.
        """
        filepath = os.path.join(self._pulse_schemes_directory, filename)
        if not os.path.exists(filepath):
            self.log.error(f"Sequence file not found: {filepath}")
            return
        
        try:
            # allow_pickle=True is needed for arrays of lists
            loaded_data = np.load(filepath, allow_pickle=True)
            self.upload_sequence(loaded_data.tolist())
            self.log.info(f"Loaded sequence data from {filename}")
        except Exception as e:
            self.log.error(f"Failed to load sequence from file: {e}")

    def save_sequence_to_file(self, sequence_data, filename):
        """
        Saves sequence data to a .npy file.
        """
        filepath = os.path.join(self._pulse_schemes_directory, filename)
        try:
            np.save(filepath, np.array(sequence_data, dtype=object), allow_pickle=True)
            self.log.info(f"Saved sequence to {filepath}")
        except Exception as e:
            self.log.error(f"Failed to save sequence to file: {e}")
    
    def plot_sequence(self):
        """
        Converts the stored RLE-list sequence to per-channel patterns,
        builds a temporary Sequence object, and calls its plot() method.
        """
        if self.sequence_data is None:
            self.log.error("No sequence data is stored to plot.")
            return
        if not self.ps:
            self.log.error("Pulse Streamer not connected. Cannot create sequence for plotting.")
            return

        print("Generating plot of the current sequence...")
        try:
            # 1. De-multiplex the RLE list into per-channel patterns
            digital_patterns = {i: [] for i in range(8)}
            analog_patterns = {i: [] for i in range(2)}

            for duration, high_channels, v0, v1 in self.sequence_data:
                for i in range(8): # For all 8 digital channels
                    level = 1 if i in high_channels else 0
                    digital_patterns[i].append((duration, level))
                analog_patterns[0].append((duration, v0))
                analog_patterns[1].append((duration, v1))
            
            # 2. Create a hardware-aware Sequence object
            # Per the manual, this is the recommended way 
            self.temp_seq = self.ps.createSequence()

            # 3. Populate the Sequence object using setDigital/setAnalog
            for i in range(8):
                self.temp_seq.setDigital(i, digital_patterns[i])
            for i in range(2):
                self.temp_seq.setAnalog(i, analog_patterns[i])

            # 4. Call the plot method on the fully constructed object 
            self.temp_seq.plot()
            
        except Exception as e:
            self.log.error(f"Failed to plot sequence: {e}")

    def start_streaming(self, n_runs=-1, use_seq = False):
        """
        Streams the currently stored pulse sequence.
        NOTE: Based on previous errors, this version only supports software triggering.
        
        :param n_runs: Number of times to repeat the sequence. Use -1 for infinite.
        """
        if not self.ps:
            self.log.error("Pulse Streamer not connected.")
            return

        if self.sequence_data is None:
            self.log.error("No sequence data is stored. Use upload_sequence() first.")
            return

        try:
            # The stream method can accept a run-length encoded list directly 
            # Since the 'trigger' keyword failed before, we call stream() without it,
            # which defaults to an immediate (software) start. 
            if self._trigger_mode == 'hardware':
                self.log.warn("Your environment does not support the 'trigger' keyword. Defaulting to software trigger.")
            if use_seq and self._seq is not None:
                # If a Sequence object is already created, use it directly
                self.ps.stream(self._seq, n_runs=n_runs)
                self.log.info(f"Pulse streaming started with software trigger for {n_runs} runs.")
            else:
                self.ps.stream(self.sequence_data, n_runs=n_runs)
                self.log.info(f"Pulse streaming started with software trigger for {n_runs} runs.")

            

        except Exception as e:
            self.log.error(f"Failed to start streaming: {e}")

    def stop_streaming(self):
        """
        Stops any running sequence and sets all outputs to zero.
        """
        if not self.ps:
            self.log.error("Pulse Streamer not connected.")
            return
        
        try:
            # Setting a constant output state stops any currently running sequence 
            # OutputState.ZERO sets all channels to 0V 
            self.ps.constant(OutputState.ZERO)
            self.log.info("Streaming stopped. All outputs set to 0V.")
        except Exception as e:
            self.log.error(f"Failed to stop streaming: {e}")