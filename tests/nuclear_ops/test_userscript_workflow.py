import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
from qudi.hardware.timetagger.nuclear_counter import GateDecoder, NuclearTimeTaggerCounter
from qudi.logic.nuclear_ops.userscripts import specification, UserScriptRecipe, source_archive
from qudi.logic.nuclear_ops.setup_parameters import SetupRegistry
from qudi.logic.nuclear_ops.recipes import RecipeRegistry, RecipeContext
from qudi.logic.nuclear_ops.scan_planner import ScanPlanner
from qudi.logic.nuclear_ops.execution_engine import NuclearExperimentEngine, ExecutionCallbacks, RunServices
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry
from qudi.logic.nuclear_ops.hdf5_store import NuclearDataset
from tests.nuclear_ops.test_offline import Machine


class CounterHarness:
    dummy_mode = True
    dummy_seed = 42
    sigCounterUpdated = SimpleNamespace(emit=lambda x: None)
    arm = NuclearTimeTaggerCounter.arm
    stop = NuclearTimeTaggerCounter.stop
    read_streams = NuclearTimeTaggerCounter.read_streams
    _dummy_chunk = NuclearTimeTaggerCounter._dummy_chunk


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_marker_decoder_preserves_raw_times_across_chunks(self):
        d = GateDecoder(['result_counts'], 2, 1, 1, 2, 3)
        d.feed([100, 125], [2, 1], [0, 0])
        d.feed([140, 150, 200, 220, 250], [1, 3, 2, 1, 3], [0]*5)
        result = d.streams()
        np.testing.assert_array_equal(result['result_counts_shots'], [[2], [1]])
        np.testing.assert_array_equal(result['_raw_events']['result'][0], [25, 40, 20])
        np.testing.assert_array_equal(result['_raw_lengths']['result'], [[2, 1]])

    def test_marker_errors_do_not_silently_shift_shots(self):
        d = GateDecoder(['result_counts'], 1, 1, 1, 2, 3)
        with self.assertRaisesRegex(RuntimeError, 'overflow'):
            d.feed([1], [1], [2])
        d.feed([10], [2], [0])
        with self.assertRaisesRegex(RuntimeError, 'Missing end'):
            d.feed([20], [2], [0])

    def test_setup_live_revisions_and_userscript_frozen_in_hdf5(self):
        setup = SetupRegistry(Path(self.tmp.name)/'setup.h5')
        script = '''def pulses(q, p):
    q.mw(p["pulse_length"])
NAME = "frozen script"
SWEEPS = {"repeat": [0, 1], "pulse_length": [40, 80]}
AXIS_EXECUTION = {"repeat": "recompile", "pulse_length": "qua"}
PARAMETERS = {"integrations": 2}
'''
        spec = specification(script, 'experiment.py')
        registry = RecipeRegistry([UserScriptRecipe()])
        services = RunServices(); services.external_counter = CounterHarness()
        def live_edit(data):
            values = setup.snapshot()['values']; values['mw_amplitude'] = .4
            setup.update(values)
        engine = NuclearExperimentEngine(registry, ThresholdRegistry(), Machine(), self.tmp.name,
            services=services, setup_provider=setup.snapshot, callbacks=ExecutionCallbacks(data=live_edit))
        result = engine.run(spec)
        self.assertEqual(result.status, 'completed', result.error)
        run = NuclearDataset.open(result.run_file)
        self.assertEqual(run.store.load_section('experiment')['metadata']['userscript']['source'], script)
        np.testing.assert_array_equal(run.dataset.setup_revision, [1, 1, 2, 2])
        self.assertEqual(run.dataset.attrs['count_source'], 'Swabian')
        self.assertEqual(run.dataset.attrs['raw_time_unit'], 'ps')
        np.testing.assert_array_equal(run.dataset.result_counts_shots, run.dataset.result_tag_lengths)
        restored = SetupRegistry(Path(self.tmp.name)/'setup.h5')
        self.assertEqual(restored.snapshot()['values']['mw_amplitude'], .4)

    def test_archive_contains_full_shared_implementation(self):
        files = {f['path']: f for f in source_archive()}
        self.assertIn('logic/nuclear_ops/setup_parameters.py', files)
        self.assertIn('hardware/OPX/configuration.py', files)
        self.assertIn('def read_streams', files['hardware/timetagger/nuclear_counter.py']['source'])

    def test_all_userscripts_generate_crc_only_qm_counting(self):
        try:
            from qm import generate_qua_script
        except ImportError:
            self.skipTest('QM SDK not installed')
        defaults = SetupRegistry(Path(self.tmp.name)/'setup.h5').snapshot()['values']
        folder = Path(__file__).parents[2]/'src/qudi/UserScripts/nuclear_ops'
        for path in folder.glob('*.py'):
            with self.subTest(script=path.name):
                spec = specification(path.read_text(), str(path))
                spec = replace(spec, parameters=dict(defaults, **spec.parameters))
                recipe = UserScriptRecipe(); recipe.validate(spec)
                ctx = RecipeContext(spec, ScanPlanner(recipe.axis_policies).plan(spec).blocks[0],
                                    ThresholdRegistry().snapshot_for_experiment(spec))
                source = generate_qua_script(recipe.build_program(ctx).program)
                self.assertEqual(source.count('time_tagging.analog'), 1)
                self.assertIn('Gate_Trigger', source)
                self.assertIn('Memory_Trigger', source)


if __name__ == '__main__':
    unittest.main()
