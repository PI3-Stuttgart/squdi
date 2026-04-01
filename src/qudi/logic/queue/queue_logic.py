# coding=utf-8
from __future__ import print_function, absolute_import, division

__metaclass__ = type

import sys, os
import imp

# from gui.queue.Queue import queue_gui
from queue import Empty, Queue
from PySide2.QtCore import Signal as pyqtSignal
from qudi.logic.qudip_enhanced import *
from qudi.logic import magnetlogic

# FIXME
from PySide2.QtCore import QTimer
from PySide2 import QtTest

# import multi_channel_awg_seq as MCAS; reload(MCAS)
import qudi.logic.misc as misc
import datetime
import os
import pickle
import sys
import threading
import traceback
from qudi.logic.generic_logic import GenericLogic
from qudi.core.connector import Connector
import multiprocess
import numpy as np
import logging

import collections
import importlib
from typing import Any, Dict, List, Optional, Union
from qin

# import qudi.logic.ODMR_nops as odmr; importlib.reload(odmr)
from qudi.util.mutex import Mutex


# from qudi.logic.currentmeasurement.current_measurement import CurrentMeasurementLogic # Voltage and Current measurements
# from logic.biaslogic import BiasLogic
class ScriptQueueStep:
    """Single queued userscript entry used for display and execution metadata."""

    def __init__(self, name: str, pd: Dict[str, Any]) -> None:
        self.name = name
        self.pd = pd


class ScriptQueueList(collections.abc.MutableSequence):
    """Append/pop-only list wrapper that notifies the owning queue logic."""

    def __init__(self, oktypes: Any, list_owner: Any, *args: Any) -> None:
        self.oktypes = oktypes
        self.list_owner = list_owner
        self._list = list()
        self.extend(list(args))

    @property
    def list(self) -> List[ScriptQueueStep]:
        return self._list

    @list.setter
    def list(self, val: List[ScriptQueueStep]) -> None:
        """
        Replace the visible queue contents while keeping GUI notifications in sync.

        This is intentionally simple and may call ``script_queue_changed`` more
        than once, which is acceptable for the small queue sizes used here.
        """
        self._list = []
        if len(val) == 0:
            self.list_owner.script_queue_changed()
        else:
            try:
                for i in val:
                    self.append(i)
            except Exception:
                self._list = []
                self.list_owner.script_queue_changed()
                exc_type, exc_value, exc_tb = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_tb)

    def check(self, val: Any) -> None:
        if not isinstance(val, self.oktypes):
            raise TypeError("list item {} is not allowed, as it can not be found in {}".format(val, self.oktypes))

    # def check_duplicate(self, v):
    #     duplicates = [item.name for item in self.list if item.name == v.name]
    #     if len(duplicates) > 0:
    #         raise Exception('Error: {}, {}, {}'.format(duplicates, self.list, v))

    def set_parent(self, v: Any) -> None:
        v.parent = self.list_owner

    def __len__(self) -> int:
        return len(self.list)

    def __getitem__(self, i: int) -> ScriptQueueStep:
        return self.list[i]

    def __delitem__(self, i: int) -> None:
        del self.list[i]
        self.list_owner.script_queue_changed()

    def __setitem__(self, i: int, v: ScriptQueueStep) -> None:
        raise NotImplementedError
        # self.check(v)
        # self.check_duplicate(v)
        # self.list[i] = v
        # self.list_owner.script_queue_changed(i, v)

    def insert(self, i: int, v: ScriptQueueStep) -> None:
        if i != len(self.list):
            raise Exception("Only appending and popping items allowed")
        self.check(v)
        # self.check_duplicate(v)
        self.list.insert(i, v)
        self.list_owner.script_queue_changed()

    def __str__(self) -> str:
        return str(self.list)

    def __repr__(self) -> str:
        return str(self.list)


