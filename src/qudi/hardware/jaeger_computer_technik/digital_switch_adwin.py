import time
from typing import Dict, Tuple, Any, Union

from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase, AdwinStatus

from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.switch_interface import SwitchInterface


class DigitalSwitchAdwin(SwitchInterface, AdwinBase):
    """This class enables to control the TTL digital outputs of the Qunantum Machine OPX.
    Control external hardware by the output of the digital channels of the Adwin.

    Example config for copy-paste:

    digital_switch_adwin:
        module.Class: 'jaeger_computer_technik.digital_switch_adwin.DigitalSwitchAdwin'
        options:
            switches:
                laser_550:
                    port: 3
                    pulsed_output: True # optional (for example for flipp mirrors)
                    states: ['out', 'in'] # optional, default is ('off', 'on')
    """

    switch_states_pulsed_outputs = {}
    switches = ConfigOption(name="switches", missing="error")
    _default_pulse_length = 0.1  # s

    def __init__(self, *args, **kwargs) -> None:
        """Create the digital switch output control module"""
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()

        self._channels = tuple()

    def on_activate(self) -> None:
        self.boot_adwin()
        self.start_adwin_processes(["control_digout.TB0"])
        self._init_pulsed_output_switches()

    def on_deactivate(self) -> None:
        """Stops all adwin process needed for the script"""
        self.stop_adwin_processes(["control_digout.TB0"], clear_processes=True)

    def _init_pulsed_output_switches(self) -> None:
        for switch, element in self.switches.items():
            if "pulsed_output" in element:
                if element["pulsed_output"]:
                    self.switch_states_pulsed_outputs[switch] = self.available_states[
                        switch
                    ][0]

    @property
    def name(self) -> str:
        """Name of the hardware as string.

        @return str: The name of the hardware
        """
        return "Adwin"

    @property
    def available_states(self) -> Dict[str, Tuple[str, ...]]:
        """Names of the states as a dict of tuples.

        The keys contain the names for each of the switches. The values are tuples of strings
        representing the ordered names of available states for each switch.

        @return dict: Available states per switch in the form {"switch": ("state1", "state2")}
        """

        _states = {}
        for switch in self.switches.keys():
            if "states" in self.switches[switch]:
                if len(self.switches[switch]["states"]) == 2:
                    _states[switch] = tuple(self.switches[switch]["states"])
                else:
                    self.log.warning(f"Defined states on {switch} are not valid.")
                    _states[switch] = ("off", "on")
            else:
                _states[switch] = ("off", "on")

        return _states

    def get_state(self, switch: str) -> Union[str, None]:
        """Query state of single switch by name

        @param str switch: name of the switch to query the state for
        @return str: The current switch state
        """
        if switch in self.switch_states_pulsed_outputs:
            return self.switch_states_pulsed_outputs[switch]
        else:
            port = self.switches[switch]["port"]
            par_idx = 8 if port == 0 else port
            do_status, _ = self.read_par(par_idx)
        if do_status == 1:
            return self.available_states[switch][1]
        else:
            return self.available_states[switch][0]

    def set_state(self, switch: str, state: str) -> None:
        """Query state of single switch by name

        @param str switch: name of the switch to change
        @param str state: name of the state to set
        """
        if switch in self.switch_states_pulsed_outputs:
            if state != self.switch_states_pulsed_outputs[switch]:
                self._pulse(switch)
                self.switch_states_pulsed_outputs[switch] = state
        else:
            port = self.switches[switch]["port"]
            par_idx = 8 if port == 0 else port
            if state == self.available_states[switch][1]:
                _ = self.write_par(par_idx, 1)
            if state == self.available_states[switch][0]:
                _ = self.write_par(par_idx, 0)

    def _pulse(self, switch: str) -> None:
        if "pulse_length" in self.switches[switch]:
            pulse_length: float = self.switches[switch]["pulse_length"]
        else:
            pulse_length: float = self._default_pulse_length

        port = self.switches[switch]["port"]
        par_idx = 8 if port == 0 else port

        _ = self.write_par(par_idx, 1)
        time.sleep(pulse_length)
        _ = self.write_par(par_idx, 0)
