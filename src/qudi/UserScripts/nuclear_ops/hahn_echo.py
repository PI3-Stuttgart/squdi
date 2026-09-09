"""Hahn Echo: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.mw(p["electron_pi_duration_ns"] / 2)
    q.wait(p["tau"])
    q.mw(p["electron_pi_duration_ns"])
    q.wait(p["tau"])
    q.mw(p["electron_pi_duration_ns"] / 2)


# ---- Sweeping parameters ----
NAME = "Hahn Echo"
PROTOCOL = "hahn_echo"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "tau": np.arange(40, 8040, 200)}
UNITS = {"tau": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "tau": "qua"}
SAVE_RAW = True
