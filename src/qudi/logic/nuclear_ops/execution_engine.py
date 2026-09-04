"""Testable execution engine for queued nuclear experiments."""

import itertools
import inspect
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import numpy as np
import xarray as xr

from .analysis import analyze_readout_thresholds, combine_analysis
from .hdf5_store import NuclearDataset
from .models import ExperimentSpec, MeasurementBatch, RunMetadata, RunProvenance
from .recipes import AcquisitionResult, ProgramBundle, RecipeContext, RecipeRegistry
from .scan_planner import ExecutionBlock, ScanPlanner
from .thresholds import ThresholdRegistry


class ExperimentCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    status: str
    run_file: str
    records: int
    error: str = ""


@dataclass
class ExecutionCallbacks:
    started: Callable[[str], None] = lambda _path: None
    progress: Callable[[float], None] = lambda _progress: None
    paused: Callable[[], None] = lambda: None
    resumed: Callable[[], None] = lambda: None
    log: Callable[[str], None] = lambda _message: None


class RunServices:
    """Lab-service hooks called at deterministic, pause-safe boundaries."""

    def before_run(self, experiment: ExperimentSpec, control: "ExecutionControl") -> None:
        pass

    def before_block(
        self,
        experiment: ExperimentSpec,
        block: ExecutionBlock,
        control: "ExecutionControl",
    ) -> Mapping[str, Any]:
        return {}

    def after_block(
        self,
        context: RecipeContext,
        result: AcquisitionResult,
        control: "ExecutionControl",
    ) -> None:
        pass

    def after_run(self, experiment: ExperimentSpec, status: str) -> None:
        pass


class ExecutionControl:
    """Thread-safe cooperative pause/cancel state shared with service hooks."""

    def __init__(self, callbacks: ExecutionCallbacks) -> None:
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._callbacks = callbacks
        self._reported_paused = False

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    def request_pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise ExperimentCancelled("Experiment cancelled")

    def wait(self, seconds: float, poll_s: float = 0.05) -> None:
        """Cancellation-aware delay for hardware settling and service hooks."""

        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self.wait_until_runnable()
            self.check_cancelled()
            time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))

    def wait_until_runnable(self) -> None:
        self.check_cancelled()
        while self._pause.is_set():
            if not self._reported_paused:
                self._reported_paused = True
                self._callbacks.paused()
            if self._cancel.wait(0.05):
                raise ExperimentCancelled("Experiment cancelled while paused")
        if self._reported_paused:
            self._reported_paused = False
            self._callbacks.resumed()
        self.check_cancelled()


def default_run_path(output_directory: Path, experiment: ExperimentSpec, queue_item_id: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", experiment.name).strip("_") or "experiment"
    identifier = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", queue_item_id or experiment.experiment_id
    ).strip("_")
    return Path(output_directory) / "{}_{}_{}.h5".format(timestamp, safe_name, identifier)


