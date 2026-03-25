from typing import Any

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.logic.aom_power_calibration_logic import AOMPowerCalibrationLogic
from qudi.logic.transition_tracker import TransitionTracker

from qm import qua
from qm.qua import play, set_dc_offset, declare, fixed, for_, align, amp, infinite_loop_

from qualang_tools.units import unit
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

    power_calibration_logic: AOMPowerCalibrationLogic = Connector(interface="AOMPowerCalibrationLogic")
    transition_tracker_logic: TransitionTracker = Connector(interface="TransitionTracker")

    _power_calibration_logic: AOMPowerCalibrationLogic
    _transition_tracker: TransitionTracker

    def on_activate(self) -> None:
        self._power_calibration_logic = self.power_calibration_logic()
        self._transition_tracker = self.transition_tracker_logic()

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

    def laser_pulse(self, laser_name: str, power_nw: float, duration_ns: float) -> None:
        play(
            "pulse" * amp(self.laser_power_to_amp(laser_name, power_nw)),
            laser_name,
            duration_ns,
        )
