"""Single-file pulse + sweep scripts. Source is frozen when enqueued."""
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from .models import ExperimentSpec, ExecutionPolicy, ReadoutStep, ScanAxis
from .recipes import ExperimentRecipe, RecipeRegistry
from .snv_qua_recipes import SnVQuaRecipe, register_recipes
from .extended_recipes import register_recipes as register_extended


def namespace(source, filename):
    scope = {"__name__": "nuclear_userscript", "__file__": filename}
    exec(compile(source, filename, "exec"), scope)
    if not callable(scope.get("pulses")):
        raise ValueError("Userscript must define pulses(q, p)")
    return scope


def specification(source, filename):
    scope = namespace(source, filename)
    axes = tuple(ScanAxis(name, tuple(values), unit=scope.get("UNITS", {}).get(name, ""),
                          execution=scope.get("AXIS_EXECUTION", {}).get(name, "auto"))
                 for name, values in scope["SWEEPS"].items())
    return ExperimentSpec(recipe="userscript", name=scope.get("NAME", Path(filename).stem),
        scan_axes=axes, parameters=dict(scope.get("PARAMETERS", {})),
        execution=ExecutionPolicy(acquisition_mode="external_counter", save_raw_events=scope.get("SAVE_RAW", True)),
        readout=(ReadoutStep("ssr", "ssr_e1", "result_counts"),),
        metadata={"userscript": {"filename": str(filename), "source": source,
                  "sha256": hashlib.sha256(source.encode()).hexdigest(),
                  "protocol": scope.get("PROTOCOL", "nuclear_rabi")}})


class UserScriptRecipe(ExperimentRecipe):
    name = "userscript"
    axis_policies = dict(SnVQuaRecipe.axis_policies, repeat="recompile")

    def _recipe(self, experiment, execute=False):
        archive = experiment.metadata["userscript"]
        registry = RecipeRegistry()
        register_recipes(registry); register_extended(registry)
        recipe = registry.get(archive["protocol"])
        recipe.name = self.name
        if execute:
            if hashlib.sha256(archive["source"].encode()).hexdigest() != archive["sha256"]:
                raise ValueError("Archived userscript checksum does not match")
            recipe.pulse_function = namespace(archive["source"], archive["filename"])["pulses"]
        return recipe

    def validate(self, experiment):
        super().validate(experiment)
        if experiment.execution.acquisition_mode.value != "external_counter":
            raise ValueError("Userscripts use Swabian counting")
        self._recipe(experiment).validate(experiment)

    def build_program(self, context):
        return self._recipe(context.experiment, execute=True).build_program(context)

    def acquire(self, job, context, timeout_s):
        return self._recipe(context.experiment).acquire(job, context, timeout_s)

    def analyze(self, dataset, experiment, thresholds):
        recipe = self._recipe(experiment)
        return recipe.analyze(dataset, replace(experiment, recipe=experiment.metadata["userscript"]["protocol"]), thresholds)


def source_archive():
    """Archive the entire native implementation, not merely a subclass body."""
    qudi = Path(__file__).resolve().parents[2]
    paths = list((qudi / "logic/nuclear_ops").glob("*.py"))
    paths += list((qudi / "gui/nuclear_ops").glob("*.py"))
    paths += [qudi / "hardware/OPX/quantum_machine_hardware.py", qudi / "hardware/OPX/configuration.py",
              qudi / "hardware/timetagger/nuclear_counter.py", qudi / "interface/nuclear_counter_interface.py"]
    return [{"path": p.relative_to(qudi).as_posix(), "source": p.read_text(encoding="utf-8"),
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