class NuclearExperimentEngine:
    """Execute one experiment at a time and commit only complete xarray batches."""

    def __init__(
        self,
        recipes: RecipeRegistry,
        thresholds: ThresholdRegistry,
        quantum_machine: Any,
        output_directory: Any,
        services: Optional[RunServices] = None,
        callbacks: Optional[ExecutionCallbacks] = None,
        metadata_provider: Optional[Callable[[ExperimentSpec], RunMetadata]] = None,
        provenance_provider: Optional[Callable[[ExperimentSpec], RunProvenance]] = None,
        run_path_factory: Callable[[Path, ExperimentSpec, str], Path] = default_run_path,
    ) -> None:
        self.recipes = recipes
        self.thresholds = thresholds
        self.quantum_machine = quantum_machine
        self.output_directory = Path(output_directory).expanduser().resolve()
        self.services = services or RunServices()
        self.callbacks = callbacks or ExecutionCallbacks()
        self.metadata_provider = metadata_provider or self._default_metadata
        self.provenance_provider = provenance_provider or (lambda _spec: RunProvenance())
        self.run_path_factory = run_path_factory
        self._control = ExecutionControl(self.callbacks)
        self._running_lock = threading.Lock()

    @staticmethod
    def _default_metadata(experiment: ExperimentSpec) -> RunMetadata:
        source = dict(experiment.metadata)
        known = {key: source.pop(key, "") for key in ("operator", "sample", "defect_id", "notes")}
        tags = tuple(source.pop("tags", ()))
        return RunMetadata(tags=tags, extra=source, **known)

    def pause(self) -> None:
        self._control.request_pause()

    def resume(self) -> None:
        self._control.resume()

    def cancel(self) -> None:
        self._control.request_cancel()
        stop = getattr(self.quantum_machine, "stop_current_job", None)
        if callable(stop):
            stop()

    def run(self, experiment: ExperimentSpec, queue_item_id: str = "") -> RunResult:
        if not self._running_lock.acquire(blocking=False):
            raise RuntimeError("A nuclear experiment is already running")
        run = None
        run_path = None
        status = "failed"
        error = ""
        try:
            self._control = ExecutionControl(self.callbacks)
            recipe = self.recipes.get(experiment.recipe)
            recipe.validate(experiment)
            threshold_snapshot = self.thresholds.snapshot_for_experiment(experiment)
            plan = ScanPlanner(recipe.axis_policies).plan(experiment)
            run_path = self.run_path_factory(self.output_directory, experiment, queue_item_id)
            provenance = self.provenance_provider(experiment)
            try:
                recipe_source = inspect.getsource(type(recipe))
            except (OSError, TypeError):
                recipe_source = ""
            if not provenance.recipe_source:
                provenance = replace(provenance, recipe_source=recipe_source)
            run = NuclearDataset.create(
                run_path,
                experiment=experiment,
                metadata=self.metadata_provider(experiment),
                provenance=provenance,
                thresholds=threshold_snapshot,
                queue_item={"item_id": queue_item_id, "status": "running"},
            )
            run.store.append_log("Execution plan contains {} program blocks".format(len(plan.blocks)))
            self.callbacks.started(str(run_path))
            self.services.before_run(experiment, self._control)

            completed_points = 0
            for block in plan.blocks:
                self._control.wait_until_runnable()
                observations = self.services.before_block(experiment, block, self._control)
                result, context = self._execute_block(
                    recipe, experiment, block, threshold_snapshot, observations, run
                )
                batch = self._normalize_batch(result.batch, block, context.observations)
                if not experiment.execution.save_raw_events:
                    batch = MeasurementBatch(dataset=batch.dataset, raw_events={})
                run.append(batch)
                self.services.after_block(context, result, self._control)
                completed_points += block.qua_points
                self.callbacks.progress(completed_points / max(1, plan.total_points))

            if experiment.execution.debug_simulation:
                analysis = xr.Dataset()
            else:
                threshold_analysis = analyze_readout_thresholds(
                    run.dataset, experiment, threshold_snapshot
                )
                recipe_analysis = recipe.analyze(run.dataset, experiment, threshold_snapshot)
                analysis = combine_analysis(threshold_analysis, recipe_analysis)
            if analysis.variables:
                run.save_analysis(analysis)
            status = "completed"
            run.finalize(status=status)
            return RunResult(status, str(run_path), run.store.committed_records)
        except ExperimentCancelled as exc:
            status = "cancelled"
            error = str(exc)
            if run is not None:
                run.store.append_log(error)
                run.finalize(status=status, error=error)
            return RunResult(status, str(run_path or ""), run.store.committed_records if run else 0, error)
        except Exception as exc:
            error = "{}: {}".format(type(exc).__name__, exc)
            if run is not None:
                run.store.append_log(error)
                run.finalize(status="failed", error=error)
            return RunResult("failed", str(run_path or ""), run.store.committed_records if run else 0, error)
        finally:
            try:
                self.services.after_run(experiment, status)
            finally:
                self._running_lock.release()

    def _execute_block(
        self,
        recipe,
        experiment,
        block,
        threshold_snapshot,
        observations,
        run,
    ):
        maximum_attempts = experiment.execution.max_retries_per_block + 1
        for attempt in range(maximum_attempts):
            self._control.wait_until_runnable()
            context = RecipeContext(
                experiment=experiment,
                block=block,
                thresholds=threshold_snapshot,
                attempt=attempt,
                observations=dict(observations),
            )
            bundle = recipe.build_program(context)
            if not isinstance(bundle, ProgramBundle):
                raise TypeError("Recipe.build_program() must return ProgramBundle")
            run.store.append_log(
                "Block {} attempt {} compiled: {}".format(
                    block.index, attempt + 1, dict(bundle.metadata)
                )
            )
            run.store.save_program_metadata(block.index, attempt, bundle.metadata)
            if experiment.execution.debug_simulation:
                self.quantum_machine.simulate(
                    bundle.program,
                    duration_cycles=experiment.execution.simulation_duration_cycles,
                )
                return self._simulation_result(block), context
            job = self.quantum_machine.execute(bundle.program)
            try:
                result = recipe.acquire(job, context, experiment.execution.result_timeout_s)
            except Exception:
                # A halt requested by cancel() often surfaces in the SDK as a
                # job/result-handle error. Preserve cancellation semantics.
                self._control.check_cancelled()
                raise
            if not isinstance(result, AcquisitionResult):
                raise TypeError("Recipe.acquire() must return AcquisitionResult")
            self._control.check_cancelled()
            if result.valid:
                return result, context
            run.store.append_log(
                "Block {} attempt {} rejected: {}".format(
                    block.index, attempt + 1, result.invalid_reason
                )
            )
        raise RuntimeError(
            "Block {} remained invalid after {} attempts".format(block.index, maximum_attempts)
        )

    @staticmethod
    def _simulation_result(block: ExecutionBlock) -> AcquisitionResult:
        dataset = xr.Dataset(
            data_vars={"simulation_completed": ("record", np.ones(block.qua_points, dtype=bool))},
        )
        return AcquisitionResult(MeasurementBatch(dataset=dataset), valid=True)

    @staticmethod
    def _normalize_batch(
        batch: MeasurementBatch,
        block: ExecutionBlock,
        observations: Mapping[str, Any],
    ) -> MeasurementBatch:
        if batch is None:
            raise ValueError("A valid acquisition returned no batch")
        if batch.record_count != block.qua_points:
            raise ValueError(
                "Block {} returned {} records, expected {}".format(
                    block.index, batch.record_count, block.qua_points
                )
            )
        dataset = batch.dataset
        if "record" in dataset.coords:
            dataset = dataset.drop_vars("record")
        point_values = list(
            itertools.product(*(axis.values for axis in block.qua_axes))
        ) if block.qua_axes else [()]
        for axis_index, axis in enumerate(block.qua_axes):
            expected = np.asarray([point[axis_index] for point in point_values])
            if axis.name in dataset.coords:
                actual = np.asarray(dataset.coords[axis.name].values)
                if not np.array_equal(actual, expected):
                    raise ValueError(
                        "Recipe returned wrong values for QUA axis {!r}".format(axis.name)
                    )
            else:
                dataset = dataset.assign_coords({axis.name: ("record", expected)})
            dataset.coords[axis.name].attrs.setdefault("unit", axis.unit)
        outer_values = dict(block.host_values)
        outer_values.update(block.recompile_values)
        for name, value in outer_values.items():
            dataset = dataset.assign_coords({name: ("record", [value] * block.qua_points)})
        for name, value in observations.items():
            if name in dataset:
                raise ValueError("Observation {!r} conflicts with acquired data".format(name))
            dataset = dataset.assign_coords({name: ("record", [value] * block.qua_points)})
        dataset = dataset.assign_coords(block=("record", [block.index] * block.qua_points))
        if "valid" not in dataset:
            dataset["valid"] = ("record", np.ones(block.qua_points, dtype=bool))
        return MeasurementBatch(dataset=dataset, raw_events=batch.raw_events)
