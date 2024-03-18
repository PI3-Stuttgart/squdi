from abc import abstractmethod
from qudi.core import Base
from typing import Dict, Mapping, Sequence, Tuple, List, Type
from enum import Enum 
from functools import singledispatch
from qudi.core.configoption import ConfigOption

class AnalogAndDigitalIO(Base):
    """ Describes a simple class to set analog and digital inputs and outputs
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    
    @property
    @abstractmethod
    def available_ports(self) -> dict:
        """returns a dictonary with all the available ports in the structure ...

        Returns:
            dict: 
        """
    
    
    @abstractmethod
    def set_digi_out(self, port: int, active: bool) -> bool:
        """Sets a digital output port to high or low.

        Args:
            port (int): Port number
            active (bool): True=high, False=low

        Returns:
            bool: Set state of output
        """
        pass
    
    @abstractmethod
    def set_analog_out(self, port: int, voltage: float) -> float:
        """Sets an analog output port to a specified voltage.

        Args:
            port (int): Port number
            voltage (float): Voltage in Volt

        Returns:
            float: Set Voltage to output 
        """
        pass
    
    @abstractmethod 
    def get_analog_out(self, port: int) -> float:
        """Gets voltage of a port.

        Args:
            port (int): Port number

        Returns:
            float: Voltage on output 
        """
        pass


    def port_by_name(self, name: str) -> int:
        """Returns port number by name of input or output.

        Args:
            name (str): In config file defined name of port

        Returns:
            int: Port number
        """
        
        for _, ports in self.available_ports().items():
            for port, values in ports.items():
                if values['name'] == name:
                    return port
            
        return Exception('port not found by name')
            
    

    
    

