import numpy as np
from qm.qua import *
from qudi.hardware.OPX.configuration import *
from qm import SimulationConfig, LoopbackInterface
from qm.quantum_machines_manager import QuantumMachinesManager
from qualang_tools.loops import qua_linspace
import time


def qm_scan_program(aoOPX):

    counts_per_second_threshold = 10  # threshold in kc/s
    scans_to_repump = 20  # number of scans before repumping regardless of counts
    i_avg = 1000  # 00  # number of averages per voltage
    nr_of_scanns = aoOPX._scan_parameters["nr_of_scans"]
    sweep_duration = aoOPX._scan_parameters["sweep_duration"] * u.s
    back_scan_duration = aoOPX._scan_parameters["back_scan_duration"] * u.s

    # Laser scan Parameters
    nr_ls_volt_steps = aoOPX._scan_parameters["nr_amp_steps"]
    min_ls_volt = aoOPX._scan_parameters["voltage_start"]
    max_ls_volt = aoOPX._scan_parameters["voltage_stop"]
    ls_volt_array = np.linspace(min_ls_volt, max_ls_volt, nr_ls_volt_steps)

    # CRC parameters
    crc_laser_voltage = aoOPX.get_setpoint("LaserScanner_red")  # in V
    crc_threshold = 20  # in c/s
    crc_pulse_len = 100 * u.us
    crc_repump_len = 1 * u.ms

    # Back scan paramters    back_scan_pulse_len = back_scan_duration / nr_ls_volt_steps_back / i_avg
    nr_ls_volt_steps_back = nr_ls_volt_steps
    back_scan_ls_volt_array = np.linspace(max_ls_volt, min_ls_volt, nr_ls_volt_steps_back)

    # Powers for laseres
    volt_620 = aoOPX.get_setpoint("AOM_620")
    volt_520 = aoOPX.get_setpoint("Laser_520")
    volt_620_pi = -0.25
    # Repump parameters
    repump_len = back_scan_duration

    # Pulse length parameters
    laser_pulse_len = sweep_duration / nr_ls_volt_steps / i_avg
    # laser_pulse_len = 1000  # in ns
    tt_trigger_len = 1000 * u.ns
    repump_pulse_len = repump_len / nr_ls_volt_steps / i_avg

    counts_threshold = counts_per_second_threshold * sweep_duration / (nr_ls_volt_steps) * 1e-6
    curr_do: list = [key for key, value in aoOPX._opx.cw_do_states.items() if value == "on"]
    curr_ao = {key: value for key, value in aoOPX._opx.cw_ao_values.items() if value != 0.0}
    curr_laser_scanner_volt = aoOPX.get_setpoint("LaserScanner_red") * 0.5
    array_volts_scan_laser_to_start = np.linspace(curr_laser_scanner_volt, min_ls_volt, nr_ls_volt_steps)
    # print(f"laser position: {aoOPX.get_setpoint("LaserScanner_red")}")
    with program() as ple:
        vLS = declare(fixed)  # voltge Laser scanner
        vLSBS = declare(fixed)  # voltage laser scanner for backscan
        n = declare(int)  # number of iterations
        count_repump = declare(int)
        assign(count_repump, 0)
        i = declare(int)  # number of integrations per laserscanner voltage step
        total_counts_scan = declare(int)  # All Counts of one line scan
        total_counts_point = declare(int)
        counts = declare(int)  # counts measured in one measering process
        times = declare(int, size=1000)  # QUA vector for storing the time-tags
        counts_st = declare_stream()  # stream for counts
        save(0, counts_st)
        # Integrations of whole scan
        # assign(total_counts_scan, 0)
        # scan_laser_to_target(aoOPX.get_setpoint("LaserScanner_red"), min_ls_volt, repump_pulse_len, i_avg, nr_ls_volt_steps_back)
        # ### Scan to start position
        # with for_each_(vLS, array_volts_scan_laser_to_start):
        #     with for_(i, 0, i < i_avg, i + 1):
        #         set_dc_offset("LaserScanner_red", "single", vLSBS)
        #         wait(repump_pulse_len * u.ns * 4)
        # wait(1000 * u.ms)
        # scan_laser_to_target(aoOPX.get_setpoint("LaserScanner_red") * 0.5, min_ls_volt)
        set_dc_offset("620_pi_w_power", "single", volt_620_pi)
        set_dc_offset("LaserScanner_red", "single", min_ls_volt)
        wait(3 * u.s)

        with for_(n, 0, n < nr_of_scanns, n + 1):
            # looping over Laser scanner voltages
            with for_each_(vLS, ls_volt_array):
                set_dc_offset("LaserScanner_red", "single", vLS)
                play("trigit", "Gate_Trigger", duration=laser_pulse_len * u.ns)
                play("pulse" * amp(volt_620), "AOM_620", duration=tt_trigger_len * u.ns)
                with for_(i, 0, i < i_avg, i + 1):
                    play("pulse" * amp(volt_620), "AOM_620", duration=laser_pulse_len * u.ns)
                    play("trigit", "620_pi", duration=laser_pulse_len * u.ns)
                    # play("trigit", "TT_attodry_trigger", duration=laser_pulse_len * u.ns)
                    # play("pulse" * amp(volt_520), "Laser_520", duration=laser_pulse_len)  # Time tagger stop trigger
                    # measure(
                    #     "readout",
                    #     "SPCM1",
                    #     None,
                    #     time_tagging.analog(times, laser_pulse_len, counts),
                    # )
                    # assign(total_counts_point, total_counts_point + counts)
                align()
                play("trigit", "Memory_Trigger", duration=tt_trigger_len * u.ns)
                # Time tagger stop trigger
                # with if_(total_counts_point > total_counts_scan):
                #     assign(total_counts_scan, total_counts_point)
                # assign(total_counts_scan, _exp=total_counts_scan + total_counts_point)
                # assign(total_counts_point, 0)
                # assign(IO2, total_counts_scan)
                # wait(1000 * u.ns)
            # Repump and laser backscan
            # assign(count_repump, count_repump + 1)

            # scan_laser_to_target(max_ls_volt, crc_laser_voltage)
            set_dc_offset("LaserScanner_red", "single", min_ls_volt)
            with for_(i, 0, i < 10000, i + 1):
                play("pulse" * amp(volt_520), "Laser_520", duration=3 * u.s / 10000)
            # crc(volt_620, volt_520, counts, counts_st)
            # scan_laser_to_target(crc_laser_voltage, min_ls_volt)
            # with for_each_(vLSBS, back_scan_ls_volt_array):
            #    set_dc_offset("LaserScanner_red", "single", vLSBS)
            #    with for_(i, 0, i < i_avg, i + 1):
            # play("pulse" * amp(volt_620), "AOM_620", duration=repump_pulse_len * u.ns * 4)

            # with if_(total_counts_scan <= counts_threshold):
            #    play("pulse" * amp(volt_520), "Laser_520", duration=repump_pulse_len)
            #    # play("active", "Laser_450", duration=repump_pulse_len)
            #    # wait(repump_pulse_len * u.ns * 4)
            # with else_():

            # with if_(count_repump >= scans_to_repump):
            #    play("pulse" * amp(volt_520), "Laser_520", duration=repump_pulse_len * u.ns * 4)
            #    # wait(repump_pulse_len * u.ns * 4)
            # with else_():
            #    wait(repump_pulse_len * u.ns * 4)

            # play("pulse" * amp(volt_520), "Laser_520", duration=repump_pulse_len * u.ns * 4)
            # assign(total_counts_scan, 0)
            # with if_(count_repump >= scans_to_repump):
            #    assign(count_repump, 0)

        # from qm import generate_qua_script

        # aoOPX._opx.simulate(ple, plot=True, duration=10000)
        # sourceFile = open("debug.py", "w")
        # print(generate_qua_script(ple, config), file=sourceFile)
        # sourceFile.close()
        # with stream_processing():
        #     counts_st.with_timestamps().save("counts")
        with stream_processing():
            counts_st.with_timestamps().save("counts")
    return ple


