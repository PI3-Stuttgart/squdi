"""Qudi logic module that runs typed nuclear experiments on a Quantum Machine."""

import importlib
import importlib.metadata
import threading
from pathlib import Path

from PySide2 import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.nuclear_operations_runner_interface import NuclearOperationsRunnerInterface
from qudi.util.mutex import RecursiveMutex

from .execution_engine import ExecutionCallbacks, NuclearExperimentEngine
from .lab_services import NuclearLabServices
from .models import ExperimentSpec, RunProvenance
from .recipes import RecipeRegistry


class NuclearOperationsLogic(NuclearOperationsRunnerInterface):
    """Queue-facing runner with direct connectors to setup services."""

    quantum_machine = Connector(interface="QuantumMachineInterface")
    threshold_provider = Connector(interface="ReadoutCalibrationLogic")
    magnet = Connector(interface="MagnetLogic", optional=True)
    microwave = Connector(interface="MicrowaveInterface", optional=True)
    external_counter = Connector(interface="GatedCounter", optional=True)
    confocal = Connector(interface="ScanningProbeLogic", optional=True)
    confocal_optimizer = Connector(interface="ScanningOptimizeLogic", optional=True)
    ple_optimizer = Connector(interface="PLEOptimizeScannerLogic", optional=True)
    wavemeter = Connector(interface="HighFinesseWavemeter", optional=True)
    laser_controller = Connector(interface="DlProLaser", optional=True)
    transition_tracker = Connector(interface="TransitionTracker", optional=True)
    analog_output = Connector(interface="AOLogic", optional=True)
    switches = Connector(interface="SwitchCombinerInterfuse", optional=True)
    ppg = Connector(interface="PPG512", optional=True)

    output_directory = ConfigOption(name="output_directory", default="nuclear_ops_data")
    recipe_modules = ConfigOption(name="recipe_modules", default=[])
    shutdown_timeout_s = ConfigOption(name="shutdown_timeout_s", default=10.0)

    sigRecipesChanged = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._recipes = RecipeRegistry()
        self._engine = None
        self._worker = None
        self._active_item_id = ""

    def on_activate(self):
        self._recipes = RecipeRegistry()
        for module_name in self.recipe_modules or ():
            module = importlib.import_module(str(module_name))
            register = getattr(module, "register_recipes", None)
            if not callable(register):
                raise TypeError(
                    "Recipe module {!r} must define register_recipes(registry)".format(
                        module_name
                    )
                )
            register(self._recipes)
        self.sigRecipesChanged.emit(self._recipes.names)

    def on_deactivate(self):
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.cancel_experiment()
            worker.join(timeout=float(self.shutdown_timeout_s))
            if worker.is_alive():
                self.log.error("Nuclear experiment worker did not stop before deactivation")
        self._engine = None
        self._worker = None
        self._active_item_id = ""

    @property
    def recipe_names(self):
        return self._recipes.names

    def register_recipe(self, recipe):
        """Register a recipe before a run (primarily useful for development)."""

        with self._thread_lock:
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("Recipes cannot be changed while an experiment is running")
            self._recipes.register(recipe)
            self.sigRecipesChanged.emit(self._recipes.names)

    @QtCore.Slot(object, str)
    def start_experiment(self, experiment, queue_item_id):
        spec = experiment if isinstance(experiment, ExperimentSpec) else ExperimentSpec.from_dict(experiment)
        with self._thread_lock:
            if self._worker is not None and self._worker.is_alive():
                self.sigExperimentFailed.emit(
                    queue_item_id,
                    "A nuclear experiment is already running",
                    "",
                )
                return
            self._active_item_id = queue_item_id
            self._engine = self._make_engine(queue_item_id)
            self._worker = threading.Thread(
                target=self._run_worker,
                args=(spec, queue_item_id),
                name="NuclearOperations-{}".format(queue_item_id),
                daemon=True,
            )
            self._worker.start()

    @QtCore.Slot()
    def pause_experiment(self):
        if self._engine is not None:
            self._engine.pause()

    @QtCore.Slot()
    def resume_experiment(self):
        if self._engine is not None:
            self._engine.resume()

    @QtCore.Slot()
    def cancel_experiment(self):
        if self._engine is not None:
            self._engine.cancel()

    def _run_worker(self, experiment, queue_item_id):
        result = self._engine.run(experiment, queue_item_id=queue_item_id)
        if result.status == "completed":
            self.sigExperimentFinished.emit(queue_item_id, result.run_file)
        elif result.status == "cancelled":
            self.sigExperimentCancelled.emit(queue_item_id, result.run_file)
        else:
            self.sigExperimentFailed.emit(queue_item_id, result.error, result.run_file)
        with self._thread_lock:
            self._active_item_id = ""

    def _make_engine(self, queue_item_id):
        machine = self.quantum_machine()
        thresholds = self.threshold_provider()
        callbacks = ExecutionCallbacks(
            started=lambda path: self.sigExperimentStarted.emit(queue_item_id, path),
            progress=lambda value: self.sigProgressUpdated.emit(queue_item_id, value),
            paused=lambda: self.sigExperimentPaused.emit(queue_item_id),
            resumed=lambda: self.sigExperimentResumed.emit(queue_item_id),
            log=self.log.info,
        )
        services = NuclearLabServices(
            quantum_machine=machine,
            magnet=self._optional(self.magnet),
            microwave=self._optional(self.microwave),
            external_counter=self._optional(self.external_counter),
            confocal=self._optional(self.confocal),
            confocal_optimizer=self._optional(self.confocal_optimizer),
            ple_optimizer=self._optional(self.ple_optimizer),
            wavemeter=self._optional(self.wavemeter),
            laser_controller=self._optional(self.laser_controller),
            transition_tracker=self._optional(self.transition_tracker),
            analog_output=self._optional(self.analog_output),
            switches=self._optional(self.switches),
            ppg=self._optional(self.ppg),
            log=self.log,
        )
        return NuclearExperimentEngine(
            recipes=self._recipes,
            thresholds=thresholds,
            quantum_machine=machine,
            output_directory=Path(str(self.output_directory)),
            services=services,
            callbacks=callbacks,
            provenance_provider=lambda _experiment: self._provenance(machine),
        )

    @staticmethod
    def _optional(connector):
        try:
            return connector()
        except Exception:
            return None

    @staticmethod
    def _provenance(machine):
        versions = {}
        for distribution in ("qudi", "qm-qua", "xarray", "h5py"):
            try:
                versions[distribution] = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                versions[distribution] = "unknown"
        snapshot = machine.configuration_snapshot
        return RunProvenance(
            qm_configuration=snapshot.get("sha256", ""),
            software_versions=versions,
            hardware={"quantum_machine": snapshot},
        )

