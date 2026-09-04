"""Serialization helpers shared by experiment, queue, and HDF5 models."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import numpy as np


def to_primitive(value: Any) -> Any:
    """Convert a model value into nested HDF5/YAML-safe primitives.

    This conversion deliberately does not use pickle.  Model snapshots must be
    readable without importing the class that originally produced them.
    """

    if is_dataclass(value):
        return to_primitive(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [to_primitive(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_primitive(item) for item in value]
    if isinstance(value, list):
        return [to_primitive(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("Unsupported value for persistent serialization: {!r}".format(value))


def parse_datetime(value: Any, field_name: str) -> datetime:
    """Parse a datetime model field and produce a useful validation error."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("{} must be an ISO-8601 datetime".format(field_name)) from exc
    raise TypeError("{} must be a datetime or ISO-8601 string".format(field_name))
