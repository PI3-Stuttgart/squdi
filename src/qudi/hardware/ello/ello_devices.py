# -*- coding: utf-8 -*-
"""Example config:

    ello_devices:
        module.Class: 'ello.ello_devices.ThorlabsElloDevices'
        options:
            _serial_port: 'COM6'
            _rotor_port: '0'
"""

import os
from serial import Serial, EIGHTBITS,STOPBITS_ONE,PARITY_NONE
import qudi.hardware.ello.ello_flip as ello_flip
import qudi.hardware.ello.ello_rotation as ello_rotor
from qudi.core.configoption import ConfigOption
from qudi.core.module import Base

class ThorlabsElloDevices(Base):
    _flipper_port = ConfigOption('_flipper_port', False, missing='warn')
    _rotor_port = ConfigOption('_rotor_port', False, missing='warn')
    _serial_port = ConfigOption('_serial_port')
	
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
    
    def on_activate(self):
        self.connect()
        if self._flipper_port:
           self.ello_flip = ello_flip.ThorlabsElloFlipper(serial_port=self._serial_port, port=self._flipper_port, ell=self.ell)
        if self._rotor_port:
            self.ello_rotor = ello_rotor.ThorlabsElloRotation(serial_port=self._serial_port, port=self._rotor_port, ell=self.ell)

    def on_deactivate(self):
        self.disconnect()
    def disconnect(self):
        self.ell.close()
    def connect(self):
        self.ell = Serial(self._serial_port, baudrate=9600, bytesize=EIGHTBITS, stopbits=STOPBITS_ONE,parity= PARITY_NONE, timeout=2)



		