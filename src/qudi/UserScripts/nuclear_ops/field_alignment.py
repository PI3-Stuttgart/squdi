"""Field Alignment: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.mw(p["electron_pi_duration_ns"])


# ---- Sweeping parameters ----
NAME = "Field Alignment"
PROTOCOL = "field_alignment"
PARAMETERS = {"integrations": 20, "B_amp": 0.0}
SWEEPS = {"repeat": range(4), "B_theta": np.linspace(0, 20, 21)}
UNITS = {"B_theta": "deg"}
AXIS_EXECUTION = {"repeat": "recompile", "B_theta": "host"}
SAVE_RAW = True
