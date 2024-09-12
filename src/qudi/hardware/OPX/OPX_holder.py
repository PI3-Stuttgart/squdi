import json
from qm import SimulationConfig, LoopbackInterface
from qm.grpc.qua import QuaProgramArrayVarRefExpression, QuaProgramVarRefExpression
from qm.qua import *
#from qm import QuantumMachinesManager
from qm.quantum_machines_manager import QuantumMachinesManager
from qm.qua._expressions import QuaVariable
#from configuration import *
import importlib
from typing import Dict, Tuple, Any, Union

import qm.exceptions
from qualang_tools.control_panel import ManualOutputControl
import qm
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.core.module import Base


#class OPXmanual(Base):
 #   ### TODO manualoutputcontrol.


class OPX(Base): #hardware, awg,
    """.
    Example config for copy-paste:
    OPX:
        module.Class: 'OPX_holder'
        options:
    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )

    _configuration: Any
    _qm_manual_output_control = None

    # TODO: Is this init function needed?
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()
        self._channels = tuple()
        self.debug_mode = False
        self.qm_device = None
        self.mcas_dict = dict()

    #def __setitem__(self, key, value):
       # print('setting mcas_ dict_ here', key, value)
    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        # Establish connection to OPX+
        self._connect_to_OPX()

    def on_deactivate(self) -> None:
        """TODO: disconnect from OPX?"""

    def cw_mode(self, analog_outputs: dict[str, float], digital_outputs: dict[str, bool]):
        self.curr_do = digital_outputs
        self.curr_ao = analog_outputs
        return cw_program


    @property
    def qm(self):
        if self.qm_device is None:
            self.qm_device = self.qmm.open_qm(config=self._configuration)
            return self.qm_device
        else:
            return self.qm_device
    def simulate(self, sequence, save_path = None, plot = False):
        """
        :param sequence: program() of the opx to simulate
        :return: opens a plotly html window with the sequence.
        """
        print('simulate')
        simulation_config = SimulationConfig(duration=1_000)  # In clock cycles = 4ns
        job_sim = self.qmm.simulate(self._configuration.config, sequence, simulation_config)
        # Simulate blocks python until the simulation is done
        # job_sim.get_simulated_samples().con1
        #job_sim.get_simulated_samples().con1.plot()
        #plt.show()
        # get DAC and digital samples (optional).
        samples = job_sim.get_simulated_samples()
        # get the waveform report object
        waveform_report = job_sim.get_simulated_waveform_report()
        waveform_dict = waveform_report.to_dict()
        if not save_path is None:
            with open(os.path.join(save_path,'awg_file.json'), 'w') as fp:
                json.dump(waveform_dict, fp)
        if plot:
            waveform_report.create_plot(samples, plot=plot, save_path="./" if save_path is None else save_path)
        # print(waveform_dict.keys())


    def _connect_to_OPX(self) -> None:
        try:
            self.qmm = QuantumMachinesManager(
               host=self._configuration.qop_ip,
                cluster_name=self._configuration.cluster_name,
                octave=self._configuration.octave_config)

        except qm.exceptions.OpenQmException:
            self.log.warning(
                "Could not connect to OPX with keeping previous connections. Previouse connections disconnected."
            )
            pass #do nothing for now...

    def stop_awgs(self):
        '''Stop all the tasks of the OPX...
        '''
        pass


    @property
    def name(self) -> str:
        """Name of the hardware as string.
        @return str: The name of the hardware
        """
        return self._configuration.cluster_name

