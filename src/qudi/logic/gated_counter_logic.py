from __future__ import print_function, absolute_import, division

__metaclass__ = type

# import misc


import traceback
import time
import sys
import os
import threading
from PySide2.QtCore import Signal as pyqtSignal
from PySide2 import QtTest
from qudi.logic import Analysis as Analysis

# from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
# from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar
# from matplotlib.figure import Figure
import PySide2.QtCore
import numpy as np
import logging

# from hardware.Keysight_AWG_M8190.pym8190a import MultiChSeq as MCAS
# from hardware.Keysight_AWG_M8190.pym8190a import start_awgs as start_awgs # here we dont have it....
import zmq

# import logic.qudip_enhanced.qtgui.gui_helpers
from numbers import Number
import copy
import datetime
import os

# import pylab as pb
import time

from collections import OrderedDict
from qudi.core.connector import Connector

# from core.util.network import netobtain
from qudi.logic.generic_logic import GenericLogic
import qudi.logic.misc as misc
from qudi.hardware.swabian_instruments.timetagger_api import TT as TT
from PySide2 import QtCore


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
        self.readout_interval = (
            1e6  # DO NOT SET BELOW 0.2, plotting runs in main loop, and takes around 0.15, which then makes the console annoying to work with.
        )
        self.readout_duration = 10e6
        self.n_values = 10
        self.trace = Analysis.Trace()
        self.analyze_trace_during_experiment = True  # TODO make it False compatible.
        self.title = "Gated_counter"

        # if title is not None:
        #    self.update_window_title(title)
        # self.tim
        self.raw_clicks_processing = False
        self.raw_clicks_processing_function = None
        self.ZPL_counter = False
        self.live_update_interval = 1.0

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
        analyze_sequence = self.trace.analyze_sequence if analyze_sequence is None else analyze_sequence
        # print('analyze sequence in gated counter logic: ',analyze_sequence)
        # for step in analyze_sequence:
        #     print(step)
        if n_values is None:

            self.n_values = int(self.readout_duration / (mcas.length_mus / sm) * sum([step[3] for step in analyze_sequence]))
        else:
            self.n_values = n_values

    def _counter_tasks(self):
        tasks_by_channel = getattr(self, "_gated_counter_tasks_by_click_channel", None)
        if tasks_by_channel:
            tasks = list(tasks_by_channel.values())
        else:
            task = getattr(self._fast_counter_device, "gated_counter_countbetweenmarkers", None)
            tasks = [] if task is None else [task]

        unique_tasks = []
        seen = set()
        for task in tasks:
            if task is not None and id(task) not in seen:
                unique_tasks.append(task)
                seen.add(id(task))
        return unique_tasks

    def _get_default_click_channel(self):
        return int(self._fast_counter_device._count_between_markers["click_channel"])

    def _coerce_click_channel(self, value):
        if isinstance(value, (int, np.integer)):
            return int(value)
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            pass

        key = text.lower().replace("-", "_")
        for prefix in ("apd_", "apd", "tt_", "tt", "ttr_", "ttr"):
            if key.startswith(prefix):
                suffix = key[len(prefix):]
                if suffix.isdigit():
                    return int(suffix)
        raise ValueError("Could not resolve APD/click-channel selector '{}'.".format(value))

    def _resolve_click_channel(self, selector):
        if selector is None or selector == "":
            return self._get_default_click_channel()

        apd_channels = getattr(self._fast_counter_device, "_apd_channels", None) or {}
        apd_channels = {str(key).lower(): value for key, value in apd_channels.items()}
        key = str(selector).strip().lower()
        if key in apd_channels:
            return self._coerce_click_channel(apd_channels[key])

        return self._coerce_click_channel(selector)

    def _analysis_click_channels(self):
        selectors = getattr(self.trace, "analyze_sequence_apd_channels", None)
        if selectors is None:
            selectors = [None] * len(self.trace.analyze_sequence)
        return [self._resolve_click_channel(selector) for selector in selectors]

    def _create_count_between_markers(self, click_channel, n_values):
        counter_settings = self._fast_counter_device._count_between_markers
        return self._fast_counter_device.count_between_markers(
            click_channel=click_channel,
            begin_channel=counter_settings["begin_channel"],
            end_channel=counter_settings.get("end_channel"),
            n_values=n_values,
        )

    def _combine_gated_counter_data_by_step(self, data_by_click_channel):
        step_lengths = [step[3] for step in self.trace.analyze_sequence]
        nlp_per_point = sum(step_lengths)
        n_sm = self.trace.number_of_simultaneous_measurements
        period_run = nlp_per_point * n_sm
        if period_run == 0:
            return np.array([], dtype=np.int16)

        min_len = min(len(data) for data in data_by_click_channel.values())
        trace_length_cut = min_len - min_len % period_run
        first_data = next(iter(data_by_click_channel.values()))
        combined = np.zeros(trace_length_cut, dtype=first_data.dtype)
        click_channels = getattr(self, "_gated_counter_click_channels", self._analysis_click_channels())

        for run_start in range(0, trace_length_cut, period_run):
            for sm in range(n_sm):
                offset = run_start + sm * nlp_per_point
                for step_idx, step_len in enumerate(step_lengths):
                    next_offset = offset + step_len
                    if next_offset > trace_length_cut:
                        break
                    click_channel = click_channels[step_idx]
                    combined[offset:next_offset] = data_by_click_channel[click_channel][offset:next_offset]
                    offset = next_offset
        return combined

    def _all_counters_ready(self):
        tasks = self._counter_tasks()
        return bool(tasks) and all(task.ready() for task in tasks)

    def _read_gated_counter_data(self):
        tasks_by_channel = getattr(self, "_gated_counter_tasks_by_click_channel", None)

        if tasks_by_channel:
            data_by_channel = {
                click_channel: task.getData() for click_channel, task in tasks_by_channel.items()
            }
            self.gated_counter_data_by_apd = data_by_channel
        else:
            data = self._fast_counter_device.gated_counter_countbetweenmarkers.getData()
            self.gated_counter_data_by_apd = {self._get_default_click_channel(): data}

        if len(self.gated_counter_data_by_apd) > 1:
            self.gated_counter_data = self._combine_gated_counter_data_by_step(
                self.gated_counter_data_by_apd
            )
        else:
            self.gated_counter_data = next(iter(self.gated_counter_data_by_apd.values()))

    def _analyze_current_trace_for_plot(self):
        self.set_progress()
        if not self.analyze_trace_during_experiment or self.progress <= 0:
            return False

        self.trace_rep = Analysis.TraceRep(
            trace=self.gated_counter_data[: self.progress],
            analyze_sequence=self.trace.analyze_sequence,
            number_of_simultaneous_measurements=self.trace.number_of_simultaneous_measurements,
        )
        self.trace.trace = np.array(
            self.trace_rep.df.groupby(["run", "sm", "step", "memory"]).agg({"n": np.sum}).reset_index().n
        )
        if len(self.trace.trace) == 0:
            return False
        self.update_plot_data()
        return True

    def update_live_trace(self):
        """Read current TimeTagger data and update the GUI while acquisition is running."""
        self._read_gated_counter_data()
        if self._analyze_current_trace_for_plot() and hasattr(self, "_gui"):
            self.sigTraceUpdated.emit(self.effective_subtrace_list, self.hist_list)

    def read_trace(self):
        print("GC:read_trace")
        self._read_gated_counter_data()
        if self.ZPL_counter:
            print("ZPL_counter in gated_counter_logic")
            if self.raw_clicks_processing:
                counter_name = "raw_zpl"
                # print('init raw clicks processing name: ', counter_name)
                data = self._fast_counter_device.get_stream_data(counter_name=counter_name, kwargs=[])
                # data = datadict['data']

                # send_time = datadict['time_before']
                # print("Send time was: {}".format(send_time))
                # print("Time now: {}".format(time.time()))
                # print('11 tt:', time.time() - t0)

                if self.raw_clicks_processing_function is not None:
                    self.raw_clicks_processing_function(data, delays=self.start_trigger_delay_ps_list, windows=self.window_ps_list)
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
                        zpl_counter_data = getattr(self._fast_counter_device, counter_name).getData()  # .astype(np.int64)
                        # getattr(self._fast_counter_device, counter_name).sync()
                        setattr(self, trace_name, zpl_counter_data)
                        # print('21 tt:', time.time() - t0)
                        if self.two_zpl_apd:
                            trace_name = "zpl_2_counter_data_{i}_{j}".format(i=i, j=j)
                            counter_name = "gated_cbm_2_zpl_{i}_{j}".format(i=i, j=j)
                            # self._fast_counter_device.gated_counter_countbetweenmarkers.sync()
                            zpl_counter_data = getattr(self._fast_counter_device, counter_name).getData()  # .astype(np.int64)
                            # getattr(self._fast_counter_device, counter_name).sync()
                            setattr(self, trace_name, zpl_counter_data)

        # UNFUG
        if self.analyze_trace_during_experiment:
            print("analyze trace during measurement in gated_counter_logic")
            self._analyze_current_trace_for_plot()

    def clear_timetaggers(self):
        for task in self._counter_tasks():
            task.clear()
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

        for task in self._counter_tasks():
            task.stop()
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
        for task in self._counter_tasks():
            task.start()
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
        number_of_subtraces = len(self.trace.analyze_sequence)

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
            last_live_update_time = 0
            while True:
                # print('stuck in Ready for data...')
                if abort.is_set():
                    break
                # print('Gated counter is falling asleep for ',self.readout_duration / 1e6)
                # time.sleep(self.readout_duration / 1e6)
                # break
                ready = self._all_counters_ready()

                if i % 2 == 0:
                    # why get counts here already? its done at the end of measurement when self.read_trace() is called
                    # seems like read_trace() is not doing much...
                    dat = self._fast_counter_device.gated_counter_countbetweenmarkers.getData()
                    print("-----------------------------------------------------\n", self.progress, len(dat))
                if time.time() - last_live_update_time >= self.live_update_interval:
                    self.update_live_trace()
                    last_live_update_time = time.time()
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

        print("GC:set_counter")
        self.ZPL_counter = False
        self._gated_counter_tasks_by_click_channel = {}
        self._gated_counter_click_channels = []

        ## Needs to be adjusted tohas the qudi gated counter #TODO
        def f():
            nlp_per_point = sum([step[3] for step in self.trace.analyze_sequence])

            # TODO redo the interfaces . Init counter to gated counter now, or make it inside the TT class?
            n_vals = self.n_values - self.n_values % nlp_per_point if hasattr(self, "_n_values") else nlp_per_point * self.points
            print("GC:set_counter:nvals", n_vals)
            print("GC:")
            click_channels = self._analysis_click_channels()
            unique_click_channels = list(OrderedDict((channel, None) for channel in click_channels).keys())
            default_click_channel = self._get_default_click_channel()

            if len(unique_click_channels) == 1 and unique_click_channels[0] == default_click_channel:
                self._fast_counter_device.count_between_markers_nops(n_values=n_vals)
                task = self._fast_counter_device.gated_counter_countbetweenmarkers
                self._gated_counter_tasks_by_click_channel = {default_click_channel: task}
            else:
                self._gated_counter_tasks_by_click_channel = {
                    click_channel: self._create_count_between_markers(click_channel, n_vals)
                    for click_channel in unique_click_channels
                }
                self._fast_counter_device.gated_counter_countbetweenmarkers = (
                    self._gated_counter_tasks_by_click_channel[unique_click_channels[0]]
                )
            self._gated_counter_click_channels = click_channels

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
                logging.getLogger().info("Setting up counter failed!")
                logging.getLogger().info("Trying to restart timetagger..")
                self._fast_counter_device.restart_timetagger()  # FIXME
            else:
                break
        else:
            raise Exception("Error: timeout.")
        print("GC: set_counter finished.")

    def set_progress(self):
        if self._all_counters_ready():
            self.progress = int(len(self.gated_counter_data))
        else:
            if len(self.gated_counter_data) == 0:
                self.progress = 0
                return
            nonzero_indices = np.flatnonzero(self.gated_counter_data != 0)
            if len(nonzero_indices) == 0:
                self.progress = 0
                return
            self.progress = int(nonzero_indices[-1] + 1)

    def init_plot(self):
        if hasattr(self, "_gui"):
            # self.gui.init_plot()
            pass

    def update_plot_data(self):
        self.effective_subtrace_list = []
        self.hist_list = []
        df = self.trace.df_extended()
        for idx, step in enumerate(self.trace.analyze_sequence):
            try:
                self.effective_subtrace_list.append(df.loc[df.step == idx, range(step[5])].astype(int).values)
                self.hist_list.append([])
                estl = self.effective_subtrace_list[-1].T
                if estl.shape[0] == 2:
                    self.hist_list[-1].append(self.trace.hist(estl[0, :] - estl[1, :]))
                else:
                    for t in estl:
                        if sum(t != 0) > 0:
                            self.hist_list[-1].append(self.trace.hist(t))
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
