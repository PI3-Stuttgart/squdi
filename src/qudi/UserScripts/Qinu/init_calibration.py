# coding=utf-8

import importlib
import os
from collections import OrderedDict

from qm import qua
from qm.qua import for_, infinite_loop_
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
        SSR_state = current_iterator_df["SSR_state"].unique()[0]

        with qua.program() as myprog:
            with infinite_loop_():
                ou.init_program()
                with for_(*from_array(ou.i_1, qua_array_1)):
                    with for_(*from_array(ou.i_2, qua_array_2)):
                        # sna.crc(mcas)

                        sna.electron_init(mcas, "e1", "e1_init_duration", "e1_init_power")
                        sna.electron_init(mcas, "e2", "e2_init_duration", "e2_init_power")

                        sna.ssr(mcas, SSR_state)

                        # Charge state readout
                        sna.csr(mcas)

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
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

    # nuclear.analyze_type = 'consecutive'
    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = False  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = True
    nuclear.ple_refocus_interval = 5  # in seconds
    nuclear.lock_laser_to_wavemeter = False

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 1000

    e2_init_duration = np.linspace(1, 500, 5) * 1e3  # ns
    B_amp = np.arange(200, 300, 5)  # mT
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [0]),
            # ("B_theta", [0]),
            # ("B_amp", B_amp),
            ("sweeps", range(1)),
            ("e1_init_power", [10]),
            ("e1_init_duration", [3e6]),
            ("e2_init_power", [6]),  # nW
            ("e2_init_duration", e2_init_duration),
            ("click_channel", [2]),
            ("SSR_state", ["e1", "e2"]),
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
