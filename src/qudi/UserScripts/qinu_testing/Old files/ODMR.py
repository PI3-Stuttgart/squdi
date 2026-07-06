# coding=utf-8

import importlib
import os
from collections import OrderedDict

from qm import qua
from qm.qua import declare, for_, infinite_loop_
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
from qudi.logic.qudip_enhanced import *

importlib.reload(sch)
importlib.reload(shared)
importlib.reload(ush)
importlib.reload(sna)
importlib.reload(pc)
importlib.reload(OPX_utils)

u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()

__TAU_HALF__ = 2 * 192 / 12e3
__SAMPLE_FREQUENCY__ = 12e3  # e.__SAMPLE_FREQUENCY__
tt_trigger_len = 1 * u.us

# Frequency vector

readout_len = 2 * u.ms  # Readout duration for this experiment
j_avg = 1000


# single_integration_time_ns = int(1000 * u.ns)
def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        sequence_name = "init sweep" if sequence_name is None else sequence_name
        ou: NuclearOpsOPXUtils = self.queue.nuclear_ops_opx_utils
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg, ou=ou)

        def chk_i(key):
            if key == sweep_keys[0]:
                return i_1
            if len(sweep_keys) == 2:
                if key == sweep_keys[1]:
                    return i_2
            else:
                return current_iterator_df[key].unique()[0]

        slow_changing_parameters = ["B_amp", "B_theta", "B_phi"]
        sweeps = []
        sweep_keys = []
        for key in current_iterator_df.keys():
            if len(current_iterator_df[key].unique()) > 1 and key not in slow_changing_parameters:
                # sweeps[key]['key_first_apperance'] = int(df['delays_ps'][df['delays_ps'].isin([df['delays_ps'].unique()[1]])].dropna(how='all').index[0])
                sweeps.append(current_iterator_df[key].unique())
                sweep_keys.append(key)

        if len(sweep_keys) > 2:
            raise (
                ValueError(
                    "   has more then two axis to iterate over by the quantum machine, which is not supportet at the moment"
                )
            )

        qua_array_1 = ou.get_fast_sweep_qua_array(0)
        qua_array_2 = ou.get_fast_sweep_qua_array(1)

        with qua.program() as myprog:
            with infinite_loop_():
                f = declare(int)  # frequencies
                j = declare(int)
                i_1 = declare(int)
                i_2 = declare(int)

                # set_dc_offset("LaserScanner_red", "single", chk_i("Laser_freqs_MHz"))
                wait(10 * u.ms)

                with for_(*from_array(i_1, i_1_array)):
                    with for_(*from_array(i_2, i_2_array)):
                        # for (
                        #     idx,
                        #     _I_,
                        # ) in current_iterator_df.iterrows():  ### #FIXME Achtung... I cant be more than 1 at once...we need to open iterator to for_each loop.

                        # _I_ is already a single, but we are iterating over it.
                        # if idx > 0:
                        #     align()

                        # Update the frequency of the digital oscillator linked to the element "NV"
                        # update_frequency("NV", chk_i("MW_freq"))
                        # align all elements before starting the sequence
                        play(
                            pulse="trigit",
                            element="Gate_Trigger",
                            duration=tt_trigger_len,  # 100*4 ns = 400 ns... lets check...
                        )
                        with for_(j, 0, j < j_avg, j + 1):
                            align()
                            # Play the mw pulse...
                            play("cw" * amp(1), "NV", duration=readout_len / j_avg)
                            # ... and the laser pulse simultaneously (the laser pulse is delayed by 'laser_delay_1')
                            # play("pulse" * amp(0.05), "AOM_620", duration=readout_len / j_avg)
                            # play("pulse" * amp(0.001), "Laser_520", duration=readout_len / j_avg)
                            # wait(1_000 * u.ns, "SPCM1")  # so readout don't catch the first part of spin reinitialization
                            # Measure and detect the photons on SPCM1

                        # Wait and align all elements before measuring the dark events
                        # wait(wait_between_runs * u.ns)

                        # wait(1 * u.ms)  # VV i commented it - this line of code breaks the thing - it is too long of a wait.

                        align()
                        play(
                            pulse="trigit",
                            element="Memory_Trigger",
                            duration=tt_trigger_len * 2,  # 100*4 ns = 400 ns... lets check...
                        )
                        wait(1000, "Memory_Trigger")
                        # play("pulse" * amp(0.1), "Laser_520", duration=10 * u.us)
            ###########################
            # Run or Simulate Program #
            ###########################
            # sna.ssr(mcas=mcas, queue=self.queue,
            # frequencies=[1000],
            # wait_dur=0.0,
            # robust=False,
            # laser_dur = E.round_length_mus_to_x_multiple_ps(_I_['t_read']),
            # nuc='charge_state',

            # mixer_deg=-90,
            # eom_ampl=0.0,
            # step_idx=1,
            # )

        #!!! important!!!!
        self.queue._gated_counter.set_n_values(
            mcas=None, sm=1, n_values=1500
        )  # myqua, self.number_of_simultaneous_measurements) #calculating the number of gated counts on the timetagger.
        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    ana_seq = [
        # ['init', '>', 1, 1, 100, 1],
        ["result", ">", 0, 1, 1, 1],  # Put "int(_I_['n_ssr']" as nlp_per_point?
        # ['init', '>', 5, 0, 0, 1],
        # ['init', '>', 5, 1, 0, 1],
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

    # nuclear.x_axis_title = "Freq [MHz]"
    # nuclear.analyze_type = 'consecutive'
    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = False  ##Doesnt save the trace

    # PLE refocus
    nuclear.do_ple_refocus_A1 = False
    nuclear.lock_laser_to_wavemeter = False
    nuclear.ple_refocus_interval = 3 * 60

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    nr_repeating_intergration: int = 10_000_000

    B_amp = np.arange(200, 300, 5)  # mT
    # pi_pulse_laser_power = np.linspace(27, 400, 40) ** 2  # nW
    pi_pulse_laser_power = np.array([5_000])  # nW

    f_vec_array = np.arange(-300 * u.MHz, 300 * u.MHz, 2 * u.MHz)
    nuclear.parameters = OrderedDict(
        (
            # ("B_phi", [90]),
            # ("B_theta", [90]),
            # ("B_amp", [0, 5, 10, 15, 20, 25, 30]),
            ("sweeps", range(300)),
            # ("A2_power", [2]),
            # ("wait_dur", [0.512]),
            # ("init_time", [60]),
            # ("n_ssr1", [250]),
            # ("t_read", [100]),
            # ("t_repump", [50]),
            # ("repump_laser_power", [0.1]),  ###
            ("MW_freq", f_vec_array),
            # ("duty_cycle", [0.5]),  # np.linspace(0.1,0.9,9)), #for laser power.
            # ("laser_duration", [0.5]),
            # ("readout", ["ssr"]),
            # ("repump", ["no"]),  # , "yes"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(f_vec_array)  # 4


def run_fun(abort, **kwargs):
    print(1, "Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue.gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
