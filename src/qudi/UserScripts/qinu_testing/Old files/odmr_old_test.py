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

readout_len = 10 * u.us  # Readout duration for this experiment
i_avg = 100


# single_integration_time_ns = int(1000 * u.ns)
def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        sequence_name = "ODMR_test" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue._awg)  # , ch_dict={'2g': [1, 2], 'ps': [1]})
        with program() as myprog:
            with infinite_loop_():

                f = declare(int)  # frequencies
                i = declare(int)

                for (
                    idx,
                    _I_,
                ) in current_iterator_df.iterrows():  ### #FIXME Achtung... I cant be more than 1 at once...we need to open iterator to for_each loop.

                    # _I_ is already a single, but we are iterating over it.
                    if idx > 0:
                        align()
                    # with for_(*from_array(f, _I_["f_vec"])):
                    # Update the frequency of the digital oscillator linked to the element "NV"
                    update_frequency("NV", _I_["f_vec"])
                    # align all elements before starting the sequence
                    play(
                        pulse="trigit",
                        element="Gate_Trigger",
                        duration=tt_trigger_len,  # 100*4 ns = 400 ns... lets check...
                    )
                    with for_(i, 0, i < i_avg, i + 1):
                        align()
                        # Play the mw pulse...
                        play("cw" * amp(1), "NV", duration=readout_len / i_avg * u.ns)
                        # ... and the laser pulse simultaneously (the laser pulse is delayed by 'laser_delay_1')
                        play("pulse" * amp(_I_["repump_laser_power"]), "Laser_520", duration=readout_len / i_avg * u.ns)
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
            mcas=None, sm=1, n_values=10000
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
    nuclear.save_smartly = False
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

    f_vec_array = np.arange(-300 * u.MHz, 300 * u.MHz, 2 * u.MHz)
    nuclear.parameters = OrderedDict(
        (
            ("sweeps", range(20)),
            ("A2_power", [2]),
            ("wait_dur", [0.512]),
            ("init_time", [60]),
            ("n_ssr1", [250]),
            ("t_read", [100]),
            ("t_repump", [50]),
            ("repump_laser_power", [1]),  ###
            ("f_vec", f_vec_array),
            ("duty_cycle", [0.5]),  # np.linspace(0.1,0.9,9)), #for laser power.
            ("laser_duration", [0.5]),
            ("readout", ["ssr"]),
            ("repump", ["no"]),  # , "yes"]),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(f_vec_array)  # 4


def run_fun(abort, **kwargs):
    print(1, " Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue._gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
