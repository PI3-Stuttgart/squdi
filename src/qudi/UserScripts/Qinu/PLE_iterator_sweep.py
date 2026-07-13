# coding=utf-8

import importlib

import qudi.UserScripts.helpers.sequence_creation_helpers as sch

importlib.reload(sch)

import qudi.UserScripts.helpers.shared as shared

importlib.reload(shared)

import qudi.UserScripts.helpers.shared as ush

importlib.reload(ush)

# import qudi.UserScripts.helpers.snippets_awg as sna
import qudi.UserScripts.helpers.snippets_awg_OPX as sna

importlib.reload(sna)

import qudi.hardware.OPX.program_container as pc

importlib.reload(pc)
import qudi.hardware.OPX.OPX_utils as OPX_utils

importlib.reload(OPX_utils)

import os
from collections import OrderedDict

from qm import qua
from qm.qua import align, for_each_, infinite_loop_, set_dc_offset, wait
from qualang_tools.units import unit

from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.logic.NuclearOPs import NuclearOPs
from qudi.logic.qudip_enhanced import *

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
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg, ou=ou)

        use_crc = current_iterator_df["use_crc"].unique()[0]
        use_detuned_laser = current_iterator_df["use_detuned_laser"].unique()[0]

        qua_array_1 = ou.get_fast_sweep_qua_array(0)  # .astype(int)
        qua_array_2 = ou.get_fast_sweep_qua_array(1)  # .astype(int)
        with qua.program() as myprog:
            with infinite_loop_():
                ou.init_program()
                if use_crc:
                    set_dc_offset(
                        "Laser_620_freq", "single", self.queue.ao.get_setpoint("Laser_620_freq")
                    )
                    align()
                    wait(1 * u.us)
                    align()
                    sna.crc(mcas)

                if use_detuned_laser:
                    ou.set_laser_power("Laser_620_det", "Laser_620_det_power")
                ou.set_laser_power("Laser_620", "Laser_620_power")

                set_dc_offset("Laser_620_freq", "single", qua_array_1[0])

                ### PLE loop ###
                with for_each_(ou.i_1, qua_array_1):
                    with for_each_(ou.i_2, qua_array_2):
                        ou.set_laser_frequency("Laser_620_freq", "Laser_620_freq_MHz")
                        ou.gate_trigger()
                        ou.pause(100_000)
                        align()
                        if use_detuned_laser:
                            ou.multiple_laser_pulses(
                                laser_names=["Laser_620", "Laser_620_det"],
                                duration_ns="readout_len_pixel",
                            )  # , powers_nw=["Laser_620_power", "Laser_620_pi_power"])
                        else:
                            ou.laser_pulse("Laser_620", "readout_len_pixel")
                        align()
                        ou.pause(100_000)
                        ou.memory_trigger()
                        ou.pause(1_000)
                ou.laser_pulse("Laser_520", 1_000_000)

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [
        ["result", ">", 1, 1, 1, 1],  # Put "int(_I_['n_ssr']" as nlp_per_point?
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
    nuclear.save_smartly = False  # Doesnt save 0 in the trace only.
    nuclear.no_trace = True  # Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = False
    nuclear.lock_laser_to_wavemeter = False
    nuclear.ple_refocus_interval = 1 * 60

    # Confocal refocus
    nuclear.do_confocal_refocus_red = False
    nuclear.do_confocal_refocus_green = True
    nuclear.confocal_refocus_interval = 1 * 30

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 1

    laser_freq_vec_MHz = np.linspace(1.5, 3.5, num=300) * 1e3  # GHz -> MHz
    B_amp = np.arange(200, 300, 5)  # mT
    B_theta = np.arange(0, 360, step=5)
    nuclear.parameters = OrderedDict(
        (
            ("B_phi", [0]),
            ("B_theta", B_theta),
            ("B_amp", [150]),
            ("sweeps", range(2)),
            ("Laser_620_power", [6]),  # nW
            ("Laser_520_power_repump", [5e3]),  # nW (50uW)
            ("Laser_620_freq_MHz", laser_freq_vec_MHz),
            ("click_channel", [2]),
            ("readout_len_pixel", [int(5e6)]),  # ns (1ms)
            ("repump_len", [int(1000e6)]),  # ns (1s)
            # ("pulse_shape_ppg", ["continuous_sin"]),  # string
            # ("pulse_width_ppg", [20]),  # ns
            ("Laser_620_det_power", [10]),  # nW
            ("use_crc", [False]),
            ("use_detuned_laser", [False]),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(laser_freq_vec_MHz)
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=nuclear.number_of_simultaneous_measurements * nr_repeating_intergration,
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
