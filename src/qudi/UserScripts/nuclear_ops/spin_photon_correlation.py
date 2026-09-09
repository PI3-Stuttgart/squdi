"""Spin Photon Correlation: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.laser("Laser_620_pi", p["optical_duration_ns"])


# ---- Sweeping parameters ----
NAME = "Spin Photon Correlation"
PROTOCOL = "spin_photon_correlation"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "sweeps": range(40)}
UNITS = {"sweeps": ""}
AXIS_EXECUTION = {"repeat": "recompile", "sweeps": "qua"}
SAVE_RAW = True
