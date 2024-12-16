from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *

# Number of chunks to get the total measurement time
total_integration_time = 25 * u.ms
single_integration_time_ns = 500 * u.us  # 500us
min_counts = 60
repump_time = 100 * u.us


nr_count = int(total_integration_time / single_integration_time_ns)
nr_repump = 100

with program() as counter:
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    total_counts = declare(int)
    n = declare(int)  # number of iterations
    i = declare(int)  # number of repumps
    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    with infinite_loop_():
        with for_(n, 0, n < nr_count, n + 1):
            # Loop over the chunks to measure for the total integration time

            # Play the laser pulse...
            play(pulse="active",element="AOM_620",duration=single_integration_time_ns)
            # ... while measuring the events from the SPC
            measure(
                "readout",
                "SPCM1",
                None,
                time_tagging.analog(times, single_integration_time_ns, counts),
            )
            assign(total_counts, total_counts + counts)
        with if_(total_counts<min_counts):
            with for_(i, 0, i < nr_repump, i + 1):
                play(pulse="active", element="Laser_450", duration=repump_time)
        assign(total_counts, 0)

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(
    host=qop_ip, cluster_name=cluster_name, octave=octave_config
)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
    job_sim = qmm.simulate(config, counter, simulation_config)
    # Simulate blocks python until the simulation is done
    samples = job_sim.get_simulated_samples()
    plt.show()

    # get the waveform report object
    waveform_report = job_sim.get_simulated_waveform_report()
    waveform_report.create_plot(samples)
else:
    qm = qmm.open_qm(config)

    job = qm.execute(counter)
    # Get results from QUA program

    while True:
        pass

    job.halt()
