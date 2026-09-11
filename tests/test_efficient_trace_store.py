"""Run with python -m unittest discover -s tests -p 'test_efficient_trace_store.py'."""
import importlib.util
import ast
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from typing import Any

import numpy as np
import pandas as pd

MODULE = Path(__file__).resolve().parents[1] / 'src/qudi/logic/efficient_trace_store.py'
spec = importlib.util.spec_from_file_location('efficient_trace_store', MODULE)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


class EfficientTraceStorageTests(unittest.TestCase):
    def test_opt_in_writes_efficient_store_and_compatibility_hdf(self):
        # Extract the actual method to exercise routing without importing Qt/hardware.
        source = ast.parse((MODULE.parent / 'NuclearOPs.py').read_text())
        nuclear = next(node for node in source.body
                       if isinstance(node, ast.ClassDef) and node.name == 'NuclearOPs')
        method = next(node for node in nuclear.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'save_measurement_data')
        base = type('Base', (), {'save_measurement_data': Mock()})
        wrapper = ast.ClassDef(name='Runner', bases=[ast.Name(id='Base', ctx=ast.Load())],
                               keywords=[], body=[method], decorator_list=[])
        tree = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
        backend = Mock()
        namespace = {'Base': base, 'efficient_trace_store': backend, 'Any': Any, 'np': np}
        exec(compile(tree, 'save-routing', 'exec'), namespace)
        runner = namespace['Runner']()
        runner.save_trace_efficient = False
        runner.save_measurement_data(notify=True)
        base.save_measurement_data.assert_called_once_with(notify=True)
        backend.save_results.assert_not_called()
        runner.save_trace_efficient = True
        runner.save_dir = 'measurement'
        runner.data = Mock(df=pd.DataFrame({'trace': ['traces/one.npy']}),
                           parameter_names=[], observation_names=['trace'])
        runner.save_measurement_data()
        backend.save_results.assert_called_once_with(
            'measurement', runner.data.df, [], ['trace'])
        self.assertEqual(base.save_measurement_data.call_count, 2)

        runner.data = Mock(df=pd.DataFrame({'trace': [np.arange(4)]}),
                           parameter_names=[], observation_names=['trace'])
        with self.assertRaises(RuntimeError):
            runner.save_measurement_data()

    def test_roundtrip_and_moved_folder(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'measurement'
            raw = np.arange(20000, dtype=np.int16)
            settings = {'analyze_sequence': [['result', '>', np.int64(3), 1, 0, 1]],
                        'number_of_simultaneous_measurements': 2}
            reference = store.write_trace(folder, raw, settings)
            frame = pd.DataFrame({'sweep': [0, 1], 'trace': [reference, reference],
                                  'result_0': [0.125, np.nan],
                                  'start_time': pd.to_datetime(['2026-01-01', '2026-01-02'])})
            store.save_results(folder, frame, ['sweep'], ['trace', 'result_0', 'start_time'])
            moved = Path(root) / 'moved'
            shutil.move(folder, moved)
            restored, metadata = store.load_results(moved)
            pd.testing.assert_frame_equal(frame, restored)
            loaded, analysis = store.load_trace(moved, reference)
            self.assertIsInstance(loaded, np.memmap)
            np.testing.assert_array_equal(raw, loaded)
            self.assertEqual(analysis['number_of_simultaneous_measurements'], 2)
            self.assertEqual(metadata['trace_column'], 'trace')
            self.assertEqual(len(list((moved / 'traces').glob('*.npy'))), 1)

    def test_failed_checkpoint_preserves_previous_results(self):
        with tempfile.TemporaryDirectory() as root:
            frame = pd.DataFrame({'result': [1.0]})
            store.save_results(root, frame, [], ['result'])
            previous = (Path(root) / 'results.json').read_bytes()
            replace = store.os.replace
            def fail_results(source, target):
                if Path(target).name == 'results.json':
                    raise OSError('simulated disk failure')
                return replace(source, target)
            with patch.object(store.os, 'replace', side_effect=fail_results):
                with self.assertRaises(OSError):
                    store.save_results(root, pd.DataFrame({'result': [2.0]}), [], ['result'])
            self.assertEqual((Path(root) / 'results.json').read_bytes(), previous)
            self.assertFalse((Path(root) / 'results.json.tmp').exists())

    def test_unique_traces_and_no_partial_array_on_error(self):
        with tempfile.TemporaryDirectory() as root:
            a = store.write_trace(root, np.arange(10), {})
            b = store.write_trace(root, np.arange(10), {})
            self.assertNotEqual(a, b)
            with self.assertRaises(TypeError):
                store.write_trace(root, np.arange(10), {'invalid': object()})
            self.assertEqual(len(list((Path(root) / 'traces').glob('*.npy'))), 2)
            self.assertEqual(len(list((Path(root) / 'traces').glob('*.tmp'))), 0)
            with self.assertRaises(ValueError):
                store.load_trace(root, '../outside.npy')


if __name__ == '__main__':
    unittest.main()
