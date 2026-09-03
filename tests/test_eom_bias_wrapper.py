import unittest

from qudi.logic.eom_bias_wrapper import calculate_wrap, calculate_wrap_preview


class CalculateWrapTest(unittest.TestCase):
    def test_value_inside_safe_range_is_unchanged(self):
        decision = calculate_wrap(0.2)

        self.assertFalse(decision.should_wrap)
        self.assertEqual(decision.target, 0.2)
        self.assertEqual(decision.periods, 0)

    def test_upper_edge_wraps_down_by_two_vpi(self):
        decision = calculate_wrap(0.58)

        self.assertTrue(decision.should_wrap)
        self.assertAlmostEqual(decision.target, -0.14)
        self.assertEqual(decision.periods, -1)

    def test_lower_edge_wraps_up_by_two_vpi(self):
        decision = calculate_wrap(-0.58)

        self.assertTrue(decision.should_wrap)
        self.assertAlmostEqual(decision.target, 0.14)
        self.assertEqual(decision.periods, 1)

    def test_safe_boundary_is_not_wrapped(self):
        self.assertFalse(calculate_wrap(0.55).should_wrap)
        self.assertFalse(calculate_wrap(-0.55).should_wrap)

    def test_target_is_safe_and_optically_equivalent(self):
        current = 1.2
        decision = calculate_wrap(current)

        self.assertTrue(decision.should_wrap)
        self.assertGreaterEqual(decision.target, -0.55)
        self.assertLessEqual(decision.target, 0.55)
        self.assertAlmostEqual(
            decision.target - current,
            decision.periods * 0.72,
        )

    def test_reports_when_no_equivalent_safe_target_exists(self):
        decision = calculate_wrap(
            0.5,
            vpi=0.36,
            min_value=-0.1,
            max_value=0.1,
            margin=0.0,
        )

        self.assertFalse(decision.should_wrap)
        self.assertEqual(
            decision.reason,
            "no_equivalent_target_in_safe_range",
        )

    def test_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            calculate_wrap(0.0, vpi=0.0)
        with self.assertRaises(ValueError):
            calculate_wrap(0.0, min_value=0.6, max_value=-0.6)
        with self.assertRaises(ValueError):
            calculate_wrap(0.0, margin=0.6)

    def test_preview_contains_live_value_and_safe_target(self):
        preview = calculate_wrap_preview(0.58)

        self.assertEqual(preview["current"], 0.58)
        self.assertTrue(preview["should_wrap"])
        self.assertAlmostEqual(preview["target"], -0.14)
        self.assertEqual(preview["periods"], -1)
        self.assertEqual(preview["period"], 0.72)
        self.assertAlmostEqual(preview["safe_minimum"], -0.55)
        self.assertAlmostEqual(preview["safe_maximum"], 0.55)


if __name__ == "__main__":
    unittest.main()
