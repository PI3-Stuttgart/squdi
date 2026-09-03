import unittest

from qudi.logic.eom_bias_wrapper import (
    calculate_pid_wrap_preview,
    calculate_wrap,
    calculate_wrap_preview,
)


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

    def test_refuses_integrator_windup_outside_output_range(self):
        for current in (-4.0, 4.0):
            decision = calculate_wrap(current)

            self.assertFalse(decision.should_wrap)
            self.assertEqual(decision.target, current)
            self.assertEqual(decision.periods, 0)
            self.assertEqual(
                decision.reason,
                "integrator_outside_output_range",
            )

    def test_output_limits_wrap_to_equivalent_safe_values(self):
        self.assertAlmostEqual(
            calculate_wrap(-0.6).target,
            0.12,
        )
        self.assertAlmostEqual(
            calculate_wrap(0.6).target,
            -0.12,
        )

    def test_reports_when_no_equivalent_safe_target_exists(self):
        decision = calculate_wrap(
            0.09,
            vpi=0.36,
            min_value=-0.1,
            max_value=0.1,
            margin=0.05,
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
        self.assertFalse(preview["recovery_required"])

    def test_preview_proposes_recovery_from_lower_windup(self):
        preview = calculate_wrap_preview(-4.0)

        self.assertFalse(preview["should_wrap"])
        self.assertEqual(
            preview["reason"],
            "integrator_outside_output_range",
        )
        self.assertTrue(preview["recovery_required"])
        self.assertAlmostEqual(preview["saturated_output"], -0.6)
        self.assertTrue(preview["recovery_available"])
        self.assertAlmostEqual(preview["recovery_target"], 0.12)
        self.assertEqual(preview["recovery_periods"], 1)
        self.assertTrue(preview["recovery_assumes_p_zero"])

    def test_preview_proposes_recovery_from_upper_windup(self):
        preview = calculate_wrap_preview(4.0)

        self.assertAlmostEqual(preview["saturated_output"], 0.6)
        self.assertAlmostEqual(preview["recovery_target"], -0.12)
        self.assertEqual(preview["recovery_periods"], -1)

    def test_p_aware_preview_recovers_lower_windup(self):
        preview = calculate_pid_wrap_preview(
            {
                'integrator_before': -4.0,
                'output': -0.6000488340861921,
                'integrator_after': -4.0,
                'integrator_change_during_read': 0.0,
                'proportional_gain': 0.10009765625,
                'input': 'iq0',
                'input_source_output': -0.02,
                'setpoint': 0.0,
                'input_filter': [0.0, 0.0, 0.0, 0.0],
                'differential_mode_enabled': False,
                'pid_minimum': -0.5999755859375,
                'pid_maximum': 0.599853515625,
            }
        )

        self.assertTrue(preview['should_wrap'])
        self.assertEqual(preview['action_mode'], 'windup_recovery')
        self.assertAlmostEqual(preview['target_output'], 0.12)
        self.assertAlmostEqual(preview['proportional_term'], -0.002001953125)
        self.assertAlmostEqual(preview['target_integrator'], 0.122001953125)
        self.assertTrue(preview['manual_write_ready'])

    def test_p_aware_preview_rejects_active_input_filter(self):
        snapshot = {
            'integrator_before': -4.0,
            'output': -0.6,
            'integrator_after': -4.0,
            'integrator_change_during_read': 0.0,
            'proportional_gain': 0.1,
            'input': 'iq0',
            'input_source_output': -0.02,
            'setpoint': 0.0,
            'input_filter': [10.0, 0.0, 0.0, 0.0],
            'differential_mode_enabled': False,
            'pid_minimum': -0.6,
            'pid_maximum': 0.6,
        }

        preview = calculate_pid_wrap_preview(snapshot)

        self.assertFalse(preview['manual_write_ready'])
        self.assertEqual(
            preview['action_reason'],
            'pid_input_filter_not_supported',
        )

    def test_p_aware_preview_wraps_normal_operating_point(self):
        preview = calculate_pid_wrap_preview(
            {
                'integrator_before': -0.56,
                'output': -0.58,
                'integrator_after': -0.56,
                'integrator_change_during_read': 0.0,
                'proportional_gain': 0.1,
                'input': 'iq0',
                'input_source_output': -0.2,
                'setpoint': 0.0,
                'input_filter': [0.0, 0.0, 0.0, 0.0],
                'differential_mode_enabled': False,
                'pid_minimum': -0.6,
                'pid_maximum': 0.6,
            }
        )

        self.assertEqual(preview['action_mode'], 'normal_wrap')
        self.assertAlmostEqual(preview['target_output'], 0.14)
        self.assertAlmostEqual(preview['target_integrator'], 0.16)
        self.assertTrue(preview['manual_write_ready'])


if __name__ == "__main__":
    unittest.main()
