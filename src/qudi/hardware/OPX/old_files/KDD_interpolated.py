from configuration import *
from qm.qua import *
from qm import SimulationConfig
from qm import LoopbackInterface
from qm.QuantumMachinesManager import QuantumMachinesManager
from qm.simulate.credentials import create_credentials
import matplotlib.pyplot as plt

################################
# Open quantum machine manager #
################################

# qmm = QuantumMachinesManager()
qmm = QuantumMachinesManager(qop_ip)

########################
# Open quantum machine #
########################

qm = qmm.open_qm(config)

###############
# QUA program #
###############
def get_c2c_time(job, pulse1, pulse2):
    """
    Returns the center-to-center time between two pulses. The calculation is based from the simulation.
    :param job: a simulation ``QmJob`` object. ex: job = qmm.simulate()
    :param pulse1: tuple containing the element and pulse number for the 1st pulse. Note that if the element contain an IQ pair, then the pulse numbers have to be counted in pairs. ex: ('ensemble', 2) correspond to the 2nd pulse played from the element 'ensemble' since the numbers '0' and '1' are the I and Q components of the first pulse.
    :param pulse2: tuple containing the element and pulse number for the 2nd pulse. ex: ('resonator', 0)
    :return: center-to-center time (in ns) between the two pulses.  Note that if the element contains an IQ pair, then the pulse numbers have to be counted in pairs. ex: ('ensemble', 2) correspond to the 2nd pulse played from the element 'ensemble' since the numbers '0' and '1' are the I and Q components of the first pulse.
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


def KDD_XY4_separate_element(tau, element, index, N_max):
    j = declare(int)
    with for_(j, 0, j < N_max, j + 1):
        # KDD along X
        play("pi", element)
        wait(
            tau[10 * j + index]
            + tau[10 * j + 1 + index]
            + tau[10 * j + 2 + index]
            + tau[10 * j + 3 + index]
            + tau[10 * j + 4 + index]
            - 20,
            element,
        )
        frame_rotation_2pi(1 / 4, element)
        # KDD along Y
        play("pi", element)
        with if_(j < N_max - 1):
            wait(
                tau[10 * j + 5 + index]
                + tau[10 * j + 6 + index]
                + tau[10 * j + 7 + index]
                + tau[10 * j + 8 + index]
                + tau[10 * j + 9 + index]
                - 55,
                element,
            )
        frame_rotation_2pi(-1 / 4, element)


pulses = 200
accuracy = 2**5
resolution = 4
perfect_taus = [148, 149, 150, 151, 152, 153, 154]
perfect_taus_fixed = np.array(perfect_taus) / accuracy

sequence = []
sequence_length = []
for perfect_tau in perfect_taus:
    taus = [
        resolution * np.floor(perfect_tau / resolution),
        resolution * np.floor(perfect_tau / resolution) + resolution,
    ]
    sequence += [
        sequence_generator((perfect_tau - taus[0]) / resolution, pulses, taus)[0]
    ]
    sequence += sequence_generator((perfect_tau - taus[0]) / resolution, pulses, taus)

    sequence_length.append(
        len(sequence_generator((perfect_tau - taus[0]) / resolution, pulses, taus)) + 1
    )

sequence = list(np.reshape(sequence, sum(sequence_length)))

for i in range(len(sequence)):
    sequence[i] = int(sequence[i] // 4)

with program() as demo_2:
    a = declare(fixed)
    i = declare(int)
    j = declare(int)
    count = declare(int)
    error = declare(fixed)
    cumulated_error = declare(fixed)
    factor = declare(fixed, value=1 / accuracy)
    assign(factor, 1 / accuracy) # why are we assigning the value again?
    threshold = declare(fixed, value=0.5 / accuracy)

    # tau = declare(int, value=sequence)
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
    with for_(count, 0, count < len(perfect_taus), count + 1):
        assign(tau_window[0], perfect_taus_qua[count])
        assign(tau_window[1], perfect_taus_qua[count] + resolution)
        assign(
            error,
            (
                perfect_taus_fixed_qua[count]
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

        assign(total, Math.sum(tau)+tau[0])

        align("NV1_1", "NV1_2", "NV1_3", "NV1_4", "NV1_5", "NV1_6")

        wait(9, 'NV1_6')
        play("pi_half", "NV1_6")

        wait(tau[0], "NV1_1")
        wait(tau[0] + tau[0], "NV1_2")
        wait(tau[0] + tau[0] + tau[1], "NV1_3")
        wait(tau[0] + tau[0] + tau[1] + tau[2], "NV1_4")
        wait(tau[0] + tau[0] + tau[1] + tau[2] + tau[3], "NV1_5")

        for k in range(5):
            KDD_XY4_separate_element(tau, f"NV1_{k + 1}", k, pulses // 10)

        wait(total - 10, "NV1_6")
        play("pi_half", "NV1_6")


############
# simulate #
############

job = qmm.simulate(
    config,
    demo_2,
    simulate=SimulationConfig(duration=80000, include_analog_waveforms=True),
)

job.get_simulated_samples().con1.plot(analog_ports=["1"])
job.get_simulated_samples().con1.plot(analog_ports=["2"])

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
print(sequence)
plt.figure()
plt.plot(sequence)
plt.plot(delays)
# delays1 = []
# for i in range(len(sequence[::2])-1):
#     delays1.append(get_c2c_time(job, ("qubit2",2*i), ("qubit2",2*i+2))//4)
# # delays2 = []
# # for i in range(len(sequence[1::2])-1):
# #     delays2.append(get_c2c_time(job, ("qubit", 2 * i), ("qubit", 2 * i+2)) // 4)

# sequence1 = np.zeros(len(sequence)//2)
# sequence2 = np.zeros(len(sequence)//2)
# for i in range(len(sequence)//2-1):
#     sequence1[i] = sequence[2*i+2] + sequence[2*i+3]
#     sequence2[i] = sequence[2 * i + 1] + sequence[2 * i + 2]
#
# print("Delays qubit 2:")
# print(list(np.array(delays1).astype(int)))
# print("Sequence qubit 2:")
# print(list(sequence1.astype(int)))
# print("Delays qubit:")
# print(list(np.array(delays2).astype(int)))
# print("Sequence qubit:")
# print(list(sequence2.astype(int)))
