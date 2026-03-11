"""
        COUNTER
The program consists in playing a laser pulse while performing time tagging continuously.
This allows measuring the received photons as a function of time while adjusting external parameters
to validate the experimental set-up.
"""

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *

###################
# The QUA program #
###################

# Total duration of the measurement
total_integration_time = 20 * u.ms  # 100ms
# Duration of a single chunk. Needed because the OPX cannot measure for more than ~1ms
single_integration_time = 500 * u.us  # 500us
# Number of chunks to get the total measurement time
n_count = int(total_integration_time / single_integration_time)
print(single_integration_time)
print(n_count)
with program() as counter:
    times = declare(int, size=1000)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts of a single chunk
    total_counts = declare(int)  # variable for the total number of counts
    n = declare(int)  # number of iterations
    counts_st = declare_stream()  # stream for counts

    # Infinite loop to allow the user to work on the experimental set-up while looking at the counts
    with infinite_loop_():
        # Loop over the chunks to measure for the total integration time
        with for_(n, 0, n < n_count, n + 1):
            # Play the laser pulse...
            play("pulse", "AOM_520", duration=single_integration_time)
            # ... while measuring the events from the SPC
            measure(
                "readout",
                "SPCM1",
                None,
                time_tagging.analog(times, single_integration_time, counts),
            )
            # Increment the received counts
            assign(total_counts, _exp=total_counts + counts)
        # Save the counts
        save(total_counts, counts_st)
        assign(total_counts, 0)

    with stream_processing():
        counts_st.with_timestamps().save("counts")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave=octave_config)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    simulation_duration = 100000
    simulation_config = SimulationConfig(duration=simulation_duration)  # In clock cycles = 4ns
    job_sim = qmm.simulate(config, counter, simulation_config)
    samples = job_sim.get_simulated_samples()
    # get the waveform report object
    waveform_report = job_sim.get_simulated_waveform_report()
    waveform_dict = waveform_report.to_dict()
    waveform_report.create_plot(
        samples,
    )
else:
    qm = qmm.open_qm(config)

    job = qm.execute(counter)
    # Get results from QUA program
    res_handles = job.result_handles
    counts_handle = res_handles.get("counts")
    counts_handle.wait_for_values(1)
    time = []
    counts = []
    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    while res_handles.is_processing():
        new_counts = counts_handle.fetch_all()
        counts.append(new_counts["value"] / (total_integration_time * 1e-9) / 1000)
        time.append(new_counts["timestamp"] / u.s)  # Convert timestamps to seconds
        plt.cla()
        if len(time) > 50:
            plt.plot(time[-50:], counts[-50:])
        else:
            plt.plot(time, counts)

        plt.xlabel("Time [s]")
        plt.ylabel("Counts [kcps]")
        plt.title("Counter")
        plt.pause(0.1)
