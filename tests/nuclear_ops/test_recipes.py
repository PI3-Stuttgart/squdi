import unittest

import numpy as np

from qudi.logic.nuclear_ops.models import ExperimentSpec, ScanAxis
from qudi.logic.nuclear_ops.recipes import (
    ProgramBundle,
    QmStreamRecipe,
    RawEventOutput,
    RecipeContext,
    StreamOutput,
)
from qudi.logic.nuclear_ops.scan_planner import ScanPlanner
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry


class FakeHandle:
    def __init__(self, value):
        self.value = value

    def fetch_all(self):
        return self.value


class FakeHandles:
    def __init__(self, values, completed=None):
        self.values = values
        self.timeout = None
        self.completed = completed

    def wait_for_all_values(self, timeout):
        self.timeout = timeout
        return self.completed

    def get(self, name):
        return FakeHandle(self.values[name])


class FakeJob:
    def __init__(self, values):
        self.result_handles = FakeHandles(values)


class StreamRecipe(QmStreamRecipe):
    name = "stream"
    axis_policies = {"tau": "qua"}
    stream_outputs = (
        StreamOutput(
            "counts",
            "counts",
            trailing_dimensions=("readout",),
            trailing_coordinates={"readout": ("initial", "result")},
            unit="counts",
        ),
    )
    raw_event_outputs = (RawEventOutput("tags", "tag_lengths", "SPCM1"),)

    def build_program(self, context):
        return ProgramBundle("program")


class QmStreamRecipeTest(unittest.TestCase):
    def context(self):
        experiment = ExperimentSpec(
            recipe="stream",
            name="stream decode",
            scan_axes=(ScanAxis("tau", (10, 20), execution="qua"),),
        )
        block = ScanPlanner(StreamRecipe.axis_policies).plan(experiment).blocks[0]
        return RecipeContext(
            experiment=experiment,
            block=block,
            thresholds=ThresholdRegistry().snapshot(),
        )

    def test_native_result_handles_become_xarray_and_raw_events(self):
        job = FakeJob(
            {
                "counts": {"value": np.asarray([[1, 2], [3, 4]])},
                "tags": np.asarray([[11, 12, 0], [21, 22, 23]]),
                "tag_lengths": np.asarray([2, 3]),
            }
        )

        result = StreamRecipe().acquire(job, self.context(), timeout_s=12.5)

        self.assertTrue(result.valid)
        self.assertEqual(result.batch.dataset.counts.dims, ("record", "readout"))
        self.assertEqual(result.batch.dataset.counts.attrs["unit"], "counts")
        self.assertEqual(result.batch.raw_events["SPCM1"][0].tolist(), [11, 12])
        self.assertEqual(job.result_handles.timeout, 12.5)

    def test_wrong_stream_size_is_rejected(self):
        job = FakeJob(
            {
                "counts": np.asarray([1, 2, 3]),
                "tags": np.zeros((2, 1), dtype=int),
                "tag_lengths": np.zeros(2, dtype=int),
            }
        )
        with self.assertRaisesRegex(ValueError, "expected 4"):
            StreamRecipe().acquire(job, self.context(), timeout_s=1)

    def test_readout_must_reference_a_stream_output(self):
        value = self.context().experiment.to_dict()
        value["readout"] = [
            {
                "kind": "result",
                "threshold_ref": "csr_accept",
                "output_name": "missing",
                "repetitions": 1,
            }
        ]
        with self.assertRaisesRegex(ValueError, "does not provide"):
            StreamRecipe().validate(ExperimentSpec.from_dict(value))

    def test_result_timeout_is_reported_before_fetch(self):
        job = FakeJob({})
        job.result_handles.completed = False
        with self.assertRaises(TimeoutError):
            StreamRecipe().acquire(job, self.context(), timeout_s=0.1)


if __name__ == "__main__":
    unittest.main()
