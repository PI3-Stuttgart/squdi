import importlib
from typing import Dict, Tuple, Any, Union

from qualang_tools.control_panel import ManualOutputControl

from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.switch_interface import SwitchInterface


class DigitalSwitchOPX(SwitchInterface):
    """This class enables to control the TTL digital outputs of the Qunantum Machine OPX.
    Control external hardware by the output of the digital channels of the OPX.
    The Switches are defined in the OPXs own configuration file, and not with the help of qudi.

    Example config for copy-paste:

    digital_switch_opx:
        module.Class: 'switches.digital_switch_OPX.DigitalSwitchOPX'
        options:

    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )

    _configuration: Any
    _qm_manual_output_control = None

    # TODO: Is this init function needed?
    def __init__(self, *args, **kwargs):
        """Create the digital switch output control module"""
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()

        self._channels = tuple()

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        # Establish connection to OPX+
        self._qm_manual_output_control = ManualOutputControl(
            self._configuration.config, host=self._configuration.qop_ip
        )

    def on_deactivate(self) -> None:
        """TODO: disconnect from OPX?"""

    @property
    def name(self) -> str:
        """Name of the hardware as string.

        @return str: The name of the hardware
        """
        return self._configuration.cluster_name

    @property
    def available_states(self) -> Dict[str, Tuple[str, ...]]:
        """Names of the states as a dict of tuples.

        The keys contain the names for each of the switches. The values are tuples of strings
        representing the ordered names of available states for each switch.

        @return dict: Available states per switch in the form {"switch": ("state1", "state2")}
        """

        _states = {}

        for name, qm_element in self._configuration.config["elements"].items():
            if "digitalInputs" in qm_element.keys():
                _states[name] = ("off", "on")

        return _states

    def get_state(self, switch: str) -> Union[str, None]:
        """Query state of single switch by name

        @param str switch: name of the switch to query the state for
        @return str: The current switch state
        """
        do_status: dict[str, str] = self._qm_manual_output_control.digital_status()

        if do_status[switch]:
            return "on"
        else:
            return "off"

    def set_state(self, switch: str, state: str) -> None:
        """Query state of single switch by name

        @param str switch: name of the switch to change
        @param str state: name of the state to set
        """
        if state == "on":
            self._qm_manual_output_control.digital_on(switch)
        if state == "off":
            self._qm_manual_output_control.digital_off(switch)
