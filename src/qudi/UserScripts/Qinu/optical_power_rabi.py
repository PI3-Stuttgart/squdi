# coding=utf-8

import importlib
import os
from collections import OrderedDict

from qm import qua
from qm.qua import assign, declare, for_, if_, infinite_loop_
from qualang_tools.loops import from_array
from qualang_tools.units import unit

import qudi.hardware.OPX.OPX_utils as OPX_utils
import qudi.hardware.OPX.program_container as pc
import qudi.UserScripts.helpers.sequence_creation_helpers as sch
import qudi.UserScripts.helpers.shared as shared
import qudi.UserScripts.helpers.shared as ush

# import qudi.UserScripts.helpers.snippets_awg as sna
import qudi.UserScripts.helpers.snippets_awg_OPX as sna
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.logic.NuclearOPs import NuclearOPs
from qudi.logic.qudip_enhanced import *

importlib.reload(sch)
importlib.reload(shared)
importlib.reload(ush)
importlib.reload(sna)
importlib.reload(pc)
importlib.reload(OPX_utils)

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

        qua_array_1 = ou.get_fast_sweep_qua_array(0)
        qua_array_2 = ou.get_fast_sweep_qua_array(1)
        crc_period = 10

        # Init_state = current_iterator_df["Init_state"].unique()[0]
        # SSR_state = current_iterator_df["SSR_state"].unique()[0]
        with qua.program() as myprog:
            crc_rep = declare(int)
            assign(crc_rep, crc_period)
            ou.init_program()
            ou.set_laser_power("Laser_620_pi", "Laser_620_pi_power")
            ou.set_laser_power("Laser_620_det", sna.GENERAL_POWER_A1)
            ou.set_laser_power("Laser_620", sna.GENERAL_POWER_B2)
            ou.set_laser_power("Laser_520", sna.CRC_PARAMS.laser_power_repump)
            ou.pause(10_000)
            with infinite_loop_():
                with for_(*from_array(ou.i_1, qua_array_1)):
                    with for_(*from_array(ou.i_2, qua_array_2)):
                        with if_(crc_rep >= crc_period):
                            sna.crc(mcas)
                            assign(crc_rep, 0)

                        ### Init in e1 or e2 ###
                        sna.electron_init(mcas=mcas, state="e1", set_laser_power=False)
                        sna.ssr(mcas, state="e2", set_laser_power=False)
                        sna.optical_pi_pulse(
                            mcas,
                            couting_duration=50,
                            set_laser_power=False,
                        )
                        sna.csr(mcas, set_laser_power=False)
                        assign(crc_rep, crc_rep + 1)
        mcas.program = myprog
        # mcas.qm.set_digital_delay("Laser_620_pi", "ppg", (560) * u.ns)
        # mcas.qm.set_digital_delay("Laser_620_pi", "AOM_620_pi", (0) * u.ns)
        # mcas.qm.set_digital_delay("Gate_Trigger", "trigger", (815) * u.ns)

        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [["init", "<", 1, 1, 0, 1], ["result", ">", 0, 1, 0, 1], ["init", ">", 3, 1, 0, 1]]
    # ana_seq = [["result", ">", 0, 1, 0, 1]]
    # [["init", "<", 1, 1, 0, 1], ["result", ">", 3, 1, 0, 1], ["init", ">", 20, 1, 0, 1]]
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

    # nuclear.x_axis_title = "Freq [MHz]"
    # nuclear.analyze_type = 'consecutive'
    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = False  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = False
    nuclear.lock_laser_to_wavemeter = True
    nuclear.ple_refocus_interval = 30 * 60

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 100_000

    B_amp = np.arange(200, 300, 5)  # mT
    pi_pulse_laser_power = np.linspace(14, 300, 20) ** 2  # nW

    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [0]),
            # ("B_theta", [0]),
            # ("B_amp", B_amp),
            ("sweeps", range(10)),
            ("click_channel", [2]),
            # ("Init_state", ["e1", "e2"]),
            # ("SSR_state", ["e1", "e2"]),
            ("pulse_shape_ppg", ["gaussian"]),
            ("pulse_width_ppg", [2]),
            ("pulse_delay_ppg", [0]),  # ns
            ("Laser_620_pi_power", pi_pulse_laser_power),
            # ("wait_between_SSR", [100]),  # ns
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
