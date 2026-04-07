import importlib
from typing import Any, Dict, Tuple, Union

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.util.mutex import RecursiveMutex

from qudi.interface.switch_interface import SwitchInterface


class DigitalSwitchOPX(SwitchInterface):
    """This class enables to control the TTL digital outputs of the Qunantum Machine OPX.
    Control external hardware by the output of the digital channels of the OPX.
    The Switches are defined in the OPXs own configuration file, and not with the help of qudi.

    Example config for copy-paste:

        digital_switch_opx:
        module.Class: 'OPX.digital_switch_OPX.DigitalSwitchOPX'
        connect:
            OPX: "OPX"
        options:
            qm_config_file: 'configuration'

    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )
    OPX = Connector(interface="OPX")
    _configuration: Any
    _qm_manual_output_control = None
    _opx = None

    # TODO: Is this init function needed?
    def __init__(self, *args, **kwargs):
        """Create the digital switch output control module"""
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()

        self._channels = tuple()  # create instance of OPX_holder

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(f"qudi.hardware.OPX.{self._qm_config_file}")
        # Check connection to OPX+
        self._opx = self.OPX()
        if not self._opx.is_connected:
            self.log.error("no connection to OPX")

        self._opx.cw_do_states = {do: "off" for do in self.available_states.keys()}

    def on_deactivate(self) -> None:
        pass

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
            if "active" in qm_element["operations"].keys():
                _states[name] = ("off", "on")

        return _states

    def get_state(self, switch: str) -> Union[str, None]:
        """Query state of single switch by name

        @param str switch: name of the switch to query the state for
        @return str: The current switch state
        """
        return self._opx.cw_do_states[switch]

    def set_state(self, switch: str, state: str) -> None:
        """Query state of single switch by name

        @param str switch: name of the switch to change
        @param str state: name of the state to set
        """
        self._opx.update_cw_do(switch, state)
