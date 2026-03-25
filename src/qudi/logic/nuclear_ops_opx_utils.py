from typing import Any

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.logic.aom_power_calibration_logic import AOMPowerCalibrationLogic
from qudi.logic.transition_tracker import TransitionTracker
from qudi.hardware.OPX.OPX_holder import OPX
from qm import qua
from qm.qua import play, set_dc_offset, declare, fixed, for_, align, amp, infinite_loop_
from qualang_tools.units import unit

u = unit(coerce_to_integer=True)

from qualang_tools.loops import from_array


class NuclearOpsOPXUtils(LogicBase):
    """Bridge logic for calibrated OPX laser helper calls.

    The module resolves logical laser names to the corresponding calibration
    channel and OPX element. It exposes small helper methods that queue logic
    and future OPX/QM helper wrappers can use to convert requested laser powers
    in nW into calibrated voltage or OPX amplitude values.

    ``TransitionTracker`` is connected intentionally even though it is not used
    yet. This keeps the integration point in place for future laser metadata or
    experiment-parameter lookup without changing the queue wiring again.
    """

    TT_TRIGGER_LENGTH = 20 * u.ns

    power_calibration_logic: AOMPowerCalibrationLogic = Connector(interface="AOMPowerCalibrationLogic")
    transition_tracker_logic: TransitionTracker = Connector(interface="TransitionTracker")
    opx: OPX = Connector(interface="OPX")

    _power_calibration_logic: AOMPowerCalibrationLogic
    _transition_tracker: TransitionTracker
    _opx: OPX

    def on_activate(self) -> None:
        self._power_calibration_logic = self.power_calibration_logic()
        self._transition_tracker = self.transition_tracker_logic()
        self._opx = self.opx()

    def on_deactivate(self) -> None:
        self._power_calibration_logic = None
        self._transition_tracker = None

    @staticmethod
    def voltage_to_amp(voltage: float) -> float:
        return 2 * voltage

    @staticmethod
    def power_nw_to_watts(power_nw: float) -> float:
        return float(power_nw) * 1e-9

    def laser_power_to_voltage(self, laser_name: str, power_nw: float) -> float:
        return self._power_calibration_logic.power_to_voltage(
            self.power_nw_to_watts(power_nw),
            laser_name,
        )

    def laser_power_to_amp(self, laser_name: str, power_nw: float) -> float:
        return self.voltage_to_amp(self.laser_power_to_voltage(laser_name, power_nw))

    def laser_pulse(self, laser_name: str, duration_ns: float, power_nw: None | float = None) -> None:

        if power_nw:
            pulse = "pulse" * amp(self.laser_power_to_amp(laser_name, power_nw))
        else:
            pulse = "active"

        if duration_ns >= 1600 * u.ns:
            j_avg = 1000
            j = declare(int)
            with for_(j, 0, j < j_avg, j + 1):
                play(pulse, laser_name, duration_ns / j_avg * u.ns)
        else:
            play(pulse, laser_name, duration_ns * u.ns)

    def multiple_laser_pulses(self, laser_names: list[str], duration_ns: float, powers_nw: None | list[float | None] = None) -> None:

        pulses = []

        if powers_nw:

            if len(powers_nw) != len(laser_names):
                raise ValueError("I powers_ns defined it needs to be defined for all lasers, if no power should be given, use None")

            for laser_name, power_nw in zip(laser_names, powers_nw):
                if power_nw:
                    pulses.append("pulse" * amp(self.laser_power_to_amp(laser_name, power_nw)))
                else:
                    pulses.append("active")

        else:
            pulses = ["active"] * len(laser_names)

        if duration_ns >= 1600 * u.ns:
            j_avg = 1000
            j = declare(int)
            with for_(j, 0, j < j_avg, j + 1):
                for laser_name, pulse in zip(laser_names, pulses):
                    play(pulse, laser_name, duration_ns / j_avg * u.ns)
        else:
            for laser_name, pulse in zip(laser_names, pulses):
                play(pulse, laser_name, duration_ns * u.ns)

    def set_laser_power(self, laser_name: str, power_nw: float) -> None:

        if "singleInput" in self._opx.config["elements"][laser_name].keys():
            element_input = "single"
        elif "multipleInputs" in self._opx.config["elements"][laser_name].keys():
            element_input = "multiple"
        else:
            raise ValueError(f"{laser_name} could not be found for setting power in OPX config")

        set_dc_offset(laser_name, element_input, self.laser_power_to_voltage(laser_name, power_nw))

    def gate_trigger(self) -> None:
        play(pulse="trigit", element="Gate_Trigger", duration=self.TT_TRIGGER_LENGTH * u.ns)

    def memory_trigger(self) -> None:
        play(pulse="trigit", element="Memory_Trigger", duration=self.TT_TRIGGER_LENGTH * u.ns)
