"""
        HELLO QUA
A simple sandbox to showcase different QUA functionalities during the installation.
"""

import time
from qm import SimulationConfig, LoopbackInterface
from qm.grpc.qua import QuaProgramArrayVarRefExpression, QuaProgramVarRefExpression
from qm.qua import *
from qm import QuantumMachinesManager
from qm.qua._expressions import QuaVariable
from configuration import *
import matplotlib.pyplot as plt

single_integration_time_ns = int(1000 * u.ns)
###################
# The QUA program #
###################
with program() as hello_QUA:
    a: QuaVariable | QuaProgramArrayVarRefExpression | QuaProgramVarRefExpression = (
        declare(fixed)
    )
    with infinite_loop_():
        with for_(a, 0, a < 1.1, a + 0.05):
            # play("x180" * amp(a), "NV")
            play("const" * amp(1), "RF")
            play(
                pulse="trigit",
                element="Gate_Trigger",
                duration=single_integration_time_ns,
            )
            wait(single_integration_time_ns, "Gate_Trigger")
        wait(25, "NV")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(
    host=qop_ip, cluster_name=cluster_name, octave=octave_config
)

###########################
# Run or Simulate Program #
###########################

simulate = False

if simulate:
    # Simulates the QUA program for the specified duration
    simulation_config = SimulationConfig(duration=1_000)  # In clock cycles = 4ns
    job_sim = qmm.simulate(config, hello_QUA, simulation_config)
    # Simulate blocks python until the simulation is done
    # job_sim.get_simulated_samples().con1
    job_sim.get_simulated_samples().con1.plot()
    plt.show()
else:
    qm = qmm.open_qm(config)
    job = qm.execute(hello_QUA)
    # Execute does not block python! As this is an infinite loop, the job would run forever. In this case, we've put a 10
    # seconds sleep and then halted the job.
    time.sleep(10)
    job.halt()
    # time.sleep(10)
    # print(job.execution_report())
