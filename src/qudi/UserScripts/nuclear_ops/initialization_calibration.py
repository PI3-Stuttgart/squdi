"""Initialization Calibration: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.align()  # Sweep the shared initialization pulse duration.


# ---- Sweeping parameters ----
NAME = "Initialization Calibration"
PROTOCOL = "initialization_calibration"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "electron_init_duration_ns": np.arange(40, 8040, 200)}
UNITS = {"electron_init_duration_ns": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "electron_init_duration_ns": "qua"}
SAVE_RAW = True
