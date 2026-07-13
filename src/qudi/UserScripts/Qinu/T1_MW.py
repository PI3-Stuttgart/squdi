# coding=utf-8

import importlib
import os
from collections import OrderedDict

from qm import qua
from qm.qua import declare, for_each_, infinite_loop_
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
        init_state = current_iterator_df["init_state"].unique()[0]
        SSR_state = current_iterator_df["SSR_state"].unique()[0]
        pi_bool = current_iterator_df["pi_bool"].unique()[0]

        #
        # qua.update_frequency("NV", new_frequency=sna.ELECTRON_PARAMS.IQ_freq)
        with qua.program() as myprog:
            with infinite_loop_():
                ou.init_program()
                ou.i_1 = declare(int)
                sna.set_IQ_freq(mcas)
                ou.pause(500 // 4)

                with for_each_(ou.i_1, qua_array_1):
                    with for_each_(ou.i_2, qua_array_2):
                        sna.crc(mcas)
                        sna.electron_init(
                            mcas,
                            init_state,
                        )
                        sna.ssr(mcas, state="e1" if init_state == "e2" else "e2")
                        qua.align()
                        if pi_bool == "mw_pi":
                            # qua.wait(500 // 4)
                            sna.electron_gate(mcas, "pi")
                        # ou.pause("readout_delay")
                        # qua.wait(ou.i_1 / 4)
                        sna.ssr(mcas, state=SSR_state)
                        # Charge state readout
                        sna.csr(mcas)

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [
        ["init", "<", 1, 1, 0, 1],
        ["result", ">", 0, 1, 0, 1],
        ["init", ">", 10, 1, 0, 1],
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
    nuclear.no_trace = False  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = True
    nuclear.lock_laser_to_wavemeter = True
    nuclear.ple_refocus_interval = 30

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 2000

    # readout_delay = np.linspace(0, 2_000, 10) * 1e3  # ns -> us
    readout_delay = np.arange(16, 1_000_000, 1000)  # ns -> us
    nuclear.parameters = OrderedDict(
        (
            ("sweeps", range(20)),
            # ("readout_delay", readout_delay),
            ("click_channel", [2]),  # nW
            ("init_state", ["e1", "e2"]),
            ("SSR_state", ["e1", "e2"]),
            ("pi_bool", ["mw_pi", "no_mw_pi"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = 1  # len(readout_delay)
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=nuclear.number_of_simultaneous_measurements
        * nr_repeating_intergration
        * len(ana_seq),
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
