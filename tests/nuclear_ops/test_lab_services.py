import unittest
from datetime import time

import numpy as np

from qudi.logic.nuclear_ops.lab_services import NuclearLabServices
from qudi.logic.nuclear_ops.models import ExecutionPolicy


class FakeMicrowave:
    def __init__(self):
        self.cw_power = -20
        self.is_scanning = False
        self.state = "idle"
        self.values = None

    def module_state(self):
        return self.state

    def set_cw_parameters_live(self, frequency, power):
        self.values = (frequency, power)

    def cw_on(self):
        self.state = "active"


class FakePpg:
    def __init__(self):
        self.kwargs = None

    def write_pulse(self, **kwargs):
        self.kwargs = kwargs
        return True


class LabServicesTest(unittest.TestCase):
    def test_quiet_hours_support_same_day_and_midnight_windows(self):
        daytime = ExecutionPolicy(quiet_hours_start="03:00", quiet_hours_end="06:00")
        overnight = ExecutionPolicy(quiet_hours_start="22:00", quiet_hours_end="06:00")

        self.assertTrue(NuclearLabServices.is_quiet_time(daytime, time(4, 0)))
        self.assertFalse(NuclearLabServices.is_quiet_time(daytime, time(7, 0)))
        self.assertTrue(NuclearLabServices.is_quiet_time(overnight, time(23, 0)))
        self.assertTrue(NuclearLabServices.is_quiet_time(overnight, time(2, 0)))
        self.assertFalse(NuclearLabServices.is_quiet_time(overnight, time(12, 0)))

    def test_microwave_live_update_keeps_output_on(self):
        microwave = FakeMicrowave()
        services = NuclearLabServices(microwave=microwave)

        services._set_microwave({"smiq_freq": 4.2e9, "smiq_power_dbm": -14})

        self.assertEqual(microwave.values, (4.2e9, -14.0))
        self.assertEqual(microwave.state, "active")

    def test_ppg_amplitude_uses_the_correct_parameter_name(self):
        ppg = FakePpg()
        services = NuclearLabServices(ppg=ppg)

        services._update_ppg(
            {
                "pulse_shape_ppg": "gaussian",
                "pulse_width_ppg": 2,
                "pulse_delay_ppg": 4,
                "pulse_amplitude_ppg": 0.7,
            }
        )

        self.assertEqual(ppg.kwargs["pulse_amplitude"], 0.7)

    def test_spherical_conversion_uses_tesla_radius(self):
        result = NuclearLabServices._spherical_to_cartesian([0.1, 90, 0])
        np.testing.assert_allclose(result, [0.1, 0, 0], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
