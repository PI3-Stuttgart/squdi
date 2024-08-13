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
volt_factor = 5 # Defined at the laser
# Frequency vector
scan_freq = 0.1
nr_amp_steps = 100
amp_vec = np.linspace(-1, 1, nr_amp_steps)
n_avg = 1_000  # number of averages
readout_len = (1/scan_freq/nr_amp_steps) * u.s  # Readout duration for this experiment
i_avg = 1_000 # number of averages per voltage

with program() as ple:
    times = declare(int, size=100)  # QUA vector for storing the time-tags  
    counts = declare(int)
    total_counts = declare(int)
    counts_st = declare_stream()  # stream for counts  
    i_amp = declare(int) # iterator amplitudes
    _amp = declare(float) # amplitude
    n = declare(int)  # number of iterations
    n_st = declare_stream()  # stream for number of iterations
    i = declare(int) # number of iterations per 

    # integrations of ehole scan
    with for_(n, 0, n < n_avg, n + 1):
        assign(i_amp, 0)
        # looping over voltages
        with for_(*from_array(_amp, amp_vec)):  
            # Integration per voltage step
            with for_(i, 0, i < i_avg, i + 1):
                play("piezo_offset" * amp(_amp), "LaserScanner_red", duration=readout_len/i_avg * u.ns)
                measure("long_readout", "SPCM1", None, time_tagging.analog(times, readout_len/i_avg * u.ns, counts))
                assign(total_counts, total_counts + counts)

            save(total_counts, counts_st)  # save counts on stream
            assign(total_counts, 0)
            assign(i_amp, i_amp + 1)
        save(n, n_st)  # save number of iteration inside for_loop

    with stream_processing():
        # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
        # counts_st.buffer(len(v_vec)).average().save("counts")
        counts_st.buffer(len(amp_vec)).average().save("counts")
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
    simulation_config = SimulationConfig(duration=100_000)  # In clock cycles = 4ns
    job = qmm.simulate(config, ple, simulation_config)
    job.get_simulated_samples().con1.plot()
    plt.show()
else:
    # Open the quantum machine
    qm = qmm.open_qm(config)
    # Send the QUA program to the OPX, which compiles and executes it
    job = qm.execute(ple)
    # Get results from QUA program
    # results = fetching_tool(job, data_list=["counts", "counts_dark", "iteration"], mode="live")
    # results = fetching_tool(job, data_list=["counts", "iteration"], mode="live")
    results = fetching_tool(job, data_list=["counts", "iteration"], mode="live")
    
    # Live plotting
    fig = plt.figure()
    interrupt_on_close(fig, job)
    
    

    while results.is_processing():
        # Fetch results
        #counts, counts_dark, iteration = results.fetch_all()
        # counts, iteration = results.fetch_all()
        counts, iteration = results.fetch_all()
        
        progress_counter(iteration, n_avg, start_time=results.get_start_time())
        # Plot data
        plt.cla()
        plt.plot(amp_vec/0.5 * volt_factor, counts / 1000 / (readout_len * n_avg  * 1e-9), label="photon counts")
        #plt.plot((NV_LO_freq * 0 + f_vec) / u.MHz, counts_dark / 1000 / (readout_len * 1e-9), label="dark counts")
        plt.xlabel("Piezo Voltage [V]")
        plt.ylabel("Counts [kcps]")
        plt.title("PLE")
        plt.legend()
        plt.pause(0.1)
        
    plt.show()
    f = open("C:\\Data\\2024\\06\\odmr.txt", "w")
    for i in range(len(counts)):
        #f.write(str(counts[i])+ '\t' + str(counts_dark[i])+ '\n')
        f.write(str(counts[i] / 1000 / (readout_len * 1e-9)) + '\n')
    f.close()