import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np
import xarray as xr

from qudi.logic.nuclear_ops.hdf5_store import Hdf5RunStore, NuclearDataset
from qudi.logic.nuclear_ops.models import MeasurementBatch, RunMetadata, RunProvenance
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry

from .helpers import experiment_spec


def batch(tau, counts, raw_events):
    count_array = np.asarray(counts, dtype=np.int64)
    return MeasurementBatch(
        dataset=xr.Dataset(
            data_vars={
                "counts": (("record", "readout"), count_array),
                "valid": ("record", np.ones(count_array.shape[0], dtype=bool)),
                "acquired_at": (
                    "record",
                    np.arange(count_array.shape[0], dtype="timedelta64[ns]")
                    + np.datetime64("2026-09-03T10:00:00", "ns"),
                ),
            },
            coords={
                "tau": ("record", np.asarray(tau, dtype=float), {"unit": "ns"}),
                "readout": np.asarray(("e1", "e2")),
            },
        ),
        raw_events={"SPCM1": [np.asarray(events, dtype=np.int64) for events in raw_events]},
    )


class Hdf5RunStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "run.h5"
        self.spec = experiment_spec()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_record(self):
        return NuclearDataset.create(
            self.path,
            experiment=self.spec,
            metadata=RunMetadata(operator="Ada", sample="sample-1", tags=("night", "SnV")),
            provenance=RunProvenance(
                git_revision="abc123",
                software_versions={"qm-qua": "test"},
            ),
            thresholds=ThresholdRegistry().snapshot(),
            queue_item={"item_id": "queue-1", "status": "running"},
        )

    def test_metadata_and_experiment_are_separate_hdf5_groups(self):
        self.create_record()
        store = Hdf5RunStore(self.path)

        self.assertEqual(store.load_section("metadata")["operator"], "Ada")
        self.assertEqual(store.load_section("experiment")["recipe"], "nuclear_rabi")
        self.assertEqual(store.load_section("thresholds")["profile"]["name"], "default")
        with h5py.File(self.path, "r") as handle:
            self.assertIn("metadata", handle)
            self.assertIn("experiment", handle)
            self.assertNotIn("metadata_json", handle.attrs)

    def test_batches_append_and_round_trip_as_xarray(self):
        record = self.create_record()
        record.append(batch([10, 20], [[1, 2], [3, 4]], [[100, 101], [200]]))
        record.append(batch([30], [[5, 6]], [[300, 301, 302]]))
        record.finalize()

        reopened = NuclearDataset.open(self.path)
        xr.testing.assert_identical(reopened.dataset, record.dataset)
        self.assertEqual(reopened.metadata.operator, "Ada")
        self.assertEqual(reopened.experiment, self.spec)
        self.assertEqual(reopened.thresholds.profile.name, "default")
        self.assertIsNotNone(reopened.metadata.finished_at)
        self.assertEqual(reopened.queue_item["status"], "completed")
        np.testing.assert_array_equal(
            reopened.store.load_raw_events("SPCM1", 2),
            np.asarray([300, 301, 302]),
        )
        self.assertEqual(reopened.store.committed_records, 3)
        self.assertEqual(reopened.dataset["tau"].attrs["unit"], "ns")

    def test_analysis_is_saved_as_a_separate_xarray_group(self):
        record = self.create_record()
        record.append(batch([10, 20], [[1, 2], [3, 4]], [[100], [200]]))
        analysis = xr.Dataset(
            data_vars={"signal": ("record", np.asarray([0.25, 0.75]))},
            coords={"record": [0, 1], "tau": ("record", [10.0, 20.0])},
        )

        record.save_analysis(analysis)

        xr.testing.assert_identical(record.analysis, analysis)
        with h5py.File(self.path, "r") as handle:
            self.assertIn("signal", handle["analysis/variables"])
            self.assertNotIn("signal", handle["data/variables"])

    def test_schema_change_after_first_batch_is_rejected(self):
        record = self.create_record()
        first = batch([10], [[1, 2]], [[100]])
        record.append(first)
        changed = MeasurementBatch(
            dataset=first.dataset.assign(extra=("record", [1])),
            raw_events=first.raw_events,
        )

        with self.assertRaisesRegex(ValueError, "schema cannot change"):
            record.append(changed)
        self.assertEqual(record.store.committed_records, 1)

    def test_non_contiguous_explicit_record_coordinate_is_rejected(self):
        record = self.create_record()
        invalid = batch([10], [[1, 2]], [[100]])
        invalid = MeasurementBatch(
            dataset=invalid.dataset.assign_coords(record=[5]),
            raw_events=invalid.raw_events,
        )

        with self.assertRaisesRegex(ValueError, "contiguous"):
            record.append(invalid)

    def test_recovery_truncates_uncommitted_array_extensions(self):
        record = self.create_record()
        record.append(batch([10], [[1, 2]], [[100]]))

        with h5py.File(self.path, "r+") as handle:
            counts = handle["data/variables/counts"]
            counts.resize((2, 2))
            counts[1] = [999, 999]
            events = handle["raw/SPCM1/events"]
            events.resize((3,))
            events[1:] = [998, 999]
            offsets = handle["raw/SPCM1/shot_offsets"]
            offsets.resize((3,))
            offsets[2] = 3
            handle.attrs["write_in_progress"] = True
            handle.flush()

        recovered = Hdf5RunStore(self.path)
        self.assertEqual(recovered.load_dataset().sizes["record"], 1)
        self.assertEqual(recovered.committed_records, 1)
        with h5py.File(self.path, "r") as handle:
            self.assertFalse(bool(handle.attrs["write_in_progress"]))
            self.assertEqual(handle["data/variables/counts"].shape, (1, 2))
            self.assertEqual(handle["raw/SPCM1/events"].shape, (1,))
            self.assertEqual(handle["raw/SPCM1/shot_offsets"].shape, (2,))

    def test_raw_event_channel_change_is_rejected(self):
        record = self.create_record()
        record.append(batch([10], [[1, 2]], [[100]]))
        second = batch([20], [[3, 4]], [[200]])
        second = MeasurementBatch(dataset=second.dataset, raw_events={})

        with self.assertRaisesRegex(ValueError, "channels cannot change"):
            record.append(second)
        with h5py.File(self.path, "r") as handle:
            self.assertFalse(bool(handle.attrs["write_in_progress"]))
            self.assertEqual(handle["data/variables/counts"].shape, (1, 2))


if __name__ == "__main__":
    unittest.main()
