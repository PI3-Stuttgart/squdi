from __future__ import absolute_import, division, print_function

__metaclass__ = type

# import misc


import logging
import copy
import sys
import threading
import time
import traceback

# from hardware.Keysight_AWG_M8190.pym8190a import MultiChSeq as MCAS
# from hardware.Keysight_AWG_M8190.pym8190a import start_awgs as start_awgs # here we dont have it....
# import logic.qudip_enhanced.qtgui.gui_helpers
from numbers import Number

import numpy as np

# from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
# from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar
# from matplotlib.figure import Figure
import PySide2.QtCore
from PySide2 import QtCore
from PySide2.QtCore import Signal as pyqtSignal

# import pylab as pb
from qudi.core.connector import Connector

import qudi.logic.misc as misc
from qudi.hardware.swabian_instruments.timetagger_api import TT as TT
from qudi.logic import Analysis as Analysis

# from core.util.network import netobtain
from qudi.logic.generic_logic import GenericLogic


class GatedCounter(GenericLogic):
    ##declare connections
    # Timetagger
    # fastcounter = Connector(interface='TimeTaggerInterface')
    # add possible signals here
    # Needed a connection to the queue as well... connection to mcas?
    fastcounter = Connector(interface="TT", name="fastcounter")
    mcas_holder = Connector(interface="McasDictHolderInterface")
    sigHistogramUpdated = QtCore.Signal()
    sigMeasurementFinished = QtCore.Signal()
    clear_plot_signal = PySide2.QtCore.Signal(int)
    update_plot_signal = PySide2.QtCore.Signal(list, list)
    sigTraceUpdated = pyqtSignal(list, list)
    readout_interval = misc.ret_property_typecheck("readout_interval", Number)
    progress = misc.ret_property_typecheck("progress", int)

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.log.debug("The following configuration was found.")
        for key in config.keys():
            self.log.debug("{0}: {1}".format(key, config[key]))
        self.readout_interval = 1e6  # DO NOT SET BELOW 0.2, plotting runs in main loop, and takes around 0.15, which then makes the console annoying to work with.
        self.readout_duration = 10e6
        self.n_values = 10
        self.trace = Analysis.Trace()
        self.traces = {}
        self.analyze_trace_during_experiment = True  # TODO make it False compatible.
        self.title = "Gated_counter"
        self.gated_counters = {}
        self.gated_counter_data_by_channel = {}
        self.trace_rep_by_channel = {}
        self.progress_by_channel = {}
        self.mixed_trace = None
        self.active_counting_channels = []
        self.counting_channels = None

        # if title is not None:
        #    self.update_window_title(title)
        # self.tim
        self.raw_clicks_processing = False
        self.raw_clicks_processing_function = None
        self.ZPL_counter = False
        self.use_multiple_channels = True

    @staticmethod
    def normalize_counting_channels(channels):
        """Return a de-duplicated list of TimeTagger click channels."""
        if channels is None:
            return []
        if isinstance(channels, np.ndarray):
            channels = channels.tolist()
        if isinstance(channels, (list, tuple, set)):
            out = []
            for channel in channels:
                out.extend(GatedCounter.normalize_counting_channels(channel))
        else:
            out = [int(channels)]

        unique_channels = []
        for channel in out:
            if channel not in unique_channels:
                unique_channels.append(channel)
        return unique_channels

    def set_counting_channels(self, channels):
        """Configure the TimeTagger click channels used for the next acquisition."""
        channels = self.normalize_counting_channels(channels)
        if len(channels) == 0:
            raise ValueError("At least one counting channel must be configured.")

        self.counting_channels = channels
        self.count_between_markers_click_channels = channels
        self.active_counting_channels = channels

        if hasattr(self, "_fast_counter_device") and hasattr(
            self._fast_counter_device, "_count_between_markers"
        ):
            self._fast_counter_device._count_between_markers["click_channel"] = channels[0]
        return channels

    def analyze_sequence_counting_channels(self):
        """Return APD channels requested by optional 7th analyze-sequence entries."""
        channels = []
        analyze_sequence = getattr(self.trace, "analyze_sequence", None)
        if analyze_sequence is None:
            return channels
        for step in analyze_sequence:
            if len(step) == 7:
                channels.extend(self.normalize_counting_channels(step[6]))
        return self.normalize_counting_channels(channels)

    def uses_mixed_analysis_channels(self):
        """Return whether any analyze-sequence step selects a specific APD channel."""
        return len(self.analyze_sequence_counting_channels()) > 0

    def get_counting_channels(self):
        """Return configured channels, falling back to the TimeTagger default."""
        channels = self.normalize_counting_channels(self.counting_channels)
        plot_channels = self.analyze_sequence_counting_channels()
        if len(channels) == 0 and len(plot_channels) > 0:
            channels = plot_channels
        if len(channels) == 0 and hasattr(self, "count_between_markers_click_channels"):
            channels = self.normalize_counting_channels(self.count_between_markers_click_channels)
        if len(channels) == 0 and hasattr(self, "_fast_counter_device"):
            channels = self.normalize_counting_channels(
                self._fast_counter_device._count_between_markers.get("click_channel")
            )
        if len(channels) == 0:
            raise ValueError("No gated-counter counting channel is configured.")
        for channel in plot_channels:
            if channel not in channels:
                channels.append(channel)
        return self.set_counting_channels(channels)

    @property
    def primary_counting_channel(self):
        channels = self.active_counting_channels or self.get_counting_channels()
        return channels[0]

    def _new_trace_like_primary(self):
        trace = Analysis.Trace()
        for key in [
            "analyze_type",
            "analyze_sequence",
            "binning_factor",
            "average_results",
            "number_of_simultaneous_measurements",
            "consecutive_valid_result_numbers",
        ]:
            setattr(trace, key, copy.deepcopy(getattr(self.trace, key)))
        return trace

    def _prepare_traces_for_channels(self, channels):
        self.traces = {}
        for idx, channel in enumerate(channels):
            self.traces[channel] = self.trace if idx == 0 else self._new_trace_like_primary()
        self.trace = self.traces[channels[0]]

    def _iter_gated_counters(self):
        if len(self.gated_counters) > 0:
            return list(self.gated_counters.items())
        if not hasattr(self, "_fast_counter_device"):
            return []
        if hasattr(self._fast_counter_device, "gated_counter_countbetweenmarkers"):
            counter = self._fast_counter_device.gated_counter_countbetweenmarkers
            if counter is not None:
                return [(self.primary_counting_channel, counter)]
        return []

    def plotting_channel_for_step(self, step):
        """Return the channel whose trace should be used to plot this sequence step."""
        if len(step) == 7:
            return int(step[6])
        return self.primary_counting_channel

    def build_mixed_analysis_trace(self):
        """Build the canonical analysis trace from per-step APD channel selections."""
        if not self.uses_mixed_analysis_channels():
            self.mixed_trace = None
            self.trace = self.traces[self.primary_counting_channel]
            return self.trace

        mixed_trace = self._new_trace_like_primary()
        reference_trace = self.traces[self.primary_counting_channel]
        mixed_df = reference_trace.df.copy()

        for idx, step in enumerate(mixed_trace.analyze_sequence):
            channel = self.plotting_channel_for_step(step)
            if channel not in self.traces:
                raise KeyError(
                    "Analyze-sequence step {} requests APD channel {}, but no gated "
                    "counter trace exists for that channel.".format(idx, channel)
                )

            source_df = self.traces[channel].df
            step_mask = mixed_df.step == idx
            mixed_df.loc[step_mask, "n"] = source_df.loc[source_df.step == idx, "n"].values

        mixed_trace.trace = np.array(mixed_df.n)
        self.mixed_trace = mixed_trace
        self.trace = mixed_trace
        return mixed_trace

    def on_activate(self):
        """Initialisation performed during activation of the module."""
        self._fast_counter_device: TT = self.fastcounter()  # FIXME
        # self._currentmeasurementlogic: CurrentMeasurementLogic = self.currentmeasurementlogic()
        # self._mcas_dict = self.mcas_holder()
        # self._pulse_generator_device = self.pulsegenerator()
        # Maybe replace with the mcas holder?
        # self._save_logic = self.savelogic() #This is done in nuclear ops.
        # self._fit_logic = self.fitlogic() #-This is nice, we can keep it
        # self._traceanalysis_logic = self.traceanalysislogic1() # Done with Analysis class.
        # self.hist_data = None
        # self.trace = None
        # self.sigMeasurementFinished.connect(self.ssr_measurement_analysis)# is it?
        self._gui = None

    def on_deactivate(self):
        """Deinitialisation performed during deactivation of the module.

        @param object e: Event class object from Fysom. A more detailed
                         explanation can be found in method activation.
        """
        return

    # =========================================================================
    #                           Raw Data Analysis
    # =========================================================================

    @property
    def points(self):
        if hasattr(self, "n_values"):
            return self.n_values / sum([step[3] for step in self.trace.analyze_sequence])
        return self._points

    @points.setter
    def points(self, val):
        self._points = misc.check_type(val, "points", int)

    @property
    def n_values(self):
        return self._n_values

    @n_values.setter
    def n_values(self, val):
        self._n_values = val

    def set_n_values(self, mcas, sm, n_values=None, analyze_sequence=None):
        """
        mcas: sequence
        sm: number of simulatanious measurements
        analyze_sequence: TBU
        """
        # print('gated counter readout_duration set_n_values', self.readout_duration)
        analyze_sequence = (
            self.trace.analyze_sequence if analyze_sequence is None else analyze_sequence
        )
        # print('analyze sequence in gated counter logic: ',analyze_sequence)
        # for step in analyze_sequence:
        #     print(step)
        if n_values is None:
            self.n_values = int(
                self.readout_duration
                / (mcas.length_mus / sm)
                * sum([step[3] for step in analyze_sequence])
            )
        else:
            self.n_values = n_values

    def read_trace(self):
        print("GC:read_trace")
        self.gated_counter_data_by_channel = {}
        for channel, counter in self._iter_gated_counters():
            self.gated_counter_data_by_channel[channel] = counter.getData()

        self.gated_counter_data = self.gated_counter_data_by_channel[
            self.primary_counting_channel
        ]  # legacy single-channel alias
        if self.ZPL_counter:
            print("ZPL_counter in gated_counter_logic")
            if self.raw_clicks_processing:
                counter_name = "raw_zpl"
                # print('init raw clicks processing name: ', counter_name)
                data = self._fast_counter_device.get_stream_data(
                    counter_name=counter_name, kwargs=[]
                )
                # data = datadict['data']

                # send_time = datadict['time_before']
                # print("Send time was: {}".format(send_time))
                # print("Time now: {}".format(time.time()))
                # print('11 tt:', time.time() - t0)

                if self.raw_clicks_processing_function is not None:
                    self.raw_clicks_processing_function(
                        data, delays=self.start_trigger_delay_ps_list, windows=self.window_ps_list
                    )
                    # print('12 tt:', time.time() - t0)

                else:
                    raise Exception("self.raw_clicks_processing_function is None")

                # print('21 tt:', time.time() - t0)
                # if self.two_zpl_apd:
                #     # trace_name = 'zpl_2_counter_data_{i}_{j}'.format(i=i, j=j)
                #     counter_name = 'raw_2_zpl'
                #     data = self._fast_counter_device.get_stream_data(counter_name=counter_name, kwargs=[])
                #     if self.raw_clicks_processing_function is not None:
                #         self.raw_clicks_processing_function(data,
                #                                             delays=self.start_trigger_delay_ps_list,
                #                                             windows=self.window_ps_list
                #                                             )
                #
                #     else:
                #         raise Exception('self.raw_clicks_processing_function is None')
                # print('22 tt:', time.time() - t0)

            else:
                for i, start_trigger_delay_ps in enumerate(self.start_trigger_delay_ps_list):
                    for j, window_ps in enumerate(self.window_ps_list):
                        trace_name = "zpl_counter_data_{i}_{j}".format(i=i, j=j)
                        counter_name = "gated_cbm_zpl_{i}_{j}".format(i=i, j=j)

                        # self._fast_counter_device.gated_counter_countbetweenmarkers.sync()
                        zpl_counter_data = getattr(
                            self._fast_counter_device, counter_name
                        ).getData()  # .astype(np.int64)
                        # getattr(self._fast_counter_device, counter_name).sync()
                        setattr(self, trace_name, zpl_counter_data)
                        # print('21 tt:', time.time() - t0)
                        if self.two_zpl_apd:
                            trace_name = "zpl_2_counter_data_{i}_{j}".format(i=i, j=j)
                            counter_name = "gated_cbm_2_zpl_{i}_{j}".format(i=i, j=j)
                            # self._fast_counter_device.gated_counter_countbetweenmarkers.sync()
                            zpl_counter_data = getattr(
                                self._fast_counter_device, counter_name
                            ).getData()  # .astype(np.int64)
                            # getattr(self._fast_counter_device, counter_name).sync()
                            setattr(self, trace_name, zpl_counter_data)

        self.set_progress()
        # UNFUG
        if self.analyze_trace_during_experiment:
            print("analyze trace during measurement in gated_counter_logic")
            self.trace_rep_by_channel = {}
            for channel, gated_counter_data in self.gated_counter_data_by_channel.items():
                trace = self.traces[channel]
                progress = self.progress_by_channel.get(channel, self.progress)
                trace_rep = Analysis.TraceRep(
                    trace=gated_counter_data[:progress],
                    analyze_sequence=trace.analyze_sequence,
                    number_of_simultaneous_measurements=trace.number_of_simultaneous_measurements,
                )
                self.trace_rep_by_channel[channel] = trace_rep
                trace.trace = np.array(
                    trace_rep.df.groupby(["run", "sm", "step", "memory"])
                    .agg({"n": np.sum})
                    .reset_index()
                    .n
                )
            self.trace_rep = self.trace_rep_by_channel[self.primary_counting_channel]
            self.build_mixed_analysis_trace()
            self.update_plot_data()

    def clear_timetaggers(self):
        for _, counter in self._iter_gated_counters():
            counter.clear()
        if self.ZPL_counter:
            if self.raw_clicks_processing:
                counter_name = "raw_zpl"
                # getattr(self._fast_counter_device, counter_name).clear()
                # self._fast_counter_device.kill_stream(counter_name=counter_name, kwargs=[])
                # if self.two_zpl_apd:
                #     counter_name = 'raw_2_zpl'
                #     self._fast_counter_device.kill_stream(counter_name=counter_name, kwargs=[])

            else:
                for i, start_trigger_delay_ps in enumerate(self.start_trigger_delay_ps_list):
                    for j, window_ps in enumerate(self.window_ps_list):
                        counter_name = "gated_cbm_zpl_{i}_{j}".format(i=i, j=j)
                        # getattr(self._fast_counter_device, counter_name).clear()

                        if self.two_zpl_apd:
                            counter_name = "gated_cbm_2_zpl_{i}_{j}".format(i=i, j=j)
                            # getattr(self._fast_counter_device, counter_name).clear()

    def get_counting_samples(self):
        return self.n_values

    def get_count_length(self):
        if self.n_values is not None:
            return self.n_values
        else:
            return 1
        # print('to be implemented')

    def stop_timetaggers(self):

        for _, counter in self._iter_gated_counters():
            counter.stop()
        if self.ZPL_counter:
            # print('Gated counter stop TT ZPL_counter')

            if self.raw_clicks_processing:
                # print('Gated counter stop TT raw_clicks_processing')

                counter_name = "raw_zpl"
                # self._fast_counter_device.stop_stream(counter_name=counter_name, kwargs=[])
                # if self.two_zpl_apd:
                #     # print('Gated counter stop TT two_zpl_apd')
                #
                #     counter_name = 'raw_2_zpl'
                #     self._fast_counter_device.stop_stream(counter_name=counter_name, kwargs=[])
            else:
                # print('Gated counter stop TT NOT== raw_clicks_processing')

                for i, start_trigger_delay_ps in enumerate(self.start_trigger_delay_ps_list):
                    for j, window_ps in enumerate(self.window_ps_list):
                        counter_name = "gated_cbm_zpl_{i}_{j}".format(i=i, j=j)
                        getattr(self._fast_counter_device, counter_name).stop()

                        if self.two_zpl_apd:
                            counter_name = "gated_cbm_2_zpl_{i}_{j}".format(i=i, j=j)
                            getattr(self._fast_counter_device, counter_name).stop()

    def start_timetaggers(self):
        for _, counter in self._iter_gated_counters():
            counter.start()
        if self.ZPL_counter:
            if self.raw_clicks_processing:
                counter_name = "raw_zpl"
                self._fast_counter_device.start_stream(counter_name=counter_name, kwargs=[])
                # if self.two_zpl_apd:
                #     counter_name = 'raw_2_zpl'
                #     self._fast_counter_device.start_stream(counter_name=counter_name, kwargs=[])
            else:
                for i, start_trigger_delay_ps in enumerate(self.start_trigger_delay_ps_list):
                    for j, window_ps in enumerate(self.window_ps_list):
                        counter_name = "gated_cbm_zpl_{i}_{j}".format(i=i, j=j)
                        getattr(self._fast_counter_device, counter_name).start()

                        if self.two_zpl_apd:
                            counter_name = "gated_cbm_2_zpl_{i}_{j}".format(i=i, j=j)
                            getattr(self._fast_counter_device, counter_name).start()

    def count(
        self,
        abort,
        mcas,
        ch_dict=None,
        turn_off_awgs=True,
        start_trigger_delay_ps_list=None,
        window_ps_list=None,
        raw_clicks_processing=False,
        two_zpl_apd=False,
        raw_clicks_processing_channels=[0, 1, 2, 3, 4, 5, 6, 7],
        hashed=False,
        seq_name="",
    ):
        """
        Main function which collects the raw clicks in the gated counter.
        :param abort:
        :param ch_dict: default None, This is the AWG ch dict, used for the MCAS. Here we can use it in principle.
        :param turn_off_awgs:
        :param start_trigger_delay_ps_list:
        :param window_ps_list:
        :param raw_clicks_processing:
        :param two_zpl_apd:
        :param raw_clicks_processing_channels:
        :param hashed:
        :param seq_name:
        :return:
        """
        self.start_trigger_delay_ps_list = start_trigger_delay_ps_list
        self.window_ps_list = window_ps_list  # This is needed for the ps for time filtering.
        self.two_zpl_apd = two_zpl_apd
        self.raw_clicks_processing = raw_clicks_processing
        self.raw_clicks_processing_channels = raw_clicks_processing_channels
        number_of_subtraces = 1  # fixme, later put a len of analyze sequence

        print("GC: count started")
        if hasattr(self, "_gui"):
            self.clear_plot_signal.emit(number_of_subtraces)
        try:
            self.set_counter()  # Prepares the gated counter to collect the data.
            # if not self._awg.debug_mode: # Actually start the AWG...
            print("start awgs in gated_counter_logic via mcas.run(), which is qm.execute(program)")
            # shouldnt it be started via mcas_dict['"sequence_name"].run()
            # How does awgs know which sequence to run?

            mcas.run()
            self.progress = 0
            i = 0
            while True:
                # print('stuck in Ready for data...')
                if abort.is_set():
                    break
                # print('Gated counter is falling asleep for ',self.readout_duration / 1e6)
                # time.sleep(self.readout_duration / 1e6)
                # break
                ready = all(counter.ready() for _, counter in self._iter_gated_counters())

                if i % 2 == 0:
                    # why get counts here already? its done at the end of measurement when self.read_trace() is called
                    # seems like read_trace() is not doing much...
                    dat = self.gated_counters[self.primary_counting_channel].getData()
                    self.gated_counter_data_by_channel[
                        self.primary_counting_channel
                    ] = dat
                    self.gated_counter_data = dat
                    self.set_progress()
                    # self.read_trace()
                    # self.update_plot()
                    # self.set_progress()
                    print(
                        "-----------------------------------------------------\n",
                        self.progress,
                        len(dat),
                    )
                i += 1
                if ready:
                    # print(self._fast_counter_device.gated_counter_countbetweenmarkers.getData())
                    break
                else:
                    time.sleep(0.1)
                    # QtTest.QTest.qSleep(100)
            self.read_trace()
            self.update_plot()

        except Exception as e:
            print(e)
            abort.set()
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)
        finally:
            if turn_off_awgs:
                mcas.stop()

            self.stop_timetaggers()

            # self._fast_counter_device.gated_counter_countbetweenmarkers.stop()
            self.state = "idle"

    def set_counter(self):

        self.log.info("GC:set_counter")
        self.ZPL_counter = False

        ## Needs to be adjusted tohas the qudi gated counter #TODO
        setup_errors = []

        def f():
            try:
                channels = self.get_counting_channels()
                self._prepare_traces_for_channels(channels)
                self.gated_counters = {}
                self.gated_counter_data_by_channel = {}
                self.trace_rep_by_channel = {}
                self.progress_by_channel = {}
                self.mixed_trace = None
                nlp_per_point = sum([step[3] for step in self.trace.analyze_sequence])

                # TODO redo the interfaces . Init counter to gated counter now, or make it inside the TT class?
                n_vals = (
                    self.n_values - self.n_values % nlp_per_point
                    if hasattr(self, "_n_values")
                    else nlp_per_point * self.points
                )
                self.log.info(f"GC:set_counter:nvals {n_vals}")
                self._fast_counter_device.count_between_markers_nops(n_values=n_vals)
                self.gated_counters[channels[0]] = (
                    self._fast_counter_device.gated_counter_countbetweenmarkers
                )

                if self.use_multiple_channels and len(channels) > 1:
                    for click_channel in channels[1:]:
                        curr_gated_counter = self._fast_counter_device.count_between_markers(
                            click_channel,
                            self._fast_counter_device._count_between_markers["begin_channel"],
                            self._fast_counter_device._count_between_markers["end_channel"],
                            n_vals,
                        )
                        self.gated_counters[click_channel] = curr_gated_counter
            except Exception as exc:
                setup_errors.append(exc)
                self.log.error(
                    "Setting up gated counter failed:\n%s", traceback.format_exc()
                )
                raise

            # ZPL STUF
            # if False: # self.raw_clicks_processing:
            #     name = 'raw_zpl'
            #     n_bins = self.n_values - self.n_values % nlp_per_point if hasattr(self,
            #                                                                       '_n_values') else nlp_per_point * self.points,
            #
            #     # print('n_bins ',n_bins)
            #     kwargs = dict(n_bins = n_bins[0]*len(self.raw_clicks_processing_channels),
            #                   channels=self.raw_clicks_processing_channels)
            #     # print('kwargs["n_bins"] ',kwargs["n_bins"])
            #
            #     self._fast_counter_device.create_stream(counter_name=name, kwargs=kwargs)
            #
            #     # if self.two_zpl_apd:
            #     #     name = 'raw_2_zpl'
            #     #     self._fast_counter_device.create_stream(counter_name=name, kwargs=kwargs)
            #
            #
            #     self.ZPL_counter = True

            # else:
            #     for i, start_trigger_delay_ps in enumerate(self.start_trigger_delay_ps_list):
            #         for j, window_ps in enumerate(self.window_ps_list):
            #             if (start_trigger_delay_ps is not None) and (window_ps is not None):
            #
            #                 name = 'gated_cbm_zpl_{i}_{j}'.format(i=i, j=j)
            #                 self._fast_counter_device.init_counter(
            #                     name,
            #                     n_values=self.n_values - self.n_values % nlp_per_point if hasattr(self,
            #                                                                                       '_n_values') else nlp_per_point * self.points,
            #                     delay_ps=start_trigger_delay_ps,
            #                     window_ps=window_ps
            #                 )
            #
            #                 if self.two_zpl_apd:
            #                     name = 'gated_cbm_2_zpl_{i}_{j}'.format(i=i, j=j)
            #                     self._fast_counter_device.init_counter(
            #                         name,
            #                         n_values=self.n_values - self.n_values % nlp_per_point if hasattr(self,
            #                                                                                           '_n_values') else nlp_per_point * self.points,
            #                         delay_ps=start_trigger_delay_ps,
            #                         window_ps=window_ps
            #                     )
            #
            #                 self.ZPL_counter = True

        for i in range(1):  # was 2 before
            t = threading.Thread(target=f)
            t.start()
            t.join(5)
            if t.is_alive():
                self.log.info("Setting up counter failed!")
                self.log.info("Trying to restart timetagger..")
                self._fast_counter_device.restart_timetagger()  # FIXME
            else:
                break
        else:
            raise Exception("Error: timeout.")
        if setup_errors:
            raise setup_errors[0]
        self.log.info("GC: set_counter finished.")

    def set_progress(self):
        self.progress_by_channel = {}
        for channel, counter in self._iter_gated_counters():
            data = self.gated_counter_data_by_channel.get(channel)
            if data is None:
                data = counter.getData()
                self.gated_counter_data_by_channel[channel] = data

            if counter.ready():
                progress = len(data)
            elif np.any(data != 0):
                progress = len(data) - np.argmax(data[::-1] != 0) - 1
            else:
                progress = 0
            self.progress_by_channel[channel] = int(progress)

        if len(self.progress_by_channel) > 0:
            self.progress = min(self.progress_by_channel.values())
        else:
            self.progress = 0

    def init_plot(self):
        if hasattr(self, "_gui"):
            # self.gui.init_plot()
            pass

    def update_plot_data(self):
        self.effective_subtrace_list = []
        self.hist_list = []
        for idx, step in enumerate(self.trace.analyze_sequence):
            try:
                plotting_channel = self.plotting_channel_for_step(step)
                trace = self.traces.get(plotting_channel, self.trace)
                df = trace.df_extended()
                self.effective_subtrace_list.append(
                    df.loc[df.step == idx, range(step[5])].astype(int).values
                )
                self.hist_list.append([])
                estl = self.effective_subtrace_list[-1].T
                if estl.shape[0] == 2:
                    self.hist_list[-1].append(trace.hist(estl[0, :] - estl[1, :]))
                else:
                    for t in estl:
                        if sum(t != 0) > 0:
                            self.hist_list[-1].append(trace.hist(t))
            except Exception as e:
                logging.error(e)
                print(e)
                pass

    def update_plot(self):
        print("GC: update_plot")
        if hasattr(self, "_gui"):
            self.update_plot_data()

            # Instead send a signal
            # self.gui.update_plot(self.effective_subtrace_list, self.hist_list)
            self.sigTraceUpdated.emit(self.effective_subtrace_list, self.hist_list)

    def clear_plot(self, number_of_subtraces):
        self.clear_plot_signal.emit(number_of_subtraces)
