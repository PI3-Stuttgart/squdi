import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# from attr import dataclass
from qm.qua import align, assign, if_, measure, save, time_tagging, update_frequency, while_

import qudi.hardware.Keysight_AWG_M8190.pym8190a as MCAS
import qudi.UserScripts.helpers.sequence_creation_helpers as sch
from qudi.hardware.OPX.configuration import *
from qudi.hardware.OPX.program_container import MultiChSeq
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils

importlib.reload(MCAS)
importlib.reload(sch)


class QubitState(str, Enum):
    """Named electron-state labels used by the OPX helper routines."""

    e1 = "e1"
    e2 = "e2"


class Gate(str, Enum):
    """Named pulse labels."""

    pi = "pi"
    pi_half = "pi_half"


class UpdateableDataclass:
    """Small mixin that updates dataclass fields only for non-``None`` inputs."""

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None:
                setattr(self, k, v)
        return self


__pause_lp__: int = 1_000  # 10us #pause after laser power update
__tt_trigg_len__: int = 20  # ns

GENERAL_POWER_A1 = 5.05  # nW # det
GENERAL_POWER_B2 = 5.05  # nW


@dataclass
class ELECTRON_PARAMS(UpdateableDataclass):
    """Default parameters for charge-state readout (CSR) helper calls."""

    electron_rabi_period: int = 4_060  # ns
    IQ_freq: int = int(201.5 * 1e6)


@dataclass
class CRC_PARAMS(UpdateableDataclass):
    """Default parameters for charge-readout check (CRC) helper calls."""

    laser_power_A1: float | str = GENERAL_POWER_A1  # 7  # nW
    laser_power_B2: float | str = GENERAL_POWER_B2  # 7  # nW
    laser_power_repump: float | str = int(5e3)  # nW
    probe_len: int | str = 1e6  # ns # TODO: max 1ms otherwise parallel issues with counting
    repump_len: int | str = 100_000  # ns
    threshold: int | str = 6  # cts
    threshold_repump: int | str = 1  # cts
    wait_before_repump: int | str = int(50e3)  # ns
    wait_after_repump: int | str = int(50e3)  # ns
    max_attempts: int = 1000  # not used right now
    SPCM_channel: str = "SPCM1"


@dataclass
class CSR_PARAMS(UpdateableDataclass):
    """Default parameters for charge-state readout (CSR) helper calls."""

    duration: int | str = CRC_PARAMS.probe_len  # ns
    laser_power_A1: float | str = CRC_PARAMS.laser_power_A1  # nW
    laser_power_B2: float | str = CRC_PARAMS.laser_power_B2  # nW


@dataclass
class SSR_PARAMS(UpdateableDataclass):
    """Default parameters for single-shot readout (SSR) helper calls."""

    state: QubitState | str = QubitState.e1
    duration: int | str = 100_000  # 50_000  # ns
    laser_power_A1: float | str = GENERAL_POWER_A1  # 7  # nW # 620_det
    laser_power_B2: float | str = GENERAL_POWER_B2  # 7  # nW # 620


@dataclass
class ELECTRON_INIT_PARAMS(UpdateableDataclass):
    """Default parameters for resonant electron-state initialization."""

    state: QubitState = QubitState.e1
    duration: int = int(500e3)  # ns (300 us)
    laser_power_A1: float = 10  # 7  # nW # det
    laser_power_B2: float = 7  # 7  # nW


@dataclass
class PLE_REFOCUS_PARAMS(UpdateableDataclass):
    use_gui_powers: bool = True
    do_green_repump: bool = True
    laser_power_A1: float = GENERAL_POWER_A1  # 7 # nW
    laser_power_B2: float = GENERAL_POWER_B2  # 7 # nW
    laser_power_repump: float = 10e3


@dataclass
class OPTICAL_PI_PULSE_PARAMS(UpdateableDataclass):
    """Default parameters for optical pi pulse."""

    couting_duration: int = 30  # ns
    laser_power: float = 50  # nW


