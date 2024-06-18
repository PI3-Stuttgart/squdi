"""
A Rabi experiment sweeping the duration of the MW pulse.
"""
from qm.QuantumMachinesManager import QuantumMachinesManager
from qm.qua import *
import matplotlib.pyplot as plt
from qm import SimulationConfig
from configuration import *

###################
# The QUA program #
###################

t_min = 10  # in clock cycles units (must be >= 4)
t_max = 200  # in clock cycles units
dt = 1  # in clock cycles units
bins = 30
t_vec = np.arange(0, bins-1 + 0.1, dt)  # +0.1 to include t_max in array
n_avg = 1e6

with program() as time_rabi:
    counts = declare(int)  # variable for number of counts
    counts_st = declare_stream()  # stream for counts
    times = declare(int, size=100)
    t = declare(int)  # variable to sweep over in time
    i = declare(int)
    counts_total = declare(int)
    n = declare(int)  # variable to for_loop
    n_st = declare_stream()  # stream to save iterations

    play("laser_ON", "AOM_green")
    wait(100, "AOM_green")
    with for_(n, 0, n < n_avg, n + 1):
        assign(counts_total, 0)
        play("laser_ON", "AOM_green")
        align('AOM_green','AOM_orange','SPCM')
        wait(100, 'AOM_orange','SPCM')
        # with for_(i, 0, i<2, i+1):
        play("laser_ON", "AOM_orange")
        measure("readout_orange", "SPCM", None, time_tagging.analog(times, meas_len_orange, counts))
            # assign(counts_total, counts_total+counts)
        save(counts, counts_st)  # save counts
        wait(100)

        save(n, n_st)  # save number of iteration inside for_loop

    with stream_processing():
        counts_st.histogram([[i, i] for i in range(0, bins, 1)]).save("counts_hist")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(qop_ip)

qm = qmm.open_qm(config)

simulate = False

if simulate:
    simulation_duration = 10000
    job_sim = qm.simulate(time_rabi,SimulationConfig(simulation_duration))
    job_sim.get_simulated_samples().con1.plot()
else:
    job = qm.execute(time_rabi)  # execute QUA program

    res_handles = job.result_handles
    times_hist_handle = res_handles.get("counts_hist")
    iteration_handle = res_handles.get("iteration")
    times_hist_handle.wait_for_values(1)
    iteration_handle.wait_for_values(1)


    def on_close(event):
        event.canvas.stop_event_loop()
        job.halt()


    f = plt.figure()
    f.canvas.mpl_connect("close_event", on_close)
    next_percent = 0.1  # First time print 10%
    print("Progress =", end=" ")

    b_cont = res_handles.is_processing()
    b_last = not b_cont

    while b_cont or b_last:
        plt.cla()
        times_hist = times_hist_handle.fetch_all()
        iteration = iteration_handle.fetch_all() + 1
        if iteration / n_avg > next_percent:
            percent = 10 * round(iteration / n_avg * 10)  # Round to nearest 10%
            print(f"{percent}%", end=" ")
            next_percent = percent / 100 + 0.1  # Print every 10%

        plt.plot(t_vec[::1] + 1 / 2, times_hist )
        plt.xlabel("t [ns]")
        plt.ylabel(f"counts [kcps / {1}ns]")
        plt.title("Delays")
        plt.pause(0.1)

        b_cont = res_handles.is_processing()
        b_last = not (b_cont or b_last)

    print("")