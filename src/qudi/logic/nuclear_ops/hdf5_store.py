"""Crash-recoverable HDF5 storage for xarray-backed nuclear measurements."""

import os
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import quote, unquote

import h5py
import numpy as np
import xarray as xr

from .models import ExperimentSpec, MeasurementBatch, RunMetadata, RunProvenance
from .serialization import to_primitive
from .thresholds import ThresholdSnapshot


SCHEMA_NAME = "qudi-nuclear-ops"
SCHEMA_VERSION = 1
_KIND = "qudi_kind"
_ORIGINAL_DTYPE = "original_dtype"
_DIMENSIONS = "dimensions"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node_name(name: str) -> str:
    return quote(str(name), safe="")


def _string_dtype():
    return h5py.string_dtype(encoding="utf-8")


def _decode_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_hdf_tree(parent: h5py.Group, name: str, value: Any) -> None:
    """Write nested primitives without pickle or external sidecar files."""

    encoded_name = _node_name(name)
    if encoded_name in parent:
        del parent[encoded_name]
    primitive = to_primitive(value)

    if isinstance(primitive, Mapping):
        group = parent.create_group(encoded_name)
        group.attrs[_KIND] = "mapping"
        group.attrs["original_name"] = str(name)
        for key, item in primitive.items():
            write_hdf_tree(group, key, item)
        return

    if isinstance(primitive, list):
        group = parent.create_group(encoded_name)
        group.attrs[_KIND] = "sequence"
        group.attrs["original_name"] = str(name)
        group.attrs["length"] = len(primitive)
        for index, item in enumerate(primitive):
            write_hdf_tree(group, "{:08d}".format(index), item)
        return

    if primitive is None:
        group = parent.create_group(encoded_name)
        group.attrs[_KIND] = "none"
        group.attrs["original_name"] = str(name)
        return

    if isinstance(primitive, str):
        dataset = parent.create_dataset(encoded_name, data=primitive, dtype=_string_dtype())
    else:
        dataset = parent.create_dataset(encoded_name, data=primitive)
    dataset.attrs[_KIND] = "scalar"
    dataset.attrs["original_name"] = str(name)


def read_hdf_tree(node: Any) -> Any:
    """Read a value produced by :func:`write_hdf_tree`."""

    kind = _decode_scalar(node.attrs.get(_KIND, ""))
    if kind == "none":
        return None
    if kind == "scalar":
        return _decode_scalar(node[()])
    if kind == "sequence":
        children = sorted(node.values(), key=lambda child: int(unquote(child.name.rsplit("/", 1)[-1])))
        return [read_hdf_tree(child) for child in children]
    if kind == "mapping":
        result = {}
        for child in node.values():
            key = _decode_scalar(child.attrs.get("original_name", unquote(child.name.rsplit("/", 1)[-1])))
            result[key] = read_hdf_tree(child)
        return result
    raise ValueError("Unknown HDF5 metadata node kind {!r} at {}".format(kind, node.name))


def _storage_array(values: np.ndarray) -> Tuple[np.ndarray, str, Optional[Any]]:
    """Convert an xarray value array to a portable HDF5 representation."""

    values = np.asarray(values)
    dtype_text = str(values.dtype)
    if values.dtype.kind == "O":
        raise TypeError("Object-dtype xarray values cannot be stored in a nuclear run")
    if values.dtype.kind == "M":
        return values.astype("datetime64[ns]").astype(np.int64), dtype_text, None
    if values.dtype.kind == "m":
        return values.astype("timedelta64[ns]").astype(np.int64), dtype_text, None
    if values.dtype.kind == "U":
        return values.astype(object), dtype_text, _string_dtype()
    return values, dtype_text, None


