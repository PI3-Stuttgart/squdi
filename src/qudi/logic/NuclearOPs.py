from __future__ import print_function, absolute_import, division

__metaclass__ = type

import json
import sys

if sys.version_info.major == 2:
    from imp import reload
else:
    from importlib import reload


import importlib
import zipfile
import time
import qudi.logic.misc as misc

importlib.reload(misc)
import traceback
import datetime
import threading
import os
import numpy as np
import time
import pandas as pd
import logging
from PySide2 import QtTest
import collections
from qm import SimulationConfig

simulation_config = SimulationConfig(duration=1_000)  # In clock cycles = 4ns

from numbers import Number

# TODO replace import with a connector to that
from qudi.logic.qudip_enhanced.data_generation import DataGeneration
from qudi.logic.qudip_enhanced.util import ret_property_list_element
from qudi.logic.qudip_enhanced import save_qutip_enhanced

from qudi.util.mutex import Mutex
import qudi.logic.qudip_enhanced.data_handling as data_handling
import base64
import hashlib
from collections import OrderedDict
from typing import Any, Dict, Optional, Sequence

from qudi.logic.queue.queue_logic import queue_logic


class NuclearOPs(DataGeneration):
    """High-level measurement runner used by queue userscripts.

    ``NuclearOPs`` coordinates sequence generation, hardware setup, trace
    acquisition, analysis, refocus actions, and result persistence. Long-running
    methods accept a cooperative ``abort`` event so the queue can stop them
    cleanly without forcing thread termination.

    Special keys in current iterator:

    'sweeps': list of sweep indices, used to track progress through the iterator and for saving intermediate results.
    'click_channel': Timetagger channel for click detection.

    'Laser_freqs_MHz': can be used to sweep the laser frequency. this input is converted from Hz to voltage used in the Quantummachine code to tune the laser.

    'B_amp': magnetic field amplitude in mT
    'B_theta': magnetic field polar angle in degree
    'B_phi': magnetic field azimuthal angle in degree

    """

    queue: queue_logic

    # TODO use the qudi state machine instead maybe?
    state = ret_property_list_element(
        "state",
        [
            "idle",
            "run",
            "sequence_testing",
            "sequence_debug_interrupted",
            "sequence_ok",
        ],
    )
    #
    # # Tracking stuff:
    refocus_interval = misc.ret_property_typecheck("refocus_interval", int)
    odmr_interval = misc.ret_property_typecheck("odmr_interval", Number)
    additional_recalibration_interval = misc.ret_property_typecheck("additional_recalibration_interval", int)

    __TITLE_DATE_FORMAT__ = "%Y%m%dh%Hm%Ms%S"
    IDLE_LASERSCANNER_DLC_SET_VOLTAGE = 60

    def __init__(self) -> None:  # TODO - revert back here from the self.queue.
        """Initialize measurement defaults and runtime state."""

        super().__init__()
        self.queue: queue_logic

        self.state = "idle"
        self._state = self.state

        # Options
        self.lock_laser_to_wavemeter: bool = False

        self.do_ple_refocus_A1: bool = False
        self.ple_refocus_interval: int = 60

        self.do_crc: bool = False

        self.do_confocal_refocus = False
        self.measure_A1_power: bool = False
        self.measure_A2_power: bool = False

        self.use_defect_frame: bool = False

        # Parameters
        self.slow_changing_parameters = ["B_amp", "B_theta", "B_phi"]
        self.sweeps_OPX: list = []
        self.sweep_keys_OPX: list = []
        self.i_1_array: np.ndarray
        self.i_2_array: np.ndarray

        self.manual_pause = False
        self.hashed = False
        self.start_pause_time = 2.75
        self.end_pause_time = 6.25

        # FIXME: Go through all that and set it correctly from QUDI
        self.A1LaserPower = 1  # nW
        self.A2LaserPower = 1  # nW
        #
        self.refocus_cw_odmr = False
        self.refocus_pulsed_odmr = False
        #
        self.do_interferometerPhase_locking = False
        self.wavemeter_lock = False
        #
        self.yellow_repump_compensation = False
        #
        self.last_red_confocal_refocus = -10000
        self.last_odmr_refocus = -10000
        self.last_ple_refocus = -10000
        self.confocal_refocus_interval = 0
        self.ple_refocus_interval = 0
        self.odmr_refocus_interval = 0
        self.last_interferometer_refocus = -10000
        self.interferometer_refocus_interval = 0
        #
        self.save_smartly = False
        self.no_trace = False
        self.delay_ps_list = []
        self.window_ps_list = []
        #
        self.two_zpl_apd = False
        self.raw_clicks_processing = False
        self.raw_clicks_processing_channels = [0, 1, 2, 3, 4, 5, 6, 7]
        self._thread_lock = Mutex()
        self.performedRefocus = False
        self.mode = 1

        # self._confocal = self.confocal()
        # self._tt = self.transition_tracker()
        # self._mcas_dict = self.mcas_dict()
        # self._gated_counter = self.gated_counter()

        # activate connectors..

    @property
    def ana_trace(self) -> Any:
        """Shortcut to the gated-counter trace object exposed by the queue."""
        # return np.array([0]) #FIXME

        return self.queue.gated_counter.trace  # self.queue.gated_counter.trace

    @property
    def analyze_type(self) -> Any:
        """Return the active trace-analysis mode from the gated counter."""
        try:
            return self.ana_trace.analyze_type
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)

    @analyze_type.setter
    def analyze_type(self, val: Any) -> None:
        """Set the trace-analysis mode used for newly acquired traces."""
        self.ana_trace.analyze_type = val

    @property
    def number_of_simultaneous_measurements(self) -> int:
        """Return the number of parallel measurements expected per sequence shot."""
        return self.ana_trace.number_of_simultaneous_measurements

    @number_of_simultaneous_measurements.setter
    def number_of_simultaneous_measurements(self, val: int) -> None:
        """Set the number of parallel measurements expected in the analysis trace."""
        self.ana_trace.number_of_simultaneous_measurements = val

    @property  # this comes form data generation.
    def observation_names(self) -> Sequence[str]:
        """Return the observation columns produced by the current run mode."""
        try:
            if hasattr(self, "_observation_names"):
                return self._observation_names
            else:
                zpl_counters = []

                for i, delay_ps in enumerate(self.delay_ps_list):
                    for j, window_ps in enumerate(self.window_ps_list):
                        name = "zpl_counter_data_{i}_{j}".format(i=i, j=j)
                        zpl_counters.append(name)
                        if self.two_zpl_apd:
                            name = "zpl_2_counter_data_{i}_{j}".format(i=i, j=j)
                            zpl_counters.append(name)

                if self.save_smartly:
                    return (
                        ["result_{}".format(i) for i in range(self.number_of_results)]
                        + zpl_counters
                        + [
                            "trace",
                            "ple_A2",
                            "ple_A1",
                            "average_counts",
                            "events",
                            "thresholds",
                            "start_time",
                            "end_time",
                            "mw_mixing_frequency",
                            "local_oscillator_freq",
                            "confocal_x",
                            "confocal_y",
                            "confocal_z",
                            "A2_Power",
                            "windows_ps",
                            "delays_ps",
                        ]
                    )

                if self.raw_clicks_processing:
                    return zpl_counters + [
                        "average_counts",
                        "events",
                        "start_time",
                        "end_time",
                        "ple_A2",
                        "ple_A1",
                        "confocal_x",
                        "confocal_y",
                        "confocal_z",
                        "A2_Power",
                        "windows_ps",
                        "delays_ps",
                    ]

                else:
                    return (
                        ["result_{}".format(i) for i in range(self.number_of_results)]
                        + zpl_counters
                        + [
                            "trace",
                            "ple_A2",
                            "ple_A1",
                            "average_counts",
                            "events",
                            "thresholds",
                            "start_time",
                            "end_time",
                            "mw_mixing_frequency",
                            "local_oscillator_freq",
                            "confocal_x",
                            "confocal_y",
                            "confocal_z",
                            "A2_Power",
                            "windows_ps",
                            "delays_ps",
                        ]
                    )
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)

    @property
    def dtypes(self) -> Dict[str, Any]:
        """Return dtype hints for the observations stored in the data object."""
        print('Nuclear OPS called "def dtypes"')
        if not hasattr(self, "_dtypes"):
            if self.save_smartly:
                self._dtypes = dict(
                    delays_ps="object",
                    windows_ps="object",
                    trace="object",
                    events="int",
                    start_time="datetime",
                    end_time="datetime",
                    local_oscillator_freq="float",
                    thresholds="object",
                    confocal_x="float",
                    confocal_y="float",
                    confocal_z="float",
                    average_counts="float",
                )

            elif self.raw_clicks_processing:
                self._dtypes = dict(
                    delays_ps="object",
                    windows_ps="object",
                    start_time="datetime",
                    end_time="datetime",
                    events="int",
                    confocal_x="float",
                    confocal_y="float",
                    confocal_z="float",
                    average_counts="float",
                )

            else:
                self._dtypes = dict(
                    delays_ps="object",
                    windows_ps="object",
                    trace="object",
                    events="int",
                    start_time="datetime",
                    end_time="datetime",
                    local_oscillator_freq="float",
                    thresholds="object",
                    confocal_x="float",
                    confocal_y="float",
                    confocal_z="float",
                    average_counts="float",
                )

            for i, delay_ps in enumerate(self.delay_ps_list):
                for j, window_ps in enumerate(self.window_ps_list):
                    name = "zpl_counter_data_{i}_{j}".format(i=i, j=j)
                    self._dtypes.update({name: "object"})

                    if self.two_zpl_apd:
                        name = "zpl_2_counter_data_{i}_{j}".format(i=i, j=j)
                        self._dtypes.update({name: "object"})

        return self._dtypes

    @property
    def number_of_results(self) -> int:
        """Return how many scalar result fields are produced by the trace analysis."""
        return self.ana_trace.number_of_results

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Start either the normal measurement thread or the debug sequence."""
        self._md = self.queue.awg.mcas_dict
        if getattr(self, "debug_mode", False):
            # self.run_debug_sequence(*args, **kwargs)

            self.thread = threading.Thread(target=self.run_debug_sequence, args=args, kwargs=kwargs)
            self.thread.start()

        else:
            self.thread = threading.Thread(target=self.run_measurement, args=args, kwargs=kwargs)
            self.thread.start()
            # Whats difference between envs/qudi/lib/threading and envs/qudi/lib/subprocess?
            # self.run_measurement(*args, **kwargs)

    def checktime(self, abort: Any) -> None:
        """Pause execution during the configured nightly quiet-time window."""
        idx = 0
        t = datetime.datetime.now()
        current_time = int(t.hour) + int(t.minute) / 60
        while current_time > self.start_pause_time and current_time < self.end_pause_time:
            if abort.is_set():
                break
            QtTest.QTest.qSleep(1000)
            if idx == 0:
                print("3 am pause. Good night, rest well.")
                idx += 1
            t = datetime.datetime.now()
            current_time = int(t.hour) + int(t.minute) / 60
        if idx > 0:
            print("Continue after sleeping")

    def check_manual_pause(self, abort: Any) -> None:
        """Wait while manual pause is enabled unless an abort is requested."""
        while self.manual_pause:
            if abort.is_set():
                break
            QtTest.QTest.qSleep(1000)

    def run_measurement(self, abort: Any, **kwargs: Any) -> None:
        """Execute the main measurement loop used during normal queue operation."""

        self.queue.log.info("cun: NuclearOps run measurement")
        self.init_run(**kwargs)

        # Get and safe confocal positions from Qudi
        x = self.queue.confocal.scanner_position["x"]
        y = self.queue.confocal.scanner_position["y"]
        z = self.queue.confocal.scanner_position["z"]

        self.df_refocus_pos = pd.DataFrame(OrderedDict(confocal_x=[x], confocal_y=[y], confocal_z=[z]))

        try:
            # Setup gated counter
            self.queue.gated_counter.set_counter()

            # Lock laser to wavemeter if specified and not continously updated by PLE refocus
            if self.lock_laser_to_wavemeter and not self.do_ple_refocus_A1:
                self.queue.wavemeter.start_lock(use_current_wavelength=True)

            for idx, _ in enumerate(self.iterator()):
                if abort.is_set():
                    break

                while True:
                    if abort.is_set():
                        break

                    # we can pause the mesurement by setting the variable self.manual_pause to True, setting it to False will continue the measurement
                    self.check_manual_pause(abort)

                    # updates click channel for gated counter if defined
                    if "click_channel" in self.current_iterator_df.keys():
                        self.queue.fast_counter_device._count_between_markers["click_channel"] = self.current_iterator_df["click_channel"].unique()[0]

                    if self.do_ple_refocus_A1:
                        self.refocus_ple_A1(abort)

                    if "pulse_shape_ppg" in self.current_iterator_df.keys():
                        self.update_waveform_ppg(abort)

                    if "B_amp" in self.current_iterator_df.keys():
                        self.ramp_magnet()

                    self.queue.log.info("Cun: Starting measurement sequence")
                    self.setup_rf(self.current_iterator_df, hashed=self.hashed)

                    if abort.is_set():
                        break

                    # Save relevant data from transition tracker to data set
                    self.data.set_observations([OrderedDict(mw_mixing_frequency=self.queue.transition_tracker.mw_mixing_frequency_L)] * self.number_of_simultaneous_measurements)
                    self.data.set_observations([OrderedDict(mw_mixing_frequency=self.queue.transition_tracker.mw_mixing_frequency_R)] * self.number_of_simultaneous_measurements)
                    self.data.set_observations([OrderedDict(local_oscillator_freq=self.queue.transition_tracker.current_local_oscillator_freq)] * self.number_of_simultaneous_measurements)
                    self.data.set_observations([OrderedDict(ple_A2=self.queue.transition_tracker.ple_A2)] * self.number_of_simultaneous_measurements)  # already inlcuded in raw_clicks_processing
                    self.data.set_observations([OrderedDict(ple_A1=self.queue.transition_tracker.ple_A1)] * self.number_of_simultaneous_measurements)  # already inlcuded in raw_clicks_processing
                    self.data.set_observations(pd.concat([self.df_refocus_pos.iloc[-1:, :]] * self.number_of_simultaneous_measurements).reset_index(drop=True))  # already inlcuded in raw_clicks_processing

                    self.data.set_observations([OrderedDict(start_time=datetime.datetime.now())] * self.number_of_simultaneous_measurements)

                    # start measurement
                    self.get_trace(
                        abort,
                        delay_ps_list=self.delay_ps_list,
                        window_ps_list=self.window_ps_list,
                    )
                    if abort.is_set():
                        break

                    self.data.set_observations([OrderedDict(end_time=datetime.datetime.now())] * self.number_of_simultaneous_measurements)

                    if self.save_smartly:  # non zero to the data
                        # FIXME:  TEMP SOLUTION FIXME LATER, Only for HOM , just uncomment this code
                        dd = self.ana_trace.trace
                        idx = np.nonzero(dd)
                        ddd = dd[idx]
                        self.data.set_observations([OrderedDict({"trace": (idx, ddd)})] * self.number_of_simultaneous_measurements)
                    elif self.raw_clicks_processing:
                        pass
                    elif self.no_trace:
                        pass
                    else:
                        self.data.set_observations([OrderedDict(trace=self.ana_trace.trace)] * self.number_of_simultaneous_measurements)

                    if abort.is_set():
                        break

                    repeat_measurement = self.analyze()

                    if abort.is_set():
                        break

                    if self.do_ple_refocus_A1:
                        self.refocus_ple_A1(abort=abort)

                    if repeat_measurement:
                        self.queue.log.info("cun:repeat_measurement ")
                    else:
                        break

                if hasattr(self, "_pld"):
                    self.pld.new_data_arrived()
                    self.queue.log.info("Cun: New data arrived")

                if abort.is_set():
                    break

                self.save()

        except Exception as e:

            self.queue.log.error("cun ERROR: Nuclear op failed in run measurement: %s", e)
            abort.set()
            self.update_current_str()
            exc_type, exc_value, exc_tb = sys.exc_info()
            raise exc_type(e)
            # traceback.print_exception(exc_type, exc_value, exc_tb)
            # self.update_current_str()
        finally:
            self.state = "idle"
            self.data._df = data_handling.df_take_duplicate_rows(self.data.df, self.iterator_df_done)  # drops unfinished measurements,
            self.pld.new_data_arrived()
            self.update_current_str()
            if self.session_meas_count == 0:
                self.pld.gui.close_gui()
                if hasattr(self.data, "init_from_file") and self.data.init_from_file is not None:
                    self.move_init_from_file_folder_back()

            if os.path.exists(self.save_dir) and not os.listdir(self.save_dir):
                os.rmdir(self.save_dir)

            self.queue.log.info("cun: Finished function run_measurement")
            self.queue.wavemeter.stop_lock()
            time.sleep(2)
            self.queue.dlc_pro_620.set_pc_voltage(self.IDLE_LASERSCANNER_DLC_SET_VOLTAGE)

    @property
    def session_meas_count(self) -> int:
        """Return how many measurements were completed during this session."""
        if len(self.data.df) == 0 or len(self.iterator_df_done) == 0:
            return 0
        else:
            return len(self.iterator_df_done) - len(self.data.df[(self.data.df.start_time < self.start_time) & (self.data.df.start_time > datetime.datetime(1900, 1, 1))])

    def run_debug_sequence(self, abort: Any, **kwargs: Any) -> None:
        """Run the sequence in debug/simulation mode instead of live acquisition."""
        ## Here maybe is for the simulation mode...

        if any([key in kwargs for key in ["iff", "init_from_file"]]):
            raise Exception("Error: Data initialization from file (.hdf or .csv) not allwoed in sequence debug mode.")
        if len(self.parameters["sweeps"]) != 1:
            print("cun:Debug mode, number of sweeps set to one.")
            self.parameters["sweeps"] = [0]
        self.init_run(**kwargs)
        self.state = "sequence_testing"
        try:
            # self._md.debug_mode = True
            self.queue.awg.debug_mode = True
            for idx, _ in enumerate(self.iterator()):
                if abort.is_set():
                    break
                self.data.set_observations([OrderedDict(start_time=datetime.datetime.now())] * self.number_of_simultaneous_measurements)

                # self.dowork()
                self.setup_rf(self.current_iterator_df, hashed=False)  # self.hashed) ##Is this guy stops the main loop?
                self.queue.awg.simulate(self.mcas.program, plot=True)

                # self.queue.awg.simulate(self.queue._awg.mcas_dict[self.sequence_name], plot = True)
                self.data.set_observations([OrderedDict(end_time=datetime.datetime.now())] * self.number_of_simultaneous_measurements)
            if not abort.is_set():
                self.state = "sequence_ok"  # FIXME why never this reaches the state?
        except Exception:
            self.state = "sequence_debug_interrupted"
            abort.set()
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)
        finally:
            # TODO do this
            # self._md.debug_mode = False
            self.queue.awg.stop_awgs()  # formely it was mcas_dict as the main...
            self.update_current_str()
            if os.path.exists(self.save_dir) and not os.listdir(self.save_dir):
                os.rmdir(self.save_dir)
            self.state = "idle"

    def dowork(
        self,
    ) -> None:
        """Legacy placeholder hook kept for experimentation."""
        pass
        # QtTest.QTest.qSleep(1000)

    def confocal_pos_moving_average(self, n: int) -> pd.DataFrame:
        """Return a moving average over the stored confocal refocus positions."""
        # FIXME ?
        return self.df_refocus_pos[["confocal_x", "confocal_y", "confocal_z"]].rolling(n, win_type="boxcar", center=True).sum().dropna() / n

    @property
    def refocus_moving_average_num(self) -> int:
        """Return the window size used for averaging stored refocus positions."""
        return getattr(self, "_refocus_moving_average_num", 10)

    @refocus_moving_average_num.setter
    def refocus_moving_average_num(self, val: int) -> None:
        """Set the moving-average window size for refocus position smoothing."""
        self._refocus_moving_average_num = val

    @property
    def sweeps(self) -> Any:
        """Expose the configured sweep indices from the parameter dictionary."""
        return self.parameters["sweeps"]

    def ramp_magnet(self) -> None:
        """Ramp the magnet to the field vector requested by the current iterator row."""
        if self.use_defect_frame:
            B_vec_SnV = np.array(
                [
                    self.current_iterator_df["B_amp"].unique()[0] * 1e-3,
                    self.current_iterator_df["B_theta"].unique()[0],
                    self.current_iterator_df["B_phi"].unique()[0],
                ]
            )

            B_vec_cart_SnV = self.spherical_to_carthesian(B_vec_SnV)

            # FIXME: Implement all this within the magnet logic and make it SnV orientation agnostic
            B_vec_cart_Lab = self.queue.magnet_logic.rotate_vector(B_vec_cart_SnV, 55, 225)
            B_vec_Lab = self.queue.magnet_logic.cartesian_to_spherical(B_vec_cart_Lab)

        else:
            B_vec_Lab = np.array(
                [
                    self.current_iterator_df["B_amp"].unique()[0] * 1e-3,
                    self.current_iterator_df["B_theta"].unique()[0],
                    self.current_iterator_df["B_phi"].unique()[0],
                ]
            )

        self.queue.magnet_logic.ramp(B_vec_Lab)
        time.sleep(0.5)
        while min(self.queue.magnet_logic._magnet.get_ramping_state()) == 1:
            time.sleep(0.1)
        time.sleep(3)

    def refocus_ple_A1(self, abort) -> bool:
        """Run SnV PLE refocus only when the refocus interval has elapsed."""
        now = time.time()
        delta_t = now - self.last_ple_refocus

        if delta_t < self.ple_refocus_interval:
            remaining = max(0, self.ple_refocus_interval - delta_t)
            self.queue.log.info(f"Not time for PLE refocus yet. Time left: {remaining:.1f}s")
            return False

        self.queue.log.info("--------- doing ple refocus ---------")

        success = self._run_refocus_ple_A1_sequence(abort)

        if success:
            self.last_ple_refocus = time.time()
            self.performedRefocus = True

        return success

    def _run_refocus_ple_A1_sequence(self, abort) -> bool:
        """Execute the SnV PLE refocus sequence."""
        REPUMP_TIME_S = 1.0
        OPTIMIZER_POLL_S = 0.2
        AFTER_OPTIMIZER_WAIT_S = 3.0
        BEFORE_CW_STOP_WAIT_S = 1
        BEFORE_DEVIATION_WAIT_S = 1.0
        AFTER_DEVIATION_WAIT_S = 1.0
        LOCK_SETTLE_TIME_S = 3.0

        q = self.queue

        def wait_or_abort(seconds, step=0.1):
            """Sleep in small increments and return early if ``abort`` is set."""
            end_time = time.time() + seconds
            while time.time() < end_time:
                if abort.is_set():
                    q.log.info("PLE refocus aborted.")
                    return False
                time.sleep(min(step, end_time - time.time()))
            return True

        if abort.is_set():
            return False

        q.wavemeter.stop_lock()
        q.dlc_pro_620.set_pc_voltage(self.IDLE_LASERSCANNER_DLC_SET_VOLTAGE)
        q.awg.stop_awgs()

        # Green repump
        q.do.set_state("Laser_520", "on")
        if not wait_or_abort(REPUMP_TIME_S):
            q.do.set_state("Laser_520", "off")
            return False
        q.do.set_state("Laser_520", "off")

        if abort.is_set():
            return False

        # Start optimization
        q.do.set_state("AOM_620", "on")
        q.ple_optimize_logic.toggle_optimize(True)
        while q.ple_optimize_logic.optimizer_running:
            if abort.is_set():
                q.log.info("Abort during PLE optimization.")
                return False
            time.sleep(OPTIMIZER_POLL_S)
        q.do.set_state("AOM_620", "off")

        if not wait_or_abort(AFTER_OPTIMIZER_WAIT_S):
            return False

        wavelength = q.wavemeter.read_single_point()[0][0] * 1e9
        actual_voltage = int(q.dlc_pro_620.get_pc_voltage_act() * 1000)

        if not wait_or_abort(BEFORE_CW_STOP_WAIT_S):
            return False

        q.ao.set_setpoint("LaserScanner_red", 0)
        q.wavemeter._proxy()._wavemeter_dll.SetDeviationSignal(actual_voltage)

        # if not wait_or_abort(BEFORE_DEVIATION_WAIT_S):
        #     return False

        if not wait_or_abort(AFTER_DEVIATION_WAIT_S):
            return False

        q.tt.update_ple(wavelength)
        q.wavemeter.start_lock(wavelength)
        q.log.info(f"PLE refocus complete. Locked to wavelength: {wavelength:.2f} nm")

        if not wait_or_abort(LOCK_SETTLE_TIME_S):
            return False

        return True

    def update_waveform_ppg(self, abort) -> bool:
        """Update the PPG waveform parameters from the current iterator row."""

        self.queue.log.info("Cun: run measurement: Updating ppg waveform")
        kwargs = {}

        if "pulse_shape_ppg" in self.current_iterator_df.keys():
            kwargs["pulse_shape"] = self.current_iterator_df["pulse_shape_ppg"].unique()[0]
        else:
            raise ValueError("'pulse_shape_ppg' needs to be in current_iterator_df for updating ppg waveform")

        if "pulse_width_ppg" in self.current_iterator_df.keys():
            kwargs["pulse_width"] = self.current_iterator_df["pulse_width_ppg"].unique()[0]
        else:
            raise ValueError("'pulse_length_ppg' needs to be in current_iterator_df for updating ppg waveform")

        if "pulse_delay_ppg" in self.current_iterator_df.keys():
            kwargs["pulse_delay"] = self.current_iterator_df["pulse_delay_ppg"].unique()[0]

        if "pulse_amplitude_ppg" in self.current_iterator_df.keys():
            kwargs["pulse_amplitude"] = self.current_iterator_df["pulse_amplitude"].unique()[0]

        try:
            success = self.queue.ppg.write_pulse(**kwargs)
            return success
        except BaseException as e:
            raise ValueError(e)
            return False

    # TODO: implement for Our setup and qudi
    def do_refocus_zpl(self, abort):
        """Placeholder for a future ZPL refocus routine."""
        pass

    def reinit(self) -> None:
        """Reset counters and timing markers for a fresh run."""
        super(NuclearOPs, self).reinit()
        self.odmr_count = 0
        self.additional_recalibration_interval_count = 0
        self.last_odmr = time.time()
        self.last_rabi_refocus = time.time()

    def get_trace(
        self,
        abort: Any,
        delay_ps_list: Optional[Sequence[float]] = None,
        window_ps_list: Optional[Sequence[float]] = None,
    ) -> None:
        """Prepare the active sequence and trigger gated-counter acquisition."""
        if not self.debug_mode:
            # This is only compilation of the sequence, test run for 1 s and stop..
            # In principle we can cut it.
            self.queue.log.info(f"cun: get_trace: initializing: {self.mcas.name}")
            self.mcas.initialize()  # FIXME might be usefull for something?

            # to keep the syntax same to keysight... (important for crossplatform)...
            self.queue.log.info("cun:get_trace:init fininished")
        self.queue.log.info("cun:get_trace:starting a longer trace")

        ## This is preparing a gated counter and running a sequence.
        self.queue.gated_counter.count(
            abort,
            ch_dict=self.mcas.ch_dict,
            mcas=self.mcas,
            start_trigger_delay_ps_list=None,  # delay_ps_list,
            window_ps_list=window_ps_list,
            two_zpl_apd=self.two_zpl_apd,
            raw_clicks_processing=self.raw_clicks_processing,
            raw_clicks_processing_channels=self.raw_clicks_processing_channels,
        )
        self.queue.log.info("cun:get_trace:measurement finished")

    def setup_rf(self, current_iterator_df: pd.DataFrame, hashed: bool = False) -> None:
        """Build and register the RF/QUA sequence for the current iterator row."""

        # Drop sweeps from current iterator
        if "sweeps" in current_iterator_df.columns:
            current_iterator_df = current_iterator_df.drop(labels=["sweeps"], axis=1)

        # create hash
        hash = base64.b64encode(hashlib.sha1((str(current_iterator_df) + "\n" + str(self.queue.gated_counter.readout_duration)).encode()).digest())

        self.sequence_name = "nuclear_op_hash_{}".format(hash)

        # This is usual.
        # self.queue._awg.mcas_dict.stop_awgs()
        # In the normal path the sequence is rebuilt for the current iterator
        # row and stored in the AWG/OPX dictionary under its generated name.
        self.queue.log.info("cun:setup_rf:This time is the qua writing...")
        self.queue.awg.stop_awgs()
        # self.create_fast_sweep_sequences_OPX(current_iterator_df)
        self.queue.nuclear_ops_opx_utils.create_fast_sweep_qua_arrays(current_iterator_df)
        self.mcas = self.ret_mcas(self, current_iterator_df)
        # Writing the sequence...
        # while self.mcas=='':
        # process_events() #TODO gui process events.
        # QtTest.QTest.qSleep(10)
        # self.sequence_name = self.mcas.name
        self.queue.awg.mcas_dict[self.mcas.name] = self.mcas

        self.performedRefocus = False

    def create_fast_sweep_sequences_OPX(self, current_iterator_df: pd.DataFrame) -> None:
        """Build the fast-sweep arrays passed into the QUA/OPX runtime loops."""

        self.sweeps_OPX = []
        self.sweep_keys_OPX = []
        for key in current_iterator_df.keys():
            if len(current_iterator_df[key].unique()) > 1 and key not in self.slow_changing_parameters:
                self.sweeps_OPX.append(current_iterator_df[key].unique())
                self.sweep_keys_OPX.append(key)

        if len(self.sweep_keys_OPX) > 2:
            raise (ValueError("Current_iterator_df has more then two axis to iterate over by the quantum machine, which is not supportet at the moment"))
        self.i_1_array = np.array([self.queue.ple_scanner_logic.frequency_to_voltage(i * 1e6) for i in self.sweeps_OPX[0]]) if "Laser_freqs_MHz" == self.sweep_keys_OPX[0] else self.sweeps_OPX[0]
        self.i_2_array = (np.array([self.queue.ple_scanner_logic.frequency_to_voltage(i * 1e6) for i in self.sweeps_OPX[1]]) if "Laser_freqs_MHz" == self.sweep_keys_OPX[1] else self.sweeps_OPX[1]) if len(self.sweep_keys_OPX) == 2 else np.array([0])

    def analyze(
        self,
        data: Optional[Any] = None,
        ana_trace: Optional[Any] = None,
        start_idx: Optional[int] = None,
    ) -> Optional[bool]:
        """Analyze the current trace object and write observations into ``data``."""
        if ana_trace is None:
            ana_trace = self.ana_trace
            if self.analyze_type != ana_trace.analyze_type:
                raise Exception("This was supposed to be a sanity check. The programmer made shit.")
        data = self.data if data is None else data
        if ana_trace.analyze_type is not None:

            # ACHTUNG!!!! trace analysis code.
            # df = ana_trace.analyze_fast().df # experimental still, but looks ok.
            df = ana_trace.analyze().df  ## TRY this for init? This was the code before.
            print(df)
            if (df.events == 0).all() and not self.analyze_type == "consecutive" and df.at[0, "events"] != 0:
                return True  # Means that runn was not succesfull, 0 events, ==> repeat measurements.
            if "result_num" in df.columns:  # if there are multiple readouts of type "result", here step index is important
                # Why we are going here, because we have only 1 readout anyway,
                obs_r = df.pivot_table(values="result", columns="result_num", index="sm").rename(columns=collections.OrderedDict([(i, "result_{}".format(i)) for i in df.result_num.unique()]))
            else:
                obs_r = df.rename(columns={"result": "result_0"}).drop(columns=["step", "events", "sm"])
            if not self.raw_clicks_processing:  # Do not add result (for some reason, they are analyzed already anyway)
                data.set_observations(obs_r, start_idx=start_idx)
                # data.set_observations(df.groupby(['sm']).agg({'thresholds': lambda x: [i for i in x]}), start_idx=start_idx)

            data.set_observations(df.groupby(["sm"]).agg({"events": np.sum}), start_idx=start_idx)
            data.set_observations(df.groupby(["sm"]).agg({"average_counts": np.mean}), start_idx=start_idx)

            # logging.getLogger().info(df)
            # logging.getLogger().info(ana_trace.analyze_type)
            return False

    def reanalyze(self, do_while_run: bool = False, **kwargs: Any) -> None:
        """Re-run the stored trace analysis over existing dataframe entries."""
        if self.state == "run" and not do_while_run:
            print("Measurement is running.\nReanalyzation will write to data.df and may interfere with the running measurement doing the same.\nIf you want to reanalyze anyway, pass argument do_while_run=True")
            return
        import Analysis

        ana_trace = Analysis.Trace()
        for key in [
            "analyze_type",
            "number_of_simultaneous_measurements",
            "analyze_sequence",
            "binning_factor",
            "average_results",
            "consecutive_valid_result_numbers",
        ]:
            setattr(ana_trace, key, kwargs.get(key, getattr(self.ana_trace, key)))
        for idx, _I_ in self.data.df.iterrows():
            if (idx - 1) % ana_trace.number_of_simultaneous_measurements:
                continue  ## What is it for? (seems that it doing nothings.
            if type(_I_["trace"]) != np.ndarray:
                print("Interrupted reanalyzation at dataframe index {}, as trace is not a numpy array.\nMaybe, this is trace has just not been measured yet?\nTotal length of dataframe is {}".format(idx, len(self.data.df)))
                break
            ana_trace.trace = _I_["trace"]
            self.analyze(ana_trace=ana_trace, start_idx=idx)

    def save(self) -> None:
        """Persist measurement results and supporting metadata to disk."""
        pass
        if len(self.iterator_df_done) > 0 and not (hasattr(self, "do_save") and not self.do_save):
            Thread1 = threading.Thread(target=super(NuclearOPs, self).save, kwargs={"notify": False})
            Thread1.start()
            # super(NuclearOPs, self).save(notify=False) #### IMPORTANT
            Thread1.join()
            self.save_sequence_file()
            self.queue.save_pi3diamond(destination_dir=self.save_dir)
            save_qutip_enhanced(destination_dir=self.save_dir)
            # TODO
            # has to switch to qudi log. logging.getLogger().info("saved nuclear to '{} ({:.3f})".format(self.save_dir, time.time() - t0))

    def save_sequence_file(self) -> None:
        """Dump the generated sequence description into ``awg-file.txt``."""
        pass
        seq_message = []
        if hasattr(self.mcas, "sequences"):
            for k in self._md[self.mcas.name].sequences.keys():
                for ch in [1, 2]:
                    try:

                        seq_message.append(self._md[self.mcas.name].sequences[k][ch].ret_info())
                        seq_message.append("\n")
                    except Exception as e:
                        print(e)
                        pass

            seq_message.append(str(self._md[self.mcas.name].sequences["ps"][1]))
            awg_file_name = "awg-file.txt"
            awg_fp = os.path.join(self.save_dir, awg_file_name)

            if not os.path.exists(awg_fp):
                with open(awg_fp, "w") as fp:
                    for page in seq_message:
                        fp.write(page)
                        fp.write("\n-------------------------------------------------------------------\n")
        else:  ## quantum machine
            seq_message.append(self.mcas.debug_info())
            awg_file_name = "awg-file.txt"
            awg_fp = os.path.join(self.save_dir, awg_file_name)
            if not os.path.exists(awg_fp):
                with open(awg_fp, "w") as fp:
                    for page in seq_message:
                        fp.write(json.dumps(page))
                        fp.write("\n-------------------------------------------------------------------\n")

    def reset_settings(self) -> None:
        """Reset run-specific settings and drop transient sequence references."""
        self.additional_recalibration_interval = 0
        self.ret_mcas = None
        self.mcas = None
        self.refocus_interval = 2
        self.odmr_interval = 15
        self.file_notes = ""
        self.thread = None
        # get rid of old hashes
        try:
            for seq in self.mcas_dict_awg.mcas_dict:
                if seq.startswith("Nuclear"):
                    print("Deleting used Nuclear Ops Sequences")
                    del seq
        except:
            pass
