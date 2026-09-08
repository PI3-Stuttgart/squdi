"""Numerical fits with uncertainty and explicit failure status per scan group."""
import warnings
import numpy as np
import xarray as xr
from scipy.optimize import curve_fit, OptimizeWarning


def analyze_spin(dataset, experiment, thresholds):
    if "result_counts" not in dataset:
        return xr.Dataset()
    candidates = ("pulse_length", "MW_pulse_len", "tau", "readout_delay", "MW_f")
    axis = experiment.parameters.get("fit_axis") or next(
        (name for name in candidates if name in dataset.coords), None)
    if axis is None:
        return xr.Dataset()
    kind = experiment.recipe
    oscillatory = kind in ("nuclear_rabi", "ramsey", "optical_rabi", "optical_power_rabi")
    resonance = kind in ("pulsed_odmr", "ple_iterator", "field_alignment")
    names = (["offset", "amplitude", "frequency", "phase", "decay"] if oscillatory else
             ["offset", "amplitude", "center", "width"] if resonance else
             ["offset", "amplitude", "decay", "exponent"])
    others = [a.name for a in experiment.scan_axes if a.name != axis and a.name not in ("sweeps", "sweep")]
    keys = [tuple(dataset[name].values[i].item() for name in others) for i in range(dataset.sizes["record"])]
    groups = list(dict.fromkeys(keys))
    params = np.full((len(groups), len(names)), np.nan)
    errors = params.copy()
    success = np.zeros(len(groups), dtype=bool)
    fitted = np.full(dataset.sizes["record"], np.nan)
    messages = []
    for group_index, key in enumerate(groups):
        indices = np.asarray([i for i, k in enumerate(keys) if k == key])
        x = np.asarray(dataset[axis].values[indices], float)
        y = np.asarray(dataset.result_counts.values[indices], float)
        good = np.isfinite(x) & np.isfinite(y)
        if np.unique(x[good]).size < max(7, len(names) + 1):
            messages.append("Insufficient distinct finite points")
            continue
        origin, scale = x[good].min(), np.ptp(x[good])
        u = (x - origin) / scale
        amp = np.ptp(y[good]) or 1
        if oscillatory:
            def model(t, offset, amplitude, frequency, phase, decay):
                return offset + amplitude * np.cos(2*np.pi*frequency*t + phase) * np.exp(-t/decay)
            guesses = [[np.mean(y[good]), amp/2, f, 0, 2] for f in (1, 2, 3, 4, 5, 8)]
            bounds = ([-np.inf, -np.inf, .01, -2*np.pi, .01], [np.inf, np.inf, 100, 2*np.pi, 1000])
        elif resonance:
            def model(t, offset, amplitude, center, width):
                return offset + amplitude / (1 + ((t-center)/width)**2)
            guesses = [[max(y[good]), -amp, u[good][np.argmin(y[good])], .1]]
            bounds = ([-np.inf, -np.inf, -1, .0001], [np.inf, np.inf, 2, 10])
        else:
            def model(t, offset, amplitude, decay, exponent):
                return offset + amplitude * np.exp(-(np.maximum(t, 0)/decay)**exponent)
            guesses = [[min(y[good]), amp, .3, 1]]
            bounds = ([-np.inf, -np.inf, .0001, .1], [np.inf, np.inf, 1000, 5])
        best = None
        for guess in guesses:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", OptimizeWarning)
                    p, cov = curve_fit(model, u[good], y[good], p0=guess, bounds=bounds, maxfev=20000)
                score = np.sum((model(u[good], *p)-y[good])**2)
                if best is None or score < best[0]:
                    best = score, p, cov
            except (RuntimeError, ValueError, OptimizeWarning):
                continue
        if best is None:
            messages.append("Fit did not converge")
            continue
        _, p, cov = best
        fitted[indices] = model(u, *p)
        err = np.sqrt(np.diag(cov))
        if oscillatory:
            p[2] /= scale; err[2] /= scale
            p[4] *= scale; err[4] *= scale
        elif resonance:
            p[2] = origin + p[2]*scale; err[2] *= scale
            p[3] *= scale; err[3] *= scale
        else:
            p[2] *= scale; err[2] *= scale
        params[group_index], errors[group_index] = p, err
        success[group_index] = np.isfinite(err).all()
        messages.append("ok" if success[group_index] else "Uncertainty is not finite")
    result = xr.Dataset({
        "fit_result_counts": ("record", fitted),
        "fit_parameters": (("fit_group", "fit_parameter"), params),
        "fit_standard_errors": (("fit_group", "fit_parameter"), errors),
        "fit_success": ("fit_group", success),
        "fit_message": ("fit_group", messages),
    }, coords={"fit_parameter": names, "fit_group": np.arange(len(groups))})
    result.fit_parameters.attrs.update(axis=axis, axis_unit=dataset[axis].attrs.get("unit", ""),
                                       model=kind, phase_reference="minimum x in each group")
    for i, name in enumerate(others):
        result = result.assign_coords({"fit_" + name: ("fit_group", [key[i] for key in groups])})
    return result


def reanalyze_file(path, registry):
    """Reanalyze a completed file with its embedded threshold snapshot."""
    from .hdf5_store import NuclearDataset
    from .models import ExperimentSpec
    from .thresholds import ThresholdSnapshot
    from .analysis import analyze_readout_thresholds, combine_analysis
    run = NuclearDataset.open(path)
    spec = ExperimentSpec.from_dict(run.store.load_section("experiment"))
    snapshot = ThresholdSnapshot.from_dict(run.store.load_section("thresholds"))
    analysis = combine_analysis(analyze_readout_thresholds(run.dataset, spec, snapshot),
                                registry.get(spec.recipe).analyze(run.dataset, spec, snapshot))
    run.save_analysis(analysis)
    return analysis
