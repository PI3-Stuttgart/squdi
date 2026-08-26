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
        init_state = current_iterator_df["init_state"].unique()[0]
        MW_freq = current_iterator_df["MW_f"].unique()[0]

        with qua.program() as myprog:
            ou.init_program()
            qua.update_frequency("NV", MW_freq)
            ou.set_laser_power("Laser_620_det", sna.GENERAL_POWER_A1)
            ou.set_laser_power("Laser_620", sna.GENERAL_POWER_B2)
            ou.set_laser_power("Laser_520", sna.CRC_PARAMS.laser_power_repump)
            ou.pause(10_000)
            with infinite_loop_(), for_each_(ou.i_1, qua_array_1):
                with for_each_(ou.i_2, qua_array_2):
                    _, MW_pulse_len_qua = ou._get_value_from_key("MW_pulse_len")
                    sna.crc(mcas)
                    sna.electron_init(
                        mcas,
                        init_state,
                    )
                    sna.ssr(mcas, state="e2" if init_state == "e1" else "e1")
                    # #### MW pulse ###
                    qua.align()

                    qua.wait(500 // 4)
                    qua.align()
                    qua.play("cw" * qua.amp(MW_amp / 100), "NV", duration=MW_pulse_len_qua / 4)
                    qua.align()
                    qua.wait(500 // 4)
                    qua.align()

                    sna.ssr(mcas, state="e1")
                    qua.align()

                    sna.csr(mcas)
                    ou.pause("cooldown_time")

        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    # ana_seq = [["init", "<", 1, 1, 0, 1], ["result", ">", 0, 1, 0, 1], ["init", ">", 3, 1, 0, 1]]
    ana_seq = [["init", "<", 1, 1, 0, 1], ["result", ">", 1, 1, 0, 1], ["init", ">", 3, 1, 0, 1]]
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
    nuclear.ple_refocus_interval = 3 * 60

    # Confocal refocus
    nuclear.do_confocal_refocus_red = False
    nuclear.do_confocal_refocus_green = False
    nuclear.confocal_refocus_interval = 10 * 60

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    MW_pulse_duration_array = np.arange(start=20, stop=2000, step=100)
    f_vec_array = np.arange(start=285 * u.MHz, stop=300 * u.MHz, step=1 * u.MHz)
    nr_repeating_intergration: int = 300
    # integrations_per_point = 500
    # pi_pulse_laser_power = np.linspace(27, 400, 40) ** 2  # nW
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [100]),
            # ("B_theta", [50]),
            # ("B_amp", [140]),
            ("sweeps", range(20)),
            ("cooldown_time", [1_000_000]),  # 100 us
            ("MW_amp", [100]),
            ("click_channel", [2]),
            ("MW_f", f_vec_array),
            ("init_state", ["e2", "e1"]),
            ("MW_pulse_len", MW_pulse_duration_array),
            # ("integrations_per_point", np.arange(0, integrations_per_point, 1)),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(MW_pulse_duration_array)
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
