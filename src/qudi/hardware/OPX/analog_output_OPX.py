import importlib
from typing import Dict, Tuple, Any
import time

from qualang_tools.control_panel import ManualOutputControl
import qm

from qudi.core.configoption import ConfigOption
from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)


class AnalogOutputOPX(ProcessSetpointInterface):
    """Module to set the manually set the Analog Outputs of the QuantumMachines OPX+.
    Channels are defined by the OPXs own config file and not using qudi.
    Example config for copy-paste:
    AO_OPX:
        module.Class: 'OPX.analog_output_OPX.AnalogOutputOPX'
        options:
            qm_config_file: "configuration"
    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )
    _switch_time = ConfigOption(name="switch_time", default=1, missing="nothing")

    _configuration = None
    _qm_manual_output_control = None
    _constraints = None

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        # Establish connection to OPX+
        self._set_constraints()
        self._connect_to_OPX()

    def on_deactivate(self) -> None:
        self._qm_manual_output_control.close()

    def _set_constraints(self):
        _channels: list = []
        for name, qm_element in self._configuration.config["elements"].items():
            if "singleInput" in qm_element.keys():
                _channels.append(name)

        self._constraints = ProcessControlConstraints(
            setpoint_channels=_channels,
            units={ch: "V" for ch in _channels},
            limits={ch: (-0.5, 0.5) for ch in _channels},
            dtypes={ch: float for ch in _channels},
        )

    def _connect_to_OPX(self) -> None:
        #try:
        self._qm_manual_output_control = ManualOutputControl(
            self._configuration.config,
            host=self._configuration.qop_ip,
            close_previous=False,
            elements_to_control=self.constraints.setpoint_channels,
        )
        #except qm.exceptions.OpenQmException:
        #        self.log.warning(
        #            "Could not connect to OPX with keeping previous connections. Previouse connections disconnected."
        #        )
        #        self._qm_manual_output_control = ManualOutputControl(
        #            self._configuration.config,
        #            host=self._configuration.qop_ip,
        #            close_previous=True,
        #            elements_to_control=self.constraints.setpoint_channels,
        #        )

    @property
    def constraints(self) -> ProcessControlConstraints:
        """Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self._constraints

    def set_activity_state(self, channel: str, active: bool) -> None:
        """Set activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        OPX channels are always active, only setting the amplitude to zero deines them as
        inactive. This means it the active input is False, the amplitude is set to zero,
        but if it is set to True an warning is raised, as with this method no amplitude
        value is defined.
        """
        if active:
            self.log.warning(
                "OPX AO is always active, amplitude only can be set to zero for inactive state"
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
        try:
            self._qm_manual_output_control.set_amplitude(channel, value)
        except: #qm.exceptions.QMConnectionError
            self.log.warning("Reconnecting OPX ...")
            self._connect_to_OPX()
            self._qm_manual_output_control.set_amplitude(channel, value)

        # time.sleep(self._switch_time)

    def get_setpoint(self, channel: str) -> float:
        """Get current setpoint for a single channel"""
        ao_status: dict[str, dict[str, float]] = (
            self._qm_manual_output_control.analog_status()
        )

        return ao_status[channel]["amplitude"]
