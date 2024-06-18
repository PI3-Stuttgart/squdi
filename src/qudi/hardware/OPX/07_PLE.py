"""


Prerequisites:


Next steps before going to the next node:
   
"""

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *


###################
# The QUA program #
###################
volt_factor = 15 # Defined at the laser
# Frequency vector
scan_freq = 0.5
nr_steps = 100
ascending = np.linspace(-1, 1, nr_steps)
v_vec = np.concatenate((ascending, ascending[::-1]))
print(v_vec)
n_avg = 1_000  # number of averages
readout_len = (1/scan_freq/nr_steps) * u.s  # Readout duration for this experiment

with program() as cw_odmr:
    times = declare(int, size=100)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts
    counts_st = declare_stream()  # stream for counts
    v = declare(float)  # voltages
    n = declare(int)  # number of iterations
    n_st = declare_stream()  # stream for number of iterations

    with for_(n, 0, n < n_avg, n + 1):
        with for_each_(v, v_vec):

            play("piezo_offset" * amp(v), "LaserScanner_red", duration=readout_len * u.ns)
            wait(0.5 * u.us, "SPCM1") 
            measure("long_readout", "SPCM1", None, time_tagging.analog(times, readout_len, counts))

            save(counts, counts_st)  # save counts on stream
            wait(wait_between_runs * u.ns)
            save(n, n_st)  # save number of iteration inside for_loop

    with stream_processing():
        # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
        counts_st.buffer(len(v_vec)).average().save("counts")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave=octave_config)

#######################
# Simulate or execute #
#######################
simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=10_000)  # In clock cycles = 4ns
    job = qmm.simulate(config, cw_odmr, simulation_config)
    job.get_simulated_samples().con1.plot()
else:
    # Open the quantum machine
    qm = qmm.open_qm(config)
    # Send the QUA program to the OPX, which compiles and executes it
    job = qm.execute(cw_odmr)
    # Get results from QUA program
    #results = fetching_tool(job, data_list=["counts", "counts_dark", "iteration"], mode="live")
    results = fetching_tool(job, data_list=["counts", "iteration"], mode="live")
    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure

    while results.is_processing():
        # Fetch results
        #counts, counts_dark, iteration = results.fetch_all()
        counts, iteration = results.fetch_all()
        counts_processed = counts[:len(counts)//2] + counts[len(counts)//2:][::-1]
        # Progress bar
        progress_counter(iteration, n_avg, start_time=results.get_start_time())
        # Plot data
        plt.cla()
        plt.plot(v_vec[:len(v_vec)//2] * volt_factor/2, counts_processed / 1000 / (readout_len * 1e-9), label="photon counts")
        plt.xlabel("Piezo offset voltage [V]")
        plt.ylabel("Intensity [kcps]")
        plt.title("PLE")
        plt.legend()
        plt.pause(0.1)
        
    plt.show()
    f = open("C:\\Data\\2024\\06\\odmr.txt", "w")
    for i in range(len(counts)):
        #f.write(str(counts[i])+ '\t' + str(counts_dark[i])+ '\n')
        f.write(str(counts[i]) + '\n')
    f.close()
    