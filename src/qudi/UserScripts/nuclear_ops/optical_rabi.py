"""Optical Rabi: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.laser("Laser_620_pi", p["optical_duration_ns"])


# ---- Sweeping parameters ----
NAME = "Optical Rabi"
PROTOCOL = "optical_rabi"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "optical_duration_ns": np.arange(16, 816, 20)}
UNITS = {"optical_duration_ns": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "optical_duration_ns": "qua"}
SAVE_RAW = True
