# coding=utf-8

import importlib
import qudi.UserScripts.helpers.sequence_creation_helpers as sch

importlib.reload(sch)
import qudi.UserScripts.helpers.shared as shared
from qudi.UserScripts.OPX_snippets.OPX_utils import crc, scan_laser_to_target

# from qudi.hardware.Keysight_AWG_M8190.pym8190a import MultiChSeq as MultiChSeq
import qudi.hardware.OPX.program_container as pc

importlib.reload(pc)
# from qudi.hardware.OPX.program_container import MultiChSeq as MultiChSeq; importlib.reload(MultiChSeq)
import qudi.UserScripts.helpers.snippets_awg as sna

importlib.reload(sna)
importlib.reload(shared)
import os
from qm.qua import *

# importlib.reload(MultiChSeq)
import qudi.UserScripts.helpers.shared as ush

importlib.reload(ush)
from qudi.logic.qudip_enhanced import *
import qudi.hardware.Keysight_AWG_M8190.elements as E
from collections import OrderedDict
from qm.grpc.qua import QuaProgramArrayVarRefExpression, QuaProgramVarRefExpression
from qm.qua import *
from qm import QuantumMachinesManager
from qm.qua._expressions import QuaVariable

# from configuration import *
from qualang_tools.units import unit
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results import progress_counter, fetching_tool
from qualang_tools.loops import from_array

u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()

__TAU_HALF__ = 2 * 192 / 12e3
__SAMPLE_FREQUENCY__ = 12e3  # e.__SAMPLE_FREQUENCY__
tt_trigger_len = 16 * u.ns

# Frequency vector

readout_len = 2 * u.ms  # Readout duration for this experiment
j_avg = 1000


