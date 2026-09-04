import unittest

from qudi.logic.nuclear_ops.models import (
    ExecutionPolicy,
    ExperimentSpec,
    ReadoutStep,
    ScanAxis,
)
from qudi.logic.nuclear_ops.thresholds import (
    ReadoutThresholdProfile,
    ThresholdRegistry,
    ThresholdRule,
)

from .helpers import experiment_spec


class ExperimentModelTest(unittest.TestCase):
    def test_experiment_round_trip(self):
        original = experiment_spec()
        restored = ExperimentSpec.from_dict(original.to_dict())

        self.assertEqual(restored, original)
        self.assertEqual(restored.expected_points, 4)

    def test_duplicate_scan_axis_is_rejected(self):
        axis = ScanAxis("tau", (1, 2), unit="ns")
        with self.assertRaisesRegex(ValueError, "unique"):
            ExperimentSpec(recipe="rabi", name="Rabi", scan_axes=(axis, axis))

    def test_empty_axis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no values"):
            ScanAxis("tau", ())

    def test_readout_repetitions_must_be_positive_integer(self):
        with self.assertRaises(ValueError):
            ReadoutStep("ssr", "ssr_e1", "state", repetitions=0)
        with self.assertRaises(TypeError):
            ReadoutStep("ssr", "ssr_e1", "state", repetitions=1.5)

    def test_execution_policy_rejects_partial_or_invalid_quiet_hours(self):
        with self.assertRaisesRegex(ValueError, "Both quiet-hours"):
            ExecutionPolicy(quiet_hours_start="22:00")
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            ExecutionPolicy(quiet_hours_start="25:00", quiet_hours_end="06:00")


class ThresholdRegistryTest(unittest.TestCase):
    def test_default_profile_has_all_global_readout_thresholds(self):
        registry = ThresholdRegistry()
        profile = registry.get()

        self.assertEqual(
            set(profile.rules),
            {"crc_accept", "crc_repump", "csr_accept", "ssr_e1", "ssr_e2"},
        )

    def test_registry_round_trip_and_snapshot(self):
        registry = ThresholdRegistry.from_dict(ThresholdRegistry().to_dict())
        snapshot = registry.snapshot_for_experiment(experiment_spec())

        self.assertEqual(snapshot.profile.resolve("csr_accept").counts, 1.0)
        self.assertEqual(snapshot.profile.resolve("ssr_e1").comparison, ">")

    def test_unknown_experiment_threshold_is_rejected_before_execution(self):
        original = experiment_spec().to_dict()
        original["readout"][0]["threshold_ref"] = "missing_threshold"

        with self.assertRaisesRegex(KeyError, "does not exist"):
            ThresholdRegistry().snapshot_for_experiment(ExperimentSpec.from_dict(original))

    def test_profile_updates_must_increment_version(self):
        registry = ThresholdRegistry()
        current = registry.get()
        replacement = ReadoutThresholdProfile(
            name=current.name,
            version=current.version,
            rules=current.rules,
        )
        with self.assertRaisesRegex(ValueError, "higher version"):
            registry.put(replacement)

    def test_previous_profile_versions_remain_resolvable(self):
        registry = ThresholdRegistry()
        current = registry.get()
        updated_rules = dict(current.rules)
        updated_rules["ssr_e1"] = ThresholdRule(">", 4)
        registry.put(
            ReadoutThresholdProfile(
                name=current.name,
                version=2,
                rules=updated_rules,
            )
        )

        self.assertEqual(registry.get("default").version, 2)
        self.assertEqual(registry.get("default", version=1).resolve("ssr_e1").counts, 1)
        self.assertEqual(registry.versions("default"), (1, 2))
        restored = ThresholdRegistry.from_dict(registry.to_dict())
        self.assertEqual(restored.versions("default"), (1, 2))

    def test_incomplete_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing rules"):
            ReadoutThresholdProfile(
                name="broken",
                rules={"crc_accept": ThresholdRule(">", 2)},
            )


if __name__ == "__main__":
    unittest.main()
