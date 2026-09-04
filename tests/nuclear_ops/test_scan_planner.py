import unittest

from qudi.logic.nuclear_ops.models import AxisExecution, ExperimentSpec, ScanAxis
from qudi.logic.nuclear_ops.scan_planner import ScanPlanner


class ScanPlannerTest(unittest.TestCase):
    def test_plans_unlimited_qua_axes_without_two_axis_legacy_limit(self):
        spec = ExperimentSpec(
            recipe="multi_axis",
            name="Multi axis",
            scan_axes=tuple(
                ScanAxis("axis_{}".format(index), range(2), execution="qua")
                for index in range(4)
            ),
        )

        plan = ScanPlanner().plan(spec)

        self.assertEqual(plan.total_points, 16)
        self.assertEqual(plan.program_executions, 1)
        self.assertEqual(plan.blocks[0].qua_points, 16)

    def test_host_and_recompile_axes_create_deterministic_outer_blocks(self):
        spec = ExperimentSpec(
            recipe="rabi",
            name="Rabi",
            scan_axes=(
                ScanAxis("field", (100, 200), unit="mT", execution="host"),
                ScanAxis("transition", ("left", "right"), execution="recompile"),
                ScanAxis("tau", (10, 20, 30), unit="ns", execution="qua"),
            ),
        )

        plan = ScanPlanner().plan(spec)

        self.assertEqual(plan.total_points, 12)
        self.assertEqual(plan.program_executions, 4)
        self.assertEqual(plan.blocks[0].host_values, {"field": 100})
        self.assertEqual(plan.blocks[0].recompile_values, {"transition": "left"})
        self.assertEqual(plan.blocks[-1].host_values, {"field": 200})
        self.assertEqual(plan.blocks[-1].recompile_values, {"transition": "right"})

    def test_auto_axis_requires_an_explicit_recipe_policy(self):
        spec = ExperimentSpec(
            recipe="rabi",
            name="Rabi",
            scan_axes=(ScanAxis("tau", (10, 20)),),
        )

        with self.assertRaisesRegex(ValueError, "did not provide a policy"):
            ScanPlanner().plan(spec)

        plan = ScanPlanner({"tau": AxisExecution.QUA}).plan(spec)
        self.assertEqual(plan.blocks[0].qua_axes[0].execution, AxisExecution.QUA)

    def test_plan_covers_every_point_once(self):
        spec = ExperimentSpec(
            recipe="mixed",
            name="Mixed",
            scan_axes=(
                ScanAxis("host", (1, 2), execution="host"),
                ScanAxis("qua_a", (1, 2, 3), execution="qua"),
                ScanAxis("compile", (1, 2), execution="recompile"),
                ScanAxis("qua_b", (1, 2, 3, 4), execution="qua"),
            ),
        )

        plan = ScanPlanner().plan(spec)

        self.assertEqual(sum(block.qua_points for block in plan.blocks), plan.total_points)
        self.assertEqual(plan.total_points, 48)


if __name__ == "__main__":
    unittest.main()
