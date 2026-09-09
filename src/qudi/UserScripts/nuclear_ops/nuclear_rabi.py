"""Nuclear Rabi: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.mw(p["pulse_length"])


# ---- Sweeping parameters ----
NAME = "Nuclear Rabi"
PROTOCOL = "nuclear_rabi"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "pulse_length": np.arange(40, 4040, 100)}
UNITS = {"pulse_length": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "pulse_length": "qua"}
SAVE_RAW = True
