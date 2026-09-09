"""Pulsed Odmr: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    q.qua.update_frequency("MW", p["MW_f"])
    q.mw(p["electron_pi_duration_ns"])


# ---- Sweeping parameters ----
NAME = "Pulsed Odmr"
PROTOCOL = "pulsed_odmr"
PARAMETERS = {"integrations": 20}
SWEEPS = {"repeat": range(4), "MW_f": np.arange(190000000, 210000001, 500000)}
UNITS = {"MW_f": "Hz"}
AXIS_EXECUTION = {"repeat": "recompile", "MW_f": "qua"}
SAVE_RAW = True
