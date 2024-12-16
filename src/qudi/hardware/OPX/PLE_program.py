import numpy as np
from qm.qua import *
from qudi.hardware.OPX.configuration import *
from qm import SimulationConfig, LoopbackInterface
from qm.quantum_machines_manager import QuantumMachinesManager
from qualang_tools.loops import qua_linspace

crc_voltage = 0.3295  # V


def qm_scan_program(aoOPX):

    nr_amp_steps = aoOPX._scan_parameters["nr_amp_steps"]
    duration = aoOPX._scan_parameters["sweep_duration"]
    back_scan_duration = aoOPX._scan_parameters["back_scan_duration"]
    nr_of_scanns = aoOPX._scan_parameters["nr_of_scans"]
    min_amp = aoOPX._scan_parameters["voltage_start"]
    max_amp = aoOPX._scan_parameters["voltage_stop"]
    nr_amp_steps_back = nr_of_scanns

    power_620 = aoOPX.get_setpoint("AOM_620_2_power")

    amp_array = np.linspace(min_amp, max_amp, nr_amp_steps)
    repump_len = 1 * u.ms
    i_avg = 1_000  # number of averages per voltage

    readout_len = duration / nr_amp_steps * u.s
    back_scan_len = back_scan_duration / 2 / nr_amp_steps_back * u.s

    repump_pulse_len = repump_len / i_avg * u.s
    curr_do: list = [
        key for key, value in aoOPX._opx.cw_do_states.items() if value == "on"
    ]
    curr_ao = {
        key: value for key, value in aoOPX._opx.cw_ao_values.items() if value != 0.0
    }
    del curr_ao["LaserScanner_red"]
    print(curr_ao)
    print(curr_do)
    print(amp_array)

    with program() as ple:
        # counts_st = declare_stream()  # stream for counts
        _amp = declare(fixed)  # amplitude
        _amp2 = declare(fixed)
        n = declare(int)  # number of iterations
        i = declare(int)  # number of iterations per
        k = declare(int)

        # integrations of whole scan
        with for_(n, 0, n < nr_of_scanns, n + 1):
            # looping over Laser scanner voltages
            with for_each_(_amp, amp_array):
                # Time tagger start trigger
                play("trigit", "Gate_Trigger", duration=10 * u.us)
                play("power" * amp(_amp), "LaserScanner_red", duration=10 * u.us)
                align()
                # Set Laser scanner voltage and send laser pulses
                with for_(i, 0, i < i_avg, i + 1):
                    play("active", "AOM_620_2", duration=readout_len / i_avg * u.ns)
                    play(
                        "power" * amp(power_620),
                        "AOM_620_2_power",
                        duration=readout_len / i_avg * u.ns,
                    )
                    # play("active", "Laser_520", duration=readout_len / i_avg * u.ns)
                    play(
                        "power" * amp(_amp),
                        "LaserScanner_red",
                        duration=readout_len / i_avg * u.ns,
                    )
                align()
                # Time tagger stop trigger
                play("trigit", "Memory_Trigger", duration=1 * u.us)
                play("power" * amp(_amp), "LaserScanner_red", duration=1 * u.us)

            # Repump and laser backscan
            with for_(*qua_linspace(_amp2, max_amp, min_amp, nr_amp_steps_back)):
                with for_(i, 0, i < i_avg, i + 1):
                    play(
                        "power" * amp(_amp2),
                        "LaserScanner_red",
                        duration=back_scan_len / i_avg * u.ns,
                    )
                    play("active", "Laser_520", duration=back_scan_len / i_avg * u.ns)
            # crc(aoOPX, crc_voltage)

        # with program() as crc2:
        #    crc(aoOPX, crc_voltage)

        # aoOPX._opx.simulate(crc2, plot=True, duration=1000)
        # with stream_processing():
        #     counts_st.with_timestamps().save("counts")
    return ple


def crc(
    aoOPX,
    target_freq,
    intigration_time=100 * u.us,
    min_counts=50,
    nr_count=1000,
    nr_repump=1000,
    repump_time=10 * u.us,
):
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    n = declare(int)  # number of iterations
    i = declare(int)  # number of repumps
    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    with while_(counts < min_counts):
        # Loop over the chunks to measure for the total integration time
        # Play the laser pulse...
        play(
            pulse="active",
            element="AOM_620_2",
            duration=intigration_time * u.ns,
        )
        play(
            "power" * amp(aoOPX._opx._volt2amp(aoOPX.get_setpoint("AOM_620_2_power"))),
            "AOM_620_2_power",
            duration=intigration_time * u.ns,
        )
        play(
            "power" * amp(target_freq),
            "LaserScanner_red",
            duration=intigration_time * u.ns,
        )
        measure(
            "readout",
            "SPCM1",
            None,
            time_tagging.analog(times, intigration_time, counts),
        )

        with if_(counts < min_counts):
            play(
                pulse="active",
                element="Laser_520",
                duration=repump_time * u.ns,
            )
            play(
                "power" * amp(target_freq),
                "LaserScanner_red",
                duration=repump_time * u.ns,
            )
