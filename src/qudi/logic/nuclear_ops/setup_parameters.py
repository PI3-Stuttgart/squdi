"""Setup-wide pulse/counter parameters, with validated live revisions."""
import copy
import os
import threading
from pathlib import Path

import h5py
from .hdf5_store import read_hdf_tree, write_hdf_tree

# key: (group, label, default, unit, minimum, maximum)
PARAMETERS = {
    "mw_frequency": ("Microwave", "IQ frequency", 194000000, "Hz", -500000000, 500000000),
    "mw_amplitude": ("Microwave", "Pulse amplitude", 1.0, "relative", -1.99, 1.99),
    "electron_pi_duration_ns": ("Microwave", "Electron pi pulse", 1620, "ns", 16, 100000000),
    "electron_init_duration_ns": ("Readout", "Initialization duration", 3000000, "ns", 16, 100000000),
    "ssr_duration_ns": ("Readout", "SSR duration", 300000, "ns", 16, 100000000),
    "csr_duration_ns": ("Readout", "CSR duration", 1000000, "ns", 16, 100000000),
    "cooldown_time": ("Readout", "Cooldown", 100000, "ns", 16, 100000000),
    "crc_probe_duration_ns": ("CRC", "Probe duration", 1000000, "ns", 16, 100000000),
    "crc_repump_duration_ns": ("CRC", "Repump duration", 100000, "ns", 16, 100000000),
    "crc_wait_ns": ("CRC", "Wait after probe", 50000, "ns", 16, 100000000),
    "crc_max_attempts": ("CRC", "Maximum attempts", 1000, "", 1, 1000000),
    "laser_620_voltage": ("Lasers", "620 laser DC offset", 0.0, "V", -.5, .5),
    "laser_620_det_voltage": ("Lasers", "620 detuned DC offset", 0.0, "V", -.5, .5),
    "laser_520_voltage": ("Lasers", "520 repump DC offset", 0.0, "V", -.5, .5),
    "optical_voltage": ("Lasers", "Optical pulse DC offset", 0.0, "V", -.5, .5),
    "optical_duration_ns": ("Lasers", "Optical trigger duration", 48, "ns", 16, 100000000),
    "optical_window_ns": ("Lasers", "Optical count window", 1000, "ns", 16, 100000000),
    "gate_trigger_ns": ("Counter", "Marker pulse duration", 20, "ns", 16, 10000),
    "click_channel": ("Counter", "Detector channel", 1, "", -64, 64),
    "begin_channel": ("Counter", "Gate start channel", 2, "", -64, 64),
    "end_channel": ("Counter", "Gate end channel", 3, "", -64, 64),
    "counter_buffer_events": ("Counter", "Stream buffer events", 1000000, "", 100, 10000000),
}


def validate(values):
    if set(values) != set(PARAMETERS):
        raise ValueError("Setup fields do not match the parameter schema")
    for key, value in values.items():
        _, _, default, unit, minimum, maximum = PARAMETERS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
        if isinstance(default, int) and int(value) != value:
            raise ValueError(f"{key} must be an integer")
        if unit == "ns" and value % 4:
            raise ValueError(f"{key} must be a multiple of 4 ns")
    channels = [values[k] for k in ("click_channel", "begin_channel", "end_channel")]
    if 0 in channels or len(set(channels)) != 3:
        raise ValueError("Detector, begin and end must be distinct nonzero channels")


class SetupRegistry:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = threading.RLock()
        self.state = {"revision": 1, "values": {k: v[2] for k, v in PARAMETERS.items()}}
        if self.path.exists():
            with h5py.File(self.path, "r") as f:
                self.state = read_hdf_tree(f["setup"])
        validate(self.state["values"])

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, values):
        validate(values)
        with self.lock:
            if values == self.state["values"]:
                return self.snapshot()
            state = {"revision": self.state["revision"] + 1, "values": dict(values)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".pending.h5")
            with h5py.File(temporary, "w") as f:
                write_hdf_tree(f, "setup", state)
                f.flush()
            os.replace(temporary, self.path)
            self.state = state
            return self.snapshot()
