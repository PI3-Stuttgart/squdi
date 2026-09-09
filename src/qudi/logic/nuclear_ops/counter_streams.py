"""Overlay external gated counts while retaining QM CRC and raw streams."""
import numpy as np


class CounterJob:
    def __init__(self, job, streams):
        self._original = job.result_handles
        self._streams = dict(streams)
        self.raw_events = self._streams.pop("_raw_events", {})
        self.raw_lengths = self._streams.pop("_raw_lengths", {})
        self.result_handles = self

    def wait_for_all_values(self, timeout=None):
        return self._original.wait_for_all_values(timeout=timeout)

    def get(self, name):
        if name not in self._streams:
            return self._original.get(name)
        return _Handle(self._streams[name])


class _Handle:
    def __init__(self, values):
        self._values = np.asarray(values)

    def fetch_all(self):
        return self._values.copy()
