"""Qudi interface implemented by the new nuclear experiment runner."""

from abc import abstractmethod

from PySide2 import QtCore

from qudi.core.module import Base


class NuclearOperationsRunnerInterface(Base):
    sigExperimentStarted = QtCore.Signal(str, str)  # queue item ID, run file
    sigExperimentFinished = QtCore.Signal(str, str)  # queue item ID, run file
    sigExperimentFailed = QtCore.Signal(str, str, str)  # queue item ID, message, run file
    sigExperimentCancelled = QtCore.Signal(str, str)  # queue item ID, run file
    sigExperimentPaused = QtCore.Signal(str)
    sigExperimentResumed = QtCore.Signal(str)
    sigProgressUpdated = QtCore.Signal(str, float)

    @abstractmethod
    def start_experiment(self, experiment, queue_item_id):
        """Start one serialized :class:`ExperimentSpec`."""

    @abstractmethod
    def pause_experiment(self):
        """Pause the active experiment at a safe boundary."""

    @abstractmethod
    def resume_experiment(self):
        """Resume the active experiment."""

    @abstractmethod
    def cancel_experiment(self):
        """Cooperatively cancel the active experiment."""
