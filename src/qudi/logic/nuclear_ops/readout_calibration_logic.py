"""Qudi module providing global versioned CRC, CSR, and SSR thresholds."""

from PySide2 import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar
from qudi.util.mutex import RecursiveMutex

from .thresholds import ReadoutThresholdProfile, ThresholdRegistry, default_threshold_profile
from .models import ExperimentSpec


def _default_state():
    return ThresholdRegistry().to_dict()


class ReadoutCalibrationLogic(LogicBase):
    """Setup-wide source of all readout threshold values."""

    configured_default_profile = ConfigOption(name="default_profile", default=None)
    _registry_state = StatusVar(name="readout_threshold_registry", default=_default_state())

    sigProfilesChanged = QtCore.Signal(object)
    sigActiveProfileChanged = QtCore.Signal(str, int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._registry = None

    def on_activate(self):
        state = self._registry_state or _default_state()
        self._registry = ThresholdRegistry.from_dict(state)
        configured_default = self.configured_default_profile
        if configured_default is not None:
            configured_default = str(configured_default)
            if configured_default not in self._registry.profiles:
                if configured_default == "default":
                    self._registry.put(default_threshold_profile(), allow_same_version=True)
                else:
                    raise KeyError(
                        "Configured readout threshold profile {!r} does not exist".format(
                            configured_default
                        )
                    )
            self._registry.default_profile = configured_default
        self._save_state()

    def on_deactivate(self):
        if self._registry is not None:
            self._save_state()
        self._registry = None

    def _save_state(self):
        self._registry_state = self._registry.to_dict()

    @property
    def profiles(self):
        return self._registry.to_dict()

    def snapshot(self, profile=None, version=None):
        with self._thread_lock:
            return self._registry.snapshot(name=profile, version=version)

    def snapshot_for_experiment(self, experiment):
        spec = (
            experiment
            if isinstance(experiment, ExperimentSpec)
            else ExperimentSpec.from_dict(experiment)
        )
        with self._thread_lock:
            return self._registry.snapshot_for_experiment(spec)

    @QtCore.Slot(object)
    def set_profile(self, profile):
        model = (
            profile
            if isinstance(profile, ReadoutThresholdProfile)
            else ReadoutThresholdProfile.from_dict(profile)
        )
        with self._thread_lock:
            self._registry.put(model)
            self._save_state()
        self.sigProfilesChanged.emit(self.profiles)
        self.sigActiveProfileChanged.emit(model.name, model.version)

    @QtCore.Slot(str)
    def remove_profile(self, name):
        with self._thread_lock:
            self._registry.remove(name)
            self._save_state()
        self.sigProfilesChanged.emit(self.profiles)

    @QtCore.Slot(str)
    def set_default_profile(self, name):
        with self._thread_lock:
            self._registry.get(name)
            self._registry.default_profile = name
            self._save_state()
        profile = self._registry.get(name)
        self.sigProfilesChanged.emit(self.profiles)
        self.sigActiveProfileChanged.emit(profile.name, profile.version)
