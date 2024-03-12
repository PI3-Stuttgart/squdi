# -*- coding: utf-8 -*
from collections import OrderedDict
import datetime
import matplotlib.pyplot as plt
import numpy as np
import time
from time import sleep
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.core.module import LogicBase
from qudi.hardware.cwave.cwave_api import PiezoChannel, StatusBit, PiezoMode, ExtRampMode, StepperChannel, Log, ShutterChannel
from PySide2 import QtCore

class LaserControllerLogic(LogicBase):
    motor_pulser = Connector(name = 'motor_pulser', interface='DigitalSwitchNI')
    ao_laser_control = Connector(name = 'ao_laser_control', interface='NIXSeriesAnalogOutput')
    _etalon_voltage = 0
    _motor_direction = 1

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_activate(self) -> None:
        self._motor_pulser = self.motor_pulser()
        self._ao_laser_control = self.ao_laser_control() 

    def on_deactivate(self) -> None:
        self._ao_laser_control.set_activity_state(active=False)
       
    @property
    def etalon_voltage(self):
        return self._etalon_voltage

    @etalon_voltage.setter
    def etalon_voltage(self, voltage):
        self._ao_laser_control.set_activity_state(channel = 'ao0', active=True)
        self._ao_laser_control.set_setpoint(channel = 'ao0', value = voltage)
        self._ao_laser_control.set_activity_state(channel = 'ao0', active=False)
        self._etalon_voltage = voltage

    @property
    def motor_direction(self):
        return self._motor_direction

    @motor_direction.setter
    def motor_direction(self, sign):
        self._ao_laser_control.set_activity_state(channel = 'ao2', active=True)
        if sign > 0:
            self._ao_laser_control.set_setpoint(channel = 'ao2', value = 5)
        elif sign < 0 :
            self._ao_laser_control.set_setpoint(channel = 'ao2', value = -5)
        self._ao_laser_control.set_activity_state(channel = 'ao2', active=False)
        self._motor_direction = sign

    def move_motor_pulse(self):
        self._motor_pulser.set_state(switch="motor", state='Low') #'High' should be pulsing?
        