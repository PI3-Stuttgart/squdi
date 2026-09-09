"""Finite optical, calibration and spin-photon protocols.

Voltage axes are explicit controller voltages. Converting lab power/frequency
units requires a measured calibration; no setup-specific conversion is guessed.
"""
import numpy as np
import xarray as xr

from .snv_qua_recipes import SnVQuaRecipe, SnVProtocol
from .recipes import AcquisitionResult
from .models import MeasurementBatch
from .analysis import evaluate_threshold


class OpticalRabiRecipe(SnVQuaRecipe):
    name = "optical_rabi"
    protocol = SnVProtocol.OPTICAL_RABI

    def analyze(self, dataset, experiment, thresholds):
        from .fitting import analyze_spin
        data = dataset.copy()
        data["result_counts"] = data["optical_counts"]
        result = analyze_spin(data, experiment, thresholds)
        if "fit_result_counts" in result:
            result = result.rename({"fit_result_counts": "fit_optical_counts"})
        return result


class OpticalPowerRabiRecipe(OpticalRabiRecipe):
    name = "optical_power_rabi"
    protocol = SnVProtocol.OPTICAL_POWER_RABI


class PleIteratorRecipe(SnVQuaRecipe):
    name = "ple_iterator"
    protocol = SnVProtocol.PLE


class InitializationCalibrationRecipe(SnVQuaRecipe):
    name = "initialization_calibration"
    protocol = SnVProtocol.INIT_CALIBRATION


class FieldAlignmentRecipe(SnVQuaRecipe):
    name = "field_alignment"
    protocol = SnVProtocol.FIELD_ALIGNMENT


class SpinPhotonCorrelationRecipe(SnVQuaRecipe):
    name = "spin_photon_correlation"
    protocol = SnVProtocol.SPIN_PHOTON

    def validate(self, experiment):
        super().validate(experiment)
        if not experiment.execution.save_raw_events:
            raise ValueError("Spin-photon correlation requires raw events")
        windows = np.asarray(experiment.parameters.get("photon_windows_ns", [[0, 1000]]), float)
        if windows.ndim != 2 or windows.shape[1] != 2 or not np.isfinite(windows).all() or np.any(windows[:, 0] >= windows[:, 1]):
            raise ValueError("photon_windows_ns must contain finite [start, end] pairs")

    def acquire(self, job, context, timeout_s):
        result = super().acquire(job, context, timeout_s)
        if not result.valid:
            return result
        ds = result.batch.dataset
        windows = np.asarray(context.parameters.get("photon_windows_ns", [[0, 1000]]))
        windows_ns = windows.copy()
        if ds.attrs.get("raw_time_unit") == "ps":
            windows = windows * 1000
        lengths = ds.optical_tag_lengths.values
        counts = np.zeros(lengths.shape + (len(windows),), dtype=np.int64)
        for record, tags in enumerate(result.batch.raw_events["optical"]):
            offset = 0
            for shot, size in enumerate(lengths[record]):
                shot_tags = tags[offset:offset+size]
                offset += size
                for window, (start, end) in enumerate(windows):
                    counts[record, shot, window] = np.count_nonzero((shot_tags >= start) & (shot_tags < end))
        ds["photon_window_counts"] = (("record", "integration", "photon_window"), counts)
        ds = ds.assign_coords(photon_window=np.arange(len(windows)),
                              window_start_ns=("photon_window", windows_ns[:, 0]),
                              window_end_ns=("photon_window", windows_ns[:, 1]))
        return AcquisitionResult(MeasurementBatch(ds, result.batch.raw_events))

    def analyze(self, dataset, experiment, thresholds):
        state, classified = evaluate_threshold(dataset.result_counts_shots, thresholds.profile.resolve("ssr_e1"))
        herald = dataset.photon_window_counts > 0
        valid = herald & classified
        denominator = valid.sum("integration")
        probability = ((state & valid).sum("integration") / denominator.where(denominator > 0))
        return xr.Dataset({"heralds": denominator, "conditional_spin_probability": probability})


def register_recipes(registry):
    for cls in (OpticalRabiRecipe, OpticalPowerRabiRecipe, PleIteratorRecipe,
                InitializationCalibrationRecipe, FieldAlignmentRecipe, SpinPhotonCorrelationRecipe):
        registry.register(cls())
