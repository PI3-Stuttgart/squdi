"""Portable NuclearOps storage: JSON results and memory-mappable NumPy traces.

No Qudi/Qt imports are needed to read this format. Trace references are relative
to the measurement folder, so the complete folder can be moved together.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd


ANALYSIS_FIELDS = (
    "analyze_sequence", "analyze_type", "number_of_simultaneous_measurements",
    "binning_factor", "average_results", "consecutive_valid_result_numbers",
)


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _atomic_text(path, contents):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(contents, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_trace(directory, trace, analysis):
    """Write before publishing the reference; never retain the input array."""
    directory = Path(directory)
    relative = Path("traces") / (uuid4().hex + ".npy")
    target = directory / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        with temporary.open("wb") as stream:
            np.save(stream, trace, allow_pickle=False)
        _atomic_text(target.with_suffix(".json"), json.dumps(
            analysis, default=_json_default, indent=2))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return relative.as_posix()


def save_results(directory, frame, parameter_names, observation_names):
    """Atomically checkpoint the small results table, without stringifying cells."""
    directory = Path(directory)
    _atomic_text(directory / "measurement.json", json.dumps({
        "format": "nuclearops-efficient-traces", "version": 1,
        "parameter_names": list(parameter_names),
        "observation_names": list(observation_names),
        "trace_column": "trace",
    }, indent=2))
    _atomic_text(directory / "results.json", frame.to_json(
        orient="table", date_format="iso", double_precision=15))


def load_results(directory):
    directory = Path(directory)
    metadata = json.loads((directory / "measurement.json").read_text())
    if metadata.get("version") != 1:
        raise ValueError("Unsupported measurement format version")
    return pd.read_json(directory / "results.json", orient="table"), metadata


def load_trace(directory, reference, mmap_mode="r"):
    """Load just one trace, optionally mapped from disk, and its analysis settings."""
    directory = Path(directory).resolve()
    target = (directory / reference).resolve()
    if directory not in target.parents:
        raise ValueError("Trace reference must stay inside the measurement folder")
    settings = json.loads(target.with_suffix(".json").read_text())
    return np.load(target, mmap_mode=mmap_mode, allow_pickle=False), settings
