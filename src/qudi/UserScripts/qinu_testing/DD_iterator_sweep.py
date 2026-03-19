# coding=utf-8

import importlib
import qudi.UserScripts.helpers.sequence_creation_helpers as sch

importlib.reload(sch)
import qudi.UserScripts.helpers.shared as shared

# from qudi.hardware.Keysight_AWG_M8190.pym8190a import MultiChSeq as MultiChSeq
import qudi.hardware.OPX.program_container as pc

importlib.reload(pc)
# from qudi.hardware.OPX.program_container import MultiChSeq as MultiChSeq; importlib.reload(MultiChSeq)
import qudi.UserScripts.helpers.snippets_awg as sna

importlib.reload(sna)
importlib.reload(shared)
import os
from qm.qua import *

# importlib.reload(MultiChSeq)
import qudi.UserScripts.helpers.shared as ush

importlib.reload(ush)
from qudi.logic.qudip_enhanced import *
import qudi.hardware.Keysight_AWG_M8190.elements as E
from collections import OrderedDict
from qm.grpc.qua import QuaProgramArrayVarRefExpression, QuaProgramVarRefExpression
from qm.qua import *
from qm import QuantumMachinesManager
from qm.qua._expressions import QuaVariable

# from configuration import *
from qualang_tools.units import unit
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results import progress_counter, fetching_tool
from qualang_tools.loops import from_array

u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()

__TAU_HALF__ = 2 * 192 / 12e3
__SAMPLE_FREQUENCY__ = 12e3  # e.__SAMPLE_FREQUENCY__
tt_trigger_len = 1 * u.us

# Frequency vector

readout_len = 3 * u.us  # Readout duration for this experiment


# single_integration_time_ns = int(1000 * u.ns)
def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        sequence_name = "DD_test" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue._awg)  # , ch_dict={'2g': [1, 2], 'ps': [1]})

        def chk_i(key):
            if key == sweep_keys[0]:
                print(1, "ckeck i")
                return i_1
            if len(sweep_keys) == 2:
                if key == sweep_keys[1]:
                    print(2, "check i")
                    return i_2

            print("scalar")
            return current_iterator_df[key].unique()[0]

        slow_changing_parameters = ["bfield_spherical"]
        sweeps = []
        sweep_keys = []
        # print(current_iterator_df.readout_phase_2pi, "ro phase")
        for key in current_iterator_df.keys():
            if len(current_iterator_df[key].unique()) > 1 and key not in slow_changing_parameters:
                # sweeps[key]['key_first_apperance'] = int(df['delays_ps'][df['delays_ps'].isin([df['delays_ps'].unique()[1]])].dropna(how='all').index[0])
                sweeps.append(current_iterator_df[key].unique())
                sweep_keys.append(key)
        print(sweep_keys)
        if len(sweep_keys) > 2:
            raise (ValueError("   has more then two axis to iterate over by the quantum machine, which is not supportet at the moment"))

        i_1_array = sweeps[0]
        i_2_array = sweeps[1] if len(sweep_keys) == 2 else np.array([0])
        print(i_1_array, i_2_array, chk_i("MW_freq"))
        with program() as myprog:
            with infinite_loop_():
                i_1 = declare(int)
                i_2 = declare(int)

                phase_offset = declare(fixed)
                update_frequency("NV", chk_i("MW_freq"))
                with for_(*from_array(i_1, i_1_array)):
                    with for_(*from_array(i_2, i_2_array)):
                        assign(phase_offset, Cast.to_fixed(0.5 * Cast.to_fixed(chk_i("readout_phase_pi"))))
                        # Update the frequency of the digital oscillator linked to the element "NV"
                        # align all elements before starting the sequence
                        align()
                        play(
                            pulse="trigit",
                            element="Gate_Trigger",
                            duration=tt_trigger_len,  # 100*4 ns = 400 ns... lets check...
                        )

                        align()
                        # Play the mw pulse...
                        pi_2 = 14
                        pi = 27
                        play("cw" * amp(1), "NV", duration=pi_2)
                        align()
                        wait(duration=chk_i("tau"))
                        align()
                        play("cw" * amp(1), "NV", duration=pi)
                        align()
                        wait(duration=chk_i("tau"))
                        align()
                        frame_rotation_2pi(phase_offset, "NV")  # phase rotation in units of 2pi.
                        play("cw" * amp(1), "NV", duration=pi_2)
                        reset_frame("NV")
                        # ... and the laser pulse simultaneously (the laser pulse is delayed by 'laser_delay_1')
                        wait(duration=31000 - chk_i("tau") - chk_i("tau"))
                        align()
                        play("pulse" * amp(chk_i("repump_laser_power")), "Laser_520", duration=readout_len)

                        align()
                        play(
                            pulse="trigit",
                            element="Memory_Trigger",
                            duration=tt_trigger_len * 2,  # 100*4 ns = 400 ns... lets check...
                        )
                        wait(1000, "Memory_Trigger")

                        align()

                        play("pulse" * amp(0.5), "Laser_520", duration=3 * u.us)

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
            mcas=None, sm=1, n_values=100000
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

    nuclear.x_axis_title = "Freq [MHz]"
    # nuclear.analyze_type = 'consecutive'
    nuclear.analyze_type = "average"  # experimental feature for the fast
    nuclear.save_smartly = False  ## Doesnt save 0 in the trace only.
    nuclear.no_trace = True  ##Doesnt save the trace
    # PLE refocus
    nuclear.do_ple_refocusA1 = False  # not used
    nuclear.do_ple_refocusA2 = False

    # ODMR refocus
    nuclear.refocus_cw_odmr = False
    nuclear.refocus_pulsed_odmr = False

    # confocal refocus
    nuclear.do_confocal_repump_refocus = False
    nuclear.do_confocal_A1A2_refocus = False
    nuclear.do_confocal_A2MW_refocus = False
    nuclear.do_repump = False
    nuclear.check_A2_power = False

    nuclear.ple_refocus_interval = 30
    nuclear.confocal_refocus_interval = 300  # seconds
    nuclear.odmr_refocus_interval = 6000

    # rabi refocus ?

    nuclear.queue._gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue._gated_counter.trace.average_results = False

    # -3/2 expected at 11.82
    # +3/2 expected at 14.15
    # lst  =  np.arange(50, 1000, 100).tolist()
    # lst1 = lst[0::2]
    # lst2 = lst[1::2][::-1]
    # ordered_list = []
    # while len(lst2)>0:
    #    ordered_list.append(lst1.pop())
    #    ordered_list.append(lst2.pop())

    f_vec_array = np.arange(-200 * u.MHz, 200 * u.MHz, 2 * u.MHz)
    tau_array = np.arange(100, 15000, 100)
    nuclear.parameters = OrderedDict(
        (
            ("sweeps", range(100)),
            ("A2_power", [2]),
            ("wait_dur", [0.512]),
            ("init_time", [60]),
            ("n_ssr1", [250]),
            ("t_read", [100]),
            ("t_repump", [50]),
            ("MW_freq", [-176 * u.MHz]),
            # ("readout_duration", np.arange(300, 2000, 300)),
            ("tau", tau_array),
            ("repump_laser_power", [1.0]),
            ("duty_cycle", [0.5]),  # np.linspace(0.1,0.9,9)), #for laser power.
            ("laser_duration", [0.5]),
            ("readout", ["ssr"]),
            ("readout_phase_pi", [0, 1]),
            ("repump", ["no"]),  # , "yes"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = 2 * len(tau_array)  # 4


def run_fun(abort, **kwargs):
    print(1, " Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue._gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
