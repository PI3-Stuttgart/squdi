from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
import time

###################
# The QUA program #
###################

config["elements"]["Gate_Trigger"]["digitalInputs"]["trigger"]["delay"] = 543 * u.ns

volt_520 = 1
aom_delay = 0 * u.ns
aom_delay = 0 * u.ns

aom_timing = 15 * u.ns
aom_pulse_len = 40 * u.ns
ppg_trigg_len = 80 * u.ns
tt_trigger_len = 80 * u.ns

with program() as pi_pulse:
    # set_dc_offset("Laser_520", "single", 0.03)
    with infinite_loop_():
        # play(pulse="trigit", element="PPG", duration=ppg_trigg_len * u.ns)
        play("pulse" * amp(0.00), "Laser_520", duration=1000 * u.ns)
        play(pulse="trigit", element="620_pi", duration=aom_pulse_len * u.ns)
        play("trigit", "Gate_Trigger", duration=tt_trigger_len * u.ns)
        # wait(500 * u.ns)
        # align()
#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave=octave_config)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    duration = 600 * u.ns
    simulation_config = SimulationConfig(duration=duration)
    job_sim = qmm.simulate(config, pi_pulse, simulation_config)
    samples = job_sim.get_simulated_samples()
    # get the waveform report object
    waveform_report = job_sim.get_simulated_waveform_report()
    waveform_dict = waveform_report.to_dict()
    waveform_report.create_plot(samples, plot=True)
else:
    qm = qmm.open_qm(config)

    job = qm.execute(pi_pulse)
    while True:
        try:
            time.sleep(1)
        except:
            job.halt()
            print("Terminate")
            raise (BaseException)
