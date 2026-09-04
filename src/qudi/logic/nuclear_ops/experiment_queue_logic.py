"""Qudi facade for the persistent sequential nuclear experiment queue."""

from pathlib import Path

from PySide2 import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex

from .models import ExperimentSpec
from .queue_model import ExperimentQueue, QueueStatus


class ExperimentQueueLogic(LogicBase):
    runner = Connector(interface="NuclearOperationsRunnerInterface")

    queue_file = ConfigOption(name="queue_file", default="nuclear_ops_queue.h5")
    auto_start = ConfigOption(name="auto_start", default=True)
    continue_on_failure = ConfigOption(name="continue_on_failure", default=True)
    requeue_interrupted = ConfigOption(name="requeue_interrupted", default=False)

    sigQueueChanged = QtCore.Signal(object)
    sigItemChanged = QtCore.Signal(object)
    sigProgressUpdated = QtCore.Signal(str, float)

    _sigStartExperiment = QtCore.Signal(object, str)
    _sigPauseExperiment = QtCore.Signal()
    _sigResumeExperiment = QtCore.Signal()
    _sigCancelExperiment = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._runner = None
        self._queue = None

    def on_activate(self):
        self._runner = self.runner()
        path = Path(str(self.queue_file)).expanduser().resolve()
        if path.exists():
            self._queue = ExperimentQueue.open(path)
            recovered = self._queue.recover_incomplete(requeue=bool(self.requeue_interrupted))
            for item in recovered:
                self.log.warning("Recovered interrupted queue item %s as %s", item.item_id, item.status.value)
        else:
            self._queue = ExperimentQueue.create(
                path, continue_on_failure=bool(self.continue_on_failure)
            )

        self._connect_runner()
        self._emit_queue()
        if self.auto_start:
            QtCore.QTimer.singleShot(0, self.start_next)

    def on_deactivate(self):
        self._disconnect_runner()
        self._runner = None
        self._queue = None

    def _connect_runner(self):
        self._sigStartExperiment.connect(
            self._runner.start_experiment, QtCore.Qt.QueuedConnection
        )
        self._sigPauseExperiment.connect(
            self._runner.pause_experiment, QtCore.Qt.QueuedConnection
        )
        self._sigResumeExperiment.connect(
            self._runner.resume_experiment, QtCore.Qt.QueuedConnection
        )
        self._sigCancelExperiment.connect(
            self._runner.cancel_experiment, QtCore.Qt.QueuedConnection
        )
        self._runner.sigExperimentStarted.connect(self._on_started, QtCore.Qt.QueuedConnection)
        self._runner.sigExperimentFinished.connect(self._on_finished, QtCore.Qt.QueuedConnection)
        self._runner.sigExperimentFailed.connect(self._on_failed, QtCore.Qt.QueuedConnection)
        self._runner.sigExperimentCancelled.connect(self._on_cancelled, QtCore.Qt.QueuedConnection)
        self._runner.sigExperimentPaused.connect(self._on_paused, QtCore.Qt.QueuedConnection)
        self._runner.sigExperimentResumed.connect(self._on_resumed, QtCore.Qt.QueuedConnection)
        self._runner.sigProgressUpdated.connect(self._on_progress, QtCore.Qt.QueuedConnection)

    def _disconnect_runner(self):
        if self._runner is None:
            return
        self._sigStartExperiment.disconnect(self._runner.start_experiment)
        self._sigPauseExperiment.disconnect(self._runner.pause_experiment)
        self._sigResumeExperiment.disconnect(self._runner.resume_experiment)
        self._sigCancelExperiment.disconnect(self._runner.cancel_experiment)
        self._runner.sigExperimentStarted.disconnect(self._on_started)
        self._runner.sigExperimentFinished.disconnect(self._on_finished)
        self._runner.sigExperimentFailed.disconnect(self._on_failed)
        self._runner.sigExperimentCancelled.disconnect(self._on_cancelled)
        self._runner.sigExperimentPaused.disconnect(self._on_paused)
        self._runner.sigExperimentResumed.disconnect(self._on_resumed)
        self._runner.sigProgressUpdated.disconnect(self._on_progress)

    @property
    def queue_snapshot(self):
        return self._queue.to_dict() if self._queue is not None else {}

    def _emit_queue(self, item=None):
        if item is not None:
            self.sigItemChanged.emit(item.to_dict())
        self.sigQueueChanged.emit(self.queue_snapshot)

    @QtCore.Slot(object)
    @QtCore.Slot(object, object)
    def enqueue(self, experiment, position=None):
        spec = experiment if isinstance(experiment, ExperimentSpec) else ExperimentSpec.from_dict(experiment)
        with self._thread_lock:
            item = self._queue.enqueue(spec, position=position)
            self._emit_queue(item)
        if self.auto_start:
            QtCore.QTimer.singleShot(0, self.start_next)
        return item.item_id

    @QtCore.Slot(str, int)
    def move_pending(self, item_id, position):
        with self._thread_lock:
            self._queue.move_pending(item_id, position)
            self._emit_queue(self._queue.get(item_id))

    @QtCore.Slot(str)
    def remove_pending(self, item_id):
        with self._thread_lock:
            item = self._queue.remove_pending(item_id)
            self._emit_queue(item)

    @QtCore.Slot(bool)
    def set_queue_paused(self, paused):
        with self._thread_lock:
            self._queue.set_paused(paused)
            self._emit_queue()
        if not paused and self.auto_start:
            QtCore.QTimer.singleShot(0, self.start_next)

    @QtCore.Slot()
    def start_next(self):
        with self._thread_lock:
            item = self._queue.claim_next()
            if item is None:
                return
            self._emit_queue(item)
            self._sigStartExperiment.emit(item.experiment.to_dict(), item.item_id)

    @QtCore.Slot()
    def pause_current(self):
        if self._queue.active_item is not None:
            self._sigPauseExperiment.emit()

    @QtCore.Slot()
    def resume_current(self):
        if self._queue.active_item is not None:
            self._sigResumeExperiment.emit()

    @QtCore.Slot()
    def cancel_current(self):
        with self._thread_lock:
            item = self._queue.active_item
            if item is None:
                return
            if item.status != QueueStatus.CANCELLING:
                item = self._queue.mark_cancelling(item.item_id)
                self._emit_queue(item)
            self._sigCancelExperiment.emit()

    @QtCore.Slot(str, str)
    def _on_started(self, item_id, run_file):
        with self._thread_lock:
            item = self._queue.mark_running(item_id, run_file=run_file)
            self._emit_queue(item)

    @QtCore.Slot(str, str)
    def _on_finished(self, item_id, run_file):
        with self._thread_lock:
            item = self._queue.mark_completed(item_id, run_file=run_file)
            self._emit_queue(item)
        QtCore.QTimer.singleShot(0, self.start_next)

    @QtCore.Slot(str, str, str)
    def _on_failed(self, item_id, message, run_file):
        with self._thread_lock:
            item = self._queue.mark_failed(item_id, error=message, run_file=run_file)
            self._emit_queue(item)
        if self._queue.continue_on_failure:
            QtCore.QTimer.singleShot(0, self.start_next)

    @QtCore.Slot(str, str)
    def _on_cancelled(self, item_id, run_file):
        with self._thread_lock:
            item = self._queue.mark_cancelled(item_id, run_file=run_file)
            self._emit_queue(item)
        QtCore.QTimer.singleShot(0, self.start_next)

    @QtCore.Slot(str)
    def _on_paused(self, item_id):
        with self._thread_lock:
            item = self._queue.mark_paused(item_id)
            self._emit_queue(item)

    @QtCore.Slot(str)
    def _on_resumed(self, item_id):
        with self._thread_lock:
            item = self._queue.mark_resumed(item_id)
            self._emit_queue(item)

    @QtCore.Slot(str, float)
    def _on_progress(self, item_id, progress):
        self.sigProgressUpdated.emit(item_id, progress)
