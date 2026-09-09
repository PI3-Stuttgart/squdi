"""Ple Iterator: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.align()  # Shared PLE voltage update and optical readout gates.


# ---- Sweeping parameters ----
NAME = "Ple Iterator"
PROTOCOL = "ple_iterator"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "laser_frequency_voltage": np.linspace(-0.1, 0.1, 41)}
UNITS = {"laser_frequency_voltage": "V"}
AXIS_EXECUTION = {"repeat": "recompile", "laser_frequency_voltage": "qua"}
SAVE_RAW = True
