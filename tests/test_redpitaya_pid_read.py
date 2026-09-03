import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_hardware_module():
    fake_modules = {
        'pyrpl': types.ModuleType('pyrpl'),
        'PySide2': types.ModuleType('PySide2'),
        'qudi': types.ModuleType('qudi'),
        'qudi.core': types.ModuleType('qudi.core'),
        'qudi.core.module': types.ModuleType('qudi.core.module'),
        'qudi.core.configoption': types.ModuleType('qudi.core.configoption'),
        'qudi.core.statusvariable': types.ModuleType('qudi.core.statusvariable'),
        'qudi.interface': types.ModuleType('qudi.interface'),
        'qudi.interface.redpitaya_interface': types.ModuleType(
            'qudi.interface.redpitaya_interface'
        ),
    }

    class FakeBase:
        pass

    class FakeInterface:
        pass

    fake_modules['pyrpl'].Pyrpl = object
    fake_modules['PySide2'].QtCore = types.SimpleNamespace()
    fake_modules['qudi.core.module'].Base = FakeBase
    fake_modules['qudi.core.configoption'].ConfigOption = (
        lambda *_args, **_kwargs: None
    )
    fake_modules['qudi.core.statusvariable'].StatusVar = (
        lambda *_args, **_kwargs: None
    )
    fake_modules[
        'qudi.interface.redpitaya_interface'
    ].RedPitayaInterface = FakeInterface

    path = (
        Path(__file__).resolve().parents[1]
        / 'src' / 'qudi' / 'hardware' / 'redpitaya'
        / 'redpitaya_pyrpl.py'
    )
    spec = importlib.util.spec_from_file_location('_pid_read_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)
    return module


class ReadPidIntegratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_hardware_module()

    def setUp(self):
        self.hardware = self.module.RedPitayaPyrpl.__new__(
            self.module.RedPitayaPyrpl
        )
        self.hardware._pid0 = types.SimpleNamespace(
            ival=-0.1,
            current_output_signal=-0.1,
            min_voltage=-0.6,
            max_voltage=0.6,
        )
        self.hardware._pid1 = types.SimpleNamespace(
            ival=0.25,
            current_output_signal=0.2,
            min_voltage=-0.5,
            max_voltage=0.5,
        )
        self.hardware._pid2 = types.SimpleNamespace(
            ival=0.5,
            current_output_signal=0.4,
            min_voltage=-0.4,
            max_voltage=0.4,
        )
        self.hardware.get_pyrpl = lambda: object()

    def test_reads_selected_pid_without_writing(self):
        self.assertEqual(self.hardware.get_pid_integrator(0), -0.1)
        self.assertEqual(self.hardware.get_pid_integrator(1), 0.25)
        self.assertEqual(self.hardware.get_pid_integrator(2), 0.5)

        self.assertEqual(self.hardware._pid0.ival, -0.1)
        self.assertEqual(self.hardware._pid1.ival, 0.25)
        self.assertEqual(self.hardware._pid2.ival, 0.5)

    def test_rejects_invalid_channel(self):
        with self.assertRaises(ValueError):
            self.hardware.get_pid_integrator(3)
        with self.assertRaises(ValueError):
            self.hardware.get_pid_wrap_state(3)

    def test_reports_missing_connection(self):
        self.hardware.get_pyrpl = lambda: None
        with self.assertRaises(RuntimeError):
            self.hardware.get_pid_integrator(0)
        with self.assertRaises(RuntimeError):
            self.hardware.get_pid_wrap_state(0)

    def test_reads_integrator_and_limited_output_without_writing(self):
        state = self.hardware.get_pid_wrap_state(1)

        self.assertEqual(
            state,
            {
                'integrator': 0.25,
                'pid_output': 0.2,
                'pid_minimum': -0.5,
                'pid_maximum': 0.5,
            },
        )
        self.assertEqual(self.hardware._pid1.ival, 0.25)
        self.assertEqual(self.hardware._pid1.current_output_signal, 0.2)


if __name__ == '__main__':
    unittest.main()
