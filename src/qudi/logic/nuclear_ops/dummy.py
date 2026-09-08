"""Deterministic offline QM jobs. No SDK import or network connection is made."""
import itertools
import threading
import time
from dataclasses import dataclass

import numpy as np

from .recipes import ProgramBundle


@dataclass(frozen=True)
class DummyProgram:
    context: object


def build_dummy_program(context):
    return ProgramBundle(DummyProgram(context), {
        "recipe": context.experiment.recipe, "dummy": True,
        "description": "Synthetic software test; not QUA simulation or measured data",
    })


class DummyHandle:
    def __init__(self, values):
        self.values = np.asarray(values)

    def fetch_all(self):
        return self.values.copy()


class DummyJob:
    def __init__(self, program, seed=0, delay_s=0.1):
        if not isinstance(program, DummyProgram):
            raise TypeError("Dummy hardware requires a DummyProgram")
        self._halted = threading.Event()
        self._ready_at = time.monotonic() + max(0, delay_s)
        self.result_handles = self
        ctx = program.context
        n = ctx.block.qua_points
        rng = np.random.default_rng(int(seed) + ctx.block.index * 1009 + ctx.attempt)
        points = list(itertools.product(*(axis.values for axis in ctx.block.qua_axes))) or [()]
        axis_names = [axis.name for axis in ctx.block.qua_axes]
        preferred = ctx.parameters.get("fit_axis")
        candidates = [preferred] if preferred else ["pulse_length", "MW_pulse_len", "tau", "readout_delay", "MW_f"]
        chosen = next((name for name in candidates if name in axis_names), None)
        x = np.asarray([point[axis_names.index(chosen)] for point in points], float) if chosen else np.arange(n, dtype=float)
        span = np.ptp(x) or 1.0
        u = (x - x.min()) / span
        recipe = ctx.experiment.recipe
        if recipe in ("t1", "hahn_echo", "initialization_calibration"):
            signal = 5 + 25 * np.exp(-3 * u)
        elif recipe in ("pulsed_odmr", "ple_iterator", "field_alignment"):
            signal = 30 - 20 / (1 + ((u - .5) / .12) ** 2)
        elif recipe == "ssr_calibration":
            signal = np.full(n, 24 if ctx.parameters.get("init_state", "e1") == "e1" else 4)
        else:
            signal = 20 + 12 * np.cos(2 * np.pi * 3 * u) * np.exp(-u / 2)
        integrations = int(ctx.parameters.get("integrations", 1))
        self._values = {
            "optical_counts": rng.poisson(np.maximum(signal, .1)),
            "crc_counts": np.full(n, 25.), "initial_counts": np.full(n, 2.),
            "result_counts": rng.poisson(np.maximum(signal, .1) * integrations) / integrations,
            "csr_counts": np.full(n, 10.), "crc_success_fraction": np.ones(n),
        }
        for name in ("crc_counts", "initial_counts", "result_counts", "csr_counts", "optical_counts"):
            self._values[name + "_shots"] = rng.poisson(np.maximum(self._values[name], .01), (integrations, n))
            self._values[name] = self._values[name + "_shots"].mean(axis=0)
        width = int(ctx.parameters.get("max_time_tags", 128))
        for name in ("initial", "result", "csr", "optical"):
            counts = np.minimum(self._values[name + "_counts_shots"].astype(int), width)
            tags = rng.integers(0, 1000, (integrations, n, width))
            tags.sort(axis=-1)
            self._values[name + "_tags"] = tags
            self._values[name + "_tag_counts"] = counts

    def get(self, name):
        return DummyHandle(self._values[name])

    def wait_for_all_values(self, timeout=None):
        deadline = float("inf") if timeout is None else time.monotonic() + timeout
        while time.monotonic() < self._ready_at:
            remaining = min(self._ready_at, deadline) - time.monotonic()
            if remaining <= 0:
                return False
            if self._halted.wait(remaining):
                raise RuntimeError("Dummy job halted")
        if self._halted.is_set():
            raise RuntimeError("Dummy job halted")
        return True

    def halt(self):
        self._halted.set()
