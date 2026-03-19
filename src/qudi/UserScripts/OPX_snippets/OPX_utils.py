import numpy as np
from qm.qua import *
from qudi.hardware.OPX.configuration import *
from qm.quantum_machines_manager import QuantumMachinesManager
from qualang_tools.loops import qua_linspace
import time
from typing import Any, Optional


from typing import Any, Optional


def crc(
    volt_power_620: float,
    volt_power_520: float,
    crc_pulse_len: Any = 500 * u.us,
    crc_threshold: int = 15,
    crc_threshold_repump: int = 5,
    crc_repump_len: Any = 1 * u.ms,
    max_attempts: int = 1000,
    counts: Optional[Any] = None,
    counts_st: Optional[Any] = None,
    SPCM_channel: str = "SPCM1",
) -> None:
    """
    Perform a CRC (count-rate check) routine with optional repumping.

    The routine repeatedly measures photon counts on an SPCM channel and
    applies a 620 nm pulse until the detected counts exceed a given threshold.
    If the counts are too low, a repump pulse at 520 nm is applied.

    Parameters
    ----------
    volt_power_620 : float
        Amplitude scaling for the 620 nm AOM pulse.

    volt_power_520 : float
        Amplitude scaling for the 520 nm repump laser pulse.

    crc_pulse_len : Any, optional
        Length of the photon-counting window during the CRC measurement.

    crc_threshold : int, optional
        Minimum photon counts required to declare the CRC successful.

    crc_threshold_repump : int, optional
        Photon-count threshold below which a repump pulse is triggered.

    crc_repump_len : Any, optional
        Duration of the repump pulse applied to the 520 nm laser.

    max_attempts : int, optional
        Maximum number of CRC attempts before aborting
        (currently not implemented).

    counts : Optional[Any], optional
        QUA variable used to store photon counts. If None, a new variable
        is declared.

    counts_st : Optional[Any], optional
        QUA stream used to save photon counts.

    SPCM_channel : str, optional
        Name of the hardware channel connected to the single-photon counting
        module.

    Returns
    -------
    None
        The routine executes inside a QUA program and updates the provided
        variables.
    """
    # QUA vector storing photon arrival time-tags
    times = declare(int, size=1000)

    # Placeholder iteration counter (currently unused)
    i = declare(int)

    # Declare counts variable if not provided
    if counts is None:
        counts = declare(int)

    assign(counts, 0)

    # Repeat until sufficient photon counts are detected
    with while_(counts < crc_threshold):
        measure(
            "readout",
            SPCM_channel,
            None,
            time_tagging.analog(times, crc_pulse_len, counts),
        )

        play("pulse" * amp(volt_power_620 * 1.25), "AOM_620", duration=crc_pulse_len / 4)

        align()

        if counts_st is not None:
            save(counts, counts_st)

        wait(500 * u.us)

        # Apply repump if the count rate is too low
        with if_(counts < crc_threshold_repump):
            play("pulse" * amp(volt_power_520), "Laser_520", duration=crc_repump_len / 4)

        # Potential safeguard against infinite looping (not implemented)
        # with if_(i > max_attempts):
        #     assign(counts, crc_threshold + 1)

        wait(5000 * u.us)


from typing import Any

import numpy as np


def scan_laser_to_target(
    curr_laser_scanner_volt: float,
    target_laser_scanner_volt: float,
    volt_power_520: float = 0.0,
    volt_scan_per_sec: float = 0.05,
    scan_steps_per_volt: int = 2000,
) -> None:
    """
    Scan the red laser scanner voltage from the current value to a target value.

    The scan is performed in small voltage steps using ``set_dc_offset``.
    Optionally, the 520 nm laser can be applied during the scan. If the
    520 nm laser power is set to zero, the sequence simply waits for the
    corresponding step duration.

    Parameters
    ----------
    curr_laser_scanner_volt : float
        Current voltage applied to the red laser scanner.

    target_laser_scanner_volt : float
        Target voltage to which the red laser scanner should be moved.

    volt_power_520 : float, optional
        Amplitude scaling for the 520 nm laser pulse applied during each
        scan step. If set to 0, no 520 nm pulse is played.

    volt_scan_per_sec : float, optional
        Scan speed in volts per second.

    scan_steps_per_volt : int, optional
        Number of discrete scan steps per volt. For example, a value of
        2000 corresponds to a voltage resolution of 0.5 mV per step.

    Returns
    -------
    None
        The routine executes inside a QUA program and updates the scanner
        voltage step by step.
    """
    # Calculate the voltage difference to be scanned
    voltage_span = abs(curr_laser_scanner_volt - target_laser_scanner_volt)

    # Convert scan speed and resolution into a duration per step
    time_per_step = (1 / volt_scan_per_sec) / scan_steps_per_volt * u.s

    # Determine the total number of scan steps; use at least 2 points for linspace
    nr_steps = max(2, int(voltage_span * scan_steps_per_volt))

    # Generate the voltage trajectory from current value to target value
    array_volts_scan_laser_to_target = np.linspace(
        curr_laser_scanner_volt,
        target_laser_scanner_volt,
        nr_steps,
    )

    # QUA variable holding the instantaneous scanner voltage
    vLS = declare(fixed)

    # Iterate through the voltage trajectory and update the scanner output
    with for_each_(vLS, array_volts_scan_laser_to_target):
        set_dc_offset("LaserScanner_red", "single", vLS)

        # Optionally apply 520 nm light during each scan step
        if volt_power_520 > 0:
            play("pulse" * amp(volt_power_520), "Laser_520", duration=time_per_step / 4)
        else:
            wait(time_per_step / 4)

        # Synchronize all involved elements before the next step
        align()
