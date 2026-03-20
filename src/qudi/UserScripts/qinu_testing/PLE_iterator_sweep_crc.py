# coding=utf-8

import importlib
import qudi.UserScripts.helpers.sequence_creation_helpers as sch

importlib.reload(sch)

import qudi.UserScripts.helpers.shared as shared

importlib.reload(shared)

import qudi.UserScripts.helpers.shared as ush

importlib.reload(ush)

import qudi.UserScripts.helpers.snippets_awg as sna

importlib.reload(sna)

import qudi.hardware.OPX.program_container as pc

importlib.reload(pc)
from qudi.hardware.OPX.OPX_utils import crc, scan_laser_to_target

# importlib.reload(OPX_utils)

from qudi.logic.qudip_enhanced import *

import os
from collections import OrderedDict
from qm import qua
from qm.qua import play, set_dc_offset, declare, fixed, for_, align, amp, infinite_loop_

from qualang_tools.units import unit
from qualang_tools.loops import from_array
from qudi.logic.NuclearOPs import NuclearOPs


### Setup the sequence and the measurement ###
u = unit(coerce_to_integer=True)
seq_name = os.path.basename(__file__).split(".")[0]
nuclear: NuclearOPs = sch.create_nuclear(__file__)
with open(os.path.abspath(__file__).split(".")[0] + ".py", "r") as f:
    meas_code = f.read()


### FIXME: Hardcoded parameters ###
tt_trigger_len = 20 * u.ns
j_avg = 1000


def ret_ret_mcas(pdc):
    def ret_mcas(self, current_iterator_df, sequence_name=None):
        """This function creates the sequence for the current itterator and returns the mcas object with the sequence programmed in it."""
        sequence_name = "PLE_itterator 2" if sequence_name is None else sequence_name
        mcas = pc.MultiChSeq(name=sequence_name, awg=self.queue.awg)

        def chk_i(key):
            if key == nuclear.sweep_keys_OPX[0]:
                return i_1
            if len(nuclear.sweep_keys_OPX) == 2:
                if key == nuclear.sweep_keys_OPX[1]:
                    return i_2
            else:
                return current_iterator_df[key].unique()[0]

        crc_620_laser_power = self.queue.power_conversion.convert_power_to_voltage(10e-9, "AOM_620")  # W to Volt
        crc_repump_laser_power = self.queue.power_conversion.convert_power_to_voltage(1e-3, "Laser_520")  # nW
        crc_threshold_repump: int = 3
        crc_threshold = 8
        crc_repump_len = 1 * u.ms  # ns
        crc_pulse_len = 500 * u.us  # ns

        with qua.program() as myprog:
            with infinite_loop_():

                j = declare(int)
                j_back = declare(int)
                i_1 = declare(fixed)
                i_2 = qua.declare(fixed)
                i_back = qua.declare(fixed)

                ### Backscan ###
                # with for_(*from_array(i_back, nuclear.i_1_array[::-1])):
                #     set_dc_offset("LaserScanner_red", "single", i_back)
                #     with for_(j_back, 0, j_back < j_avg, j_back + 1):
                #         play(
                #             "pulse" * amp(chk_i("repump_laser_power")),
                #             "Laser_520",
                #             duration=chk_i("backscan_len_pixel") * u.ns / j_avg,
                #         )
                #     align()

                # scan_laser_to_target(
                #     self.queue.ple_scanner_logic.frequency_to_voltage(current_iterator_df["Laser_freqs_MHz"].unique()[-1] * 1e6), self.queue.ple_scanner_logic.frequency_to_voltage(1e9)
                # )
                align()
                set_dc_offset("LaserScanner_red", "single", self.queue.ple_scanner_logic.frequency_to_voltage(1e9))
                align()
                qua.wait(1 * u.s)
                crc(
                    volt_power_620=crc_620_laser_power,
                    volt_power_520=crc_repump_laser_power,
                    crc_pulse_len=crc_pulse_len,
                    crc_threshold=crc_threshold,
                    crc_threshold_repump=crc_threshold_repump,
                    crc_repump_len=crc_repump_len,
                )
                align()
                set_dc_offset("LaserScanner_red", "single", self.queue.ple_scanner_logic.frequency_to_voltage(current_iterator_df["Laser_freqs_MHz"].unique()[0] * 1e6))
                qua.wait(1 * u.s)
                # scan_laser_to_target(
                #     self.queue.ple_scanner_logic.frequency_to_voltage(1e9),
                #     self.queue.ple_scanner_logic.frequency_to_voltage(current_iterator_df["Laser_freqs_MHz"].unique()[0] * 1e6),
                # )
                align()
                ### PLE loop ###
                with for_(*from_array(i_1, nuclear.i_1_array)):
                    with for_(*from_array(i_2, nuclear.i_2_array)):
                        set_dc_offset("LaserScanner_red", "single", chk_i("Laser_freqs_MHz"))
                        play(pulse="trigit", element="Gate_Trigger", duration=tt_trigger_len * u.ns)

                        with for_(j, 0, j < j_avg, j + 1):
                            play("pulse" * amp(chk_i("620_laser_power")), "AOM_620", duration=chk_i("readout_len_pixel") * u.ns / j_avg)
                            # play("pulse" * amp(chk_i("repump_laser_power")), "Laser_520", duration=chk_i("readout_len_pixel")*u.ns / j_avg,)

                        align()
                        play(pulse="trigit", element="Memory_Trigger", duration=tt_trigger_len * u.ns)
        #!!! important!!!!
        # myqua, self.number_of_simultaneous_measurements) #calculating the number of gated counts on the timetagger.
        mcas.program = myprog
        return mcas

    return ret_mcas


def settings(pdc={}):
    laserpower_to_v = nuclear.queue.power_conversion.convert_power_to_voltage
    ana_seq = [
        ["result", ">", -1, 1, 1, 1],  # Put "int(_I_['n_ssr']" as nlp_per_point?
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
    nuclear.do_ple_refocus_A1 = False  # not used

    nuclear.queue.gated_counter.trace.consecutive_valid_result_numbers = [0]
    nuclear.queue.gated_counter.trace.average_results = False

    laser_freq_vec_MHz = np.linspace(0, 2, 200) * 1e3
    nuclear.parameters = OrderedDict(
        (
            ("B_phi", [0]),
            ("B_theta", [0]),
            ("B_amp", [0]),
            ("sweeps", range(20)),
            ("620_laser_power", [laserpower_to_v(10e-9, "AOM_620")]),
            ("repump_laser_power", [laserpower_to_v(50e-6, "Laser_520")]),
            ("Laser_freqs_MHz", laser_freq_vec_MHz),
            ("click_channel", [3]),
            ("readout_len_pixel", [10 * u.ms]),
            ("backscan_len_pixel", [5 * u.ms]),
        )
    )
    nuclear.number_of_simultaneous_measurements = len(laser_freq_vec_MHz)
    nuclear.queue.gated_counter.set_n_values(mcas=None, sm=1, n_values=len(laser_freq_vec_MHz) * 5)


def run_fun(abort, **kwargs):
    print(1, "Nuclear started!!!")
    nuclear.queue = kwargs["queue"]
    nuclear.queue.gated_counter.readout_duration = 1 * 1e6
    nuclear.hashed = False
    nuclear.debug_mode = False
    settings()
    print("run_fun started")
    nuclear.run(abort)
