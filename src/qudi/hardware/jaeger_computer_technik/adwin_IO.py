"""
This file contains the Qudi dummy module for the confocal scanner.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import time
import numpy as np
from PySide2 import QtCore
from fysom import FysomError
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.anolog_and_digital_io import AnalogAndDigitalIO 
from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase
import os
import ADwin

class Adwin_IO(AnalogAndDigitalIO, AdwinBase):
    
    # Imports the conifg for all available ports
    _ports = ConfigOption(name='ports', missing='warn')

    def on_activate(self):
        self.boot_adwin()
        self.start_adwin_processes(['control_analog_out.TB9'])  
        self.start_adwin_processes(['control_digout.TB0'])
        
        
    def on_deactivate(self):
        """Stops all adwin process needed for the script
        """
        # TODO
        pass
    
    def init_analog_outputs(self):
        pass

    
    def set_digi_out(self, port: int, active: bool):
        
        if self.available_ports()['digital'][port]['IO'] == 'in':
            par_idx = 8 if port == 0 else port
        
            if active:
                self.adwin.Set_Par(par_idx, 1)
            if not active:
                self.adwin.Set_Par(par_idx, 0)
        else:
            raise ValueError('Port is not defined')
    
    def get_digi_out(self, port: int) -> bool:
        pass
    
    
    def set_analog_out(self, port: int, voltage: float):
        
        if self.available_ports()['analog'][port] is not None:
            par_idx = 8 if port == 0 else port

            self.adwin.Set_FPar(par_idx, voltage)
    
    
    def get_analog_out(self, port: int) -> float:
        pass
    
    def available_ports(self) -> dict:
        return self._ports