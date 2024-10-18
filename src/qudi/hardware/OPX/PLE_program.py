import numpy as np
from qm.qua import *
from qudi.hardware.OPX.configuration import *
def qm_scan_program(aoOPX):

    nr_amp_steps = aoOPX._scan_parameters['nr_amp_steps']
    duration = aoOPX._scan_parameters['sweep_duration']
    nr_of_scanns = aoOPX._scan_parameters['nr_of_scans']

    repump_len = 20 * u.ms
    i_avg = 1_000  # number of averages per voltage

    amp_vec = np.linspace(-1, 1, nr_amp_steps)
    readout_len = (duration / nr_amp_steps) * u.s
    repump_pulse_len = repump_len / i_avg

    curr_do: list = [key for key, value in aoOPX._opx.cw_do_states.items() if value == 'on']
    curr_ao = {key: value for key, value in aoOPX._opx.cw_ao_values.items() if value != 0.0}

    with program() as ple:
        i_amp = declare(int)  # iterator amplitudes
        _amp = declare(float)  # amplitude
        n = declare(int)  # number of iterations
        i = declare(int)  # number of iterations per
        k = declare(int)
        # integrations of whole scan
        with for_(n, 0, n < nr_of_scanns, n + 1):
            # play("trigit", "Gate_Trigger", duration=200 * u.us)
            # looping over voltages
            with for_(*from_array(_amp, amp_vec)):
                play("trigit", "Gate_Trigger", duration=1 * u.us)
                # Integration per voltage step
                with for_(i, 0, i < i_avg, i + 1):
                    # for ao, power in curr_ao.items():
                    #     play('power' * amp(aoOPX._opx._volt2amp(power)), ao, duration=readout_len / i_avg * u.ns)
                    # for do in curr_do:
                    #     play('active', do, duration=readout_len / i_avg * u.ns)
                    play('active', 'AOM_620', duration=readout_len / i_avg * u.ns)
                    play("power" * amp(_amp), "LaserScanner_red", duration=readout_len / i_avg * u.ns)
                align()
                play("trigit", "Memory_Trigger", duration=1 * u.us)
                play("power" * amp(_amp), "LaserScanner_red", duration=1 * u.us)

            with for_(k, 0, k < i_avg, k + 1):
                play("power" * amp(-1), "LaserScanner_red", duration=repump_pulse_len)
                play("active", "Laser_520", duration=repump_pulse_len)
        # play("trigit", "Memory_Trigger", duration=2 * u.us)
    return ple
