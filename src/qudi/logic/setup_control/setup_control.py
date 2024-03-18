# -*- coding: utf-8 -*-
"""
Interact with switches.

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

from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
import time


class SetupControlLogicQINU(LogicBase):
    
    Adwin_IO = Connector(interface='Adwin_IO')
    
    powermeter_in = False

    
    def __init__(self, config, **kwargs):   
        super().__init__(config=config, **kwargs)
        
        
    def on_activate(self):
        self.io_dev = self.Adwin_IO()
        self.io_dev.boot_adwin()
        self.io_dev.start_adwin_processes(['control_analog_out.TB9'])  
        self.io_dev.start_adwin_processes(['control_digout.TB0'])
    
    def on_deactivate(self):
        del self.io_dev
        
    def activate_green_laser(self, active: bool):
        self.io_dev.set_digi_out(
            self.io_dev.port_by_name('green_laser'), active)
        
        
    def activate_lamp(self, active: bool):
        self.io_dev.set_digi_out(
            self.io_dev.port_by_name('lamp'), active)
      
      
    def flip_powermeter(self, flipped_in:bool):
        self._flip(self.io_dev.port_by_name('flip_powermeter'))
    
    def set_green_power(self, power_percentage: float):
        self.io_dev.set_analog_out(
            self.io_dev.port_by_name('green_laser_attenuation'), 
            self._calculate_attenuation_from_power(power_percentage)
            )
        

    ### Helper functions for standard devices ##
  
    def _flip(self, port: int, delta_t_on: float = 0.1):
        print(delta_t_on)
        self.io_dev.set_digi_out(port, True)
        time.sleep(delta_t_on)
        self.io_dev.set_digi_out(port, False)
       
    @staticmethod 
    def _calculate_attenuation_from_power(power_percentage: float) -> float:
        """Calculates voltage for needed attenuation for thorlabs 
        'Electronic Variable Optical Attenuators, Voltage Controlled & SM Fiber Coupled'
        out of percentage [0,100] of wanted power.

        Args:
            power_percentage (float): percentage of wanted power [0,100]

        Returns:
            float: Needed voltage supplied by the IO_device to the attenuater
        """
        min_voltage = 0
        max_voltage = 5
        if 0 <=  power_percentage <= 1000:
            return 5 * (1 - power_percentage/100)
        
        raise ValueError('Power out of range')
        
        
        
        
        
         
        
    
    
        
        
        
        
    