import importlib
from collections import OrderedDict

import numpy as np
from qm import qua
from qm.qua import declare, for_each_, infinite_loop_

import qudi.hardware.OPX.program_container as pc
import qudi.UserScripts.helpers.shared as ush
import qudi.UserScripts.helpers.snippets_awg_OPX as sna
import qudi.UserScripts.Qinu.common as qinu_common
from qudi.hardware.OPX import OPX_utils
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils
from qudi.logic.NuclearOPs import NuclearOPs
from qudi.logic.qudip_enhanced import *
from qudi.UserScripts.helpers import shared

importlib.reload(shared)
importlib.reload(ush)
importlib.reload(qinu_common)
importlib.reload(sna)
importlib.reload(pc)
importlib.reload(OPX_utils)


nuclear: NuclearOPs
nuclear, meas_code, seq_name = qinu_common.create_experiment(__file__)

SMIQ_POWER_DBM = -45.0


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        """Create one OPX sequence while the SMIQ frequency is set by NuclearOPs."""
        sequence_name = "ODMR_SnV_SMIQ" if sequence_name is None else sequence_name
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg, ou=ou)

        qua_array_1 = ou.get_fast_sweep_qua_array(0)
        qua_array_2 = ou.get_fast_sweep_qua_array(1)
        mw_pulse_len = int(current_iterator_df["MW_pulse_len"].unique()[0])

        with qua.program() as myprog:
            ou.init_program()
            ou.i_1 = declare(int)
            ou.i_2 = declare(int)

            ou.set_laser_power("Laser_620_det", sna.GENERAL_POWER_A1)
            ou.set_laser_power("Laser_620", sna.GENERAL_POWER_B2)
            ou.set_laser_power("Laser_520", sna.CRC_PARAMS.laser_power_repump)
            ou.pause(10_000)

            with infinite_loop_(), for_each_(ou.i_1, qua_array_1):
                with for_each_(ou.i_2, qua_array_2):
                    sna.crc(mcas)
                    sna.electron_init(mcas, "e1")
                    sna.ssr(mcas, state="e2")
                    ou.pause(10_000)

                    qua.align()
                    ou.gate_trigger()
                    qua.play("mw_switch", "NV", duration=mw_pulse_len // 4)
                    ou.laser_pulse("Laser_620_det", mw_pulse_len // 4)
                    qua.align()
                    ou.memory_trigger()

                    sna.csr(mcas)
                    ou.pause("cooldown_time")

        mcas.program = myprog
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
        ple_refocus_interval=2 * 60,
    )

    nuclear.x_axis_title = "SMIQ freq [Hz]"

    # smiq_center_freq = e9
    # smiq_span = 60e6
    # smiq_step = 0.5e6
    # smiq_freq_array = np.arange(
    #     start=smiq_center_freq - smiq_span / 2,
    #     stop=smiq_center_freq + smiq_span / 2 + smiq_step / 2,
    #     step=smiq_step,
    # )

    smiq_freq_array = np.arange(start=4.16e9, stop=4.21e9, step=1e6)
    repetitions_per_point = 1000
    nuclear.parameters = OrderedDict(
        (
            ("sweeps", range(10)),
            ("click_channel", [2]),
            ("smiq_power_dbm", [SMIQ_POWER_DBM]),
            ("MW_pulse_len", [2_000_000]),
            ("cooldown_time", [2_000_000]),
            ("smiq_freq", smiq_freq_array),
        )
    )
    nuclear.number_of_simultaneous_measurements = 1
    nuclear.queue.gated_counter.set_n_values(
        mcas=None,
        sm=1,
        n_values=(
            nuclear.number_of_simultaneous_measurements * repetitions_per_point * len(ana_seq)
            # * sum(step[3] for step in ana_seq)
            # * nr_repeating_intergration
        ),
    )


def start_smiq_cw() -> None:
    smiq_freq = float(nuclear.parameters["smiq_freq"][0])
    smiq_power = float(nuclear.parameters["smiq_power_dbm"][0])
    microwave = nuclear.queue.mw_source_smiq

    if microwave.module_state() != "idle":
        microwave.off()
    microwave.set_cw(frequency=smiq_freq, power=smiq_power)
    microwave.cw_on()


def run_fun(abort, **kwargs):
    print(1, "Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue.gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    start_smiq_cw()
    print("run_fun started")
    nuclear.run(abort)
