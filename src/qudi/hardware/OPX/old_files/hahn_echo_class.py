"""
A Hahn Echo experiment designed to be accessed through other python files.
"""
from qm.QuantumMachinesManager import QuantumMachinesManager
from qm.qua import *
import matplotlib.pyplot as plt
from qm import SimulationConfig
from configuration import *

###################
# The QUA program #
###################


class hahn_echo:

    n_avg = 1e6
    alternating = True

    def __init__(self, pi_half_len, pi_len, freq, amp_corr, t_min, t_max, dt):
        self.pi_half_len = pi_half_len
        self.pi_len = pi_len
        self.new_freq = freq
        self.amp_corr = amp_corr
        self.t_min = t_min  # in clock cycles units (must be >= 4)
        self.t_max = t_max  # in clock cycles units
        self.dt = dt  # in clock cycles units
        self.t_vec = np.arange(self.t_min, self.t_max + 0.1, self.dt)  # +0.1 to include t_max in array

    def program(self):
        with program() as time_rabi:
            update_frequency("NV1", self.new_freq)
            counts = declare(int)  # variable for number of counts
            counts_alt = declare(int)
            counts_st = declare_stream()  # stream for counts
            counts_st_alt = declare_stream()
            times = declare(int, size=100)
            times_alt = declare(int, size=100)
            t = declare(int)  # variable to sweep over in time
            n = declare(int)  # variable to for_loop
            n_st = declare_stream()  # stream to save iterations

            play("laser_ON", "AOM_green")
            wait(100, "AOM_green")
            with for_(n, 0, n < self.n_avg, n + 1):
                with for_(t, self.t_min, t <= self.t_max, t + self.dt):
                    play("pi_half"*amp(self.amp_corr), "NV1", duration=self.pi_half_len)
                    wait(t, "NV1")
                    play("pi"*amp(self.amp_corr), "NV1", duration=self.pi_len)
                    wait(t, "NV1")
                    play("pi_half"*amp(self.amp_corr), "NV1", duration=self.pi_half_len)
                    wait(100, "NV1")
                    align("NV1", "AOM_green", "SPCM")
                    play("laser_ON", "AOM_green")
                    measure("readout", "SPCM", None, time_tagging.analog(times, meas_len, counts))
                    save(counts, counts_st)  # save counts
                    wait(1000)
                    align("NV1", "AOM_green", "SPCM")

                    if self.alternating:
                        play("pi_half" * amp(self.amp_corr), "NV1", duration=self.pi_half_len)
                        wait(t, "NV1")
                        play("pi" * amp(self.amp_corr), "NV1", duration=self.pi_len)
                        wait(t, "NV1")
                        frame_rotation_2pi(0.5, "NV1")
                        play("pi_half" * amp(self.amp_corr), "NV1", duration=self.pi_half_len)
                        wait(100, "NV1")
                        reset_frame("NV1")
                        align("NV1", "AOM_green", "SPCM")
                        play("laser_ON", "AOM_green")
                        measure("readout", "SPCM", None, time_tagging.analog(times_alt, meas_len, counts_alt))
                        save(counts_alt, counts_st_alt)  # save counts
                        wait(1000)
                        align("NV1", "AOM_green", "SPCM")

                save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
                counts_st.buffer(len(self.t_vec)).average().save("counts")
                counts_st_alt.buffer(len(self.t_vec)).average().save("counts_alt")
                n_st.save("iteration")

        #####################################
        #  Open Communication with the QOP  #
        #####################################
        qmm = QuantumMachinesManager(qop_ip)

        qm = qmm.open_qm(config)

        simulation_duration = 10000
        job_sim = qm.simulate(time_rabi, SimulationConfig(simulation_duration))
        job_sim.get_simulated_samples().con1.plot()
