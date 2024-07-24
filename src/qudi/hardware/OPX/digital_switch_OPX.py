import importlib
from qualang_tools.control_panel import ManualOutputControl
from configuration import *

import time
import re
import nidaqmx
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.switch_interface import SwitchInterface
from qudi.core.statusvariable import StatusVar

class DigitalSwitchOPX(SwitchInterface):
    """ This class enables to control the TTL digital outputs of the Qunantum Machine OPX.
    Control external hardware by the output of the digital channels of the OPX.

    Example config for copy-paste:

    digital_switch_ni:
        module.Class: 'switches.digital_switch_OPX.DigitalSwitchOPX'
        options:
            remember_states: True
            qm_config_file: 'configuration'

    """
    # switch_time to wait after setting the states for the connected hardware to react
    _switch_time = ConfigOption(name='switch_time', default=0.1, missing='nothing')
    # if remember_states is True the last state will be restored at reloading of the module
    _remember_states = ConfigOption(name='remember_states', default=True, missing='nothing')
    # relative path to QM configurtation file
    _qm_config_file = ConfigOption(name='qm_config_file', missing='warn')
    
    # TODO: Is this init function needed?
    def __init__(self, *args, **kwargs):
        """ Create the digital switch output control module
        """
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()

        self._channels = tuple()
        
    
    def on_activate(self) -> None:
        self.config = importlib.import_module(self._qm_config_file)
        
    def on_deactivate(self) -> None:
        pass
        
    
    def name(self) -> str:
        return self.config.cluster_name
    

    