def crc(
    mcas: MultiChSeq,
    laser_power_A1: Optional[float | str] = None,
    laser_power_B2: Optional[float | str] = None,  # nW
    laser_power_repump: Optional[float | str] = None,  # nW
    probe_len: Optional[int | str] = None,  # ns
    repump_len: Optional[int | str] = None,  # ns
    crc_threshold: Optional[int | str] = None,  # cts
    crc_threshold_repump: Optional[int | str] = None,  # cts
    wait_before_repump: Optional[int | str] = None,  # ns
    wait_after_repump: Optional[int | str] = None,  # ns
    max_attempts: Optional[int] = None,
    counts_st: Optional[Any] = None,
    SPCM_channel: Optional[str] = None,
    set_laser_power: bool = True,
) -> None:
    """Run a count-rate check loop with optional 520 nm repumping.

    The routine measures counts on ``SPCM_channel`` and keeps probing with the
    620 nm laser until the measured counts exceed ``crc_threshold``. If the
    count rate falls below ``crc_threshold_repump``, a 520 nm repump pulse is
    inserted before the next attempt.

    Args:
        mcas: Sequence container that provides access to
            :class:`NuclearOpsOPXUtils`.
        laser_power_A1: Probe laser power for ``Laser_620`` in nW, or a QUA key
            resolved by the OPX helper utilities.
        laser_power_B2: Probe laser power for ``Laser_620_det`` in nW,
            or a QUA key resolved by the OPX helper utilities.
        laser_power_repump: Repump laser power for ``Laser_520`` in nW, or a QUA key
            resolved by the OPX helper utilities.
        probe_len: Probe pulse length in ns, or a QUA key resolved by the OPX
            helper utilities.
        repump_len: Repump pulse length in ns, or a QUA key resolved by the
            OPX helper utilities.
        crc_threshold: Minimum counts required to leave the CRC loop.
        crc_threshold_repump: Count threshold below which a repump pulse is
            applied.
        wait_before_repump: Delay in ns between the probe readout and the
            repump decision.
        wait_after_repump: Delay in ns before the next CRC iteration.
        max_attempts: Reserved safeguard against infinite looping. Currently
            unused.
        counts_st: Optional QUA stream used to save counts for each CRC
            iteration.
        SPCM_channel: OPX element name used for the readout measurement.

    Returns:
        None. The function emits QUA instructions into the active program.
    """
    params = CRC_PARAMS()
    params.update(
        laser_power_A1=laser_power_A1,
        laser_power_B2=laser_power_B2,
        laser_power_repump=laser_power_repump,
        probe_len=probe_len,
        repump_len=repump_len,
        threshold=crc_threshold,
        threshold_repump=crc_threshold_repump,
        wait_before_repump=wait_before_repump,
        wait_after_repump=wait_after_repump,
        max_attempts=max_attempts,
        SPCM_channel=SPCM_channel,
    )

    ou: NuclearOpsOPXUtils = mcas.ou

    # set counts and attemopts to 0
    assign(ou.crc_counts, 0)
    assign(ou.crc_attempts, 0)

    ### Set laser powers ###
    if set_laser_power:
        ou.set_laser_power("Laser_620_det", params.laser_power_A1, __pause_lp__)
        ou.set_laser_power("Laser_620", params.laser_power_B2, __pause_lp__)
        ou.set_laser_power("Laser_520", params.laser_power_repump, __pause_lp__)

    ### Main Loop: Repeat until sufficient photon counts are detected ###
    with while_(ou.crc_counts < params.threshold):
        measure(
            "readout",
            params.SPCM_channel,
            None,
            time_tagging.analog(ou.times, params.probe_len, ou.crc_counts),
        )
        ou.multiple_laser_pulses(["Laser_620", "Laser_620_det"], params.probe_len)

        # Provide counts in Stream if provided
        if counts_st is not None:
            save(ou.crc_counts, counts_st)

        ou.pause(params.wait_before_repump)

        # Apply repump if the count rate is too low
        with if_(ou.crc_counts < params.threshold_repump):
            ou.laser_pulse("Laser_520", params.repump_len)

        # Potential safeguard against infinite looping (not implemented)
        assign(ou.crc_attempts, ou.crc_attempts + 1)
        with if_(ou.crc_attempts > params.max_attempts):
            assign(ou.crc_counts, params.threshold + 1)
        ou.pause(params.wait_after_repump)
    align()


