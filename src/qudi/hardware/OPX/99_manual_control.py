from qualang_tools.control_panel import ManualOutputControl
from configuration import *
from qm import QuantumMachinesManager


# qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave=octave_config)
manual_output_control = ManualOutputControl(config, host=qop_ip)
manual_output_control.turn_on_element('AOM_575_MOD')
# manual_output_control.turn_off_elements('AOM_575_MOD')
# manual_output_control.set_amplitude('qubit', 0.25)
# manual_output_control.digital_off('qubit')
manual_output_control.set_amplitude('AOM_575_MOD', 0)
print(manual_output_control.analog_status())