def _restored_array(dataset: h5py.Dataset) -> np.ndarray:
    values = np.asarray(dataset[...])
    original_dtype = _decode_scalar(dataset.attrs.get(_ORIGINAL_DTYPE, str(values.dtype)))
    if str(original_dtype).startswith("datetime64"):
        return values.astype("datetime64[ns]").astype(original_dtype)
    if str(original_dtype).startswith("timedelta64"):
        return values.astype("timedelta64[ns]").astype(original_dtype)
    if values.dtype.kind in ("O", "S"):
        decoder = np.vectorize(
            lambda item: item.decode("utf-8") if isinstance(item, bytes) else item,
            otypes=[object],
        )
        decoded = decoder(values)
        if str(original_dtype).startswith("<U") or str(original_dtype).startswith("U"):
            return decoded.astype(original_dtype)
        return decoded
    return values.astype(original_dtype, copy=False)


class Hdf5RunStore:
    """Single-writer, append-only storage for one experiment run.

    Appends use a root-level ``committed_records`` marker.  If a process exits
    between extending datasets and advancing the marker, :meth:`recover`
    truncates all arrays and raw-event offsets back to the last complete batch.
    """

    def __init__(self, path: os.PathLike) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        if not self.path.exists():
            raise FileNotFoundError(str(self.path))
        self.recover()

    @classmethod
    def create(
        cls,
        path: os.PathLike,
        experiment: ExperimentSpec,
        metadata: Optional[RunMetadata] = None,
        provenance: Optional[RunProvenance] = None,
        thresholds: Optional[ThresholdSnapshot] = None,
        queue_item: Optional[Mapping[str, Any]] = None,
    ) -> "Hdf5RunStore":
        final_path = Path(path).expanduser().resolve()
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            raise FileExistsError(str(final_path))
        temporary_path = final_path.with_name(final_path.name + ".creating")
        if temporary_path.exists():
            temporary_path.unlink()
        try:
            metadata = metadata or RunMetadata()
            if metadata.started_at is None:
                metadata = replace(metadata, started_at=datetime.now(timezone.utc))
            with h5py.File(str(temporary_path), "x") as handle:
                handle.attrs["schema"] = SCHEMA_NAME
                handle.attrs["schema_version"] = SCHEMA_VERSION
                handle.attrs["run_id"] = experiment.experiment_id
                handle.attrs["status"] = "created"
                handle.attrs["created_at"] = _utc_iso()
                handle.attrs["committed_records"] = 0
                handle.attrs["write_in_progress"] = False
                data_group = handle.create_group("data")
                data_group.create_group("coordinates")
                data_group.create_group("variables")
                data_group.create_group("coordinate_attributes")
                data_group.create_group("variable_attributes")
                handle.create_group("raw")
                handle.create_group("analysis")
                handle.create_group("programs")
                write_hdf_tree(handle, "experiment", experiment.to_dict())
                write_hdf_tree(handle, "metadata", metadata.to_dict())
                write_hdf_tree(handle, "provenance", (provenance or RunProvenance()).to_dict())
                write_hdf_tree(handle, "thresholds", thresholds.to_dict() if thresholds else {})
                write_hdf_tree(handle, "queue", dict(queue_item) if queue_item else {})
                handle.create_dataset(
                    "logs",
                    shape=(0,),
                    maxshape=(None,),
                    chunks=True,
                    dtype=_string_dtype(),
                )
                handle.flush()
            os.replace(str(temporary_path), str(final_path))
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        return cls(final_path)

    @property
    def committed_records(self) -> int:
        with h5py.File(str(self.path), "r") as handle:
            self._validate_root(handle)
            return int(handle.attrs["committed_records"])

    @staticmethod
    def _validate_root(handle: h5py.File) -> None:
        schema = _decode_scalar(handle.attrs.get("schema", ""))
        version = int(handle.attrs.get("schema_version", -1))
        if schema != SCHEMA_NAME:
            raise ValueError("Not a Qudi NuclearOps HDF5 file")
        if version != SCHEMA_VERSION:
            raise ValueError(
                "Unsupported NuclearOps HDF5 schema version {} (expected {})".format(
                    version, SCHEMA_VERSION
                )
            )

    def _normalise_batch(self, batch: MeasurementBatch, start: int) -> xr.Dataset:
        dataset = batch.dataset.copy(deep=False)
        expected_record = np.arange(start, start + batch.record_count, dtype=np.int64)
        if "record" in dataset.coords:
            actual = np.asarray(dataset.coords["record"].values)
            if actual.shape != expected_record.shape or not np.array_equal(actual, expected_record):
                raise ValueError(
                    "Batch record coordinates must be contiguous from {}; got {!r}".format(
                        start, actual
                    )
                )
        else:
            dataset = dataset.assign_coords(record=expected_record)
        for name, array in list(dataset.coords.items()) + list(dataset.data_vars.items()):
            if "record" in array.dims and array.dims[0] != "record":
                raise ValueError(
                    "Record-dependent array {!r} must use 'record' as its first dimension".format(
                        name
                    )
                )
        return dataset

    def append(self, batch: MeasurementBatch) -> xr.Dataset:
        """Append one complete batch and return its normalized dataset."""

        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            start = int(handle.attrs["committed_records"])
            dataset = self._normalise_batch(batch, start)
            stop = start + batch.record_count
            handle.attrs["write_in_progress"] = True
            handle.flush()
            try:
                self._append_xarray_group(handle["data"], dataset, start, stop)
                self._append_raw_events(handle["raw"], batch.raw_events, start, stop)
                handle.flush()
                handle.attrs["committed_records"] = stop
                handle.attrs["status"] = "running"
                handle.attrs["updated_at"] = _utc_iso()
                handle.attrs["write_in_progress"] = False
                handle.flush()
            except Exception:
                self._truncate_to_committed(handle, start)
                handle.attrs["write_in_progress"] = False
                handle.flush()
                raise
            return dataset

    def _append_xarray_group(
        self, group: h5py.Group, dataset: xr.Dataset, start: int, stop: int
    ) -> None:
        expected_coords = set(dataset.coords)
        expected_variables = set(dataset.data_vars)
        if start > 0:
            stored_coords = {
                _decode_scalar(item.attrs.get("original_name", unquote(name)))
                for name, item in group["coordinates"].items()
            }
            stored_variables = {
                _decode_scalar(item.attrs.get("original_name", unquote(name)))
                for name, item in group["variables"].items()
            }
            if expected_coords != stored_coords or expected_variables != stored_variables:
                raise ValueError(
                    "A run's xarray schema cannot change after the first committed batch"
                )

        for collection_name, arrays in (
            ("coordinates", dataset.coords),
            ("variables", dataset.data_vars),
        ):
            destination = group[collection_name]
            attribute_destination = group[
                "coordinate_attributes" if collection_name == "coordinates" else "variable_attributes"
            ]
            for name, array in arrays.items():
                self._append_data_array(
                    destination,
                    attribute_destination,
                    name,
                    array,
                    start,
                    stop,
                )

    @staticmethod
    def _append_data_array(
        destination: h5py.Group,
        attribute_destination: h5py.Group,
        name: str,
        array: xr.DataArray,
        start: int,
        stop: int,
    ) -> None:
        key = _node_name(name)
        values, original_dtype, explicit_dtype = _storage_array(array.values)
        record_dependent = bool(array.dims) and array.dims[0] == "record"
        dimensions = np.asarray(array.dims, dtype=_string_dtype())

        if key not in destination:
            if start > 0 and record_dependent:
                raise ValueError("Cannot introduce {!r} after records were committed".format(name))
            maxshape = (None,) + values.shape[1:] if record_dependent else values.shape
            kwargs = {
                "shape": values.shape,
                "maxshape": maxshape,
                "dtype": explicit_dtype or values.dtype,
            }
            if values.ndim > 0:
                kwargs["chunks"] = True
                if values.dtype.kind not in ("O", "U"):
                    kwargs["compression"] = "gzip"
                    kwargs["shuffle"] = True
            target = destination.create_dataset(key, **kwargs)
            target[...] = values
            target.attrs["original_name"] = name
            target.attrs[_ORIGINAL_DTYPE] = original_dtype
            target.attrs[_DIMENSIONS] = dimensions
            write_hdf_tree(attribute_destination, name, dict(array.attrs))
            return

        target = destination[key]
        stored_dims = tuple(_decode_scalar(value) for value in target.attrs[_DIMENSIONS])
        if stored_dims != tuple(array.dims):
            raise ValueError("Dimensions changed for {!r}: {} -> {}".format(name, stored_dims, array.dims))
        if record_dependent:
            if target.shape[1:] != values.shape[1:]:
                raise ValueError("Trailing shape changed for {!r}".format(name))
            target.resize((stop,) + target.shape[1:])
            target[start:stop, ...] = values
        elif target.shape != values.shape or not np.array_equal(_restored_array(target), array.values):
            raise ValueError("Static coordinate/variable {!r} changed between batches".format(name))

    @staticmethod
    def _append_raw_events(
        raw_group: h5py.Group,
        raw_events: Mapping[str, Any],
        start: int,
        stop: int,
    ) -> None:
        existing_channels = {
            _decode_scalar(group.attrs.get("original_name", unquote(name)))
            for name, group in raw_group.items()
        }
        incoming_channels = set(raw_events)
        if start > 0 and existing_channels != incoming_channels:
            raise ValueError("Raw-event channels cannot change during a run")
        for channel, shots in raw_events.items():
            key = _node_name(channel)
            if key not in raw_group:
                channel_group = raw_group.create_group(key)
                channel_group.attrs["original_name"] = channel
                first_dtype = np.asarray(shots[0]).dtype
                if first_dtype.kind == "O":
                    raise TypeError("Raw events cannot use object dtype")
                channel_group.create_dataset(
                    "events",
                    shape=(0,),
                    maxshape=(None,),
                    chunks=True,
                    compression="gzip",
                    shuffle=True,
                    dtype=first_dtype,
                )
                offsets = channel_group.create_dataset(
                    "shot_offsets",
                    shape=(1,),
                    maxshape=(None,),
                    chunks=True,
                    compression="gzip",
                    dtype=np.int64,
                )
                offsets[0] = 0
            channel_group = raw_group[key]
            events_target = channel_group["events"]
            offsets_target = channel_group["shot_offsets"]
            if offsets_target.shape[0] != start + 1:
                raise RuntimeError("Raw-event offsets do not match committed records")
            arrays = [np.asarray(shot) for shot in shots]
            for array in arrays:
                if array.dtype != events_target.dtype:
                    raise TypeError("Raw-event dtype changed for channel {!r}".format(channel))
            old_event_count = int(offsets_target[-1])
            lengths = np.asarray([array.size for array in arrays], dtype=np.int64)
            new_offsets = old_event_count + np.cumsum(lengths)
            combined = (
                np.concatenate(arrays)
                if int(lengths.sum()) > 0
                else np.asarray([], dtype=events_target.dtype)
            )
            events_target.resize((old_event_count + int(lengths.sum()),))
            if combined.size:
                events_target[old_event_count:] = combined
            offsets_target.resize((stop + 1,))
            offsets_target[start + 1 : stop + 1] = new_offsets

    def recover(self) -> None:
        """Roll an interrupted append back to the last committed record."""

        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            committed = int(handle.attrs["committed_records"])
            self._truncate_to_committed(handle, committed)
            handle.attrs["write_in_progress"] = False
            handle.flush()

    @staticmethod
    def _truncate_to_committed(handle: h5py.File, committed: int) -> None:
        for collection in (handle["data/coordinates"], handle["data/variables"]):
            for dataset in collection.values():
                dimensions = tuple(_decode_scalar(value) for value in dataset.attrs[_DIMENSIONS])
                if dimensions and dimensions[0] == "record" and dataset.shape[0] > committed:
                    dataset.resize((committed,) + dataset.shape[1:])
        for channel_group in handle["raw"].values():
            offsets = channel_group["shot_offsets"]
            if offsets.shape[0] > committed + 1:
                offsets.resize((committed + 1,))
            event_count = int(offsets[-1]) if offsets.shape[0] else 0
            events = channel_group["events"]
            if events.shape[0] > event_count:
                events.resize((event_count,))

    def load_dataset(self) -> xr.Dataset:
        with self._lock, h5py.File(str(self.path), "r") as handle:
            self._validate_root(handle)
            committed = int(handle.attrs["committed_records"])
            coordinates = self._load_array_collection(
                handle["data/coordinates"], handle["data/coordinate_attributes"], committed
            )
            variables = self._load_array_collection(
                handle["data/variables"], handle["data/variable_attributes"], committed
            )
        return xr.Dataset(data_vars=variables, coords=coordinates)

    @staticmethod
    def _load_array_collection(
        collection: h5py.Group, attributes: h5py.Group, committed: int
    ) -> Dict[str, Any]:
        result = {}
        for key, dataset in collection.items():
            name = _decode_scalar(dataset.attrs.get("original_name", unquote(key)))
            dimensions = tuple(_decode_scalar(value) for value in dataset.attrs[_DIMENSIONS])
            values = _restored_array(dataset)
            if dimensions and dimensions[0] == "record":
                values = values[:committed, ...]
            attrs = read_hdf_tree(attributes[_node_name(name)]) if _node_name(name) in attributes else {}
            result[name] = (dimensions, values, attrs)
        return result

    def load_section(self, name: str) -> Any:
        with h5py.File(str(self.path), "r") as handle:
            self._validate_root(handle)
            key = _node_name(name)
            if key not in handle:
                raise KeyError(name)
            return read_hdf_tree(handle[key])

    def update_section(self, name: str, value: Mapping[str, Any]) -> None:
        """Atomically replace a structured non-array section within the run file."""

        if name not in ("metadata", "provenance", "thresholds", "queue"):
            raise ValueError("Unsupported mutable run-file section: {!r}".format(name))
        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            write_hdf_tree(handle, name, dict(value))
            handle.flush()

    def save_analysis(self, dataset: xr.Dataset) -> None:
        """Replace the derived analysis group with a complete xarray dataset."""

        if not isinstance(dataset, xr.Dataset):
            raise TypeError("Analysis must be an xarray.Dataset")
        committed = self.committed_records
        if "record" in dataset.sizes and int(dataset.sizes["record"]) != committed:
            raise ValueError(
                "Record-dependent analysis must contain {} records".format(committed)
            )
        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            if "analysis" in handle:
                del handle["analysis"]
            analysis = handle.create_group("analysis")
            analysis.create_group("coordinates")
            analysis.create_group("variables")
            analysis.create_group("coordinate_attributes")
            analysis.create_group("variable_attributes")
            self._append_xarray_group(analysis, dataset, 0, committed)
            handle.flush()

    def load_analysis(self) -> xr.Dataset:
        with self._lock, h5py.File(str(self.path), "r") as handle:
            self._validate_root(handle)
            analysis = handle["analysis"]
            if "coordinates" not in analysis:
                return xr.Dataset()
            committed = int(handle.attrs["committed_records"])
            coordinates = self._load_array_collection(
                analysis["coordinates"], analysis["coordinate_attributes"], committed
            )
            variables = self._load_array_collection(
                analysis["variables"], analysis["variable_attributes"], committed
            )
            return xr.Dataset(data_vars=variables, coords=coordinates)

    def load_raw_events(self, channel: str, record: int) -> np.ndarray:
        with h5py.File(str(self.path), "r") as handle:
            self._validate_root(handle)
            if record < 0 or record >= int(handle.attrs["committed_records"]):
                raise IndexError(record)
            group = handle["raw"][_node_name(channel)]
            offsets = group["shot_offsets"]
            return np.asarray(group["events"][int(offsets[record]) : int(offsets[record + 1])])

    def append_log(self, message: str) -> None:
        with self._lock, h5py.File(str(self.path), "r+") as handle:
            logs = handle["logs"]
            logs.resize((logs.shape[0] + 1,))
            logs[-1] = "{} {}".format(_utc_iso(), message)
            handle.flush()

    def save_program_metadata(self, block: int, attempt: int, value: Mapping[str, Any]) -> None:
        """Save structured recipe compilation data inside the run file."""

        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            programs = handle.require_group("programs")
            block_group = programs.require_group("block_{:08d}".format(int(block)))
            write_hdf_tree(block_group, "attempt_{:08d}".format(int(attempt)), dict(value))
            handle.flush()

    def finalize(self, status: str = "completed", error: str = "") -> None:
        allowed = {"completed", "failed", "cancelled"}
        if status not in allowed:
            raise ValueError("Final run status must be one of {}".format(sorted(allowed)))
        with self._lock, h5py.File(str(self.path), "r+") as handle:
            self._validate_root(handle)
            finished_at = _utc_iso()
            handle.attrs["status"] = status
            handle.attrs["finished_at"] = finished_at
            if error:
                handle.attrs["error"] = error
            metadata = read_hdf_tree(handle["metadata"])
            metadata["finished_at"] = finished_at
            write_hdf_tree(handle, "metadata", metadata)
            queue_item = read_hdf_tree(handle["queue"])
            if queue_item:
                queue_item["status"] = status
                queue_item["finished_at"] = finished_at
                if error:
                    queue_item["error"] = error
                write_hdf_tree(handle, "queue", queue_item)
            handle.flush()


