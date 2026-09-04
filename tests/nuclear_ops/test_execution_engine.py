import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import xarray as xr
import h5py

from qudi.logic.nuclear_ops.execution_engine import NuclearExperimentEngine, RunServices
from qudi.logic.nuclear_ops.hdf5_store import NuclearDataset
from qudi.logic.nuclear_ops.models import (
    ExecutionPolicy,
    ExperimentSpec,
    MeasurementBatch,
    ReadoutStep,
    ScanAxis,
)
from qudi.logic.nuclear_ops.recipes import (
    AcquisitionResult,
    ExperimentRecipe,
    ProgramBundle,
    RecipeRegistry,
)
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry


class FakeQuantumMachine:
    def __init__(self):
        self.executed = []
        self.simulated = []
        self.stopped = False

    def execute(self, program):
        self.executed.append(program)
        return {"program": program}

    def simulate(self, program, duration_cycles):
        self.simulated.append((program, duration_cycles))

    def stop_current_job(self):
        self.stopped = True


class FakeRecipe(ExperimentRecipe):
    name = "fake"
    axis_policies = {"tau": "qua", "B_amp": "host"}

    def __init__(self, reject_first=False):
        self.reject_first = reject_first
        self.acquire_calls = []

    def build_program(self, context):
        return ProgramBundle(
            program=(context.block.index, context.attempt),
            metadata={"block": context.block.index},
        )

    def acquire(self, job, context, timeout_s):
        self.acquire_calls.append((context.block.index, context.attempt, timeout_s))
        if self.reject_first and context.block.index == 0 and context.attempt == 0:
            return AcquisitionResult(None, valid=False, invalid_reason="failed CRC")
        count = context.block.qua_points
        batch = MeasurementBatch(
            xr.Dataset({"signal": ("record", np.arange(count) + 2)}),
            raw_events={
                "SPCM1": [np.asarray([context.block.index, index]) for index in range(count)]
            },
        )
        return AcquisitionResult(batch)

    def analyze(self, dataset, experiment, thresholds):
        return xr.Dataset({"centered": dataset["signal"] - dataset["signal"].mean()})


class ObservationServices(RunServices):
    def __init__(self):
        self.blocks = []
        self.final_status = None

    def before_block(self, experiment, block, control):
        self.blocks.append(block.index)
        return {"laser_frequency": 484.12 + block.index}

    def after_run(self, experiment, status):
        self.final_status = status


class CancellingServices(RunServices):
    def before_block(self, experiment, block, control):
        control.request_cancel()
        return {}


def experiment(debug=False):
    return ExperimentSpec(
        recipe="fake",
        name="engine test",
        scan_axes=(
            ScanAxis("B_amp", (100, 110), unit="mT", execution="host"),
            ScanAxis("tau", (10, 20), unit="ns", execution="qua"),
        ),
        readout=(ReadoutStep("result", "csr_accept", "signal"),),
        execution=ExecutionPolicy(debug_simulation=debug, max_retries_per_block=1),
    )


class ExecutionEngineTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_directory = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_engine(self, recipe, services=None):
        machine = FakeQuantumMachine()
        engine = NuclearExperimentEngine(
            recipes=RecipeRegistry((recipe,)),
            thresholds=ThresholdRegistry(),
            quantum_machine=machine,
            output_directory=self.output_directory,
            services=services,
        )
        return engine, machine

    def test_complete_run_retries_invalid_block_and_persists_all_data(self):
        recipe = FakeRecipe(reject_first=True)
        services = ObservationServices()
        engine, machine = self.make_engine(recipe, services)

        result = engine.run(experiment(), queue_item_id="queue-1")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.records, 4)
        self.assertEqual(len(machine.executed), 3)
        self.assertEqual(services.blocks, [0, 1])
        self.assertEqual(services.final_status, "completed")
        reopened = NuclearDataset.open(result.run_file)
        self.assertEqual(reopened.dataset["B_amp"].values.tolist(), [100, 100, 110, 110])
        self.assertEqual(reopened.dataset["tau"].values.tolist(), [10, 20, 10, 20])
        self.assertEqual(
            reopened.dataset["laser_frequency"].values.tolist(),
            [484.12, 484.12, 485.12, 485.12],
        )
        self.assertIn("signal_csr_accept_accepted", reopened.analysis)
        self.assertIn("centered", reopened.analysis)
        self.assertEqual(reopened.queue_item["status"], "completed")
        self.assertTrue(reopened.provenance.recipe_source)
        with h5py.File(result.run_file, "r") as handle:
            self.assertIn("block_00000000", handle["programs"])
            self.assertIn(
                "attempt_00000001", handle["programs/block_00000000"]
            )

    def test_debug_mode_simulates_each_block_without_executing(self):
        spec = replace(experiment(debug=True), readout=())
        engine, machine = self.make_engine(FakeRecipe())

        result = engine.run(spec)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(machine.executed), 0)
        self.assertEqual(len(machine.simulated), 2)
        self.assertTrue(NuclearDataset.open(result.run_file).dataset.simulation_completed.all())

    def test_cooperative_cancel_finalizes_a_recoverable_hdf5_file(self):
        engine, machine = self.make_engine(FakeRecipe(), CancellingServices())

        result = engine.run(experiment(), queue_item_id="cancelled-item")

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.records, 0)
        reopened = NuclearDataset.open(result.run_file)
        self.assertEqual(reopened.queue_item["status"], "cancelled")

    def test_unknown_recipe_fails_before_creating_a_file(self):
        engine, _machine = self.make_engine(FakeRecipe())
        unknown = replace(experiment(), recipe="missing")

        result = engine.run(unknown)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.run_file, "")
        self.assertEqual(list(self.output_directory.glob("*.h5")), [])


if __name__ == "__main__":
    unittest.main()
