from configuration import *
from qm.qua import *
from qm import SimulationConfig
# from qm import LoopbackInterface
from qm.QuantumMachinesManager import QuantumMachinesManager
# from qm.simulate.credentials import create_credentials
import matplotlib.pyplot as plt

################################
# Open quantum machine manager #
################################

qmm = QuantumMachinesManager(qop_ip)

########################
# Open quantum machine #
########################

qm = qmm.open_qm(config)

###############
# QUA program #
###############

KDD_order = 10

tau_start = 120  # tau/2 must be greater than pi/2 + pi or pulses start to overlap
tau_step = 0.1
step_number = 50

simulate = True
repetitions = 1e6

perfect_taus = np.arange(tau_start/2, (tau_start+tau_step*step_number)/2+0.00001, tau_step/2)


accuracy = 2**5  # may need adjusting to accurately calculate the pulse sequence in QUA
resolution = 4  # hardware limitation
perfect_taus_fixed = np.array(perfect_taus) / accuracy
pulses = KDD_order*20


def get_c2c_time(job, pulse1, pulse2):
    """
    Returns the center-to-center time between two pulses. The calculation is based from the simulation.
    :param job: a simulation ``QmJob`` object. ex: job = qmm.simulate()
    :param pulse1: tuple containing the element and pulse number for the 1st pulse. Note that if the element contain an
    IQ pair, then the pulse numbers have to be counted in pairs. ex: ('ensemble', 2) correspond to the 2nd pulse played
    from the element 'ensemble' since the numbers '0' and '1' are the I and Q components of the first pulse.
    :param pulse2: tuple containing the element and pulse number for the 2nd pulse. ex: ('resonator', 0) :return: center
    -to-center time (in ns) between the two pulses. Note that if the element contains an IQ pair, then the pulse numbers
    have to be counted in pairs. ex: ('ensemble', 2) correspond to the 2nd pulse played from the element 'ensemble'
    since the numbers '0' and '1' are the I and Q components of the first pulse.
    """
    analog_wf = job.simulated_analog_waveforms()
    element1 = pulse1[0]
    pulse_nb1 = pulse1[1]
    element2 = pulse2[0]
    pulse_nb2 = pulse2[1]

    time2 = (
        analog_wf["elements"][element2][pulse_nb2]["timestamp"]
        + analog_wf["elements"][element2][pulse_nb2]["duration"] / 2
    )
    time1 = (
        analog_wf["elements"][element1][pulse_nb1]["timestamp"]
        + analog_wf["elements"][element1][pulse_nb1]["duration"] / 2
    )

    return time2 - time1


def sequence_generator(error, N_pulses, taus):
    m = 0
    U = []
    for i in range(N_pulses):
        m += error
        if np.abs(m <= 0.5):
            U.append(int(taus[0]))
        else:
            U.append(int(taus[1]))
            m -= 1
    return U


def real_taus_generator(sequence):
    real_taus = [sequence[0]]
    for i in range(len(sequence)-1):
        real_taus.append(sequence[i] + sequence[i+1])
    real_taus.append(sequence[-1])
    return real_taus


def KDD_XY4_separate_element(tau, element, index, N_max):
    j = declare(int)
    with for_(j, 0, j < N_max, j + 1):
        # KDD along X
        play("pi", element)
        wait(
            tau[10 * j + index]
            + tau[10 * j + 1 + index]
            + tau[10 * j + 1 + index]
            + tau[10 * j + 2 + index]
            + tau[10 * j + 2 + index]
            + tau[10 * j + 3 + index]
            + tau[10 * j + 3 + index]
            + tau[10 * j + 4 + index]
            + tau[10 * j + 4 + index]
            + tau[10 * j + 5 + index]
            - 20,
            element,
        )
        frame_rotation_2pi(1 / 4, element)
        # KDD along Y
        play("pi", element)
        with if_(j < N_max - 1):
            wait(tau[10 * j + 5 + index]
                + tau[10 * j + 6 + index]
                + tau[10 * j + 6 + index]
                + tau[10 * j + 7 + index]
                + tau[10 * j + 7 + index]
                + tau[10 * j + 8 + index]
                + tau[10 * j + 8 + index]
                + tau[10 * j + 9 + index]
                + tau[10 * j + 9 + index]
                + tau[10 * j + 10 + index]
                - 72,
                element)
        frame_rotation_2pi(-1 / 4, element)


sequence = []
real_taus = []
for perfect_tau in perfect_taus:
    taus = [resolution * np.floor(perfect_tau / resolution),
            resolution * np.floor(perfect_tau / resolution) + resolution]

    seq = sequence_generator((perfect_tau - taus[0]) / resolution, pulses, taus)
    sequence += seq
    real_taus.append(real_taus_generator(seq))

sequence = list(np.reshape(sequence, np.array(sequence).size))
real_taus = list(np.reshape(real_taus, np.array(real_taus).size))

