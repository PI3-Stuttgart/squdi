"""Ssr Calibration: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.align()  # Common initialization and SSR gates only.


# ---- Sweeping parameters ----
NAME = "Ssr Calibration"
PROTOCOL = "ssr_calibration"
PARAMETERS = {"integrations": 20}
SWEEPS = {"init_state": ("e1", "e2"), "sweeps": range(40)}
UNITS = {"sweeps": ""}
AXIS_EXECUTION = {"init_state": "recompile", "sweeps": "qua"}
SAVE_RAW = True