from qudi.logic.transition_tracker import TransitionTracker
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.hardware.OPX.OPX_holder import OPX
from qudi.hardware.picoquant.ppg512 import PPG512
from qudi.logic.magnetlogic import MagnetLogic
from qudi.logic.ple.ple_scanner_logic import PLEScannerLogic
from qudi.logic.ple.optimize_logic import PLEOptimizeScannerLogic
from qudi.logic.AO_logic import AOLogic
from qudi.hardware.wavemeter.high_finesse_wavemeter import HighFinesseWavemeter
from qudi.hardware.laser.toptica_dl_pro import DlProLaser
from qudi.hardware.interfuse.switch_combiner_interfuse import SwitchCombinerInterfuse


class queue_logic(GenericLogic):
    """Timer-driven scheduler for dynamically loaded queue userscripts.

    The queue keeps two parallel structures:
    - ``self.q`` stores runnable task dictionaries for execution.
    - ``self._script_queue`` stores GUI-facing queue entries.
    """

    # declare connections
    # McasHolder = Connector(interface="McasDictHolderInterface")
    OpxHolder_connector = Connector(interface="OPX")
    TransitionTracker_connector = Connector(interface="TransitionTracker")
    Confocal_connector = Connector(interface="ScanningProbeLogic")
    GatedCounter_connector = Connector("GatedCounter")
    Optimizer_connector = Connector("ScanningOptimizeLogic")
    FastCounter_connector = Connector(interface="TT")
    PleOptimizeLogic_connector = Connector(interface="PLEOptimizeScannerLogic")
    PleScannerLogic_connector = Connector(interface="PLEScannerLogic")
    MagnetLogic_connector = Connector(interface="MagnetLogic")
    PPG_connector = Connector(interface="PPG512")
    counterlogic1_connector = Connector(interface="TimeTaggerLogic")
    Wavemeter_connector = Connector(interface="HighFinesseWavemeter")
    DlcPro620_connector = Connector(interface="DlProLaser")
    PowerCalibrationLogic_connector = Connector(interface="AOMPowerCalibrationLogic")
    NuclearOpsOPXUtils_connector = Connector(interface="NuclearOpsOPXUtils")
    AOLogic_connector = Connector(interface="AOLogic")
    Switches_connector = Connector(interface="SwitchCombinerInterfuse")

    update_selected_user_script_combo_box_signal = pyqtSignal(collections.OrderedDict)
    update_queue_list = pyqtSignal(collections.OrderedDict)
    user_script_list = misc.ret_property_array_like_typ("user_script_list", str)
    guis = []  # stores names of all open guis (later on used to dump them periodically)
    _StopTimeout = 60.0

    __TIME_FORMAT_STR__ = "%Y%m%d-h%Hm%Ms%S"
    
    
    awg: OPX
    transition_tracker: TransitionTracker
    gated_counter: Any
    optimizer: Any
    ple_optimize_logic: PLEOptimizeScannerLogic
    ple_scanner_logic: PLEScannerLogic
    magnet_logic: MagnetLogic
    ppg: PPG512
    _counter: Any
    fast_counter_device: Any
    wavemeter: HighFinesseWavemeter
    dlc_pro_620: DlProLaser
    ao: AOLogic
    do: SwitchCombinerInterfuse

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        super(queue_logic, self).__init__(config=config, **kwargs)
        self._threadlock = Mutex()
        self.script_history: List[Dict[str, Any]] = []
        self.timer = QTimer(self)
        self.thread = None
        self._shutting_down = False

        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.mainloop_handler)
        self._user_script_folder: Optional[str] = None

    def on_activate(self) -> None:
        """Resolve module connectors and start the timer-driven queue runtime."""
        self._shutting_down = False

        # self._awg = self.mcas_holder()
        self.awg = self.OpxHolder_connector()
        self.transition_tracker = self.TransitionTracker_connector()
        self.gated_counter = self.GatedCounter_connector()
        self.optimizer = self.Optimizer_connector()
        self.ple_optimize_logic = self.PleOptimizeLogic_connector()
        self.ple_scanner_logic = self.PleScannerLogic_connector()
        self.magnet_logic = self.MagnetLogic_connector()
        self.ppg = self.PPG_connector()

        self._counter = self.counterlogic1_connector()  #
        self.fast_counter_device = self.FastCounter_connector()
        self.wavemeter = self.Wavemeter_connector()  # type: HighFinesseWavemeter
        self.dlc_pro_620 = self.DlcPro620_connector()
        self.ao = self.AOLogic_connector()
        self.do = self.Switches_connector()
        self.nuclear_ops_opx_utils = self.NuclearOpsOPXUtils_connector()
        # self.create_odmr()  #only logic (no gui)
        self.init_run()
        # self.write_standardawg_sequences()
        self.confocal = self.Confocal_connector()
        self.tt = self.transition_tracker
        self.power_calibration_logic = self.PowerCalibrationLogic_connector()
        self.tt.load_rabi_parameters()

    def on_deactivate(self) -> None:
        """Stop the queue gently and request cooperative abort of active work."""
        if self._shutting_down:
            return

        self._shutting_down = True
        self.log.info("Shutting down queue logic.")

        if hasattr(self, "timer"):
            self.timer.stop()

        self._set_stop_request()
        self._clear_pending_queue(update_gui=False, keep_current=True)

        if hasattr(self, "_gui"):
            self._gui = None

        @property
        def md(self):
            return self._mcas_dict  #

        @property
        def gui(self):
            return self._gui

    # def restart_timetagger(self):
    #     import TimeTaggerHandler
    #     reload(TimeTaggerHandler)
    #     self._timetagger = TimeTaggerHandler.init_timetagger()

    def init_run(self) -> None:
        """Create the queue containers and start the periodic scheduler timer."""
        self.user_script_folder = r"C:\Users\yy3\git\squdi\src\qudi\UserScripts\electron_t2"  # r"C:/src/qudi/notebooks/UserScripts/electron_t2"
        self._script_queue = ScriptQueueList(oktypes=(ScriptQueueStep), list_owner=self)
        # ``self.q`` is the authoritative execution queue.
        self.q = Queue()
        self.timer.start()
        self.run_thread()
        # self.track_memory_usage_thread()

    @property
    def script_queue(self) -> ScriptQueueList:
        return self._script_queue

    @property
    def nowstr(self) -> str:
        return datetime.datetime.now().strftime("%Y%m%d-h%Hm%Ms%S")

    @property
    def nowstr_colon(self) -> str:
        return datetime.datetime.now().strftime("%Y/%m/%d-%H:%M:%S")

    @property
    def nowstr_pd(self) -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d-%H:%M:%S")

    @property
    def awgs(self):
        return self._mcas_dict.awgs

    ####################################################################################################################
    # dump and restore
    ####################################################################################################################

    def persistent_file_name(self, model: Any) -> str:
        if hasattr(model, "pi3d_dump_filename"):
            return self.log_dir + model.pi3d_dump_filename
        return self.log_dir + str(model.__class__).replace(">", "").replace("<", "") + ".pyd"  # windows does not allow '>' and '<' in filenames

    #
    def restore(self, model: Any, fp: Optional[str] = None) -> None:
        """Restore a serialized model state from disk into ``model``."""
        filename = self.persistent_file_name(model) if fp is None else fp

        if os.access(filename, os.F_OK):

            self.log.info("Restoring state of " + model.__str__() + "\nfrom " + filename + "..")

            try:
                a = pickle.load(open(filename, "rb"))
                a = a if type(a) is dict else a.__getstate__()
                model.set_items(a)
                self.log.info("[DONE1]")

            except Exception as inst:
                self.log.exception(str(inst))
                self.log.warning("[FAILED]")
                raise inst

    def dump(self, model: Any) -> None:
        """Persist the current state of ``model`` into the queue log folder."""
        filename = self.persistent_file_name(model)
        self.log.info(
            "attempting to save state of " + model.__str__() + "\nto " + filename + "..",
        )
        try:
            fil = open(filename, "wb")
            pickle.dump(model.__getstate__(), fil)
            fil.close()
            self.log.info("[DONE]")
        except Exception:
            self.log.exception(str(Exception))
            self.log.warning("[FAILED]")

    # @property
    # def current_nuclear(self):
    #     l = [i for i in self.__dict__ if 'Nuclear' in i]
    #     df = pd.DataFrame({'attr_name': l, 'date': [datetime.datetime.strptime(i[-17:], '%Y%m%dh%Hm%Ms%S') for i in l]})
    #     return getattr(self, df[df['date'] == df['date'].max()].iloc[0, 0])

    @property
    def script_module_names(self) -> List[str]:
        return [i for i in sys.modules if "__script__" in i]

    @property
    def last_running_script_name(self) -> Union[int, str]:
        """Return the currently active userscript module name.

        Stale ``__script__...`` modules left in ``sys.modules`` are ignored on
        purpose. Only the module referenced by ``current_script`` is considered
        active queue work.
        """
        if not hasattr(self, "current_script"):
            return -1

        module_name = self.current_script["module_name"]
        if module_name not in sys.modules:
            return -1

        return module_name

    @property
    def cun_modules(self) -> Optional[Any]:
        """Return the active userscript module if it still exposes ``nuclear``."""
        lrs = self.last_running_script_name
        if lrs == -1:
            return None
        if hasattr(sys.modules[lrs], "nuclear"):
            return sys.modules[lrs]
        return None

    @property
    def cun(self) -> Optional[Any]:
        """Return the active ``NuclearOPs``-like object for the current script."""
        if self.cun_modules is None:
            return None
        else:
            return self.cun_modules.nuclear

    def track_memory_usage(self) -> None:
        while True:
            self.save_value_to_file(self.current_memory_usage(), "memory_mb")
            # CAREFUL WITH THREADING AND WRITING TO SAME HDF FILE self.save_values_hdf(classifier='memory_mb', vd=dict(none=self.current_memory_usage()))
            # possible solution: https://stackoverflow.com/questions/22522551/pandas-hdf5-as-a-database
            QtTest.QTest.qSleep(5000)  # time.sleep(5)

    # def current_memory_usage(self):
    #     print(os.getpid())
    #     p = psutil.Process(os.getpid())
    #     return p.memory_info()[0] / 1024.
    #
    # def track_memory_usage_thread(self):
    #     self.tmu_thread = threading.Thread(target=self.track_memory_usage)
    #     self.tmu_thread.stop_request = multiprocess.Event()
    #     self.tmu_thread.start()

    def script_queue_changed(self) -> None:
        self.update_script_queue_table_data()

    @property
    def script_queue_table_data(self):
        return self._script_queue_table_data

    def update_script_queue_table_data(self) -> None:
        """Rebuild the queue-table payload and publish it to the GUI."""
        out = collections.OrderedDict([("name", []), ("pd", [])])
        for ridx, i in enumerate(self.script_queue):
            for cidx, attr_name in enumerate(["name", "pd"]):
                out[attr_name].append(getattr(i, attr_name))
        self._script_queue_table_data = out
        if hasattr(self, "_gui"):  # this is the problem.
            self.gui.update_script_queue_table_data(self.script_queue_table_data)
        self.update_queue_list.emit(self.script_queue_table_data)

    ####################################################################################################################
    # script queue
    ####################################################################################################################

    def run_new(self) -> None:
        """
        Legacy placeholder thread target.

        The queue itself is driven by ``self.timer``. The auxiliary thread still
        exists because its ``stop_request`` event is passed into userscripts as
        the cooperative abort flag.
        """
        pass
        # self.timer.start()

    def mainloop_handler(self) -> None:
        """Single scheduler tick.

        The timer repeatedly calls this method to:
        1. process a stop request,
        2. inspect the currently running userscript, or
        3. start the next queued script.
        """
        if not hasattr(self, "q"):
            return

        stop_requested = self.thread is not None and self.thread.stop_request.is_set()

        # print('mainloop NOPS QUEUE watcher..')
        if stop_requested:
            # Clear all queued-but-not-started work. The currently running script
            # is left in place so it can notice the abort event and exit cleanly.
            print("stop request")
            self._clear_pending_queue(update_gui=not self._shutting_down, keep_current=True)
            if self._shutting_down:
                return
            if not hasattr(self, "current_script"):
                self.thread.stop_request.clear()
                return

        if self._shutting_down:
            return

        try:
            if hasattr(self, "current_script"):
                # ``cun`` is the NuclearOPs-like object created by the active
                # userscript module. Its ``state`` tells the queue whether that
                # run is still executing or can be finalized.
                cun = self.cun
                if cun is None or cun.state not in ["run", "sequence_testing"]:
                    print("its finished, fininishing ")
                    self.finish_measurement()
                    if stop_requested:
                        self.thread.stop_request.clear()
                        return
                    self.start_next_measurement()
                else:
                    print("CUN state is " + cun.state + " doing nothing...")
                    pass
                    # print('There is a cun but it is workin, check you later...')
                    # we need to wait...
            else:
                if self.q.empty():
                    return
                print("starting a new measurements")
                self.start_next_measurement()
                # waiting for the measurement to finish.

        except Exception as e:
            print(e)
            self._clear_pending_queue(update_gui=not self._shutting_down, keep_current=True)
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)
            self.finish_measurement()
        """
        This should do what previously was in while loop of the run old function
        :return: 
        """

    def start_next_measurement(self) -> bool:
        """Pop the next queued task and call its ``run_fun`` entry point."""
        if self._shutting_down:
            return False

        try:
            self.current_script = self.q.get_nowait()
        except Empty:
            return False

        stop_request = self.thread.stop_request if self.thread is not None else multiprocess.Event()
        stop_request.clear()  # this is necessary although it shouldn't be.
        self.log.info(
            "Starting Userscript {}...{}".format(
                self.current_script["module_name"][10:],
                stop_request.is_set(),
            )
        )
        # Userscripts are loaded dynamically with unique module names and must
        # provide a ``run_fun(stop_request, queue=self, **pd)`` entry point.
        sys.modules[self.current_script["module_name"]].run_fun(stop_request, queue=self, **self.current_script["pd"])  ## Creates a nuclear and runs it.!!!
        print("entering waiting loop in queue...")

        ### Here the queue should wait for the measurement to be finished...# TODO signal replacement for the future...
        return True

    def wait_for_a_measurement(self) -> None:
        """
        Legacy blocking wait helper kept for reference.

        The active implementation uses the non-blocking timer scheduler instead.
        """
        if hasattr(self, "cun"):
            while self.cun.state == "run":
                QtTest.QTest.qSleep(1000)  # This is Qt version for time.sleep to prevent freezinng. also doesnt work for PySide2.
            else:
                print("new measurement can be started")
        else:
            pass

    def finish_measurement(self) -> None:
        """Finalize bookkeeping for the active userscript and unload its module."""
        if not hasattr(self, "current_script"):
            self.log.debug("finish_measurement called without an active current_script.")
            return

        module_name = self.current_script["module_name"]
        try:
            self.script_queue.pop(0)
            self.script_history.append(self.current_script)
            self.log.info("Userscript {} has finished...".format(module_name[10:]))
            del self.current_script
            self.q.task_done()

        except IndexError:
            print("no more scripts in the queue..")
            return
        finally:
            sys.modules.pop(module_name, None)

    def run_old(self) -> None:
        """Legacy blocking queue implementation retained for comparison/debugging."""

        ## Why this is needed??????

        # from tools_2 import emod
        # emod.JobManager().start() ## maybe this is something which makes multiple sequences actuakly working.
        # start the CronDaemon
        # from tools_2 import cron
        # cron.CronDaemon().start()
        self.dummy_test_variable = 123

        while True:
            if self.thread.stop_request.is_set():
                self.q.queue.clear()
                self.script_queue.list = []
                self.thread.stop_request.clear()
            try:  ### runs the measurement!
                self.current_script = self.q.get()
                self.thread.stop_request.clear()  # this is necessary although it shouldn't be.
                self.log.info(
                    "Starting Userscript {}...{}".format(
                        self.current_script["module_name"][10:],
                        self.thread.stop_request.is_set(),
                    )
                )
                sys.modules[self.current_script["module_name"]].run_fun(self.thread.stop_request, queue=self, **self.current_script["pd"])  ## Creates a nuclear and runs it.!!!
                print("entering waiting loop in queue...")

                ### Here the queue should wait for the measurement to be finished...# TODO signal replacement for the future...

                if hasattr(self, "cun"):
                    while self.cun.state == "run":
                        QtTest.QTest.qSleep(1000)  # 1000  # This is Qt version for time.sleep to prevent freezinng.
                        print("waaaaaaaiiittt")
                    else:
                        print("new measurement can be started")
                else:
                    pass

                self.script_history.append(self.current_script)
                self.script_queue.pop(0)
                self.log.info("Userscript {} has finished...".format(self.current_script["module_name"][10:]))
                del self.current_script
                self.q.task_done()
            except Exception:  # Not running the measurement.
                self.q.queue.clear()
                self.script_queue.list = []
                exc_type, exc_value, exc_tb = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_tb)

    def run_thread(self) -> None:
        """Create the auxiliary thread object that stores the stop event."""
        self.thread = threading.Thread(target=self.run_new)
        self.thread.stop_request = multiprocess.Event()
        self.thread.start()

    def _set_stop_request(self) -> None:
        """Set the cooperative abort event seen by active userscripts."""
        if self.thread is not None:
            self.thread.stop_request.set()

    def _clear_pending_queue(self, update_gui: bool = True, keep_current: bool = False) -> None:
        """Remove queued jobs that have not started yet.

        Parameters
        ----------
        update_gui:
            When ``True``, rebuild the visible queue table immediately.
        keep_current:
            When ``True``, preserve the currently running script as the first
            queue entry while dropping everything behind it.
        """
        if hasattr(self, "q"):
            while True:
                try:
                    self.q.get_nowait()
                except Empty:
                    break
                else:
                    self.q.task_done()

        if not hasattr(self, "_script_queue"):
            return

        remaining_steps = []
        if keep_current and hasattr(self, "current_script") and len(self._script_queue) > 0:
            remaining_steps = [self._script_queue[0]]

        if update_gui:
            self.script_queue.list = remaining_steps
        else:
            self._script_queue._list = list(remaining_steps)
            self._script_queue_table_data = collections.OrderedDict(
                [
                    ("name", [step.name for step in remaining_steps]),
                    ("pd", [step.pd for step in remaining_steps]),
                ]
            )

    def set_user_script_list(self) -> None:
        """Scan the selected user-script folder and refresh the combo-box list."""
        file_list = []
        unwanted_files = ["__init__.py", "refocus_confocal_odmr.py"]
        for files in os.listdir(self.user_script_folder):
            if files.endswith(".py") and not files in unwanted_files:
                file_list.append(str(files.split(".")[0]))
        self._user_script_list = file_list
        if len(self.user_script_list) > 0:
            self._selected_user_script = self.user_script_list[0]
            # if hasattr(self, '_gui'):
            val = collections.OrderedDict(
                [
                    ("user_script_list", self.user_script_list),
                    ("selected_user_script", self.selected_user_script),
                ]
            )
            # self.update_selected_user_script_combo_box(val)
            # Instead emit a signal which will updates it.
            self.update_selected_user_script_combo_box_signal.emit(val)

    @property
    def selected_user_script(self) -> str:
        return self._selected_user_script

    @selected_user_script.setter
    def selected_user_script(self, val: str) -> None:
        if val != "":
            if val not in self.user_script_list:
                raise Exception("Script {} not in {}".format(val, self.user_script_list))
            self._selected_user_script = val
            # if hasattr(self, '_gui'):
            val = collections.OrderedDict([("selected_user_script", self.selected_user_script)])
            self.update_selected_user_script_combo_box_signal.emit(val)
            # self.gui.update_selected_user_script_combo_box(val)

    @property
    def user_script_params(self) -> Dict[str, Any]:
        return getattr(self, "_user_script_params", {})

    @user_script_params.setter
    def user_script_params(self, val: Dict[str, Any]) -> None:
        self.user_script_params = misc.check_type(val, "user_script_params", dict)

    @property
    def user_script_folder(self) -> Optional[str]:
        return self._user_script_folder

    @user_script_folder.setter
    def user_script_folder(self, val: str) -> None:
        if os.path.isdir(val):
            print(val, "is a current folder opened for scripts...")
            self._user_script_folder = val
            self.set_user_script_list()
            # This now is done in gui automatically.
            # if hasattr(self, '_gui'):
            # self.gui.update_user_script_folder_text_field(val)
        else:
            print(val, "not a valid dir, cant open it right now")

    def add_to_queue(
        self,
        name: Optional[str] = None,
        pd: Optional[Dict[str, Any]] = None,
        folder: Optional[str] = None,
    ) -> None:
        """Load a userscript module and append it to the execution/UI queues."""
        # self.confocal.counter_state = 'idle'
        # self.md.stop_awgs()
        folder = self.user_script_folder if folder is None else folder
        name = self.selected_user_script if name is None else name
        pd = self.user_script_params if pd is None else pd
        if name == "":
            return
        try:
            module_name = self.init_task(name, folder)
            self.q.put({"module_name": module_name, "pd": pd})
            self.script_queue.append(ScriptQueueStep(module_name[10:], self.user_script_params))
        except Exception:
            print("Queuelogic: Could not add script to queue.")
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)

    def add_rco(self) -> None:
        """Queue the legacy refocus helper script."""
        folder = r"C:\src\qudi\notebooks\UserScripts"
        print("I am here", "who has called me?")
        name = "refocus_confocal_odmr"
        pd = self.user_script_params
        self.add_to_queue(name, pd, folder)

    def in_script_queue(self, name: str) -> bool:
        for step in self.script_queue:
            if step.name == name:
                return True
        else:
            return False

    def evaluate(self) -> None:
        raise NotImplementedError
        # name = self.selected_user_script
        # pd = self.user_script_params
        # if self.in_script_queue(name):
        #     raise Exception("Running the 'evaluate' function of a script is only possible when its 'run_fun' is not running.")
        # else:
        #     self.get_user_script(name).evaluate(**pd)

    def remove_last_script(self) -> None:
        """Remove the most recently queued script that has not started yet."""
        if self.q.qsize() > 0:
            del self.script_queue[-1]
            try:
                self.q.get_nowait()
            except Empty:
                pass
            else:
                self.q.task_done()

    def create_odmr(self) -> None:

        self.odmr = odmr.ODMR(self)

    def init_task(self, name: str, folder: Optional[str] = None) -> str:
        """Import a userscript file under a unique ``__script__...`` module name."""
        folder = self.user_script_folder if folder is None else folder
        funa = "{}/{}.py".format(folder, name)
        task_name = "__script__{}_{}".format(self.nowstr, name)
        _ = imp.load_source(task_name, funa)
        return task_name

    def set_stop_request(self) -> None:
        """Public slot used by the queue GUI stop button."""
        self._set_stop_request()

    def write_standard_awg_sequences(self) -> None:
        """Queue the helper script that writes standard AWG sequences."""
        self.add_to_queue(
            "standard_awg_sequences",
            folder=r"C:\src\qudi\notebooks\UserScripts\helpers",
        )

    def dl(self, key: str, *args: Any, **kwargs: Any) -> Any:
        return self._mcas_dict[key].dl(*args, **kwargs)

    def save_pi3diamond(self, destination_dir: str) -> None:
        """Archive the current source tree into ``destination_dir``."""
        src = os.getcwd()
        f = "{}/qudi.zip".format(destination_dir)
        if not os.path.isfile(f):
            zf = zipfile.ZipFile(f, "a")
            for root, dirs, files in os.walk(src):
                if (
                    (
                        not any(
                            [
                                i in root
                                for i in [
                                    "__pycache__",
                                    "awg_settings",
                                    "currently_unused",
                                    ".idea",
                                    ".hg",
                                    "UserScripts",
                                    "log",
                                    "notebooks",  # FIXME - include logic, explode heavy stuff.
                                ]
                            ]
                        )
                    )
                    or root.endswith("transition_tracker_log")
                    or root.endswith("helpers")
                ):
                    for file in files:
                        if any([file.endswith(i) for i in [".py", ".dat", ".ui"]]):
                            zf.write(
                                os.path.join(root, file),
                                os.path.join(
                                    root.replace(os.path.commonprefix([root, src]), ""),
                                    file,
                                ),
                            )
            zf.close()
