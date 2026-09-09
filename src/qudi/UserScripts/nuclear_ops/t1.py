"""T1: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.wait(p["readout_delay"])


# ---- Sweeping parameters ----
NAME = "T1"
PROTOCOL = "t1"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "readout_delay": np.arange(40, 80040, 2000)}
UNITS = {"readout_delay": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "readout_delay": "qua"}
SAVE_RAW = True
