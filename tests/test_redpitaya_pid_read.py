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

    class FakeBoundSignal:
        def __init__(self):
            self._slot = None

        def connect(self, slot, _connection_type=None):
            self._slot = slot

        def emit(self, request):
            self._slot(request)

    class FakeSignal:
        def __set_name__(self, _owner, name):
            self._storage_name = f'_fake_signal_{name}'

        def __get__(self, instance, _owner):
            if instance is None:
                return self
            signal = getattr(instance, self._storage_name, None)
            if signal is None:
                signal = FakeBoundSignal()
                setattr(instance, self._storage_name, signal)
            return signal

    class FakeThread:
        current = object()

        @classmethod
        def currentThread(cls):
            return cls.current

    class FakeQObject:
        def __init__(self):
            self._thread = FakeThread.current

        def thread(self):
            return self._thread

    def fake_slot(*_args, **_kwargs):
        return lambda function: function

    fake_modules['pyrpl'].Pyrpl = object
    fake_modules['PySide2'].QtCore = types.SimpleNamespace(
        QObject=FakeQObject,
        QThread=FakeThread,
        Signal=lambda *_args, **_kwargs: FakeSignal(),
        Slot=fake_slot,
        Qt=types.SimpleNamespace(QueuedConnection=object()),
    )
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
            p=0.0,
            min_voltage=-0.6,
            max_voltage=0.6,
            current_output_signal=-0.1,
        )
        self.hardware._pid1 = types.SimpleNamespace(
            ival=0.25,
            p=0.1,
            min_voltage=-0.5,
            max_voltage=0.5,
            current_output_signal=0.3,
        )
        self.hardware._pid2 = types.SimpleNamespace(
            ival=0.5,
            p=-0.2,
            min_voltage=-0.4,
            max_voltage=0.4,
            current_output_signal=0.4,
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

    def test_reads_complete_wrap_state_without_writing(self):
        state = self.hardware.get_pid_wrap_state(1)

        self.assertEqual(
            state,
            {
                'integrator': 0.25,
                'proportional_gain': 0.1,
                'pid_minimum': -0.5,
                'pid_maximum': 0.5,
            },
        )
        self.assertEqual(self.hardware._pid1.ival, 0.25)

    def test_reads_pid_output_snapshot_without_writing(self):
        snapshot = self.hardware.get_pid_output_snapshot(1)

        self.assertEqual(
            snapshot,
            {
                'integrator_before': 0.25,
                'output': 0.3,
                'integrator_after': 0.25,
                'integrator_change_during_read': 0.0,
                'proportional_gain': 0.1,
                'pid_minimum': -0.5,
                'pid_maximum': 0.5,
            },
        )
        self.assertEqual(self.hardware._pid1.ival, 0.25)
        self.assertEqual(self.hardware._pid1.current_output_signal, 0.3)

    def test_checked_write_updates_integrator(self):
        result = self.hardware.set_pid_integrator_checked(
            pid_channel=0,
            expected_current=-0.1,
            target=0.12,
        )

        self.assertAlmostEqual(self.hardware._pid0.ival, 0.12)
        self.assertAlmostEqual(result['previous_integrator'], -0.1)
        self.assertAlmostEqual(result['written_integrator'], 0.12)

    def test_checked_write_rejects_nonzero_proportional_gain(self):
        with self.assertRaisesRegex(RuntimeError, "proportional gain"):
            self.hardware.set_pid_integrator_checked(
                pid_channel=1,
                expected_current=0.25,
                target=-0.1,
            )
        self.assertEqual(self.hardware._pid1.ival, 0.25)

    def test_checked_write_rejects_stale_integrator_value(self):
        with self.assertRaisesRegex(RuntimeError, "ival has changed"):
            self.hardware.set_pid_integrator_checked(
                pid_channel=0,
                expected_current=-0.2,
                target=0.12,
            )
        self.assertEqual(self.hardware._pid0.ival, -0.1)

    def test_checked_write_rejects_target_outside_pid_limits(self):
        with self.assertRaisesRegex(ValueError, "outside the configured PID limits"):
            self.hardware.set_pid_integrator_checked(
                pid_channel=0,
                expected_current=-0.1,
                target=0.7,
            )
        self.assertEqual(self.hardware._pid0.ival, -0.1)

    def test_checked_write_rejects_non_finite_pid_state(self):
        self.hardware._pid0.ival = float('nan')

        with self.assertRaisesRegex(RuntimeError, "non-finite PID state"):
            self.hardware.set_pid_integrator_checked(
                pid_channel=0,
                expected_current=-0.1,
                target=0.12,
            )

    def test_checked_write_rejects_invalid_pid_limits(self):
        self.hardware._pid0.min_voltage = 0.6
        self.hardware._pid0.max_voltage = -0.6

        with self.assertRaisesRegex(RuntimeError, "invalid PID limits"):
            self.hardware.set_pid_integrator_checked(
                pid_channel=0,
                expected_current=-0.1,
                target=0.12,
            )
        self.assertEqual(self.hardware._pid0.ival, -0.1)


if __name__ == '__main__':
    unittest.main()
