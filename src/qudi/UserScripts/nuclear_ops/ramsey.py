"""Ramsey: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.mw(p["electron_pi_duration_ns"] / 2)
    q.wait(p["tau"])
    q.phase(p.get("last_phase", 0.0))
    q.mw(p["electron_pi_duration_ns"] / 2)
    q.reset_phase()


# ---- Sweeping parameters ----
NAME = "Ramsey"
PROTOCOL = "ramsey"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "tau": np.arange(40, 4040, 100)}
UNITS = {"tau": "ns"}
AXIS_EXECUTION = {"repeat": "recompile", "tau": "qua"}
SAVE_RAW = True