for i in range(len(sequence)):
    sequence[i] = int(sequence[i] // 4)

real_taus = [int(tau)//4 for tau in real_taus]

with program() as KDD_interpolated:
    i = declare(int)
    j = declare(int)
    n = declare(int)
    times = declare(int, size=100)
    counts = declare(int)
    counts_st = declare_stream()
    n_st = declare_stream()
    error = declare(fixed)
    cumulated_error = declare(fixed)
    factor = declare(fixed, value=1 / accuracy)
    threshold = declare(fixed, value=0.5 / accuracy)

    tau = declare(int, size=pulses)
    tau_window = declare(int, size=2)
    total = declare(int)
    perfect_taus_qua = declare(
        int, value=[int(item // resolution) * resolution for item in perfect_taus]
    )
    perfect_taus_fixed_qua = declare(fixed, value=perfect_taus_fixed)

    reset_frame("NV1_1", "NV1_2", "NV1_3", "NV1_4", "NV1_5", "NV1_6")
    frame_rotation_2pi(1 / 12, "NV1")
    frame_rotation_2pi(1 / 4, "NV1_3")
    frame_rotation_2pi(1 / 12, "NV1_5")
    align("NV1_1", "NV1_2", "NV1_3", "NV1_4", "NV1_5", "NV1_6")
    with for_(n, 0, n < repetitions, n + 1):
        with for_(j, 0, j < len(perfect_taus), j + 1):
            assign(tau_window[0], perfect_taus_qua[j])
            assign(tau_window[1], perfect_taus_qua[j] + resolution)
            assign(
                error,
                (
                    perfect_taus_fixed_qua[j]
                    - Cast.mul_fixed_by_int(factor, tau_window[0])
                )
                / resolution,
            )
            assign(cumulated_error, 0.0)
            with for_(i, 0, i < pulses, i + 1):
                assign(cumulated_error, cumulated_error + error)
                assign(tau[i],
                       Util.cond(Math.abs(cumulated_error) > 0.5 * factor, tau_window[1] >> 2, tau_window[0] >> 2))
                assign(cumulated_error,
                       Util.cond(Math.abs(cumulated_error) > 0.5 * factor, cumulated_error-factor, cumulated_error))

            assign(total, 2*Math.sum(tau))

            align("NV1_1", "NV1_2", "NV1_3", "NV1_4", "NV1_5", "NV1_6")

            wait(17, 'NV1_6')
            play("pi_half", "NV1_6")

            wait(tau[0], "NV1_1")
            wait(tau[0] + tau[0] + tau[1], "NV1_2")
            wait(tau[0] + tau[0] + tau[1] + tau[1] + tau[2], "NV1_3")
            wait(tau[0] + tau[0] + tau[1] + tau[1] + tau[2] + tau[2] + tau[3], "NV1_4")
            wait(tau[0] + tau[0] + tau[1] + tau[1] + tau[2] + tau[2] + tau[3] + tau[3] + tau[4], "NV1_5")

            for k in range(5):
                KDD_XY4_separate_element(tau, f"NV1_{k + 1}", k, pulses // 10)

            wait(total - 10, "NV1_6")
            play("pi_half", "NV1_6")

            align()
            play("laser_ON", "AOM_green")
            measure("readout", "SPCM", None, time_tagging.analog(times, meas_len, counts))
            save(counts, counts_st)  # save counts
            wait(500)

        save(n, n_st)

    with stream_processing():
        counts_st.buffer(len(perfect_taus)).average().save("counts")
        n_st.save("iteration")

############
# simulate #
############

if simulate:
    job = qmm.simulate(
        config,
        KDD_interpolated,
        simulate=SimulationConfig(duration=3*5000, include_analog_waveforms=True),
    )

    # job.get_simulated_samples().con1.plot(analog_ports=["1"])
    # job.get_simulated_samples().con1.plot(analog_ports=["2"])
    job.get_simulated_samples().con1.plot()

    delays = []
    N = pulses // 5
    for j in range(len(perfect_taus)):
        for i in range(N):
            if i == 0:
                delays.append(
                    get_c2c_time(job, ("NV1_6", j * 4), ("NV1_1", 2 * i + j * 2 * N)) // 4
                )
            delays.append(
                get_c2c_time(
                    job,
                    ("NV1_1", 2 * i + j * 2 * N),
                    ("NV1_2", 2 * i + j * 2 * N)
                )
                // 4
            )
            delays.append(
                get_c2c_time(
                    job,
                    ("NV1_2", 2 * i + j * 2 * N),
                    ("NV1_3", 2 * i + j * 2 * N)
                )
                // 4
            )
            delays.append(
                get_c2c_time(
                    job,
                    ("NV1_3", 2 * i + j * 2 * N),
                    ("NV1_4", 2 * i + j * 2 * N),
                )
                // 4
            )
            delays.append(
                get_c2c_time(
                    job,
                    ("NV1_4", 2 * i + j * 2 * N),
                    ("NV1_5", 2 * i + j * 2 * N),
                )
                // 4
            )
            if i < N - 1:
                delays.append(
                    get_c2c_time(
                        job,
                        ("NV1_5", 2 * i + j * 2 * N),
                        ("NV1_1", 2 * i + 2 + j * 2 * N),
                    )
                    // 4
                )
            else:
                delays.append(
                    get_c2c_time(
                        job,
                        ("NV1_5", 2 * i + j * 2 * N),
                        ("NV1_6", 2 + j * 4),
                    )
                    // 4
                )

    print("Measured delay:")
    print(list(np.array(delays).astype(int)))
    print("Sequence:")
    print(real_taus)
    plt.figure()
    plt.plot(real_taus)
    plt.plot(delays)

else:
    job = qm.execute(KDD_interpolated)  # execute QUA program

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
        if iteration / repetitions > next_percent:
            percent = 10 * round(iteration / repetitions * 10)  # Round to nearest 10%
            print(f"{percent}%", end=" ")
            next_percent = percent / 100 + 0.1  # Print every 10%

        plt.plot(perfect_taus, counts / 1000)
        plt.xlabel("Tau [ns]")
        plt.ylabel("Intensity [kcps]")
        plt.title("KDD Interpolated")
        plt.pause(0.1)

        b_cont = res_handles.is_processing()
        b_last = not (b_cont or b_last)

    print("")
