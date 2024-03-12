
import numpy as np
from abc import abstractmethod
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict

from qudi.core.module import Base
from qudi.util.helpers import in_range

from qudi.interface.process_control_interface import ProcessControlConstraints
from qudi.interface.process_control_interface import ProcessSetpointInterface
from qudi.interface.mixins.process_control_switch import ProcessControlSwitchMixin
_Real = Union[int, float]

class TriggeredAOInterface(ProcessSetpointInterface):
    """ A simple interface to control the setpoint for one or multiple process values.

    This interface is in fact a very general/universal interface that can be used for a lot of
    things. It can be used to interface any hardware where one to control one or multiple control
    values, like a temperature or how much a PhD student get paid.
    """

    @abstractmethod
    def set_setpoint(self, channel: str, value: _Real) -> None:
        """ Set new setpoint for a single channel """
        pass

    @abstractmethod
    def get_setpoint(self, channel: str) -> _Real:
        """ Get current setpoint for a single channel """
        pass

    @abstractmethod
    def set_scan_parameters(self, channel: str, 
                            voltage_start: _Real, 
                            voltage_stop: _Real,
                            sweep_duration: _Real) -> None:
        """ Get current setpoint for a single channel """
        pass
    @abstractmethod
    def get_scan_parameters(self, channel: str) -> (_Real, _Real, _Real):
        """ Get current setpoint for a single channel """
        pass

    @abstractmethod
    def start_scan(self, channel: str) -> None:
        """ Get current setpoint for a single channel """
        pass

    @abstractmethod
    def stop_scan(self, channel: str) -> None:
        """ Get current setpoint for a single channel """
        pass

    
    
    # Non-abstract default implementations below

    @property
    def setpoints(self) -> Dict[str, _Real]:
        """ The current setpoints (values) for all channels (keys) """
        return {ch: self.get_setpoint(ch) for ch in self.constraints.setpoint_channels}

    @setpoints.setter
    def setpoints(self, values: Mapping[str, _Real]) -> None:
        """ Set the setpoints (values) for all channels (keys) at once """
        for ch, setpoint in values.items():
            self.set_setpoint(ch, setpoint)
