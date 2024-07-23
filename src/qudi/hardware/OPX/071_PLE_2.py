from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
import numpy as np
from configuration import *

###################
# The QUA program #
###################
volt_factor = 5  # Defined at the laser
scan_freq = 1
nr_steps = 100
ascending = np.linspace(-1, 1, nr_steps)
v_vec = ascending
n_avg = 1_000  # number of averages
readout_len = (1/scan_freq/nr_steps) * u.s  # Readout duration for this experiment
i_avg = 1_000  # number of averages per voltage

with program() as cw_odmr:
    times = declare(int, size=100)  # QUA vector for storing the time-tags
    counts = declare(int)  # variable for number of counts
    total_counts = declare(int)
    counts_st = declare_stream()  # stream for counts  
    v = declare(float)  # voltages
    n = declare(int)  # number of iterations
    n_st = declare_stream()  # stream for number of iterations
    i = declare(int)  # number of iterations per voltage

    with for_(n, 0, n < n_avg, n + 1):
        with for_each_(v, v_vec):       
            with for_(i, 0, i < i_avg, i + 1):
                play("piezo_offset" * amp(v), "LaserScanner_red", duration=readout_len/i_avg * u.ns)
                measure("long_readout", "SPCM1", None, time_tagging.analog(times, readout_len/i_avg * u.ns, counts))
                assign(total_counts, total_counts + counts)
                
            save(total_counts, counts_st)  # save counts on stream
            assign(total_counts, 0)
        save(n, n_st)  # save number of iterations inside for_loop

    with stream_processing():
        counts_st.save("counts")
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
    simulation_config = SimulationConfig(duration=100_000)  # In clock cycles = 4ns
    job = qmm.simulate(config, cw_odmr, simulation_config)
    job.get_simulated_samples().con1.plot()
    plt.show()
else:
    qm = qmm.open_qm(config)
    job = qm.execute(cw_odmr)
    res_handles = job.result_handles
    counts_handle = res_handles.get("counts")
    counts_handle.wait_for_values(1)
    
    iter_handle = res_handles.get("iteration")
    iter_handle.wait_for_values(1)
    
    # Live plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    interrupt_on_close(fig, job)  # Interrupts the job when closing the figure
    
    counts = np.zeros((n_avg, nr_steps))  # Initialize a 2D array for the heatmap
    iteration = 0  # Track the current iteration

    heatmap = ax1.imshow(counts, aspect='auto', interpolation='nearest', extent=[v_vec.min(), v_vec.max(), 0, n_avg])
    ax1.set_ylabel("Iteration")
    ax1.set_title("Counts Heatmap")

    line, = ax2.plot(v_vec * volt_factor, np.zeros(nr_steps))
    ax2.set_xlabel("Piezo offset voltage [V]")
    ax2.set_ylabel("Intensity [kcps]")
    ax2.set_title("Current Scan Line")

    while res_handles.is_processing():
        new_counts = counts_handle.fetch_all()
        iteration = iter_handle.fetch_all()

        counts[iteration] = new_counts
        heatmap.set_data(counts)
        line.set_ydata(new_counts)

        # progress_counter(iteration, n_avg, start_time=res_handles.get_start_time())
        
        fig.canvas.draw()
        fig.canvas.flush_events()
        plt.pause(0.1)
        
    plt.show()