def csr(
    mcas: MultiChSeq,
    duration: Optional[int | str] = None,
    laser_power_A1: Optional[float | str] = None,
    laser_power_B2: Optional[float | str] = None,  # nW
    set_laser_power: bool = True,
) -> None:
    """Run a charge-state readout pulse sequence on both transitions.

    The helper sets the A1 and B2 probe powers, issues the standard gate
    trigger, plays simultaneous red probe pulses on ``Laser_620`` and
    ``Laser_620_det``, and finally emits the memory trigger.

    Args:
        mcas: Sequence container that provides access to
            :class:`NuclearOpsOPXUtils`.
        duration: Shared probe duration in ns.
        laser_power_A1: Probe power for ``Laser_620`` in nW, or a QUA key.
        laser_power_B2: Probe power for ``Laser_620_det`` in nW, or a QUA key.

    Returns:
        None. The function emits QUA instructions into the active program.
    """
    params = CSR_PARAMS()
    params.update(duration=duration, laser_power_A1=laser_power_A1, laser_power_B2=laser_power_B2)

    ou: NuclearOpsOPXUtils = mcas.ou

    if set_laser_power:
        ou.set_laser_power(
            "Laser_620_det",
            params.laser_power_A1,
            __pause_lp__,
        )
        ou.set_laser_power(
            "Laser_620",
            params.laser_power_B2,
            __pause_lp__,
        )

    ou.gate_trigger()
    ou.multiple_laser_pulses(["Laser_620", "Laser_620_det"], params.duration)
    align()
    ou.memory_trigger()
    align()


def electron_init(
    mcas: MultiChSeq,
    state: Optional[QubitState | str] = None,
    duration: Optional[int | str] = None,
    laser_power_pump: Optional[float | str] = None,
    set_laser_power: bool = True,
) -> None:
    """Initialize the electron spin into ``e1`` or ``e2`` with a red pump pulse.

    The selected state determines which resonant red transition is driven:
    ``e1`` maps to ``Laser_620_det`` and ``e2`` maps to ``Laser_620``. The
    helper updates the static laser power first and then plays the pump pulse.

    Args:
        mcas: Sequence container that provides access to
            :class:`NuclearOpsOPXUtils`.
        state: Target electron state label.
        duration: Pump duration in ns.
        laser_power_pump: Optional pump power override in nW, or a QUA key for
            the selected transition.

    Returns:
        None. The function emits QUA instructions into the active program.
    """

    params = ELECTRON_INIT_PARAMS()
    params.update(state=state, duration=duration)
    ou: NuclearOpsOPXUtils = mcas.ou

    match params.state:
        case QubitState.e1:
            if set_laser_power:
                params.update(laser_power_B2=laser_power_pump)
                ou.set_laser_power(
                    laser_name="Laser_620",
                    power_nw=params.laser_power_B2,
                    pause_after=__pause_lp__,
                )
            # Drive transition B2
            ou.laser_pulse("Laser_620", params.duration)

        case QubitState.e2:
            if set_laser_power:
                params.update(laser_power_A1=laser_power_pump)
                ou.set_laser_power(
                    laser_name="Laser_620_det",
                    power_nw=params.laser_power_A1,
                    pause_after=__pause_lp__,
                )
            # Drive transition A1
            ou.laser_pulse("Laser_620_det", params.duration)

        case _:
            raise ValueError("Given state can not be initilized")
    align()


def ssr(
    mcas: MultiChSeq,
    state: Optional[QubitState | str] = None,
    duration: Optional[int | str] = None,
    laser_power_probe: Optional[float | str] = None,
    set_laser_power=True,
) -> None:
    """Run single-shot readout on the selected red transition.

    The helper sets the requested probe power, emits the standard gate trigger,
    probes the selected optical transition, and then emits the memory trigger.

    Args:
        mcas: Sequence container that provides access to
            :class:`NuclearOpsOPXUtils`.
        state: Readout transition selector. ``e1`` maps to ``Laser_620`` and
            ``e2`` maps to ``Laser_620_det``.
        duration: Probe duration in ns.
        laser_power_probe: Optional probe power override in nW, or a QUA key
            for the selected transition.

    Returns:
        None. The function emits QUA instructions into the active program.
    """

    params = SSR_PARAMS()
    params.update(state=state, duration=duration)
    ou: NuclearOpsOPXUtils = mcas.ou

    match params.state:
        case QubitState.e1:
            if set_laser_power:
                params.update(laser_power_A1=laser_power_probe)
                ou.set_laser_power(
                    laser_name="Laser_620_det",
                    power_nw=params.laser_power_A1,
                    pause_after=__pause_lp__,
                )
            ou.gate_trigger()
            ou.laser_pulse("Laser_620_det", params.duration)
            align()
            ou.memory_trigger()

        case QubitState.e2:
            if set_laser_power:
                params.update(laser_power_B2=laser_power_probe)
                ou.set_laser_power(
                    laser_name="Laser_620",
                    power_nw=params.laser_power_B2,
                    pause_after=__pause_lp__,
                )
            ou.gate_trigger()
            ou.laser_pulse("Laser_620", params.duration)
            align()
            ou.memory_trigger()

        case _:
            raise ValueError("Given state can not be readout")
    align()


