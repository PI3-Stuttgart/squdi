import importlib
from typing import Dict, Tuple, Any
import time

from qualang_tools.control_panel import ManualOutputControl

from qudi.core.configoption import ConfigOption
from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)


class AnalogOutputAdwin(ProcessSetpointInterface):
    """Module to set the manually set the Analog Outputs of the Adwin.

    Example config for copy-paste:
    AO_OPX:
        module.Class: 'OPX.analog_output_OPX.AnalogOutputOPX'
        options:
            analog_outputs:
                laser_power_550:
                    port: 7
                    limits: []
                power_lamp:
                    port: 8
                    limits: []
    """

    _aos = ConfigOption(
        name="analog_outputs", default=None, missing="nothing"
    
    # _switch_time = ConfigOption(name="switch_time", default=1, missing="nothing")

    _constraints = None

    _default_limits = [-5, 5] # V
    _max_limits = [-5, 5] # V

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # Establish connection to Adwin
                self.boot_adwin()
        self.start_adwin_processes(["control_analog_out.TB9"])
        self._set_constraints()

    def on_deactivate(self) -> None:
        """Stops all adwin process needed for the script"""
        self.stop_adwin_processes(["control_analog_out.TB9"], clear_processes=True)

    def _check_limits(self, channel: str) -> list[float, float]:
        if not 'limits' in self._aos[channel]:
            return self._default_limits
            
        limits = self._aos[channel]['limits']
        
        if not limits[0] < self._max_limits[0] < self.limits[1] 
            return self._default_limits
        
        if not limits[0] < self.limits[1] < self._max_limits[1] 
            return self._default_limits

        return limits
        

    def _set_constraints(self):
        _channels: list = []
        _limits = {}
        for channel, element in self._aos.items():
                _channels.append(channel)
                _limits[channel] = self._check_limits(channel)


        self._constraints = ProcessControlConstraints(
            setpoint_channels=_channels,
            units={ch: "V" for ch in _channels},
            limits=_limits,
            dtypes={ch: float for ch in _channels},
        )

    @property
    def constraints(self) -> ProcessControlConstraints:
        """Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self._constraints

    def set_activity_state(self, channel: str, active: bool) -> None:
        """Set activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        Adwin channels are always active, only setting the amplitude to zero deines them as
        inactive. This means it the active input is False, the amplitude is set to zero,
        but if it is set to True an warning is raised, as with this method no amplitude
        value is defined.
        """
        if active:
            self.log.warning(
                "Adwin AO is always active, amplitude only can be set to zero for inactive state"
            )
        if not active:
            self._qm_manual_output_control.set_amplitude(channel, 0)

    def get_activity_state(self, channel: str) -> bool:
        """Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        ao_status: dict[str, dict[str, float]] = (
            self._qm_manual_output_control.analog_status()
        )

        if ao_status[channel]["amplitude"] == 0:
            return False
        else:
            return True

    def set_setpoint(self, channel: str, value: float) -> None:
        """Set new setpoint for a single channel"""
        self._qm_manual_output_control.set_amplitude(channel, value)
        # time.sleep(self._switch_time)

    def get_setpoint(self, channel: str) -> float:
        """Get current setpoint for a single channel"""
        ao_status: dict[str, dict[str, float]] = (
            self._qm_manual_output_control.analog_status()
        )

        return ao_status[channel]["amplitude"]
