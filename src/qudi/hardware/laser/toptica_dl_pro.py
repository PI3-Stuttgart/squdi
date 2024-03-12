

from qudi.core.configoption import ConfigOption
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict
from qudi.interface.simple_laser_interface import SimpleLaserInterface
from qudi.interface.triggered_ao_interface import TriggeredAOInterface
from qudi.interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from enum import IntEnum
from qudi.interface.process_control_interface import ProcessControlConstraints
import time
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro,LaserHead,  NetworkConnection, DeviceNotFoundError
import functools
import asyncio
_Real = Union[int, float]

def connect_laser(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(loop)
        with DLCpro(NetworkConnection(self.tcp_address)) as self.dlc:
            res = func(self, *args, **kwargs)
        return res

    return wrapper

def get_key_by_value(dictionary, target_value):
    for key, value in dictionary.items():
        if value == target_value:
            return key
    return None  # Return None if the value is not found in the dictionary


class LaserState(IntEnum):
    OFF = 0
    ON = 1

class DlProLaser(SimpleLaserInterface, TriggeredAOInterface):
    """ ToDo: describe

    Example config for copy-paste:

    dl_pro:
        module.Class: 'laser.toptica_dl_pro.DlProLaser'
        tcp_address: '169.254.128.41'
        current_range: [0, 90]
    """

    tcp_address = ConfigOption(name='tcp_address', missing='error')
    current_range = ConfigOption(name='current_range', default=(0, 4), missing='warn')
    _ao_channel_config = ConfigOption(
        name='ao_channel_config',
        default={
            'OutA': {'limits': (0.0, 4.0), 'keep_value': True},
            'OutB': {'limits': (0.0, 4.0), 'keep_value': True},
        },
        missing='warn'
    )
    _trigger_channel = ConfigOption(name='trigger_channel', default=3, missing='warn')
    # max = ConfigOption(name='maxpower', default=0.250, missing='warn')
    channel_mapping = {
       "OutA": 20,
       "OutB": 21
    }
    detune_for_trigger = 0.01
    def on_activate(self):
        """ Activate module.
        """
        self._ao_channel = list(self._ao_channel_config.keys())[0]
    
        self._constraints = ProcessControlConstraints(
            setpoint_channels=self._ao_channel_config.keys(),
            units={ch: 'V' for ch in self._ao_channel_config},
            limits={ch:config["limits"]  for ch, config in self._ao_channel_config.items()},
            dtypes={ch: float for ch in self._ao_channel_config}
        )
        self.get_laser_state()

    def on_deactivate(self):
        """ Deactivate module.
        """
        return 
    
    def set_activity_state(self, channel: str, active: bool) -> None:

        pass

    def get_activity_state(self, channel: str) -> bool:
        """ Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        return True


    @property
    def constraints(self) -> ProcessControlConstraints:
        """ Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self._constraints

    @connect_laser
    def get_current_setpoint(self):
        """ Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.dlc._laser1.dl.cc.current_set.get()

    @connect_laser
    def set_current(self, current):
        """ Set laser current setpoint

        @param float current: desired laser current setpoint
        set current in mA
        """
       
        self.dlc._laser1.dl.cc.current_set.set(current)

    @connect_laser
    def set_laser_state(self, state):
        """ Set laser state.

        @param LaserState state: desired laser state enum

        dlc is instantianed in the decorator
        """
        return self.dlc._laser1.dl.cc.enabled.set(bool(state))

    @connect_laser
    def get_laser_state(self):
        """ Get laser state

        @return LaserState: current laser state
        """
        return int(self.dlc._laser1.dl.cc.enabled.get())

    @connect_laser
    def get_current(self):
        """ Get actual laser current

        @return float: laser current in current units
        """
        return self.dlc._laser1.dl.cc.current_set.get()


    def get_current_range(self):
        """ Get laser current range.

        @return float[2]: laser current range
        """
        return self.current_range

    def get_current_unit(self):
        """ Get unit for laser current.

        @return str: unit
        """
        return "mA"

    def get_power_range(self):
        """ Return laser power range

        @return float[2]: power range (min, max)
        """
        return (0,1)

    
    def get_power(self):
        """ Return actual laser power

        @return float: Laser power in watts
        """
        return 0

    
    def set_power(self, power):
        """ Set power setpoint.

        @param float power: power to set
        """
        pass


    def get_power_setpoint(self):
        """ Return laser power setpoint.

        @return float: power setpoint in watts
        """
        return 0
 


    def allowed_control_modes(self):
        """ Get supported control modes

        @return frozenset: set of supported ControlMode enums
        """
        return {ControlMode.CURRENT}

 
    def get_control_mode(self):
        """ Get the currently active control mode

        @return ControlMode: active control mode enum
        """
        return ControlMode.CURRENT

  
    def set_control_mode(self, control_mode):
        """ Set the active control mode

        @param ControlMode control_mode: desired control mode enum
        """
        return ControlMode.CURRENT


    def get_shutter_state(self):
        """ Get laser shutter state

        @return ShutterState: actual laser shutter state
        """
        return ShutterState.NO_SHUTTER

 
    def set_shutter_state(self, state):
        """ Set laser shutter state.

        @param ShutterState state: desired laser shutter state
        """
        pass

   
    def get_temperatures(self):
        """ Get all available temperatures.

        @return dict: dict of temperature names and value in degrees Celsius
        """
        return {"Laser": 0}

    
    def get_extra_info(self):
        """ Show dianostic information about lasers.
          @return str: diagnostic info as a string
        """
        pass

    @connect_laser
    def set_setpoint(self, channel: str, value) -> None:
        """ Set new setpoint for a single channel """
        value = float(value)
        
        if not self.constraints.channel_value_in_range(channel, value)[0]:
            raise ValueError(f'Setpoint {value} for channel "{channel}" out of allowed '
                                f'value bounds {self.constraints.channel_limits[channel]}')
        self.dlc.laser1.wide_scan.value_set.set(value)

    @connect_laser
    def get_setpoint(self, channel: str):
        """ Get current setpoint for a single channel """
        return self.dlc.laser1.wide_scan.value_set.get()
    @connect_laser
    def set_pc_voltage(self, voltage):
        return self.dlc.laser1.pc.voltage_set.set(voltage)
    @connect_laser
    def get_pc_voltage_set(self):
        return self.dlc.laser1.pc.voltage_set.get()
    @connect_laser
    def get_pc_voltage_act(self):
        return self.dlc.laser1.pc.voltage_act.get()
    
    @connect_laser 
    def set_scan_parameters(self, 
                            voltage_start: _Real, 
                            voltage_stop: _Real,
                            sweep_duration: _Real,
                            )->None:
        """
            voltages in Volts
            sweep in seconds
        """
        self.dlc.laser1.wide_scan.scan_begin.set(voltage_start - self.detune_for_trigger) # fix the 0.01
        self.dlc.laser1.wide_scan.trigger.output_threshold.set(voltage_start)

        self.dlc.laser1.wide_scan.scan_end.set(voltage_stop)
        self.dlc.laser1.wide_scan.duration.set(sweep_duration)

    @connect_laser 
    def get_scan_parameters(self):
        """ Get current setpoint for a single channel """
        voltage_start = self.dlc.laser1.wide_scan.scan_begin.get()
        voltage_stop = self.dlc.laser1.wide_scan.scan_end.get()
        sweep_duration = self.dlc.laser1.wide_scan.duration.get()
        return voltage_start, voltage_stop, sweep_duration

    @connect_laser 
    def start_scan(self) -> None:
        """ Get current setpoint for a single channel """
        # self.enable_trigger()
        # self.dlc.laser1.scan.enabled.set(True)
        self.dlc.laser1.wide_scan.start()
    
    @connect_laser
    def stop_scan(self) -> None:
        """ Get current setpoint for a single channel """
        # self.dlc.laser1.scan.enabled.set(True)
        self.dlc.laser1.wide_scan.stop()
    
    @connect_laser
    def enable_trigger(self):
        self.dlc.laser1.wide_scan.trigger.output_channel.set(self._trigger_channel)
        self.dlc.laser1.wide_scan.trigger.output_enabled.set(True)

    @connect_laser
    def is_scanning(self):
        return self.dlc.laser1.scan.enabled.get()
    
    @property
    @connect_laser
    def ao_channel(self):
        return get_key_by_value(self.channel_mapping, self.dlc.laser1.wide_scan.output_channel.get())
    
    @ao_channel.setter
    @connect_laser
    def ao_channel(self, ao_channel: str) -> None:
        self._ao_channel = self.channel_mapping[ao_channel]
        self.dlc.laser1.wide_scan.output_channel.set(self._ao_channel)


