# coding=utf-8

import importlib
from collections import OrderedDict

from qm import qua
from qm.qua import declare, for_each_, infinite_loop_
from qualang_tools.units import unit

import qudi.hardware.OPX.OPX_utils as OPX_utils
import qudi.hardware.OPX.program_container as pc
import qudi.UserScripts.helpers.shared as shared
import qudi.UserScripts.helpers.shared as ush
import qudi.UserScripts.Qinu.common as qinu_common

# import qudi.UserScripts.helpers.snippets_awg as sna
import qudi.UserScripts.helpers.snippets_awg_OPX as sna
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.logic.qudip_enhanced import *

importlib.reload(shared)
importlib.reload(ush)
importlib.reload(qinu_common)
importlib.reload(sna)
importlib.reload(pc)
importlib.reload(OPX_utils)

### Setup the sequence and the measurement ###
u = unit(coerce_to_integer=True)
nuclear, meas_code, seq_name = qinu_common.create_experiment(__file__)


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        """This function creates the sequence for the current itterator and returns the mcas object with the sequence programmed in it."""
        sequence_name = "init sweep" if sequence_name is None else sequence_name
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg, ou=ou)

        qua_array_1 = ou.get_fast_sweep_qua_array(0)
        qua_array_2 = ou.get_fast_sweep_qua_array(1)

        MW_pulse_len = current_iterator_df["MW_pulse_len"].unique()[0]  # ns
        # SSR_state = current_iterator_df["SSR_state"].unique()[0]
        with qua.program() as myprog:
            ou.init_program()
            ou.i_1 = declare(int)
            ou.set_laser_power("Laser_620_det", sna.GENERAL_POWER_A1)
            ou.set_laser_power("Laser_620", sna.GENERAL_POWER_B2)
            ou.set_laser_power("Laser_520", sna.CRC_PARAMS.laser_power_repump)
            ou.pause(10_000)
            with infinite_loop_():
                with for_each_(ou.i_1, qua_array_1):
                    with for_each_(ou.i_2, qua_array_2):
                        _, mw_freq_qua = ou._get_value_from_key("MW_f")
                        qua.update_frequency(
                            "NV",
                            mw_freq_qua,
                        )
                        sna.crc(mcas)

                        sna.electron_init(mcas, "e1")
                        sna.ssr(mcas, state="e2")
                        qua.align()
                        qua.play("cw" * qua.amp(1), "NV", duration=MW_pulse_len / 4)
                        qua.align()
                        sna.ssr(mcas, state="e2")
                        sna.csr(mcas)
                        ou.pause("cooldown_time")

        mcas.program = myprog
        # mcas.qm.set_mixer_correction("mixer_NV", intermediate_frequency=)

        return mcas

    return ret_mcas


def settings(pdc=None):
    pdc = {} if pdc is None else pdc
    ana_seq = [
        qinu_common.init("<", threshold=1),
        qinu_common.result(">", threshold=1),
        qinu_common.init(">", threshold=10),
    ]

    qinu_common.configure_experiment(
        nuclear=nuclear,
        ret_mcas=ret_ret_mcas(pdc),
        analyze_sequence=ana_seq,
        meas_code=meas_code,
        pdc=pdc,
        ple_refocus=True,
        lock_laser_to_wavemeter=True,
    )

    # nuclear.x_axis_title = "Freq [MHz]"

    MW_freq_array = np.arange(start=185 * u.MHz, stop=195 * u.MHz, step=0.1 * u.MHz)
    # MW_pulse_duration_array = np.arange(start=500, stop=20_000, step=500)
    nr_repeating_intergration: int = 10
    # pi_pulse_laser_power = np.linspace(27, 400, 40) ** 2  # nW
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [100]),
            # ("B_theta", [50]),
            # ("B_amp", [140]),
            ("sweeps", range(10)),
            ("click_channel", [2]),
            ("MW_pulse_len", [1_000]),
            # ("MW_amp", [1.0]),
            ("cooldown_time", [5_000_000]),
            ("MW_f", MW_freq_array),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(MW_freq_array)
    qinu_common.set_counter_length(
        nuclear,
        repetitions=nr_repeating_intergration,
        analyze_sequence=ana_seq,
    )


def run_fun(abort, **kwargs):
    qinu_common.run_nuclear_experiment(nuclear, abort, kwargs["queue"], settings)
