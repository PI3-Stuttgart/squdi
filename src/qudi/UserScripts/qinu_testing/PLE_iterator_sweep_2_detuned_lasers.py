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
from qm.qua import play, set_dc_offset, declare, fixed, for_, align, amp, infinite_loop_

from qualang_tools.units import unit
from qualang_tools.loops import from_array
from qudi.logic.NuclearOPs import NuclearOPs


### Setup the sequence and the measurement ###
u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear: NuclearOPs = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()


### FIXME: Hardcoded parameters ###
tt_trigger_len = 20 * u.ns
j_avg = 1000


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        """This function creates the sequence for the current itterator and returns the mcas object with the sequence programmed in it."""
        sequence_name = "PLE_itterator 2" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg)

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

                j = declare(int)
                j_back = declare(int)
                i_1 = declare(fixed)
                i_2 = qua.declare(fixed)
                i_back = qua.declare(fixed)

                #
                set_dc_offset(
                    "620_pi_w_power",
                    "single",
                )

                ### Backscan ###
                with for_(*from_array(i_back, nuclear.i_1_array[::-1])):
                    set_dc_offset("LaserScanner_red", "single", i_back)
                    with for_(j_back, 0, j_back < j_avg, j_back + 1):
                        play(
                            "pulse" * amp(chk_i("repump_laser_power")),
                            "Laser_520",
                            duration=chk_i("backscan_len_pixel") * u.ns / j_avg,
                        )
                    align()

                ### PLE loop ###
                with for_(*from_array(i_1, nuclear.i_1_array)):
                    with for_(*from_array(i_2, nuclear.i_2_array)):
                        set_dc_offset("LaserScanner_red", "single", chk_i("Laser_freqs_MHz"))
                        play(
                            pulse="trigit",
                            element="Gate_Trigger",
                            duration=tt_trigger_len * u.ns,
                        )

                        with for_(j, 0, j < j_avg, j + 1):
                            play(
                                "pulse" * amp(chk_i("620_laser_power")),
                                "AOM_620",
                                duration=chk_i("readout_len_pixel") * u.ns / j_avg,
                            )
                            play(
                                pulse="trigit",
                                element="620_pi",
                                duration=chk_i("readout_len_pixel") * u.ns / j_avg,
                            )
                            # play("pulse" * amp(chk_i("repump_laser_power")), "Laser_520", duration=chk_i("readout_len_pixel")*u.ns / j_avg,)

                        align()
                        play(
                            pulse="trigit",
                            element="Memory_Trigger",
                            duration=tt_trigger_len * u.ns,
                        )

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    laserpower_to_v = nuclear.queue.power_conversion.convert_power_to_voltage
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

    laser_freq_vec_MHz = np.linspace(-10000, 10000, 2000)
    nuclear.parameters = OrderedDict(
        (
            ("B_phi", [0]),
            ("B_theta", np.arange(0, 365, 10)),
            ("B_amp", [0]),
            ("sweeps", range(2)),
            ("620_laser_power", [laserpower_to_v(20e-9, "AOM_620")]),
            ("repump_laser_power", [laserpower_to_v(50e-6, "Laser_520")]),
            ("Laser_freqs_MHz", laser_freq_vec_MHz),
            ("click_channel", [1]),
            ("readout_len_pixel", [10 * u.ms]),
            ("backscan_len_pixel", [5 * u.ms]),
            ("pulse_shape_ppg", ["square"]),  # string
            ("pulse_width_ppg", [20]),  # ns
            ("AOM_620_pi_power", [-1.6]),  # V
        )
    )
    nuclear.number_of_simultaneous_measurements = len(nuclear.i_1_array)
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=len(nuclear.i_1_array) * len(nuclear.i_2_array) * nr_repeating_intergration,
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
