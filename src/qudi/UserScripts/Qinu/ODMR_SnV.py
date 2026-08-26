import importlib
import os
from collections import OrderedDict

from qm import qua
from qm.qua import for_each_, infinite_loop_
from qualang_tools.units import unit

import qudi.hardware.OPX.program_container as pc
import qudi.UserScripts.helpers.sequence_creation_helpers as sch
import qudi.UserScripts.helpers.shared as ush

# import qudi.UserScripts.helpers.snippets_awg as sna
import qudi.UserScripts.helpers.snippets_awg_OPX as sna
from qudi.hardware.OPX import OPX_utils
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.logic.NuclearOPs import NuclearOPs
from qudi.logic.qudip_enhanced import *
from qudi.UserScripts.helpers import shared

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

        MW_amp = current_iterator_df["MW_amp"].unique()[0]

        # Init_state = current_iterator_df["Init_state"].unique()[0]
        # SSR_state = current_iterator_df["SSR_state"].unique()[0]
        with qua.program() as myprog:
            ou.init_program()
            with infinite_loop_(), for_each_(ou.i_1, values=qua_array_1):
                with for_each_(ou.i_2, qua_array_2):
                    _, mw_freq_qua = ou._get_value_from_key("MW_f")
                    # mw_amp, _ = ou._get_value_from_key("MW_amp")
                    qua.update_frequency(
                        "NV",
                        mw_freq_qua,
                    )
                    sna.crc(mcas)
                    ou.pause(1e4)
                    sna.electron_init(mcas, "e2")
                    ou.pause(1e4)
                    sna.ssr(mcas, state="e1")
                    qua.align()
                    ou.gate_trigger()
                    ou.MW_pulse("NV", 2e6, MW_amp / 100)
                    ou.laser_pulse("Laser_620_det", 2e6)
                    qua.align()
                    ou.memory_trigger()
                    sna.csr(mcas)
                    ou.pause(100e6)
                # ou.pause(int(10e12))

        mcas.program = myprog
        # mcas.qm.set_digital_delay("NV", "switch", (113 + 21 + 1_015) * u.ns)
        # mcas.qm.set_digital_buffer("NV", "switch", (27) * u.ns)
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [["init", "<", 1, 1, 0, 1], ["result", ">", 1, 1, 0, 1], ["init", ">", 2, 1, 0, 1]]
    # ana_seq = [["init", "<", 1, 1, 0, 1], ["result", ">", 1, 1, 0, 1], ["init", ">", 5, 1, 0, 1]]
    # ana_seq = [["result", ">", 1, 1, 0, 1]]
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
    nuclear.do_ple_refocus_A1 = True
    nuclear.lock_laser_to_wavemeter = True
    nuclear.ple_refocus_interval = 2 * 60

    # Confocal refocus
    nuclear.do_confocal_refocus_red = False
    nuclear.do_confocal_refocus_green = False
    nuclear.confocal_refocus_interval = 1 * 60

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    f_vec_array = np.arange(start=270 * u.MHz, stop=310 * u.MHz, step=0.5 * u.MHz)
    # MW_power_array = np.array([1.0, 0.7, 0.5, 0.2, 0.1])
    nr_repeating_intergration: int = 5
    # pi_pulse_laser_power = np.linspace(27, 400, 40) ** 2  # nW
    nuclear.parameters = OrderedDict(
        (
            ("sweeps", range(5)),
            # ("B_phi", [0]),
            # ("B_theta", [126]),
            # ("B_amp", [110, 112, 114, 116]),
            ("click_channel", [2]),
            # ("first_init_duration", [5e6]),
            # ("ODMR_readout_power", [6]),
            ("MW_amp", [5, 3, 1]),
            # ("Init_state", ["e1", "e2"]),
            # ("SSR_state", ["e1", "e2"]),
            # ("pulse_shape_ppg", ["square"]),
            # ("pulse_width_ppg", [10]),
            # ("pulse_delay_ppg", [0]),  # ns
            # ("Laser_620_pi_power", pi_pulse_laser_power),
            ("MW_f", f_vec_array),
            # ("wait_between_SSR", [100]),  # ns
        )
    )
    nuclear.number_of_simultaneous_measurements = len(f_vec_array)
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=(
            nuclear.number_of_simultaneous_measurements * nr_repeating_intergration * len(ana_seq)
            # * sum(step[3] for step in ana_seq)
            # * nr_repeating_intergration
        ),
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
