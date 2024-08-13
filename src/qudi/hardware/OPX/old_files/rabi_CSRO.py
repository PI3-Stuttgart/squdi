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

t_min = 4  # in clock cycles units (must be >= 4)
t_max = 45  # in clock cycles units
dt = 1  # in clock cycles units
t_vec = np.arange(t_min, t_max + 0.1, dt)  # +0.1 to include t_max in array
n_avg = 1e6
threshold = 10
with program() as time_rabi:
    counts = declare(int)  # variable for number of counts
    counts_st = declare_stream()  # stream for counts
    times = declare(int, size=100)
    t = declare(int)  # variable to sweep over in time
    n = declare(int)  # variable to for_loop
    n_st = declare_stream()  # stream to save iterations

    play("laser_ON", "AOM_green")
    wait(100, "AOM_green")
    with for_(n, 0, n < n_avg, n + 1):
        with for_(t, t_min, t <= t_max, t + dt):
            ## Charge state readout
            assign(counts, 0)
            with while_(counts < threshold):
                play("laser_ON", "AOM_green")
                align('AOM_green', 'AOM_orange', 'SPCM')
                wait(100, 'AOM_orange', 'SPCM')
                play("laser_ON", "AOM_orange")
                measure("readout_orange", "SPCM", None, time_tagging.analog(times, meas_len_orange, counts))
            align('NV1', 'AOM_green','SPCM')
            wait(500, 'NV1', "AOM_green", "SPCM")
            ## Rabi
            play("pi", "NV1", duration=t)  # pulse of varied lengths
            align()
            wait(50, 'AOM_green')
            play("laser_ON", "AOM_green")
            measure("readout", "SPCM", None, time_tagging.analog(times, meas_len, counts))
            save(counts, counts_st)  # save counts
            wait(1000)

        save(n, n_st)  # save number of iteration inside for_loop

    with stream_processing():
        counts_st.buffer(len(t_vec)).average().save("counts")
        n_st.save("iteration")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(qop_ip)

qm = qmm.open_qm(config)

simulate = False

if simulate:
    simulation_duration = 2000
    job_sim = qm.simulate(time_rabi,SimulationConfig(simulation_duration))
    job_sim.get_simulated_samples().con1.plot()
else:
    job = qm.execute(time_rabi)  # execute QUA program

    res_handles = job.result_handles  # get access to handles
    counts_handle = res_handles.get("counts")
    iteration_handle = res_handles.get("iteration")
    counts_handle.wait_for_values(1)
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
        counts = counts_handle.fetch_all()
        iteration = iteration_handle.fetch_all() + 1
        if iteration / n_avg > next_percent:
            percent = 10 * round(iteration / n_avg * 10)  # Round to nearest 10%
            print(f"{percent}%", end=" ")
            next_percent = percent / 100 + 0.1  # Print every 10%

        plt.plot(4 * t_vec, counts / 1000)
        plt.xlabel("Tau [ns]")
        plt.ylabel("Intensity [kcps]")
        plt.title("Charge check Rabi")
        plt.pause(0.1)

        b_cont = res_handles.is_processing()
        b_last = not (b_cont or b_last)

    print("")