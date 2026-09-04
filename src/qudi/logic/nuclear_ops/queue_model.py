"""Persistent state machine for sequential nuclear experiment execution."""

import os
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4

import h5py

from .hdf5_store import read_hdf_tree, write_hdf_tree
from .models import ExperimentSpec
from .serialization import parse_datetime


QUEUE_SCHEMA = "qudi-nuclear-ops-queue"
QUEUE_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class QueueStatus(str, Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = frozenset(
    (QueueStatus.PREPARING, QueueStatus.RUNNING, QueueStatus.PAUSED, QueueStatus.CANCELLING)
)
FINAL_STATUSES = frozenset((QueueStatus.COMPLETED, QueueStatus.FAILED, QueueStatus.CANCELLED))


@dataclass(frozen=True)
class ExperimentQueueItem:
    experiment: ExperimentSpec
    item_id: str = field(default_factory=lambda: str(uuid4()))
    status: QueueStatus = QueueStatus.PENDING
    created_at: datetime = field(default_factory=_utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    run_file: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", QueueStatus(self.status))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "run_file": self.run_file,
            "error": self.error,
            "experiment": self.experiment.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentQueueItem":
        return cls(
            item_id=value["item_id"],
            status=QueueStatus(value.get("status", QueueStatus.PENDING.value)),
            created_at=parse_datetime(value.get("created_at", _utc_now()), "created_at"),
            started_at=(
                parse_datetime(value["started_at"], "started_at")
                if value.get("started_at")
                else None
            ),
            finished_at=(
                parse_datetime(value["finished_at"], "finished_at")
                if value.get("finished_at")
                else None
            ),
            run_file=value.get("run_file", ""),
            error=value.get("error", ""),
            experiment=ExperimentSpec.from_dict(value["experiment"]),
        )


class QueueHdf5Store:
    """Atomic HDF5 persistence for the small queue state document."""

    def __init__(self, path: os.PathLike) -> None:
        self.path = Path(path).expanduser().resolve()

    def save(self, value: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".writing")
        if temporary.exists():
            temporary.unlink()
        try:
            with h5py.File(str(temporary), "x") as handle:
                handle.attrs["schema"] = QUEUE_SCHEMA
                handle.attrs["schema_version"] = QUEUE_SCHEMA_VERSION
                write_hdf_tree(handle, "state", dict(value))
                handle.flush()
            os.replace(str(temporary), str(self.path))
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise

    def load(self) -> Dict[str, Any]:
        with h5py.File(str(self.path), "r") as handle:
            schema = handle.attrs.get("schema", "")
            if isinstance(schema, bytes):
                schema = schema.decode("utf-8")
            version = int(handle.attrs.get("schema_version", -1))
            if schema != QUEUE_SCHEMA or version != QUEUE_SCHEMA_VERSION:
                raise ValueError("Unsupported NuclearOps queue HDF5 file")
            return read_hdf_tree(handle["state"])


class ExperimentQueue:
    """Thread-safe queue state machine with persistence after every mutation."""

    def __init__(
        self,
        store: QueueHdf5Store,
        items: Iterable[ExperimentQueueItem] = (),
        paused: bool = False,
        continue_on_failure: bool = True,
    ) -> None:
        self.store = store
        self._items = list(items)
        self.paused = bool(paused)
        self.continue_on_failure = bool(continue_on_failure)
        self._lock = threading.RLock()
        self._validate()

    @classmethod
    def create(
        cls, path: os.PathLike, continue_on_failure: bool = True
    ) -> "ExperimentQueue":
        store = QueueHdf5Store(path)
        if store.path.exists():
            raise FileExistsError(str(store.path))
        queue = cls(store=store, continue_on_failure=continue_on_failure)
        queue._persist()
        return queue

    @classmethod
    def open(cls, path: os.PathLike) -> "ExperimentQueue":
        store = QueueHdf5Store(path)
        value = store.load()
        return cls(
            store=store,
            items=[ExperimentQueueItem.from_dict(item) for item in value.get("items", [])],
            paused=bool(value.get("paused", False)),
            continue_on_failure=bool(value.get("continue_on_failure", True)),
        )

    def _validate(self) -> None:
        ids = [item.item_id for item in self._items]
        if len(ids) != len(set(ids)):
            raise ValueError("Queue item IDs must be unique")
        active = [item for item in self._items if item.status in ACTIVE_STATUSES]
        if len(active) > 1:
            raise ValueError("Only one queue item may be active")

    def _persist(self) -> None:
        self.store.save(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paused": self.paused,
            "continue_on_failure": self.continue_on_failure,
            "items": [item.to_dict() for item in self._items],
        }

    @property
    def items(self) -> List[ExperimentQueueItem]:
        with self._lock:
            return list(self._items)

    @property
    def active_item(self) -> Optional[ExperimentQueueItem]:
        with self._lock:
            return next((item for item in self._items if item.status in ACTIVE_STATUSES), None)

    def get(self, item_id: str) -> ExperimentQueueItem:
        with self._lock:
            index = self._index(item_id)
            return self._items[index]

    def _index(self, item_id: str) -> int:
        for index, item in enumerate(self._items):
            if item.item_id == item_id:
                return index
        raise KeyError("Unknown queue item: {!r}".format(item_id))

    def enqueue(self, experiment: ExperimentSpec, position: Optional[int] = None) -> ExperimentQueueItem:
        with self._lock:
            item = ExperimentQueueItem(experiment=experiment)
            pending_indices = [
                index for index, existing in enumerate(self._items) if existing.status == QueueStatus.PENDING
            ]
            if position is None:
                insertion_index = pending_indices[-1] + 1 if pending_indices else len(self._items)
            else:
                if position < 0 or position > len(pending_indices):
                    raise IndexError("Pending queue position out of range")
                insertion_index = pending_indices[position] if position < len(pending_indices) else len(self._items)
            self._items.insert(insertion_index, item)
            self._persist()
            return item

    def move_pending(self, item_id: str, new_position: int) -> None:
        with self._lock:
            item = self.get(item_id)
            if item.status != QueueStatus.PENDING:
                raise ValueError("Only pending experiments can be reordered")
            pending = [existing for existing in self._items if existing.status == QueueStatus.PENDING]
            if new_position < 0 or new_position >= len(pending):
                raise IndexError("Pending queue position out of range")
            pending.remove(item)
            pending.insert(new_position, item)
            iterator = iter(pending)
            self._items = [next(iterator) if old.status == QueueStatus.PENDING else old for old in self._items]
            self._persist()

    def remove_pending(self, item_id: str) -> ExperimentQueueItem:
        with self._lock:
            index = self._index(item_id)
            item = self._items[index]
            if item.status != QueueStatus.PENDING:
                raise ValueError("Only pending experiments can be removed")
            removed = self._items.pop(index)
            self._persist()
            return removed

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)
            self._persist()

    def claim_next(self) -> Optional[ExperimentQueueItem]:
        with self._lock:
            if self.paused or self.active_item is not None:
                return None
            if not self.continue_on_failure:
                last_final = next(
                    (item for item in reversed(self._items) if item.status in FINAL_STATUSES), None
                )
                if last_final is not None and last_final.status == QueueStatus.FAILED:
                    return None
            for index, item in enumerate(self._items):
                if item.status == QueueStatus.PENDING:
                    updated = replace(item, status=QueueStatus.PREPARING, started_at=_utc_now())
                    self._items[index] = updated
                    self._persist()
                    return updated
            return None

    def mark_running(self, item_id: str, run_file: str = "") -> ExperimentQueueItem:
        return self._transition(item_id, QueueStatus.PREPARING, QueueStatus.RUNNING, run_file=run_file)

    def mark_paused(self, item_id: str) -> ExperimentQueueItem:
        return self._transition(item_id, QueueStatus.RUNNING, QueueStatus.PAUSED)

    def mark_resumed(self, item_id: str) -> ExperimentQueueItem:
        return self._transition(item_id, QueueStatus.PAUSED, QueueStatus.RUNNING)

    def mark_cancelling(self, item_id: str) -> ExperimentQueueItem:
        return self._transition(
            item_id, (QueueStatus.PREPARING, QueueStatus.RUNNING, QueueStatus.PAUSED), QueueStatus.CANCELLING
        )

    def mark_completed(self, item_id: str, run_file: str = "") -> ExperimentQueueItem:
        return self._transition(
            item_id,
            ACTIVE_STATUSES,
            QueueStatus.COMPLETED,
            run_file=run_file,
            finished_at=_utc_now(),
        )

    def mark_failed(self, item_id: str, error: str, run_file: str = "") -> ExperimentQueueItem:
        return self._transition(
            item_id,
            ACTIVE_STATUSES,
            QueueStatus.FAILED,
            error=error,
            run_file=run_file,
            finished_at=_utc_now(),
        )

    def mark_cancelled(self, item_id: str, run_file: str = "") -> ExperimentQueueItem:
        return self._transition(
            item_id,
            ACTIVE_STATUSES,
            QueueStatus.CANCELLED,
            run_file=run_file,
            finished_at=_utc_now(),
        )

    def _transition(self, item_id, expected, target, **changes) -> ExperimentQueueItem:
        with self._lock:
            index = self._index(item_id)
            item = self._items[index]
            expected_statuses = {expected} if isinstance(expected, QueueStatus) else set(expected)
            if item.status not in expected_statuses:
                raise ValueError(
                    "Invalid queue transition for {}: {} -> {}".format(
                        item_id, item.status.value, QueueStatus(target).value
                    )
                )
            updated = replace(item, status=QueueStatus(target), **changes)
            self._items[index] = updated
            self._validate()
            self._persist()
            return updated

    def recover_incomplete(self, requeue: bool = False) -> List[ExperimentQueueItem]:
        """Resolve items left active by an interrupted Qudi process."""

        with self._lock:
            recovered = []
            for index, item in enumerate(self._items):
                if item.status not in ACTIVE_STATUSES:
                    continue
                if requeue:
                    updated = replace(
                        item,
                        status=QueueStatus.PENDING,
                        started_at=None,
                        finished_at=None,
                        error="",
                    )
                else:
                    updated = replace(
                        item,
                        status=QueueStatus.FAILED,
                        finished_at=_utc_now(),
                        error="Qudi stopped before the experiment completed",
                    )
                self._items[index] = updated
                recovered.append(updated)
            if recovered:
                self._persist()
            return recovered
