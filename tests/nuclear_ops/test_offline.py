import importlib.util
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from qudi.logic.nuclear_ops.dummy import DummyJob
from qudi.logic.nuclear_ops.models import ExperimentSpec, ExecutionPolicy
from qudi.logic.nuclear_ops.recipes import RecipeRegistry, RecipeContext
from qudi.logic.nuclear_ops.scan_planner import ScanPlanner
from qudi.logic.nuclear_ops.snv_qua_recipes import register_recipes
from qudi.logic.nuclear_ops.extended_recipes import register_recipes as register_extended
from qudi.logic.nuclear_ops.templates import experiment_template
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry
from qudi.logic.nuclear_ops.execution_engine import NuclearExperimentEngine, ExecutionCallbacks, RunServices
from qudi.logic.nuclear_ops.hdf5_store import NuclearDataset
from qudi.logic.nuclear_ops.fitting import reanalyze_file


class Machine:
    dummy_mode = True
    job = None
    def execute(self, program):
        self.job = DummyJob(program, seed=42, delay_s=.02)
        return self.job
    def stop_current_job(self):
        if self.job is not None:
            self.job.halt()


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = RecipeRegistry()
        register_recipes(self.registry); register_extended(self.registry)
        self.thresholds = ThresholdRegistry()

    def spec(self, name):
        data = experiment_template(name)
        data['scan_axes'][0]['values'] = ['e1', 'e2'] if name == 'ssr_calibration' else [0]
        data['parameters']['integrations'] = 3
        return ExperimentSpec.from_dict(data)

    def engine(self, **kwargs):
        return NuclearExperimentEngine(self.registry, self.thresholds, Machine(), self.temp.name, **kwargs)

    def test_all_twelve_recipes_save_real_schema_and_raw_shots(self):
        self.assertEqual(len(self.registry.names), 12)
        for name in self.registry.names:
            with self.subTest(recipe=name):
                spec = self.spec(name)
                result = self.engine().run(spec)
                self.assertEqual(result.status, 'completed', result.error)
                run = NuclearDataset.open(result.run_file)
                self.assertEqual(run.dataset.sizes['record'], spec.expected_points)
                self.assertEqual(run.dataset.sizes['integration'], 3)
                self.assertIn('result_counts_ssr_e1_accepted', run.analysis)
                lengths = run.dataset.result_tag_lengths.values[0]
                self.assertEqual(len(run.store.load_raw_events('result', 0)), sum(lengths))
                reanalyze_file(result.run_file, self.registry)

    def test_raw_disabled_keeps_counts_but_no_tags(self):
        spec = replace(self.spec('t1'), execution=ExecutionPolicy(save_raw_events=False))
        result = self.engine().run(spec)
        self.assertEqual(result.status, 'completed', result.error)
        self.assertNotIn('result_tag_lengths', NuclearDataset.open(result.run_file).dataset)

    def test_pause_then_cancel_unblocks_and_finalizes(self):
        paused = threading.Event()
        engine = self.engine(callbacks=ExecutionCallbacks(paused=paused.set))
        engine.pause()
        results = []
        thread = threading.Thread(target=lambda: results.append(engine.run(self.spec('t1'))))
        thread.start()
        self.assertTrue(paused.wait(3))
        engine.cancel(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, 'cancelled')

    def test_external_counter_counts_replace_qm_counts_and_stop(self):
        class Counter:
            stopped = False
            def arm(self, context):
                self.armed = True
            def read_streams(self, context, control, timeout_s):
                self.assert_armed = self.armed
                shots = np.full((3, context.block.qua_points), 777)
                return {'result_counts': shots.mean(axis=0), 'result_counts_shots': shots}
            def stop(self):
                self.stopped = True
        services = RunServices(); services.external_counter = Counter()
        spec = replace(self.spec('t1'), execution=ExecutionPolicy(acquisition_mode='external_counter', save_raw_events=False))
        result = self.engine(services=services).run(spec)
        self.assertEqual(result.status, 'completed', result.error)
        self.assertTrue(services.external_counter.stopped)
        np.testing.assert_array_equal(NuclearDataset.open(result.run_file).dataset.result_counts, 777)

    def test_external_counter_missing_fails_explicitly(self):
        spec = replace(self.spec('t1'), execution=ExecutionPolicy(acquisition_mode='external_counter'))
        result = self.engine().run(spec)
        self.assertEqual(result.status, 'failed')
        self.assertIn('NuclearCounterInterface', result.error)

    @unittest.skipUnless(importlib.util.find_spec("qm"), "QM SDK not installed")
    def test_native_programs_include_tags_and_external_markers(self):
        from qm import generate_qua_script
        for name in self.registry.names:
            with self.subTest(recipe=name):
                spec = replace(self.spec(name), execution=ExecutionPolicy(acquisition_mode='external_counter'))
                recipe = self.registry.get(name)
                recipe.validate(spec)
                block = ScanPlanner(recipe.axis_policies).plan(spec).blocks[0]
                ctx = RecipeContext(spec, block, self.thresholds.snapshot_for_experiment(spec))
                source = generate_qua_script(recipe.build_program(ctx).program)
                self.assertIn('result_tags', source)
                self.assertIn('Gate_Trigger', source)
                self.assertIn('Memory_Trigger', source)


if __name__ == '__main__':
    unittest.main()
