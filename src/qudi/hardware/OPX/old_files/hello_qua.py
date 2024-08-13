"""
Counts photons while sweeping the frequency of the applied MW.
"""
from qm.QuantumMachinesManager import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *

###################
# The QUA program #
###################

with program() as prog:
    # update_frequency('NV1', 10e6)
    a = declare(fixed)
    timestamps = declare(int, size = 100)
    counts = declare(int)
    # with infinite_loop_():
    wait(10, 'NV2')
    # play('cw', 'NV1', duration=10)
    # play('cw', 'NV2', duration=10)
    wait(1000, 'NV1')




#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(qop_ip, host)

qm = qmm.open_qm(config)
simulate = True

if simulate:
    simulation_duration = 5000
    job_sim = qm.simulate(prog,SimulationConfig(simulation_duration))
    job_sim.get_simulated_samples().con1.plot()
    plt.show()
else:
    job = qm.execute(prog)  # execute QUA program




