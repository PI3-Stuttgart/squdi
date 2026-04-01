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
        sequence_name = "init sweep" if sequence_name is None else sequence_name
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg, ou=ou)

        qua_array_1 = [0]  # ou.get_fast_sweep_qua_array(0)
        qua_array_2 = [0]  # ou.get_fast_sweep_qua_array(1)
        with qua.program() as myprog:
            with infinite_loop_():

                ou.init_program()

                readout_transition = current_iterator_df["readout_transition"].unique()[0]

                with for_(*from_array(ou.i_1, qua_array_1)):
                    with for_(*from_array(ou.i_2, qua_array_2)):
                        sna.crc(mcas, probe_power="Laser_620_pi_power_crc", probe_2_power="Laser_620_pi_power_crc")
                        # set laser power
                        ou.set_laser_power("Laser_620_pi", "Laser_620_pi_power_init")
                        ou.set_laser_power("Laser_620", "Laser_620_power_init")
                        align()
                        wait(500 * u.us)
                        # Init state 2 (by pumping B2)
                        ou.laser_pulse("Laser_620", "state_2_init_len")
                        align()
                        wait(500 * u.us)
                        # Init state 1 (by pumping A1) (sweep)
                        ou.laser_pulse("Laser_620_pi", "state_1_init_len")
                        align()
                        ou.set_laser_power("Laser_620_pi", "Laser_620_pi_power_readout")
                        ou.set_laser_power("Laser_620", "Laser_620_power_readout")
                        align()
                        wait(500 * u.us)

                        # Spin readout
                        ou.gate_trigger()  # A1 or B2
                        if readout_transition == "A1":
                            ou.laser_pulse("Laser_620", "SSR_redout_len")
                        elif readout_transition == "B2":
                            ou.laser_pulse("Laser_620_pi", "SSR_redout_len")
                        align()
                        ou.memory_trigger()
                        align()
                        ou.set_laser_power("Laser_620_pi", "Laser_620_pi_power_crc")
                        ou.set_laser_power("Laser_620", "Laser_620_power_crc")
                        wait(500 * u.us)

                        # Charge state readout
                        ou.gate_trigger()  # Both - Csr but reecorded.
                        ou.multiple_laser_pulses(["Laser_620", "Laser_620_pi"], "csr_redout_len")
                        align()
                        ou.memory_trigger()
                        align()

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    # ana_seq = [["init", ">", 0, 1, 1, 1], ["result", ">", 1, 1, 1, 1], ["init", ">", 1, 1, 1, 1]]  # Put "int(_I_['n_ssr']" as nlp_per_point?
    ana_seq = [["result", ">", 2, 1, 1, 1], ["init", ">", 15, 1, 1, 1]]
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
    nuclear.no_trace = False  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = True
    nuclear.ple_refocus_interval = 30

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 2000

    init_pump_len = np.linspace(1, 200, 10) * 1e3  # ns
    B_amp = np.arange(200, 300, 5)  # mT
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [0]),
            # ("B_theta", [0]),
            # ("B_amp", B_amp),
            ("sweeps", range(1)),
            ("Laser_620_power_init", [50]),
            ("Laser_620_pi_power_init", [100, 150, 200, 250]),
            ("Laser_620_power_readout", [100]),  # nW
            ("Laser_620_pi_power_readout", [100]),  # nW
            ("Laser_620_power_crc", [50]),  # nW
            ("Laser_620_pi_power_crc", [100]),
            ("click_channel", [3]),  # nW
            ("state_1_init_len", init_pump_len),
            ("SSR_redout_len", [1e6]),
            ("state_2_init_len", [3e6]),
            ("csr_redout_len", [1e6]),
            ("pulse_shape_ppg", ["continuous_sin"]),  # string
            ("pulse_width_ppg", [20]),  # ns
            ("readout_transition", ["A1", "B2"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = 1
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
