"""Typed domain models for nuclear experiments and acquired data."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

import numpy as np

from .serialization import parse_datetime, to_primitive


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AxisExecution(str, Enum):
    """Where a scan axis is evaluated."""

    AUTO = "auto"
    QUA = "qua"
    HOST = "host"
    RECOMPILE = "recompile"


class ReadoutKind(str, Enum):
    CRC = "crc"
    CSR = "csr"
    SSR = "ssr"
    RESULT = "result"


class AcquisitionMode(str, Enum):
    """Source used to acquire the result of a QUA program."""

    QM_STREAMS = "qm_streams"
    EXTERNAL_COUNTER = "external_counter"


@dataclass(frozen=True)
class ScanAxis:
    name: str
    values: Tuple[Any, ...]
    unit: str = ""
    execution: AxisExecution = AxisExecution.AUTO

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("ScanAxis.name must be a non-empty string")
        object.__setattr__(self, "values", tuple(self.values))
        if not self.values:
            raise ValueError("Scan axis '{}' has no values".format(self.name))
        to_primitive(list(self.values))
        object.__setattr__(self, "execution", AxisExecution(self.execution))
        if not isinstance(self.unit, str):
            raise TypeError("ScanAxis.unit must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScanAxis":
        return cls(
            name=value["name"],
            values=tuple(value["values"]),
            unit=value.get("unit", ""),
            execution=AxisExecution(value.get("execution", AxisExecution.AUTO.value)),
        )


@dataclass(frozen=True)
class ReadoutStep:
    """A named readout operation using a threshold from a global profile."""

    kind: ReadoutKind
    threshold_ref: str
    output_name: str
    repetitions: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ReadoutKind(self.kind))
        if not self.threshold_ref:
            raise ValueError("ReadoutStep.threshold_ref must not be empty")
        if not self.output_name:
            raise ValueError("ReadoutStep.output_name must not be empty")
        if isinstance(self.repetitions, bool) or int(self.repetitions) != self.repetitions:
            raise TypeError("ReadoutStep.repetitions must be an integer")
        if self.repetitions < 1:
            raise ValueError("ReadoutStep.repetitions must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReadoutStep":
        return cls(
            kind=ReadoutKind(value["kind"]),
            threshold_ref=value["threshold_ref"],
            output_name=value["output_name"],
            repetitions=int(value.get("repetitions", 1)),
        )


@dataclass(frozen=True)
class StabilizationPolicy:
    ple_refocus_interval_s: Optional[float] = None
    confocal_refocus_interval_s: Optional[float] = None
    green_confocal_refocus_interval_s: Optional[float] = None
    red_confocal_refocus_interval_s: Optional[float] = None
    lock_laser_to_wavemeter: bool = False
    use_defect_frame: bool = False

    def __post_init__(self) -> None:
        for name in (
            "ple_refocus_interval_s",
            "confocal_refocus_interval_s",
            "green_confocal_refocus_interval_s",
            "red_confocal_refocus_interval_s",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError("{} must be positive when enabled".format(name))

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Optional[Mapping[str, Any]]) -> "StabilizationPolicy":
        value = {} if value is None else value
        return cls(
            ple_refocus_interval_s=value.get("ple_refocus_interval_s"),
            confocal_refocus_interval_s=value.get("confocal_refocus_interval_s"),
            green_confocal_refocus_interval_s=value.get(
                "green_confocal_refocus_interval_s"
            ),
            red_confocal_refocus_interval_s=value.get(
                "red_confocal_refocus_interval_s"
            ),
            lock_laser_to_wavemeter=bool(value.get("lock_laser_to_wavemeter", False)),
            use_defect_frame=bool(value.get("use_defect_frame", False)),
        )

    @property
    def green_interval_s(self) -> Optional[float]:
        return (
            self.green_confocal_refocus_interval_s
            if self.green_confocal_refocus_interval_s is not None
            else self.confocal_refocus_interval_s
        )

    @property
    def red_interval_s(self) -> Optional[float]:
        return (
            self.red_confocal_refocus_interval_s
            if self.red_confocal_refocus_interval_s is not None
            else self.confocal_refocus_interval_s
        )


@dataclass(frozen=True)
class ExecutionPolicy:
    """Run controls that are independent from the pulse-sequence recipe."""

    acquisition_mode: AcquisitionMode = AcquisitionMode.QM_STREAMS
    result_timeout_s: float = 300.0
    max_retries_per_block: int = 3
    debug_simulation: bool = False
    simulation_duration_cycles: int = 10_000
    save_raw_events: bool = True
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "acquisition_mode", AcquisitionMode(self.acquisition_mode))
        if not np.isfinite(self.result_timeout_s) or self.result_timeout_s <= 0:
            raise ValueError("ExecutionPolicy.result_timeout_s must be positive")
        if (
            isinstance(self.max_retries_per_block, bool)
            or int(self.max_retries_per_block) != self.max_retries_per_block
        ):
            raise TypeError("ExecutionPolicy.max_retries_per_block must be an integer")
        if self.max_retries_per_block < 0:
            raise ValueError("ExecutionPolicy.max_retries_per_block must not be negative")
        if (
            isinstance(self.simulation_duration_cycles, bool)
            or int(self.simulation_duration_cycles) != self.simulation_duration_cycles
        ):
            raise TypeError("ExecutionPolicy.simulation_duration_cycles must be an integer")
        if self.simulation_duration_cycles < 1:
            raise ValueError("ExecutionPolicy.simulation_duration_cycles must be positive")
        for name in ("quiet_hours_start", "quiet_hours_end"):
            value = getattr(self, name)
            if value is not None:
                try:
                    hour, minute = (int(part) for part in value.split(":"))
                except (TypeError, ValueError) as exc:
                    raise ValueError("{} must use HH:MM format".format(name)) from exc
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("{} must use HH:MM format".format(name))
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("Both quiet-hours boundaries must be configured together")

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Optional[Mapping[str, Any]]) -> "ExecutionPolicy":
        value = {} if value is None else value
        return cls(
            acquisition_mode=AcquisitionMode(
                value.get("acquisition_mode", AcquisitionMode.QM_STREAMS.value)
            ),
            result_timeout_s=float(value.get("result_timeout_s", 300.0)),
            max_retries_per_block=int(value.get("max_retries_per_block", 3)),
            debug_simulation=bool(value.get("debug_simulation", False)),
            simulation_duration_cycles=int(value.get("simulation_duration_cycles", 10_000)),
            save_raw_events=bool(value.get("save_raw_events", True)),
            quiet_hours_start=value.get("quiet_hours_start"),
            quiet_hours_end=value.get("quiet_hours_end"),
        )


@dataclass(frozen=True)
class ExperimentSpec:
    """Complete, serializable definition of one queued experiment."""

    recipe: str
    name: str
    scan_axes: Tuple[ScanAxis, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    readout: Tuple[ReadoutStep, ...] = field(default_factory=tuple)
    stabilization: StabilizationPolicy = field(default_factory=StabilizationPolicy)
    execution: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    threshold_profile: str = "default"
    threshold_version: Optional[int] = None
    experiment_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.recipe or not isinstance(self.recipe, str):
            raise ValueError("ExperimentSpec.recipe must be a non-empty string")
        if not self.name or not isinstance(self.name, str):
            raise ValueError("ExperimentSpec.name must be a non-empty string")
        object.__setattr__(self, "scan_axes", tuple(self.scan_axes))
        object.__setattr__(self, "readout", tuple(self.readout))
        axis_names = [axis.name for axis in self.scan_axes]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError("Experiment scan-axis names must be unique")
        if not self.threshold_profile:
            raise ValueError("ExperimentSpec.threshold_profile must not be empty")
        if self.threshold_version is not None and self.threshold_version < 1:
            raise ValueError("ExperimentSpec.threshold_version must be positive")
        # Fail early if parameters/metadata contain values that cannot be saved.
        to_primitive(dict(self.parameters))
        to_primitive(dict(self.metadata))

    @property
    def expected_points(self) -> int:
        return int(np.prod([len(axis.values) for axis in self.scan_axes], dtype=int))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipe": self.recipe,
            "name": self.name,
            "scan_axes": [axis.to_dict() for axis in self.scan_axes],
            "parameters": to_primitive(dict(self.parameters)),
            "readout": [step.to_dict() for step in self.readout],
            "stabilization": self.stabilization.to_dict(),
            "execution": self.execution.to_dict(),
            "metadata": to_primitive(dict(self.metadata)),
            "threshold_profile": self.threshold_profile,
            "threshold_version": self.threshold_version,
            "experiment_id": self.experiment_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentSpec":
        return cls(
            recipe=value["recipe"],
            name=value["name"],
            scan_axes=tuple(ScanAxis.from_dict(axis) for axis in value.get("scan_axes", [])),
            parameters=dict(value.get("parameters", {})),
            readout=tuple(ReadoutStep.from_dict(step) for step in value.get("readout", [])),
            stabilization=StabilizationPolicy.from_dict(value.get("stabilization")),
            execution=ExecutionPolicy.from_dict(value.get("execution")),
            metadata=dict(value.get("metadata", {})),
            threshold_profile=value.get("threshold_profile", "default"),
            threshold_version=value.get("threshold_version"),
            experiment_id=value.get("experiment_id", str(uuid4())),
            created_at=parse_datetime(value.get("created_at", utc_now()), "created_at"),
        )


@dataclass(frozen=True)
class RunMetadata:
    operator: str = ""
    sample: str = ""
    defect_id: str = ""
    notes: str = ""
    tags: Tuple[str, ...] = field(default_factory=tuple)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunMetadata":
        return cls(
            operator=value.get("operator", ""),
            sample=value.get("sample", ""),
            defect_id=value.get("defect_id", ""),
            notes=value.get("notes", ""),
            tags=tuple(value.get("tags", ())),
            started_at=(
                parse_datetime(value["started_at"], "started_at")
                if value.get("started_at")
                else None
            ),
            finished_at=(
                parse_datetime(value["finished_at"], "finished_at")
                if value.get("finished_at")
                else None
            ),
            extra=dict(value.get("extra", {})),
        )


@dataclass(frozen=True)
class RunProvenance:
    git_revision: str = ""
    qm_configuration: str = ""
    recipe_source: str = ""
    software_versions: Mapping[str, str] = field(default_factory=dict)
    calibration_versions: Mapping[str, Any] = field(default_factory=dict)
    hardware: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunProvenance":
        return cls(
            git_revision=value.get("git_revision", ""),
            qm_configuration=value.get("qm_configuration", ""),
            recipe_source=value.get("recipe_source", ""),
            software_versions=dict(value.get("software_versions", {})),
            calibration_versions=dict(value.get("calibration_versions", {})),
            hardware=dict(value.get("hardware", {})),
        )


@dataclass(frozen=True)
class MeasurementBatch:
    """One append-only xarray acquisition batch.

    ``dataset`` must have ``record`` as its leading dimension for every
    record-dependent coordinate and variable.  Static trailing coordinates
    such as ``readout`` or ``histogram_bin`` are permitted.  ``raw_events`` is
    keyed by acquisition channel and contains one one-dimensional array per
    record.
    """

    dataset: Any
    raw_events: Mapping[str, Sequence[np.ndarray]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Import lazily so model-only users do not require xarray at import time.
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("MeasurementBatch requires the 'xarray' package") from exc
        if not isinstance(self.dataset, xr.Dataset):
            raise TypeError("MeasurementBatch.dataset must be an xarray.Dataset")
        if "record" not in self.dataset.sizes:
            raise ValueError("MeasurementBatch.dataset must contain a 'record' dimension")
        record_count = int(self.dataset.sizes["record"])
        if record_count < 1:
            raise ValueError("MeasurementBatch must contain at least one record")
        for name, values in self.raw_events.items():
            if len(values) != record_count:
                raise ValueError(
                    "Raw-event channel '{}' has {} shots, expected {}".format(
                        name, len(values), record_count
                    )
                )
            for events in values:
                if np.asarray(events).ndim != 1:
                    raise ValueError("Raw-event shots must be one-dimensional")

    @property
    def record_count(self) -> int:
        return int(self.dataset.sizes["record"])
