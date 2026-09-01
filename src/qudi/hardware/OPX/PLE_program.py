import numpy as np
from qm.qua import (
    align,
    amp,
    assign,
    declare,
    declare_stream,
    fixed,
    for_,
    for_each_,
    if_,
    measure,
    play,
    program,
    save,
    set_dc_offset,
    stream_processing,
    time_tagging,
    wait,
    while_,
)

from qudi.hardware.OPX.analog_output_OPX import AnalogOutputOPX
from qudi.hardware.OPX.configuration import *


def qm_scan_program(aoOPX: AnalogOutputOPX):

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
    crc_laser_voltage = aoOPX.get_setpoint("Laser_620_freq")  # in V
    crc_threshold = 20  # in c/s
    crc_pulse_len = 100 * u.us
    crc_repump_len = 1 * u.ms

    # Back scan paramters    back_scan_pulse_len = back_scan_duration / nr_ls_volt_steps_back / i_avg
    nr_ls_volt_steps_back = nr_ls_volt_steps
    back_scan_ls_volt_array = np.linspace(max_ls_volt, min_ls_volt, nr_ls_volt_steps_back)

    # Powers for laseres
    volt_620 = aoOPX.get_setpoint("Laser_620")
    volt_520 = aoOPX.get_setpoint("Laser_520")
    volt_620_pi = aoOPX.get_setpoint("Laser_620_pi")
    volt_620_det = aoOPX.get_setpoint("Laser_620_det")
    # Repump parameters
    repump_len = back_scan_duration

    # Pulse length parameters
    laser_pulse_len = sweep_duration / nr_ls_volt_steps / i_avg
    # laser_pulse_len = 1000  # in ns
    tt_trigger_len = 1000 * u.ns
    repump_pulse_len = repump_len / nr_ls_volt_steps / i_avg

    # print(f"laser position: {aoOPX.get_setpoint("Laser_620_freq")}")
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

        ### Set laser powers ###
        # set_dc_offset("Laser_620_pi", "single", volt_620_pi)
        set_dc_offset("Laser_620_det", "single", volt_620_det)
        set_dc_offset("Laser_620", "input1", volt_620)
        set_dc_offset("Laser_620", "input2", volt_620)
        set_dc_offset("Laser_620_freq", "single", min_ls_volt)
        wait(1_000 * u.ms)

        with for_(n, 0, n < nr_of_scanns, n + 1):
            ### looping over Laser scanner voltages ###
            with for_each_(vLS, ls_volt_array):
                set_dc_offset("Laser_620_freq", "single", vLS)
                play("trigit", "Gate_Trigger", duration=laser_pulse_len * u.ns)
                with for_(i, 0, i < i_avg, i + 1):
                    play("active", "Laser_620", duration=laser_pulse_len * u.ns)
                    # play("active", "Laser_620_pi", duration=laser_pulse_len * u.ns)
                    #
                    play("active", "Laser_620_det", duration=laser_pulse_len * u.ns)
                align()
                play("trigit", "Memory_Trigger", duration=tt_trigger_len * u.ns)

            ### Backscan ###
            align()
            set_dc_offset("Laser_620_freq", "single", min_ls_volt)
            # with for_(i, 0, i < 10_000, i + 1):
            #     play("pulse" * amp(volt_520 * 2), "Laser_520", duration=3 * u.s / 10_000)

            wait(2 * u.s)

            # set_dc_offset("Laser_620_freq", "single", crc_laser_voltage)
            # wait(1 * u.s)
            # crc(volt_620, volt_520, counts, counts_st)
            # set_dc_offset("Laser_620_freq", "single", min_ls_volt)
            # wait(300 * u.ms)

            # with for_each_(vLSBS, back_scan_ls_volt_array):
            #    set_dc_offset("Laser_620_freq", "single", vLSBS)
            #    with for_(i, 0, i < i_avg, i + 1):
            # play("pulse" * amp(volt_620), "Laser_620", duration=repump_pulse_len * u.ns * 4)

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
        set_dc_offset("Laser_620_freq", "single", vLS)
        wait(repump_pulse_len)
        align()


def crc(
    volt_620,
    volt_520,
    counts,
    counts_st,
    crc_pulse_len=500 * u.us,
    crc_threshold=40,
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
        play("pulse" * amp(volt_620 * 1), "Laser_620", duration=crc_pulse_len / 4)
        align()
        save(counts, counts_st)
        wait(500 * u.us)
        with if_(counts < crc_threshold_repump):
            play("pulse" * amp(volt_520), "Laser_520", duration=crc_repump_len / 4)
        # with if_(i > max_attempts):
        #    assign(counts, crc_threshold + 1)  # exit loop after max_attempts repumps
        wait(5000 * u.us)
