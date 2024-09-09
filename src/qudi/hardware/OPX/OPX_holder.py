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
        """Create the digital switch output control module"""
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()
        self._channels = tuple()
        self.mcas_dict = dict()

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

