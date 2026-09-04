"""Recipe contracts for Quantum-Machines-native nuclear experiments.

A recipe owns pulse-sequence construction and result decoding.  The execution
engine owns scan ordering, lifecycle control, persistence and lab services.
Keeping that boundary explicit makes recipes small and testable and prevents
the old pattern where user scripts mutated a monolithic runner.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import xarray as xr

from .models import ExperimentSpec, MeasurementBatch
from .scan_planner import ExecutionBlock
from .thresholds import ThresholdSnapshot
from .serialization import to_primitive


@dataclass(frozen=True)
class RecipeContext:
    experiment: ExperimentSpec
    block: ExecutionBlock
    thresholds: ThresholdSnapshot
    attempt: int = 0
    observations: Mapping[str, Any] = field(default_factory=dict)

    @property
    def parameters(self) -> Dict[str, Any]:
        """Return fixed parameters overlaid with this block's outer-axis values."""

        values = dict(self.experiment.parameters)
        values.update(self.block.host_values)
        values.update(self.block.recompile_values)
        return values


@dataclass(frozen=True)
class ProgramBundle:
    """A compiled QUA program plus serializable compilation information."""

    program: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        to_primitive(dict(self.metadata))


@dataclass(frozen=True)
class AcquisitionResult:
    """Decoded result of one program execution.

    Invalid results are retried without being committed to the main xarray
    dataset.  The reason and attempt number are still written to the run log.
    """

    batch: Optional[MeasurementBatch]
    valid: bool = True
    invalid_reason: str = ""

    def __post_init__(self) -> None:
        if self.valid and self.batch is None:
            raise ValueError("A valid acquisition result requires a MeasurementBatch")
        if not self.valid and not self.invalid_reason:
            raise ValueError("An invalid acquisition result requires a reason")


class ExperimentRecipe(ABC):
    """Base class implemented by each migrated nuclear pulse sequence."""

    name = ""
    axis_policies = {}

    def validate(self, experiment: ExperimentSpec) -> None:
        if experiment.recipe != self.name:
            raise ValueError(
                "Recipe {!r} cannot execute experiment recipe {!r}".format(
                    self.name, experiment.recipe
                )
            )

    @abstractmethod
    def build_program(self, context: RecipeContext) -> ProgramBundle:
        """Build the QUA program for one host/recompile execution block."""

    @abstractmethod
    def acquire(self, job: Any, context: RecipeContext, timeout_s: float) -> AcquisitionResult:
        """Wait for and decode one program execution into an xarray batch."""

    def analyze(
        self,
        dataset: xr.Dataset,
        experiment: ExperimentSpec,
        thresholds: ThresholdSnapshot,
    ) -> xr.Dataset:
        """Return recipe-specific derived data for the HDF5 analysis group."""

        return xr.Dataset()


@dataclass(frozen=True)
class StreamOutput:
    """Map one finite QM result handle to an xarray data variable."""

    handle: str
    variable: str
    trailing_dimensions: Tuple[str, ...] = field(default_factory=tuple)
    trailing_coordinates: Mapping[str, Any] = field(default_factory=dict)
    unit: str = ""


@dataclass(frozen=True)
class RawEventOutput:
    """Map padded QM time tags plus per-record lengths to raw HDF5 events."""

    values_handle: str
    lengths_handle: str
    channel: str


def _fetch_values(handle):
    value = handle.fetch_all()
    if isinstance(value, Mapping) and "value" in value:
        value = value["value"]
    if isinstance(value, np.ndarray) and value.dtype.fields and "value" in value.dtype.fields:
        value = value["value"]
    return np.asarray(value)


class QmStreamRecipe(ExperimentRecipe):
    """Base recipe that decodes finite native QM streams into xarray."""

    stream_outputs = ()
    raw_event_outputs = ()

    def validate(self, experiment: ExperimentSpec) -> None:
        super().validate(experiment)
        output_names = {output.variable for output in self.stream_outputs}
        missing = {step.output_name for step in experiment.readout}.difference(output_names)
        if missing:
            raise ValueError(
                "Recipe {!r} does not provide readout variables {}".format(
                    self.name, sorted(missing)
                )
            )

    def acquire(self, job: Any, context: RecipeContext, timeout_s: float) -> AcquisitionResult:
        handles = job.result_handles
        completed = handles.wait_for_all_values(timeout=timeout_s)
        if completed is False:
            raise TimeoutError("QM result streams did not complete within {} s".format(timeout_s))
        expected = context.block.qua_points
        variables = {}
        coordinates = {}
        for output in self.stream_outputs:
            values = _fetch_values(handles.get(output.handle))
            expected_shape = (expected,) + tuple(
                len(output.trailing_coordinates[name]) for name in output.trailing_dimensions
            )
            if values.size != int(np.prod(expected_shape, dtype=int)):
                raise ValueError(
                    "QM stream {!r} returned {} values, expected {}".format(
                        output.handle, values.size, int(np.prod(expected_shape, dtype=int))
                    )
                )
            values = values.reshape(expected_shape)
            dimensions = ("record",) + tuple(output.trailing_dimensions)
            variables[output.variable] = (dimensions, values, {"unit": output.unit})
            for name in output.trailing_dimensions:
                incoming = np.asarray(output.trailing_coordinates[name])
                if name in coordinates and not np.array_equal(coordinates[name], incoming):
                    raise ValueError("Conflicting stream coordinate {!r}".format(name))
                coordinates[name] = incoming

        raw_events = {}
        for output in self.raw_event_outputs:
            padded = _fetch_values(handles.get(output.values_handle))
            lengths = _fetch_values(handles.get(output.lengths_handle)).astype(int).reshape(-1)
            if padded.shape[0] != expected or lengths.size != expected:
                raise ValueError(
                    "Raw stream {!r} does not contain {} records".format(
                        output.values_handle, expected
                    )
                )
            if np.any(lengths < 0) or np.any(lengths > np.prod(padded.shape[1:], dtype=int)):
                raise ValueError("Raw-event lengths exceed the padded QM stream width")
            raw_events[output.channel] = [
                np.asarray(padded[index]).reshape(-1)[: length]
                for index, length in enumerate(lengths)
            ]

        return AcquisitionResult(
            MeasurementBatch(
                dataset=xr.Dataset(data_vars=variables, coords=coordinates),
                raw_events=raw_events,
            )
        )


class RecipeRegistry:
    """Explicit recipe registry; serialized experiments only store recipe names."""

    def __init__(self, recipes=()) -> None:
        self._recipes = {}
        for recipe in recipes:
            self.register(recipe)

    @property
    def names(self):
        return tuple(sorted(self._recipes))

    def register(self, recipe: ExperimentRecipe) -> None:
        if not isinstance(recipe, ExperimentRecipe):
            raise TypeError("Recipes must inherit ExperimentRecipe")
        if not recipe.name:
            raise ValueError("A recipe must define a non-empty name")
        if recipe.name in self._recipes:
            raise ValueError("Recipe {!r} is already registered".format(recipe.name))
        self._recipes[recipe.name] = recipe

    def get(self, name: str) -> ExperimentRecipe:
        try:
            return self._recipes[name]
        except KeyError as exc:
            raise KeyError(
                "Unknown nuclear recipe {!r}; available recipes: {}".format(
                    name, ", ".join(self.names) or "none"
                )
            ) from exc
