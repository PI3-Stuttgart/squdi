"""Direct Qudi hardware module for a Quantum Machines controller.

Unlike the historical OPX holder, this module does not expose an AWG-shaped
sequence cache.  Recipes submit QUA programs directly and consume native job
result handles.
"""

import hashlib
import importlib
import importlib.metadata
from typing import Any

from qudi.core.configoption import ConfigOption
from qudi.interface.quantum_machine_interface import QuantumMachineInterface
from qudi.util.mutex import RecursiveMutex


class QuantumMachineHardware(QuantumMachineInterface):
    configuration_module = ConfigOption(
        name="configuration_module",
        default="qudi.hardware.OPX.configuration",
    )
    close_on_deactivate = ConfigOption(name="close_on_deactivate", default=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._configuration = None
        self._qmm = None
        self._qm = None
        self._current_job = None

    def on_activate(self):
        self._configuration = importlib.import_module(str(self.configuration_module))
        self._connect()

    def on_deactivate(self):
        self.stop_current_job()
        if bool(self.close_on_deactivate) and self._qm is not None:
            close = getattr(self._qm, "close", None)
            if callable(close):
                close()
        self._current_job = None
        self._qm = None
        self._qmm = None

    def _connect(self):
        from qm.quantum_machines_manager import QuantumMachinesManager

        kwargs = {"host": self._configuration.qop_ip}
        cluster_name = getattr(self._configuration, "cluster_name", None)
        octave_config = getattr(self._configuration, "octave_config", None)
        if cluster_name is not None:
            kwargs["cluster_name"] = cluster_name
        if octave_config is not None:
            kwargs["octave"] = octave_config
        self._qmm = QuantumMachinesManager(**kwargs)
        self._qm = self._qmm.open_qm(config=self._configuration.config)

    def execute(self, program):
        with self._thread_lock:
            if self._qm is None:
                raise RuntimeError("Quantum Machine hardware is not connected")
            self.stop_current_job()
            self._current_job = self._qm.execute(program)
            return self._current_job

    def simulate(self, program, duration_cycles=10_000):
        from qm import SimulationConfig

        with self._thread_lock:
            if self._qmm is None:
                raise RuntimeError("Quantum Machine hardware is not connected")
            return self._qmm.simulate(
                self._configuration.config,
                program,
                SimulationConfig(duration=int(duration_cycles)),
            )

    def stop_current_job(self):
        with self._thread_lock:
            job = self._current_job
            self._current_job = None
            if job is None:
                return
            halt = getattr(job, "halt", None)
            if callable(halt):
                halt()

    @property
    def is_connected(self):
        return self._qm is not None

    @property
    def qm(self):
        """Native QM object for setup-level controls that are not job execution."""

        return self._qm

    @property
    def configuration_snapshot(self):
        configuration = getattr(self._configuration, "config", {})
        digest = hashlib.sha256(repr(configuration).encode("utf-8")).hexdigest()
        try:
            qm_version = importlib.metadata.version("qm-qua")
        except importlib.metadata.PackageNotFoundError:
            qm_version = "unknown"
        return {
            "module": str(self.configuration_module),
            "sha256": digest,
            "cluster_name": getattr(self._configuration, "cluster_name", ""),
            "qop_host": getattr(self._configuration, "qop_ip", ""),
            "qm_qua_version": qm_version,
        }

