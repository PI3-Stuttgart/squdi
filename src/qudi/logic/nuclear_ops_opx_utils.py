"""QUA helper utilities for calibrated laser control on the OPX+.

This module provides a thin logic-layer wrapper around the OPX configuration
and the AOM power calibration logic. Its main purpose is to let higher-level
measurement scripts express laser powers in nW and pulse lengths in ns while
keeping the OPX-facing details in one place.

The helper methods here are intended to be called from inside a
``with qua.program():`` context. They are ordinary Python functions, but the
``play()`` and ``set_dc_offset()`` calls they contain still emit QUA
instructions into the surrounding program being constructed.
"""

from numbers import Real

from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.logic.aom_power_calibration_logic import AOMPowerCalibrationLogic
from qudi.logic.transition_tracker import TransitionTracker
from qudi.hardware.OPX.OPX_holder import OPX
from qm.qua import play, set_dc_offset, amp, declare, for_
from qualang_tools.units import unit

u = unit(coerce_to_integer=True)


class NuclearOpsOPXUtils(LogicBase):
    """Bridge logic for calibrated OPX laser helper calls.

    The module resolves logical laser names to the corresponding calibration
    channel and OPX element. It exposes small helper methods that queue logic
    and future OPX/QM helper wrappers can use to convert requested laser powers
    in nW into calibrated voltage or OPX amplitude values.

    ``TransitionTracker`` is connected intentionally even though it is not used
    yet. This keeps the integration point in place for future laser metadata or
    experiment-parameter lookup without changing the queue wiring again.

    Timing convention:
        Public helper methods in this class accept durations in physical
        nanoseconds. Conversion to the QUA/OPX internal duration unit happens
        exactly once in :meth:`duration_ns_to_qua`.
    """

    TT_TRIGGER_LENGTH_NS: int = 20  # ns
    LONG_PULSE_THRESHOLD_NS: int = 10_000  # ns
    LONG_PULSE_CHUNK_NS: int = 5_000  # ns

    power_calibration_logic: AOMPowerCalibrationLogic = Connector(interface="AOMPowerCalibrationLogic")
    transition_tracker_logic: TransitionTracker = Connector(interface="TransitionTracker")
    opx: OPX = Connector(interface="OPX")

    _power_calibration_logic: AOMPowerCalibrationLogic
    _transition_tracker: TransitionTracker
    _opx: OPX

    def on_activate(self) -> None:
        """Resolve external logic and hardware connectors on activation."""
        self._power_calibration_logic = self.power_calibration_logic()
        self._transition_tracker = self.transition_tracker_logic()
        self._opx = self.opx()

    def on_deactivate(self) -> None:
        """Clear cached connector references on deactivation."""
        self._power_calibration_logic = None
        self._transition_tracker = None
        self._opx = None

    @staticmethod
    def voltage_to_amp(voltage: float) -> float:
        """Convert an OPX analog voltage target to a QUA ``amp()`` factor.

        The OPX configuration uses the constant waveform ``cw_aom`` with a base
        sample of ``0.5``. Scaling that waveform by ``2 * voltage`` therefore
        reproduces the desired analog output voltage.
        """
        return 2 * voltage

    @staticmethod
    def power_nw_to_watts(power_nw: float) -> float:
        """Convert an optical power value from nW to W."""
        return float(power_nw) * 1e-9

    def laser_power_to_voltage(self, laser_name: str, power_nw: float) -> float:
        """Convert a requested optical power in nW to a calibrated drive voltage.

        Args:
            laser_name: Name of the calibrated OPX/AOM/Laser channel.
            power_nw: Desired optical power in nanowatts.

        Returns:
            The calibrated analog voltage in volts required to produce the
            requested optical power.
        """
        return self._power_calibration_logic.power_to_voltage(
            self.power_nw_to_watts(power_nw),
            laser_name,
        )

    def laser_power_to_amp(self, laser_name: str, power_nw: float) -> float:
        """Convert a requested optical power in nW to a QUA ``amp()`` factor."""
        return self.voltage_to_amp(self.laser_power_to_voltage(laser_name, power_nw))

    @staticmethod
    def duration_ns_to_qua(duration_ns: float) -> int:
        """Convert a physical duration in ns to the QUA duration argument.

        ``qualang_tools.units.unit`` performs the ns-to-OPX clock-cycle
        conversion for literal numeric durations. This helper centralizes the
        conversion so that callers pass physical nanoseconds and the conversion
        is applied only once.
        """
        return duration_ns * u.ns

    def play_chunked(self, pulse: object, laser_name: str, duration_ns: float) -> None:
        """Play a single-laser pulse, splitting long durations into chunks.

        Long single ``play()`` durations can increase QUA compile cost. For
        plain Python durations above :attr:`LONG_PULSE_THRESHOLD_NS`, this
        helper emits a QUA ``for_`` loop over fixed-size chunks plus a final
        remainder pulse. Non-literal durations are passed through directly.

        Args:
            pulse: QUA pulse expression, e.g. ``"active"`` or
                ``"pulse" * amp(...)``.
            laser_name: OPX element name to play on.
            duration_ns: Total requested pulse duration in nanoseconds.
        """
        if not isinstance(duration_ns, Real) or duration_ns <= self.LONG_PULSE_THRESHOLD_NS:
            play(pulse, laser_name, duration=self.duration_ns_to_qua(duration_ns))
            return

        full_chunks = int(duration_ns // self.LONG_PULSE_CHUNK_NS)
        remainder_ns = duration_ns - full_chunks * self.LONG_PULSE_CHUNK_NS

        if full_chunks:
            j = declare(int)
            # Emit a compact QUA loop instead of one very long play duration.
            with for_(j, 0, j < full_chunks, j + 1):
                play(pulse, laser_name, duration=self.duration_ns_to_qua(self.LONG_PULSE_CHUNK_NS))

        if remainder_ns:
            play(pulse, laser_name, duration=self.duration_ns_to_qua(remainder_ns))

    def laser_pulse(self, laser_name: str, duration_ns: float, power_nw: None | float = None) -> None:
        """Play a calibrated laser pulse on one OPX element.

        Args:
            laser_name: OPX element name to play on.
            duration_ns: Pulse duration in nanoseconds.
            power_nw: Optical power in nanowatts. When ``None``, the helper
                falls back to the element's ``"active"`` operation, i.e. a
                digital-only trigger without calibrated analog amplitude.
        """
        if power_nw is not None:
            pulse = "pulse" * amp(self.laser_power_to_amp(laser_name, power_nw))
        else:
            pulse = "active"
        self.play_chunked(pulse, laser_name, duration_ns)

    def multiple_laser_pulses(self, laser_names: list[str], duration_ns: float, powers_nw: None | list[float | None] = None) -> None:
        """Play synchronized pulses on multiple laser elements.

        All elements receive the same duration. When the duration is long
        enough to require chunking, the method chunks at the shared-duration
        level so each chunk iteration plays all requested laser pulses.

        Args:
            laser_names: OPX element names to play on.
            duration_ns: Shared pulse duration in nanoseconds.
            powers_nw: Optional per-laser optical powers in nanowatts. Use
                ``None`` for a laser that should use the ``"active"``
                operation instead of a calibrated analog pulse.

        Raises:
            ValueError: If a power list is supplied with a different length than
                ``laser_names``.
        """
        pulses = []

        if powers_nw is not None:
            if len(powers_nw) != len(laser_names):
                raise ValueError("I powers_ns defined it needs to be defined for all lasers, if no power should be given, use None")

            for laser_name, power_nw in zip(laser_names, powers_nw):
                if power_nw is not None:
                    pulses.append("pulse" * amp(self.laser_power_to_amp(laser_name, power_nw)))
                else:
                    pulses.append("active")
        else:
            pulses = ["active"] * len(laser_names)

        if not isinstance(duration_ns, Real) or duration_ns <= self.LONG_PULSE_THRESHOLD_NS:
            for laser_name, pulse in zip(laser_names, pulses):
                play(pulse, laser_name, duration=self.duration_ns_to_qua(duration_ns))
            return

        full_chunks = int(duration_ns // self.LONG_PULSE_CHUNK_NS)
        remainder_ns = duration_ns - full_chunks * self.LONG_PULSE_CHUNK_NS

        if full_chunks:
            j = declare(int)
            # Chunk at the grouped-play level so all lasers stay synchronized.
            with for_(j, 0, j < full_chunks, j + 1):
                for laser_name, pulse in zip(laser_names, pulses):
                    play(pulse, laser_name, duration=self.duration_ns_to_qua(self.LONG_PULSE_CHUNK_NS))

        if remainder_ns:
            for laser_name, pulse in zip(laser_names, pulses):
                play(pulse, laser_name, duration=self.duration_ns_to_qua(remainder_ns))

    def set_laser_power(self, laser_name: str, power_nw: float) -> None:
        """Set a static calibrated analog output level for one laser element.

        Args:
            laser_name: OPX element name whose analog input should be offset.
            power_nw: Desired optical power in nanowatts.

        Raises:
            ValueError: If the OPX element does not expose a supported analog
                input layout.
        """
        element_config = self._opx.config["elements"][laser_name]
        if "singleInput" in element_config:
            element_input = "single"
        elif "multipleInputs" in element_config:
            input_names = tuple(element_config["multipleInputs"]["inputs"].keys())
            if len(input_names) != 1:
                raise ValueError(f"{laser_name} has multiple analog inputs {input_names}; set_laser_power only supports single-input elements")
            element_input = input_names[0]
        else:
            raise ValueError(f"{laser_name} could not be found for setting power in OPX config")

        set_dc_offset(laser_name, element_input, self.laser_power_to_voltage(laser_name, power_nw))

    def gate_trigger(self) -> None:
        """Play the standard gate trigger TTL pulse."""
        play(pulse="trigit", element="Gate_Trigger", duration=self.duration_ns_to_qua(self.TT_TRIGGER_LENGTH_NS))

    def memory_trigger(self) -> None:
        """Play the standard memory trigger TTL pulse."""
        play(pulse="trigit", element="Memory_Trigger", duration=self.duration_ns_to_qua(self.TT_TRIGGER_LENGTH_NS))
