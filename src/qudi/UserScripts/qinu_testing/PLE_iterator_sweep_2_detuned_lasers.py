# coding=utf-8

import importlib
import qudi.UserScripts.helpers.sequence_creation_helpers as sch

importlib.reload(sch)

import qudi.UserScripts.helpers.shared as shared

importlib.reload(shared)

import qudi.UserScripts.helpers.shared as ush

importlib.reload(ush)

import qudi.UserScripts.helpers.snippets_awg as sna

importlib.reload(sna)

import qudi.hardware.OPX.program_container as pc

importlib.reload(pc)
import qudi.hardware.OPX.OPX_utils as OPX_utils

importlib.reload(OPX_utils)

from qudi.logic.qudip_enhanced import *

import os
from collections import OrderedDict
from qm import qua
from qm.qua import play, declare, fixed, for_, align, amp, infinite_loop_, wait

from qualang_tools.units import unit
from qualang_tools.loops import from_array
from qudi.logic.NuclearOPs import NuclearOPs
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils


### Setup the sequence and the measurement ###
u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear: NuclearOPs = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        """This function creates the sequence for the current itterator and returns the mcas object with the sequence programmed in it."""
        sequence_name = "PLE_itterator 2" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg)
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils

        def chk_i(key):
            if key == nuclear.sweep_keys_OPX[0]:
                return i_1
            if len(nuclear.sweep_keys_OPX) == 2:
                if key == nuclear.sweep_keys_OPX[1]:
                    return i_2
            else:
                return current_iterator_df[key].unique()[0]

        with qua.program() as myprog:
            with infinite_loop_():

                j_back = declare(int)
                i_1 = declare(fixed)
                i_2 = qua.declare(fixed)
                i_back = qua.declare(fixed)

                #
                ou.set_laser_power("620_pi_w_power", chk_i("AOM_620_pi_power"))
                ### Backscan ###
                with for_(*from_array(i_back, nuclear.i_1_array[::-1])):
                    ou.set_laser_voltage("LaserScanner_red", i_back)
                    ou.laser_pulse("Laser_520", chk_i("backscan_len_pixel"), chk_i("repump_laser_power"))
                    align()

                wait(1 * u.s)
                ### PLE loop ###
                with for_(*from_array(i_1, nuclear.i_1_array)):
                    with for_(*from_array(i_2, nuclear.i_2_array)):
                        ou.set_laser_frequency("LaserScanner_red", chk_i("Laser_freqs_MHz"))

                        ou.gate_trigger()
                        align()
                        ou.multiple_laser_pulses(laser_names=["AOM_620", "620_pi_w_power"], duration_ns=chk_i("readout_len_pixel"), powers_nw=[chk_i("620_laser_power"), None])
                        align()
                        ou.memory_trigger()

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [
        ["result", ">", -1, 1, 1, 1],  # Put "int(_I_['n_ssr']" as nlp_per_point?
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
    # nuclear.analyze_type = 'consecutive'
    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = True  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = False  # not used

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 1

    laser_freq_vec_MHz = np.linspace(-2, 3, 1000) * 1e3  # GHz -> MHz
    B_amp = np.arange(200, 290, 2)  # mT
    nuclear.parameters = OrderedDict(
        (
            ("B_phi", [0]),
            ("B_theta", [0]),
            ("B_amp", B_amp),
            ("sweeps", range(3)),
            ("620_laser_power", [5]),  # nW
            ("repump_laser_power", [1e6]),  # nW
            ("Laser_freqs_MHz", laser_freq_vec_MHz),
            ("click_channel", [3]),
            ("readout_len_pixel", [5_000_000]),  # ns
            ("backscan_len_pixel", [2_000_000]),  # ns
            ("pulse_shape_ppg", ["gaussian"]),  # string
            ("pulse_width_ppg", [20]),  # ns
            ("AOM_620_pi_power", [100.7]),  # nW
        )
    )
    nuclear.number_of_simultaneous_measurements = len(laser_freq_vec_MHz)
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=len(laser_freq_vec_MHz) * nr_repeating_intergration,
    )


def run_fun(abort, **kwargs):
    print(1, "Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue.gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
