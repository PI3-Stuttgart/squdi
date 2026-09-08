"""Finite gated acquisition contract for the native NuclearOps engine."""
from abc import abstractmethod
from qudi.core.module import Base


class NuclearCounterInterface(Base):
    @abstractmethod
    def arm(self, context):
        """Prepare and start counters before submitting the QUA program."""

    @abstractmethod
    def read_streams(self, context, control, timeout_s):
        """Return named finite counts/counts_shots streams in QUA scan order."""

    @abstractmethod
    def stop(self):
        """Release active measurements, also after timeout or cancellation."""