def optical_pi_pulse(
    mcas: MultiChSeq,
    couting_duration: int = 16,  # ns
    laser_power: Optional[float | str] = 50,  # nW
    set_laser_power=True,
) -> None:
    """Runs optical (pi) pulse acting on e1"""
    params = OPTICAL_PI_PULSE_PARAMS()
    params.update(
        couting_duration=couting_duration,
        laser_power=laser_power,
    )
    ou: NuclearOpsOPXUtils = mcas.ou
    if set_laser_power:
        ou.set_laser_power(
            laser_name="Laser_620_pi", power_nw=params.laser_power, pause_after=__pause_lp__
        )
    align()
    ou.gate_trigger()
    # ou.laser_pulse("Laser_620_pi", duration_ns=16)
    ou.laser_pulse("Laser_620_pi", duration_ns=50)
    ou.pause(params.couting_duration, align_before=False)
    ou.memory_trigger()
    align()


### QUBIT manupulation


def electron_gate(mcas: MultiChSeq, gate: str | Gate, electron_rabi_period: Optional[int] = None):
    params = ELECTRON_PARAMS()
    params.update(electron_rabi_period=electron_rabi_period)
    ou: NuclearOpsOPXUtils = mcas.ou

    match gate:
        case Gate.pi:
            pulse_duration = params.electron_rabi_period / 2
        case Gate.pi_half:
            pulse_duration = params.electron_rabi_period / 4

    ou.MW_pulse("NV", pulse_duration)


def set_IQ_freq(mcas, IQ_freq: int | None = None):
    params = ELECTRON_PARAMS()
    params.update(IQ_freq=IQ_freq)
    update_frequency("NV", params.IQ_freq)


def scan_laser_to_target(
    curr_laser_scanner_volt: float,
    target_laser_scanner_volt: float,
    volt_power_520: float = 0.0,
    volt_scan_per_sec: float = 0.05,
    scan_steps_per_volt: int = 2000,
) -> None:
    """Placeholder for a stepwise scanner-voltage sweep helper.

    The original implementation has been commented out and this function
    currently emits no QUA instructions. The arguments are kept to preserve the
    intended public interface for future reactivation.

    Args:
        curr_laser_scanner_volt: Current scanner voltage in V.
        target_laser_scanner_volt: Target scanner voltage in V.
        volt_power_520: Optional 520 nm laser amplitude to apply during scan
            steps.
        volt_scan_per_sec: Requested scan speed in V/s.
        scan_steps_per_volt: Number of discrete scan steps per volt.

    Returns:
        None.
    """
    # # Calculate the voltage difference to be scanned
    # voltage_span = abs(curr_laser_scanner_volt - target_laser_scanner_volt)

    # # Convert scan speed and resolution into a duration per step
    # time_per_step = (1 / volt_scan_per_sec) / scan_steps_per_volt * u.s

    # # Determine the total number of scan steps; use at least 2 points for linspace
    # nr_steps = max(2, int(voltage_span * scan_steps_per_volt))

    # # Generate the voltage trajectory from current value to target value
    # array_volts_scan_laser_to_target = np.linspace(
    #     curr_laser_scanner_volt,
    #     target_laser_scanner_volt,
    #     nr_steps,
    # )

    # # QUA variable holding the instantaneous scanner voltage
    # vLS = declare(fixed)

    # # Iterate through the voltage trajectory and update the scanner output
    # with for_each_(vLS, array_volts_scan_laser_to_target):
    #     set_dc_offset("LaserScanner_red", "single", vLS)

    #     # Optionally apply 520 nm light during each scan step
    #     if volt_power_520 > 0:
    #         play("pulse" * amp(volt_power_520), "Laser_520", duration=time_per_step / 4)
    #     else:
    #         wait(time_per_step * u.ns)

    #     # Synchronize all involved elements before the next step
    #     align()
