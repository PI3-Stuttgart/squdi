"""Qudi interface for direct Quantum Machines execution."""

from abc import abstractmethod

from qudi.core.module import Base


class QuantumMachineInterface(Base):
    @abstractmethod
    def execute(self, program):
        """Execute a QUA program and return its job object."""

    @abstractmethod
    def simulate(self, program, duration_cycles=10_000):
        """Simulate a QUA program and return the simulation job."""

    @abstractmethod
    def stop_current_job(self):
        """Halt the job most recently started through this module."""

    @property
    @abstractmethod
    def configuration_snapshot(self):
        """Return serializable identifying information for run provenance."""

    @property
    @abstractmethod
    def is_connected(self):
        """Return whether a quantum machine is currently open."""