class NuclearDataset:
    """Domain wrapper around an xarray dataset and its HDF5 run store."""

    def __init__(self, store: Hdf5RunStore, dataset: Optional[xr.Dataset] = None) -> None:
        self.store = store
        self.dataset = store.load_dataset() if dataset is None else dataset
        self.experiment = ExperimentSpec.from_dict(store.load_section("experiment"))
        self.metadata = RunMetadata.from_dict(store.load_section("metadata"))
        self.provenance = RunProvenance.from_dict(store.load_section("provenance"))
        threshold_value = store.load_section("thresholds")
        self.thresholds = ThresholdSnapshot.from_dict(threshold_value) if threshold_value else None
        self.queue_item = store.load_section("queue")

    @classmethod
    def create(
        cls,
        path: os.PathLike,
        experiment: ExperimentSpec,
        metadata: Optional[RunMetadata] = None,
        provenance: Optional[RunProvenance] = None,
        thresholds: Optional[ThresholdSnapshot] = None,
        queue_item: Optional[Mapping[str, Any]] = None,
    ) -> "NuclearDataset":
        store = Hdf5RunStore.create(
            path=path,
            experiment=experiment,
            metadata=metadata,
            provenance=provenance,
            thresholds=thresholds,
            queue_item=queue_item,
        )
        return cls(store=store, dataset=xr.Dataset())

    @classmethod
    def open(cls, path: os.PathLike) -> "NuclearDataset":
        return cls(store=Hdf5RunStore(path))

    def append(self, batch: MeasurementBatch) -> None:
        normalized = self.store.append(batch)
        if "record" not in self.dataset.sizes:
            self.dataset = normalized
        else:
            self.dataset = xr.concat(
                (self.dataset, normalized),
                dim="record",
                data_vars="all",
                coords="minimal",
                compat="equals",
                join="exact",
            )

    def refresh(self) -> None:
        self.dataset = self.store.load_dataset()
        self.metadata = RunMetadata.from_dict(self.store.load_section("metadata"))
        self.queue_item = self.store.load_section("queue")

    def finalize(self, status: str = "completed", error: str = "") -> None:
        self.store.finalize(status=status, error=error)
        self.refresh()

    def save_analysis(self, dataset: xr.Dataset) -> None:
        self.store.save_analysis(dataset)

    @property
    def analysis(self) -> xr.Dataset:
        return self.store.load_analysis()

    def grid(self, coordinate_names) -> xr.Dataset:
        """Return a multidimensional view indexed by record coordinates."""

        coordinate_names = tuple(coordinate_names)
        missing = [name for name in coordinate_names if name not in self.dataset.coords]
        if missing:
            raise KeyError("Unknown grid coordinates: {}".format(missing))
        return self.dataset.set_index(record=coordinate_names).unstack("record")
