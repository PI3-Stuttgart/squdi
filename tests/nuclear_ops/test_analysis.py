import unittest

import numpy as np
import xarray as xr

from qudi.logic.nuclear_ops.analysis import analyze_readout_thresholds, evaluate_threshold
from qudi.logic.nuclear_ops.models import ExperimentSpec, ReadoutStep, ScanAxis
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry, ThresholdRule


class ThresholdAnalysisTest(unittest.TestCase):
    def test_exclusion_band_is_preserved_separately_from_acceptance(self):
        values = xr.DataArray([8.0, 9.0, 9.5, 10.0, 10.5, 11.0, 12.0], dims=("record",))
        accepted, classified = evaluate_threshold(
            values, ThresholdRule(">", 10, exclusion_width=1)
        )

        np.testing.assert_array_equal(
            accepted.values, [False, False, False, False, False, False, True]
        )
        np.testing.assert_array_equal(
            classified.values, [True, True, False, False, False, True, True]
        )

    def test_all_readout_thresholds_are_derived_in_xarray(self):
        experiment = ExperimentSpec(
            recipe="test",
            name="thresholds",
            scan_axes=(ScanAxis("tau", (1, 2), execution="qua"),),
            readout=(
                ReadoutStep("crc", "crc_accept", "crc_counts"),
                ReadoutStep("csr", "csr_accept", "csr_counts"),
                ReadoutStep("ssr", "ssr_e1", "ssr_counts"),
            ),
        )
        dataset = xr.Dataset(
            {
                "crc_counts": ("record", [11, 1]),
                "csr_counts": ("record", [2, 0]),
                "ssr_counts": ("record", [2, 0]),
            }
        )

        result = analyze_readout_thresholds(
            dataset, experiment, ThresholdRegistry().snapshot()
        )

        self.assertIn("crc_counts_crc_accept_accepted", result)
        self.assertIn("csr_counts_csr_accept_accepted", result)
        self.assertIn("ssr_counts_ssr_e1_accepted", result)
        self.assertEqual(
            result["csr_counts_csr_accept_accepted"].values.tolist(), [True, False]
        )


if __name__ == "__main__":
    unittest.main()
