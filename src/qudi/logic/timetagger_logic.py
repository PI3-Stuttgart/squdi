from qtpy import QtCore
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
import os
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase
from qudi.util.mutex import Mutex
import traceback
from qtpy import QtCore
from qudi.util.datastorage import TextDataStorage, ImageFormat
from qudi.util.units import ScaledFloat
from qudi.util.datafitting import FitContainer, FitConfigurationsModel

class TimeTaggerLogic(LogicBase):
    """ Logic module agreggating multiple hardware switches.
    """

    timetagger = Connector(interface='TT')
    queryInterval = ConfigOption('query_interval', 500)
    # Optional CRC veto channel for gated counter (set to None to disable)
    _gated_counter_crc_veto_channel = ConfigOption('gated_counter_crc_veto_channel', default=None, missing='nothing')
    
    sigCounterDataChanged = QtCore.Signal(object)
    sigCorrDataChanged = QtCore.Signal(object)
    sigHistDataChanged = QtCore.Signal(object)
    sigTimeDiffDataChanged = QtCore.Signal(object)
    sigDumpSizeChanged = QtCore.Signal(object)
    sigGatedCounterDataChanged = QtCore.Signal(object)

    sigUpdate = QtCore.Signal()
    sigNewMeasurement = QtCore.Signal()
    sigHistRefresh = QtCore.Signal(float)
    sigUpdateGuiParams=QtCore.Signal()

    sig_fit_updated = QtCore.Signal(str, object)
    _default_fit_configs = (
        {'name'             : 'g2',
        'model'            : 'Autocorrelation',
        'estimator'        : 'Dip',
        'custom_parameters': None},
    )

    def __init__(self, **kwargs):
        """ Create CwaveScannerLogic object with connectors.

          @param dict kwargs: optional parameters
        """
        super().__init__(**kwargs)
        self._fit_config_model = None
        self._fit_container = None
        self._fit_results = None
        self._fit_method = ''
        # locking for thread safety
        self.threadlock = Mutex()
        self.stopRequested = False

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._timetagger = self.timetagger()
        self.file_write = None
        self._constraints = self._timetagger._constraints
        self.stopRequested = False

        self._fit_config_model = FitConfigurationsModel(parent=self)
        self._fit_config_model.load_configs(self._default_fit_configs)
        self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)

        # Timer for Counter data
        self._counter_poll_timer = QtCore.QTimer()
        self._counter_poll_timer.setSingleShot(False)
        self._counter_poll_timer.timeout.connect(self.acquire_data_block, QtCore.Qt.QueuedConnection)
        self._counter_poll_timer.setInterval(50)

        # Timer for Correlation data
        self._corr_poll_timer = QtCore.QTimer()
        self._corr_poll_timer.setSingleShot(False)
        self._corr_poll_timer.timeout.connect(self.acquire_corr_block, QtCore.Qt.QueuedConnection)
        self._corr_poll_timer.setInterval(50)
        
        # Timer for Histogram data
        self._hist_poll_timer = QtCore.QTimer()
        self._hist_poll_timer.setSingleShot(False)
        self._hist_poll_timer.timeout.connect(self.acquire_hist_block, QtCore.Qt.QueuedConnection)
        self._hist_poll_timer.setInterval(50)

        # Timer for Time Difference data
        self._time_diff_poll_timer = QtCore.QTimer()
        self._time_diff_poll_timer.setSingleShot(False)
        self._time_diff_poll_timer.timeout.connect(self.acquire_time_diff_block, QtCore.Qt.QueuedConnection)
        self._time_diff_poll_timer.setInterval(50)

        # Timer for data dump size
        self._dump_poll_timer = QtCore.QTimer()
        self._dump_poll_timer.setSingleShot(False)
        self._dump_poll_timer.timeout.connect(self.acquire_dump_size, QtCore.Qt.QueuedConnection)
        self._dump_poll_timer.setInterval(1000)

        # Timer for Gated Counter data (CRC-filtered)
        self._gated_counter_poll_timer = QtCore.QTimer()
        self._gated_counter_poll_timer.setSingleShot(False)
        self._gated_counter_poll_timer.timeout.connect(self.acquire_gated_counter_block, QtCore.Qt.QueuedConnection)
        self._gated_counter_poll_timer.setInterval(50)

        # Initialize measurement objects and parameters
        self.counter = None
        self.corr = None
        self.hist = None
        self.time_diff = None
        self.gated_counter = None
        self._gated_veto_channel_obj = None
        self.trace_data = {}
        self.counter_params = self._timetagger._counter
        self.hist_params = self._timetagger._hist
        self.corr_params  = self._timetagger._corr
        self.time_diff_params = self._timetagger._time_differences
        self.time_diff_sum_start = self._timetagger.time_diff_sum_start  # ns
        self.time_diff_sum_stop = self._timetagger.time_diff_sum_stop # ns
        
        self.time_diff_ref_start = self._timetagger.time_diff_ref_start # ns
        self.time_diff_ref_stop = self._timetagger.time_diff_ref_stop # ns
        self.time_diff_use_ref = False

        self.dump_channels = [1,2,3, 5, 8, 6]
        self._recorded_data = None
        self.trace_data = None
        self.corr_data = None
        self.hist_data = None
        self.time_diff_data = None
        self.time_diff_data_raw = None
        self.gated_counter_data = None

        self.metadata = {'counter':None, 'hist':None, 'corr':None, 'time_diff':None, 'time_diff_raw':None, 'gated_counter':None}
    
    def on_deactivate(self):
        self._fit_config = self._fit_config_model.dump_configs()
        self._counter_poll_timer.stop()
        self._corr_poll_timer.stop()
        self._hist_poll_timer.stop()
        self._time_diff_poll_timer.stop()
        self._dump_poll_timer.stop()
        self._gated_counter_poll_timer.stop()
        self._counter_poll_timer = None
        self._corr_poll_timer = None
        self._hist_poll_timer = None
        self._time_diff_poll_timer = None
        self._dump_poll_timer = None
        self._gated_counter_poll_timer = None
        self.gated_counter = None
        self._gated_veto_channel_obj = None
    
    def configure_counter(self, data):
        self.counter_freq, self.counter_length, self.counter_channels, self.counter_toggle, self.display_channel = data['counter']

        with self.threadlock:
            self.toggled_channels = []
            self.display_channel_number = 0
            for ch in self.counter_channels:
                if self.counter_channels[ch]:
                    self.toggled_channels.append(ch)
                    if self.display_channel == f'Channel {ch}':
                        self.display_channel_number = ch

            if self.toggled_channels and self.counter_toggle:
                bin_width = int(1/self.counter_freq*1e12)
                n_values = int(self.counter_length*1e12/bin_width)
                self.counter = self._timetagger.counter(channels = self.toggled_channels, bin_width = bin_width, n_values = n_values)
                meta_dict = {'Channels': self.toggled_channels, 'Bin Width': bin_width/1e12, 'Number of Bins': n_values, 'Units': [(ch,'Cps') for ch in self.toggled_channels]}
                self.metadata.update([['counter', meta_dict]])
                self._counter_poll_timer.start()
            else:
                self._counter_poll_timer.stop()
                self.counter = None
    
    def configure_corr(self, data):
        self.corr_bin_width, self.corr_record_length, self.corr_toggled = data['corr']
        
        with self.threadlock:
            if self.corr_toggled:
                self.corr_record_length_ps = self.corr_record_length * 1e6 # convert us to ps
                self.corr = self._timetagger.correlation(channel_start = self._constraints['corr']['channel_start'], 
                                                        channel_stop = self._constraints['corr']['channel_stop'], 
                                                        bin_width = int(self.corr_bin_width), 
                                                        number_of_bins = int(self.corr_record_length_ps/self.corr_bin_width))
        
                meta_dict = {'Channel start': self._constraints['corr']['channel_start'], 'Channel stop': self._constraints['corr']['channel_stop'], 
                        'Bin Width': int(self.corr_bin_width)/1e12, 'Number of Bins': int(self.corr_record_length_ps/self.corr_bin_width), 'Units': [('g2','arb.u.')]}
                self.metadata.update([['corr', meta_dict]])
                self._corr_poll_timer.start()
            else:
                self._corr_poll_timer.stop()
                self.corr = None

    def configure_hist(self, data):
        self.hist_bin_width, self.hist_record_length, self.hist_channel, self.hist_toggled = data['hist']
        
        with self.threadlock:
            if self.hist_toggled:
                self.hist_record_length_ps = self.hist_record_length * 1e6 # convert us to ps
                self.hist = self._timetagger.histogram(channel = self.hist_channel, 
                                                    trigger_channel = self._constraints['hist']['trigger_channel'], 
                                                    bin_width = int(self.hist_bin_width), 
                                                    number_of_bins = int(self.hist_record_length_ps/self.hist_bin_width))

                meta_dict = {'Histogram Channel': self.hist_channel, 'Trigger Channel': self._constraints['hist']['trigger_channel'], 
                            'Bin Width': int(self.hist_bin_width)/1e12, 'Number of Bins': int(self.hist_record_length_ps/self.hist_bin_width), 'Units': [(self.hist_channel,'Counts')]}
                self.metadata.update([['hist', meta_dict]])
                self._hist_poll_timer.start()
            else:
                self._hist_poll_timer.stop()
                self.hist = None

    def configure_time_diff(self, data):
        self.time_diff_bin_width, self.time_diff_record_length, self.time_diff_click_channel, self.time_diff_num_histograms, self.time_diff_toggled, self.time_diff_use_ref = data['time_diff']
        
        with self.threadlock:
            if self.time_diff_toggled:
                self.time_diff_record_length_ps = self.time_diff_record_length * 1e6 # convert us to ps
                start_channel = self._constraints['time_differences']['start_channel']
                next_channel = self._constraints['time_differences']['next_channel']
                number_of_bins = int(self.time_diff_record_length_ps/self.time_diff_bin_width)

                self.time_diff = self._timetagger.time_differences(
                                                    click_channel = self.time_diff_click_channel,
                                                    start_channel = start_channel,
                                                    next_channel = next_channel,
                                                    binwidth = int(self.time_diff_bin_width),
                                                    n_bins = number_of_bins,
                                                    n_histograms = self.time_diff_num_histograms
                                                    )

                meta_dict = {'Click Channel': self.time_diff_click_channel, 
                             'Start Channel': start_channel, 
                             'Next Channel': next_channel,
                             'Bin Width': int(self.time_diff_bin_width)/1e12, 
                             'Number of Bins': number_of_bins, 
                             'Number of Histograms': self.time_diff_num_histograms,
                             'Use Reference': self.time_diff_use_ref,
                             'Units': [('Counts','arb.')]}
                self.metadata.update([['time_diff', meta_dict]])
                
                meta_dict_raw = {'Click Channel': self.time_diff_click_channel, 
                                 'Start Channel': start_channel, 
                                 'Next Channel': next_channel,
                                 'Bin Width': int(self.time_diff_bin_width)/1e12, 
                                 'Number of Bins': number_of_bins, 
                                 'Number of Histograms': self.time_diff_num_histograms,
                                 'Units': [('Events','arb.')]}
                self.metadata.update([['time_diff_raw', meta_dict_raw]])

                self._time_diff_poll_timer.start()
            else:
                self._time_diff_poll_timer.stop()
                self.time_diff = None

    @QtCore.Slot(float, float)
    def set_time_diff_ranges(self, start_ns, stop_ns):
        """Set the start and stop time for processing the time_diff data."""
        with self.threadlock:
            self.time_diff_sum_start = self._timetagger.time_diff_sum_start = start_ns
            self.time_diff_sum_stop = self._timetagger.time_diff_sum_stop = stop_ns
            
    @QtCore.Slot(float, float)
    def set_time_diff_ref_ranges(self, start_ns, stop_ns):
        """Set the start and stop time for the time_diff reference data."""
        with self.threadlock:
            self.time_diff_ref_start = self._timetagger.time_diff_ref_start = start_ns
            self.time_diff_ref_stop = self._timetagger.time_diff_ref_stop = stop_ns

    def acquire_data_block(self):
        """
        This method gets the available counter data from the hardware.
        """
        with self.threadlock:
            if self.counter is None:
                return
            self.trace_data = {}
            self.trace_data_avg = {}
            raw = self.counter.getDataNormalized()
            index = self.counter.getIndex()/1e12
            w = int(round(len(index)/50)) if len(index) > 50 else 1
            counter_sum = np.zeros_like(raw[0])
            for i, ch in enumerate(self.toggled_channels):
                self.trace_data[ch] = (index, raw[i])
                avg = np.convolve(raw[i], np.ones(w), 'same') / w
                self.trace_data_avg[ch] = (index[w:-w], avg[w:-w])
                
                if self.display_channel_number==0:
                    counter_sum += raw[i]
                elif self.display_channel_number==ch:
                    counter_sum += raw[i]

            self.sigCounterDataChanged.emit({'trace_data':self.trace_data, 'trace_data_avg':self.trace_data_avg,'sum': np.mean(np.nan_to_num(counter_sum[-w:-1]))})
        return
    
    def acquire_corr_block(self):
        """
        This method gets the available correlation data from the hardware.
        """
        with self.threadlock:
            if self.corr is None:
                return
            raw = self.corr.getDataNormalized()
            index = self.corr.getIndex()/1e12
            self.corr_data = (index, np.nan_to_num(raw))
            self.sigCorrDataChanged.emit({'corr_data':self.corr_data})
        return   
    
    def acquire_hist_block(self):
        """
        This method gets the available histogram data from the hardware.
        """
        with self.threadlock:
            if self.hist is None:
                return
            raw = self.hist.getData()
            index = self.hist.getIndex()/1e12
            self.hist_data = (index, np.nan_to_num(raw))
            self.sigHistDataChanged.emit({'hist_data':self.hist_data})
        return
    
    def acquire_time_diff_block(self):
        """
        This method gets and processes the time difference data.
        """
        with self.threadlock:
            if self.time_diff is None:
                return
            
            raw_data_2d = self.time_diff.getData()
            time_index_ps = self.time_diff.getIndex()  # in picoseconds

            # --- Raw Data Plot (Sum over all histograms) ---
            summed_raw_data = np.sum(raw_data_2d, axis=0) if raw_data_2d.ndim > 1 else raw_data_2d
            index_s = time_index_ps / 1e12 # Convert to seconds for plotting
            self.time_diff_data_raw = (index_s, np.nan_to_num(summed_raw_data))

            # --- Processed Data Plot (Sum over time window for each histogram) ---
            if raw_data_2d.ndim < 2:
                self.time_diff_data = (np.array([]), np.array([]))
            else:
                # Signal window
                start_ps = self.time_diff_sum_start * 1000
                stop_ps = self.time_diff_sum_stop * 1000
                idx_start = np.searchsorted(time_index_ps, start_ps, side='left')
                idx_stop = np.searchsorted(time_index_ps, stop_ps, side='right')
                
                if idx_start >= raw_data_2d.shape[1]:
                    processed_counts = np.zeros(raw_data_2d.shape[0])
                else:
                    idx_stop = min(idx_stop, raw_data_2d.shape[1])
                    signal_counts = np.sum(raw_data_2d[:, idx_start:idx_stop], axis=1)

                    if self.time_diff_use_ref:
                        # Reference window
                        ref_start_ps = self.time_diff_ref_start * 1000
                        ref_stop_ps = self.time_diff_ref_stop * 1000
                        idx_ref_start = np.searchsorted(time_index_ps, ref_start_ps, side='left')
                        idx_ref_stop = np.searchsorted(time_index_ps, ref_stop_ps, side='right')
                        
                        idx_ref_stop = min(idx_ref_stop, raw_data_2d.shape[1])
                        ref_counts_in_window = np.sum(raw_data_2d[:, idx_ref_start:idx_ref_stop], axis=1)
                        
                        # Calculate the mean of the reference counts over all histograms
                        mean_ref_counts = np.mean(ref_counts_in_window)
                        
                        # Divide signal by mean reference, handle division by zero
                        if mean_ref_counts > 0:
                            processed_counts = signal_counts / mean_ref_counts
                        else:
                            processed_counts = np.zeros_like(signal_counts, dtype=float)
                    else:
                        # If not using reference, just use the raw signal counts
                        processed_counts = signal_counts

                processed_x_axis = np.arange(processed_counts.shape[0])
                self.time_diff_data = (processed_x_axis, np.nan_to_num(processed_counts))

            self.sigTimeDiffDataChanged.emit({
                'time_diff_data': self.time_diff_data, 
                'time_diff_data_raw': self.time_diff_data_raw
            })
        return

    def configure_gated_counter(self, data):
        """Start or stop a CRC-gated counter using the configured veto channel."""
        freq, length, channels, toggle = data['gated_counter']
        veto_ch = self._gated_counter_crc_veto_channel
        if veto_ch is None:
            self.log.warning('No gated_counter_crc_veto_channel configured, cannot start gated counter.')
            return

        with self.threadlock:
            self._gated_counter_poll_timer.stop()
            self.gated_counter = None
            self._gated_veto_channel_obj = None

            self.gated_toggled_channels = [ch for ch, enabled in channels.items() if enabled]
            self.gated_counter_freq = freq
            self.gated_counter_length = length

            if self.gated_toggled_channels and toggle:
                bin_width = int(1 / freq * 1e12)
                n_values = int(length * 1e12 / bin_width)
                try:
                    from TimeTagger import GatedChannel, GatedChannelInitial
                    # Gate is ACTIVE HIGH: CRC pulls veto line HIGH during bad state.
                    # We want to COUNT when veto is LOW (charge is resonant / OK).
                    # Gate opens on FALLING edge (-veto_ch) and closes on RISING edge (+veto_ch).
                    self._gated_veto_channel_obj = GatedChannel(
                        tagger=self._timetagger.tagger,
                        input_channel=self.gated_toggled_channels[0],
                        gate_start_channel=-int(veto_ch),
                        gate_stop_channel=int(veto_ch),
                        initial=GatedChannelInitial.Open
                    )
                    gated_ch = self._gated_veto_channel_obj.getChannel()
                    self.gated_counter = self._timetagger.counter(
                        channels=[gated_ch], bin_width=bin_width, n_values=n_values
                    )
                    meta_dict = {'Channels': self.gated_toggled_channels, 'Veto Channel': veto_ch,
                                 'Bin Width': bin_width / 1e12, 'Number of Bins': n_values,
                                 'Units': [(self.gated_toggled_channels[0], 'Cps')]}
                    self.metadata['gated_counter'] = meta_dict
                    self._gated_counter_poll_timer.start()
                except Exception:
                    self.log.exception('Failed to configure gated counter.')
                    self.gated_counter = None
                    self._gated_veto_channel_obj = None

    def acquire_gated_counter_block(self):
        """Poll the gated counter and emit the data."""
        with self.threadlock:
            if self.gated_counter is None:
                return
            raw = self.gated_counter.getDataNormalized()
            index = self.gated_counter.getIndex() / 1e12
            w = max(1, int(round(len(index) / 50)))
            y = raw[0] if raw.ndim > 1 else raw
            avg = np.convolve(y, np.ones(w), 'same') / w
            count_now = float(np.mean(np.nan_to_num(y[-w:-1]))) if len(y) > w else 0.0
            self.gated_counter_data = (index, np.nan_to_num(y))
            self.sigGatedCounterDataChanged.emit({
                'trace': self.gated_counter_data,
                'trace_avg': (index[w:-w], avg[w:-w]),
                'sum': count_now
            })

    @property
    def gated_counter_available(self):
        """Returns True if a CRC veto channel is configured."""
        return self._gated_counter_crc_veto_channel is not None

    @QtCore.Slot(bool, str, str)
    def dump_data(self, do_dump, name_tag, save_path):
        if do_dump:
            if not os.path.isdir(save_path):
                self.log.error(f"Dump path does not exist: {save_path}")
                self._dump_poll_timer.stop()
                return

            self._dump_poll_timer.start()
            self.file_write = self._timetagger.write_into_file(os.path.join(save_path, 
                                                            f'{name_tag}.ttbin'),
                                                            channels=self.dump_channels)
        else:
            self._dump_poll_timer.stop()
            if self.file_write is not None:
                self.file_write.stop()
                self.file_write = None
            

    def acquire_dump_size(self):
        fw = self.file_write
        memory_used = fw.getTotalSize() if fw is not None else 0
        self.sigDumpSizeChanged.emit(memory_used)   

    @QtCore.Slot()
    def _save_recorded_data(self, to_file=True, name_tag='', save_figure=True, save_type='counter', save_path='Default'):
        """ Save the data and writes it to a file.
        """
        if save_type is None:
            self.log.error('No save type selected.')
            return
            
        data_to_save = {'counter': self.trace_data, 'corr': self.corr_data, 'hist': self.hist_data, 'time_diff': self.time_diff_data, 'time_diff_raw': self.time_diff_data_raw}.get(save_type)
        
        if data_to_save is None:
            self.log.error(f'No data for type "{save_type}" has been recorded. Save to file failed.')
            return
        
        if to_file:
            parameters = self.metadata[save_type]
            if parameters is None:
                self.log.error(f"Metadata for '{save_type}' not found. Cannot save.")
                return

            if save_type == 'counter':
                if not self.toggled_channels:
                    self.log.error("No counter channels are active. Cannot save.")
                    return
                # Get x_data from the first toggled channel (it's the same for all)
                x_data = data_to_save[self.toggled_channels[0]][0]
                # Get all y_data series
                y_data_list = [np.nan_to_num(data_to_save[ch][1]) for ch in self.toggled_channels]
                # Combine for saving: x column followed by all y columns
                data_to_store_in_file = np.vstack([x_data] + y_data_list).transpose()
                
                header = ['Time (s)'] + [f'{ch} ({unit})' for ch, unit in parameters['Units']]
                column_formats = ['.8f'] * (len(self.toggled_channels) + 1)
                y_data_for_plot = y_data_list[0] # Just plot the first channel for the figure
                x_label = 'Time (s)'
            else: # For all other data types (corr, hist, time_diff, time_diff_raw)
                x_data = data_to_save[0]
                y_data = np.nan_to_num(data_to_save[1])
                # Combine for saving: x column and y column
                data_to_store_in_file = np.vstack((x_data, y_data)).transpose()

                header = ['Time (s)'] + [f'{ch} ({unit})' for ch, unit in parameters['Units']]
                if save_type == 'time_diff':
                    header[0] = 'Histogram Number' # Special case for time_diff x-axis label
                
                column_formats = ['.8f'] * 2
                y_data_for_plot = y_data
                x_label = header[0]

            if data_to_store_in_file.size == 0:
                self.log.error('No data has been recorded. Save to file failed.')
                return

            filelabel = f'{save_type}_data_trace_{name_tag}' if name_tag else f'{save_type}_data_trace'
            filepath = save_path if save_path != 'Default' else self.module_default_data_dir 
            y_unit = parameters['Units'][0][1]

            fig = self._draw_figure(x_data, y_data_for_plot, y_unit, x_label) if save_figure else None
            
            data_storage = TextDataStorage(root_dir=filepath,
                               comments='# ', 
                               delimiter='\t',
                               file_extension='.dat',
                               column_formats=column_formats,
                               include_global_metadata=True,
                               image_format=ImageFormat.PNG)

            file_path, _, _ = data_storage.save_data(data_to_store_in_file, 
                                                     timestamp=dt.datetime.now(), 
                                                     metadata=parameters, 
                                                     notes='',
                                                     nametag=filelabel,
                                                     column_headers=header,
                                                     column_dtypes=[float] * len(header))
            if fig:
                data_storage.save_thumbnail(fig, file_path.rsplit('.', 1)[0])
            self.log.info(f'Time series saved to: {file_path}')

    def _draw_figure(self, x_data, y_data, y_unit, x_label):
        """ Draw figure to save with data file.
        """
        if y_data.ndim > 1 and y_data.shape[0] > 1:
            y_data_to_plot = y_data[0,:] # Just plot the first trace if multiple exist
        else:
            y_data_to_plot = y_data.flatten()

        if y_data_to_plot.size == 0:
            return None
            
        max_abs_value = ScaledFloat(max(y_data_to_plot.max(), np.abs(y_data_to_plot.min())))
        fig, ax = plt.subplots()
        scaled_data = y_data_to_plot / max_abs_value.scale_val if max_abs_value.scale else y_data_to_plot
        ax.plot(x_data, scaled_data, linestyle='-', linewidth=1)
        ax.set_xlabel(x_label)
        ax.set_ylabel(f'Signal ({max_abs_value.scale}{y_unit})')
        plt.tight_layout()
        return fig
    
    ################
    # Fitting things

    @property
    def fit_config_model(self):
        return self._fit_config_model

    @property
    def fit_container(self):
        return self._fit_container

    def do_fit(self, fit_method):
        if fit_method == 'No Fit':
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        if self.corr_data is None:
            self.log.error('No data to fit.')
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        x_data, y_data = self.corr_data
        
        try:
            self._fit_method, self._fit_results = self._fit_container.fit_data(fit_method, x_data, y_data)
        except:
            self.log.exception(f'Data fitting failed:\n{traceback.format_exc()}')
            self.sig_fit_updated.emit('No Fit', None)
            return 'No Fit', None

        self.sig_fit_updated.emit(self._fit_method, self._fit_results)
        return self._fit_method, self._fit_results

    @property
    def fit_results(self):
        return self._fit_results

    @property
    def fit_method(self):
        return self._fit_method
