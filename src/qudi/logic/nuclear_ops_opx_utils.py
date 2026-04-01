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
from qudi.logic.ple.ple_scanner_logic import PLEScannerLogic
from qudi.logic.transition_tracker import TransitionTracker
from qudi.hardware.OPX.OPX_holder import OPX
from qm import qua
from qm.qua import play, set_dc_offset, amp, declare, for_, fixed, wait, align
from qualang_tools.units import unit
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

u = unit(coerce_to_integer=True)


@dataclass
class FastSweepQUA:
    element: None | str
    key: str
    quantity_kind: None | str
    raw_array: np.ndarray
    qua_array: np.ndarray


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
    LONG_PULSE_THRESHOLD_NS: int = 1_000_000  # ns (1ms)
    LONG_PULSE_CHUNK_NS: int = 5_000  # ns

    power_calibration_logic: AOMPowerCalibrationLogic = Connector(interface="AOMPowerCalibrationLogic")
    ple_scanner_logic: PLEScannerLogic = Connector(interface="PLEScannerLogic")
    transition_tracker_logic: TransitionTracker = Connector(interface="TransitionTracker")
    opx: OPX = Connector(interface="OPX")

    _power_calibration_logic: AOMPowerCalibrationLogic
    _ple_scanner_logic: PLEScannerLogic
    _transition_tracker: TransitionTracker
    _opx: OPX

    laser_elements: list[str] = ["Laser_520", "Laser_620", "Laser_620_pi", "Laser_620_freq"]
    quantity_types: list[str] = ["power", "freq"]
    SLOW_CHANGING_PARAMETERS: list[str] = ["B_amp", "B_theta", "B_phi"]
    fast_sweeps_qua: OrderedDict[str, FastSweepQUA] = OrderedDict()
    current_iterator_df: pd.DataFrame

    i_1: qua.Variable[fixed] | None = None
    i_2: qua.Variable[fixed] | None = None
    j: qua.Variable[int] | None = None

    def on_activate(self) -> None:
        """Resolve external logic and hardware connectors on activation."""
        self._power_calibration_logic = self.power_calibration_logic()
        self._ple_scanner_logic = self.ple_scanner_logic()
        self._transition_tracker = self.transition_tracker_logic()
        self._opx = self.opx()

    def on_deactivate(self) -> None:
        """Clear cached connector references on deactivation."""
        self._power_calibration_logic = None
        self._ple_scanner_logic = None
        self._transition_tracker = None
        self._opx = None

    def create_fast_sweep_qua_arrays(self, current_iterator_df: pd.DataFrame):
        self.current_iterator_df = current_iterator_df

        self.fast_sweeps_qua = OrderedDict()
        self.sweep_keys_OPX = []

        for key in current_iterator_df.keys():
            if len(current_iterator_df[key].unique()) > 1 and key not in self.SLOW_CHANGING_PARAMETERS:
                element = self._find_element_from_current_iterator(key)
                quantity_kind = self._find_quantity_kind_from_current_iterator(key)
                raw_array = np.asarray(current_iterator_df[key].unique())
                self.sweep_keys_OPX.append(key)
                self.fast_sweeps_qua[key] = FastSweepQUA(
                    element=element,
                    key=key,
                    quantity_kind=quantity_kind,
                    raw_array=raw_array,
                    qua_array=self._get_qua_array(element, quantity_kind, raw_array),
                )

        if len(self.fast_sweeps_qua) > 2:
            raise (ValueError("Current_iterator_df has more then two axis to iterate over by the quantum machine, which is not supportet at the moment"))

    def get_fast_sweep_qua_array(self, idx: int) -> np.ndarray:
        if idx not in (0, 1):
            raise IndexError(f"Fast sweep index must be 0 or 1, got {idx}")

        values = tuple(self.fast_sweeps_qua.values())
        if idx < len(values):
            return values[idx].qua_array
        if idx == 1:
            return np.array([0.0])
        raise IndexError("Fast sweep index 0 requested, but no fast sweep arrays are available")

    @staticmethod
    def _find_longest_substring_match(key: str, candidates: list[str]) -> None | str:
        matching_candidates = [candidate for candidate in candidates if candidate in key]
        if not matching_candidates:
            return None
        return max(matching_candidates, key=len)

    def _find_element_from_current_iterator(self, key: str):
        return self._find_longest_substring_match(key, self.laser_elements)

    def _get_value_from_key(self, key: str | float) -> tuple[None | Real, None | qua.Variable]:
        # if value is float or similar, it is not a key but an actuall value
        if not isinstance(key, str):
            return key, None

        if len(self.sweep_keys_OPX) > 0 and key == self.sweep_keys_OPX[0]:
            return None, self.i_1

        if len(self.sweep_keys_OPX) > 1 and key == self.sweep_keys_OPX[1]:
            return None, self.i_2

        longest_matching_sweep_key = self._find_longest_substring_match(key, self.sweep_keys_OPX)
        if longest_matching_sweep_key is not None and longest_matching_sweep_key in self.current_iterator_df:
            if len(self.sweep_keys_OPX) > 0 and longest_matching_sweep_key == self.sweep_keys_OPX[0]:
                return None, self.i_1
            if len(self.sweep_keys_OPX) > 1 and longest_matching_sweep_key == self.sweep_keys_OPX[1]:
                return None, self.i_2
            return self.current_iterator_df[longest_matching_sweep_key].unique()[0], None

        return self.current_iterator_df[key].unique()[0], None

    def _find_quantity_kind_from_current_iterator(self, key: str):
        return self._find_longest_substring_match(key, self.quantity_types)

    def _get_qua_array(self, element: None | str, quantity_kind: None | str, raw_array: np.ndarray):
        match quantity_kind:
            case "power":
                return np.asarray([self.laser_power_to_voltage(element, i) for i in raw_array])
            case "freq":
                return np.asarray([self.laser_frequency_to_voltage(i) for i in raw_array])
            case _:
                return raw_array

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

    def laser_frequency_to_voltage(self, frequency_mhz: float) -> float:
        """Convert a target laser frequency in MHz to the scanner voltage in V."""
        return self._ple_scanner_logic.frequency_to_voltage(float(frequency_mhz) * 1e6)

    def set_laser_voltage(self, laser_name: str, voltage_v: float | qua.Variable[fixed]) -> None:
        """Set a static analog offset for one laser element in volts.

        This is the direct wrapper around QUA ``set_dc_offset()`` and can take
        either a Python scalar voltage or a QUA expression that already
        evaluates to a voltage inside the program.
        It automaticaly finds all "inputs" of the element.

         Args:
            laser_name: OPX element name to set_dc_offset.
            voltage_v: Voltag to be used in set_dc_offset.
        """
        element_config = self._opx.config["elements"][laser_name]
        if "singleInput" in element_config:
            set_dc_offset(laser_name, "single", voltage_v)
        elif "multipleInputs" in element_config:
            input_names = tuple(element_config["multipleInputs"]["inputs"].keys())
            for input_name in input_names:
                set_dc_offset(laser_name, input_name, voltage_v)
        else:
            raise ValueError(f"{laser_name} could not be found for setting a DC offset in OPX config")

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
        if duration_ns <= self.LONG_PULSE_THRESHOLD_NS:
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

    def laser_pulse(self, laser_name: str, duration_ns: float | str, power_nw: None | float | str = None) -> None:
        """Play a calibrated laser pulse on one OPX element.

        Args:
            laser_name: OPX element name to play on.
            duration_ns: Pulse duration in nanoseconds.
            power_nw: Optical power in nanowatts. When ``None``, the helper
                falls back to the element's ``"active"`` operation, i.e. a
                digital-only trigger without calibrated analog amplitude.
        """

        duration_ns, duration_ns_qua = self._get_value_from_key(duration_ns)
        power_nw, power_v_qua = self._get_value_from_key(power_nw)

        if power_nw is not None:
            pulse = "pulse" * amp(self.laser_power_to_amp(laser_name, power_nw))
        elif power_v_qua is not None:
            pulse = "pulse" * amp(power_v_qua * 2)
        else:
            pulse = "active"

        self.play_chunked(pulse, laser_name, duration_ns if duration_ns is not None else duration_ns_qua)

    def multiple_laser_pulses(self, laser_names: list[str], duration_ns: float | str, powers_nw: None | list[float | str | None] = None) -> None:
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
        duration_ns, duration_ns_qua = self._get_value_from_key(duration_ns)

        if powers_nw is not None:

            if len(powers_nw) != len(laser_names):
                raise ValueError("I powers_ns defined it needs to be defined for all lasers, if no power should be given, use None")

            for laser_name, power_nw in zip(laser_names, powers_nw):
                power_nw, power_v_qua = self._get_value_from_key(power_nw)

                if power_nw is not None:
                    pulse = "pulse" * amp(self.laser_power_to_amp(laser_name, power_nw))
                elif power_v_qua is not None:
                    pulse = "pulse" * amp(power_v_qua * 2)
                else:
                    pulse = "active"
                pulses.append(pulse)
        else:
            pulses = ["active"] * len(laser_names)

        duration_ns_general = duration_ns if duration_ns is not None else duration_ns_qua

        if duration_ns_general <= self.LONG_PULSE_THRESHOLD_NS:
            for laser_name, pulse in zip(laser_names, pulses):
                play(pulse, laser_name, duration=self.duration_ns_to_qua(duration_ns_general))
            return

        full_chunks = int(duration_ns_general // self.LONG_PULSE_CHUNK_NS)
        remainder_ns = duration_ns_general - full_chunks * self.LONG_PULSE_CHUNK_NS

        if full_chunks:
            # Chunk at the grouped-play level so all lasers stay synchronized.
            with for_(self.j, 0, self.j < full_chunks, self.j + 1):
                for laser_name, pulse in zip(laser_names, pulses):
                    play(pulse, laser_name, duration=self.duration_ns_to_qua(self.LONG_PULSE_CHUNK_NS))

        if remainder_ns:
            for laser_name, pulse in zip(laser_names, pulses):
                play(pulse, laser_name, duration=self.duration_ns_to_qua(remainder_ns))

    def set_laser_power(self, laser_name: str, power_nw: float | str) -> None:
        """Set a static calibrated analog output level for one laser element.

        Args:
            laser_name: OPX element name whose analog input should be offset.
            power_nw: Desired optical power in nanowatts.

        Raises:
            ValueError: If the OPX element does not expose a supported analog
                input layout.
        """

        power_nw, power_v_qua = self._get_value_from_key(power_nw)

        self.set_laser_voltage(
            laser_name,
            self.laser_power_to_voltage(laser_name, power_nw) if power_nw is not None else power_v_qua,
        )

    def set_laser_frequency(self, laser_name: str, frequency_mhz: object) -> None:
        """Set a static laser-scanner offset using a target frequency in MHz.

        The frequency-to-voltage conversion is resolved via
        :class:`PLEScannerLogic`, so this helper is intended for fixed Python
        frequency values. When a QUA expression is passed instead, it is
        assumed to already represent the target voltage. That matches the
        fast-sweep path in ``NuclearOPs``, where ``Laser_freqs_MHz`` arrays are
        preconverted to voltages before entering the QUA loop.
        """

        frequency_mhz, frequency_v_qua = self._get_value_from_key(frequency_mhz)

        self.set_laser_voltage(
            laser_name,
            self.laser_frequency_to_voltage(frequency_mhz) if frequency_mhz is not None else frequency_v_qua,
        )

    def gate_trigger(self) -> None:
        """Play the standard gate trigger TTL pulse."""
        play(pulse="trigit", element="Gate_Trigger", duration=self.duration_ns_to_qua(self.TT_TRIGGER_LENGTH_NS))

    def memory_trigger(self) -> None:
        """Play the standard memory trigger TTL pulse."""
        play(pulse="trigit", element="Memory_Trigger", duration=self.duration_ns_to_qua(self.TT_TRIGGER_LENGTH_NS))

    def pause(self, duration_ns: int | qua.Variable[int]) -> None:
        """Insert a delay by playing no pulses for the specified duration."""

        _duration_ns, _duration_ns_qua = self._get_value_from_key(duration_ns)
        wait(self.duration_ns_to_qua(_duration_ns if _duration_ns is not None else _duration_ns_qua))

    def init_program(self) -> None:
        self.i_1 = declare(fixed)
        self.i_2 = declare(fixed)
        self.j = declare(int)