def scan_laser_to_target(curr_laser_volt, laser_target_voltage):
    repump_pulse_len = 10 * u.ms  # duration
    nr_steps = int(abs(curr_laser_volt - laser_target_voltage) / 1 * 2000)
    array_volts_scan_laser_to_target = np.linspace(curr_laser_volt, laser_target_voltage, nr_steps)
    vLS = declare(fixed)
    with for_each_(vLS, array_volts_scan_laser_to_target):
        set_dc_offset("LaserScanner_red", "single", vLS)
        wait(repump_pulse_len)
        align()


def crc(
    volt_620,
    volt_520,
    counts,
    counts_st,
    crc_pulse_len=500 * u.us,
    crc_threshold=8,
    crc_threshold_repump=3,
    crc_repump_len=1 * u.ms,
    max_attempts=1000,
):
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    # counts = declare(int)  # variable for number of counts of a single chunk
    i = declare(int)  # number of iterations

    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    assign(counts, 0)
    with while_(counts < crc_threshold):
        # play("trigit", "Gate_Trigger", duration=crc_pulse_len / 8)
        measure(
            "readout",
            "SPCM1",
            None,
            time_tagging.analog(times, crc_pulse_len, counts),
        )
        play("pulse" * amp(volt_620 * 1), "AOM_620", duration=crc_pulse_len / 4)
        align()
        save(counts, counts_st)
        wait(500 * u.us)
        with if_(counts < crc_threshold_repump):
            play("pulse" * amp(volt_520), "Laser_520", duration=crc_repump_len / 4)
        # with if_(i > max_attempts):
        #    assign(counts, crc_threshold + 1)  # exit loop after max_attempts repumps
        wait(5000 * u.us)
