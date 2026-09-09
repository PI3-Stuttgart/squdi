"""Optical Power Rabi: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.laser("Laser_620_pi", p["optical_duration_ns"])


# ---- Sweeping parameters ----
NAME = "Optical Power Rabi"
PROTOCOL = "optical_power_rabi"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "optical_voltage": np.linspace(0, 0.2, 41)}
UNITS = {"optical_voltage": "V"}
AXIS_EXECUTION = {"repeat": "recompile", "optical_voltage": "qua"}
SAVE_RAW = True