# single_integration_time_ns = int(1000 * u.ns)
def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        sequence_name = "optical_power_rabi" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue._awg)  # , ch_dict={'2g': [1, 2], 'ps': [1]})

        def chk_i(key):
            if key == sweep_keys[0]:
                return i_1
            if len(sweep_keys) == 2:
                if key == sweep_keys[1]:
                    return i_2
            else:
                return current_iterator_df[key].unique()[0]

        slow_changing_parameters = ["B_amp", "B_theta", "B_phi"]
        sweeps = []
        sweep_keys = []
        for key in current_iterator_df.keys():
            if len(current_iterator_df[key].unique()) > 1 and key not in slow_changing_parameters:
                # sweeps[key]['key_first_apperance'] = int(df['delays_ps'][df['delays_ps'].isin([df['delays_ps'].unique()[1]])].dropna(how='all').index[0])
                sweeps.append(current_iterator_df[key].unique())
                sweep_keys.append(key)

        if len(sweep_keys) > 2:
            raise (ValueError("   has more then two axis to iterate over by the quantum machine, which is not supportet at the moment"))
        i_1_array = np.array([self.queue.tt.rp("laser_tuning", omega=i).amp for i in sweeps[0]]) if "MHz" in sweep_keys[0] else sweeps[0]
        i_2_array = (
            (np.array([self.queue.tt.rp("laser_tuning", omega=i).amp for i in sweeps[1]]) if "MHz" in sweep_keys[1] else sweeps[1])
            if len(sweep_keys) == 2
            else np.array([0])
        )

        # print(f"---------array_1: {i_1_array}")
        # print(f"---------array_2: {i_2_array}")

        with program() as myprog:
            with infinite_loop_():

                f = declare(int)  # frequencies
                j = declare(int)
                j_avg = declare(int, value=20)
                i_1 = declare(float)
                i_2 = declare(int)

                # set_dc_offset("LaserScanner_red", "single", chk_i("Laser_freq"))

                with for_each_(i_1, i_1_array):
                    with for_(*from_array(i_2, i_2_array)):
                        if chk_i("do_crc") == True:
                            crc(
                                volt_power_620=chk_i("crc_probe_power"),
                                volt_power_520=chk_i("crc_repump_power"),
                                crc_threshold=chk_i("crc_threshold"),
                                crc_threshold_repump=5,
                            )
                        set_dc_offset("620_pi_w_power", "single", chk_i("aom_attenuation"))
                        # play("pulse" * amp(chk_i("repump_laser_power")), "Laser_520", duration=100 * u.us)
                        # align all elements before starting the sequence
                        align()
                        play(pulse="trigit", element="620_pi", duration=16 * u.ns)
                        play("trigit", "Gate_Trigger", duration=100 * u.ns)
                        # wait(int(chk_i("delay_gate_trigger") / 4))
                        align()
                        # wait(int(chk_i("delay_memory_trigger") / 4))

                        play("trigit", "Memory_Trigger", duration=20 * u.ns)
                        wait(200 * u.ns)

        #!!! important!!!!
        self.queue._gated_counter.set_n_values(
            mcas=None, sm=1, n_values=len(i_1_array) * 10000
        )  # myqua, self.number_of_simultaneous_measurements) #calculating the number of gated counts on the timetagger.
        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [
        # ['init', '>', 1, 1, 100, 1],
        ["result", ">", 0, 1, 0, 1],  # >, th value, n_freqs, eexclusion, rep readouts number.  ###Put "int(_I_['n_ssr']" as nlp_per_point?
        # ['init', '>', 5, 0, 0, 1],
        # ['init', '>', 5, 1, 0, 1],
    ]
    # what does each entry do?
    # ana_seq[0]: ? 'result' or 'init', init - for postselection
    # ana_seq[1]: ? > or <
    # ana_seq[2]: "threshold"
    # ana_seq[3]: "nlp_per_point", number of laser pulses per point. N of repetitions.
    # ana_seq[4]: set to 100 --> no counts measured; set to 7 --> counts can be measured; --> delta - exclusion zone. n > threshold +delta, or n< threhold - delta.
    # ana_seq[5]: "number of results" --> ssr = cnot1 + laser1 + cnot2 + laser2, -> n=2, etc.. laser2-laser1,  histograms are centered around 0,
    sch.settings(
        nuclear=nuclear,
        ret_mcas=ret_ret_mcas(pdc),
        analyze_sequence=ana_seq,
        pdc=pdc,
        meas_code=meas_code,
    )

    nuclear.x_axis_title = "Freq [MHz]"

    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = True  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = True
    nuclear.ple_refocus_interval = 60

    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    # delay_vec = np.arange(20, 150, 1)
    aom_attenuation_vec = np.arange(-0.24, -0.2, 0.00025)
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [90]),
            # ("B_theta", [90]),
            # ("B_amp", [0, 5, 10, 15, 20, 25, 30]),
            ("sweeps", range(1000)),
            ("aom_attenuation", aom_attenuation_vec),
            # ("A2_power", [2]),
            # ("wait_dur", [0.512]),
            # ("init_time", [60]),
            # ("n_ssr1", [250]),
            # ("t_read", [100]),
            # ("t_repump", [50]),
            ("delay_memory_trigger", [20]),  # ns
            # ("delay_gate_trigger", [50]),  # ns
            # ("repump_laser_power", [nuclear.queue._power_calibration_logic.power_to_voltage(50e-6, "Laser_520")]),
            # ("aom_attenuation", np.arange(-0.24, 0, 0.1)),
            # ("duty_cycle", [0.5]),  # np.linspace(0.1,0.9,9)), #for laser power.
            # ("Laser_freq", [nuclear.queue._PLE_logic._scan_logic()._scanner()._triggered_ao().get_setpoint("LaserScanner_red") / 2]),
            # ("scanns", range(100)),
            ("click_channel", [2]),
            ("crc_repump_power", [nuclear.queue._power_calibration_logic.power_to_voltage(20e-6, "Laser_520")]),
            ("crc_probe_power", [nuclear.queue._power_calibration_logic.power_to_voltage(5e-9, "Laser_620")]),
            ("crc_threshold", [20]),
            ("crc_threshold_repump", [5]),
            ("do_crc", [False]),
            # ("readout", ["ssr"]),
            # ("repump", ["no"]),  # , "yes"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(aom_attenuation_vec)  # 4


def run_fun(abort, **kwargs):
    print(1, " Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue._gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
