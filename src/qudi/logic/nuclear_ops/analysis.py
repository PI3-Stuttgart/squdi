"""Reusable xarray analysis for global CRC, CSR and SSR thresholds."""

from typing import Tuple

import numpy as np
import xarray as xr

from .thresholds import ThresholdRule, ThresholdSnapshot


def evaluate_threshold(values: xr.DataArray, rule: ThresholdRule) -> Tuple[xr.DataArray, xr.DataArray]:
    """Return ``(accepted, classified)`` masks for a threshold rule.

    ``classified`` is false in the configured exclusion band.  This preserves
    the distinction between a rejected physical state and an ambiguous shot.
    """

    lower = rule.counts - rule.exclusion_width
    upper = rule.counts + rule.exclusion_width
    if rule.comparison == ">":
        accepted = values > upper
    elif rule.comparison == ">=":
        accepted = values >= upper
    elif rule.comparison == "<":
        accepted = values < lower
    else:
        accepted = values <= lower
    classified = (values <= lower) | (values >= upper)
    if rule.exclusion_width == 0:
        classified = xr.ones_like(values, dtype=bool)
    return accepted.astype(bool), classified.astype(bool)


def analyze_readout_thresholds(
    dataset: xr.Dataset,
    experiment,
    thresholds: ThresholdSnapshot,
) -> xr.Dataset:
    """Apply every experiment readout step and return derived xarray variables."""

    variables = {}
    for step in experiment.readout:
        if step.output_name not in dataset:
            raise KeyError(
                "Readout {!r} expects data variable {!r}".format(
                    step.kind.value, step.output_name
                )
            )
        source = dataset[step.output_name]
        rule = thresholds.profile.resolve(step.threshold_ref)
        accepted, classified = evaluate_threshold(source, rule)
        base = "{}_{}".format(step.output_name, step.threshold_ref)
        accepted.attrs.update(
            threshold_counts=rule.counts,
            threshold_comparison=rule.comparison,
            threshold_profile=thresholds.profile.name,
            threshold_version=thresholds.profile.version,
        )
        classified.attrs.update(exclusion_width=rule.exclusion_width)
        variables[base + "_accepted"] = accepted
        variables[base + "_classified"] = classified

    if not variables:
        return xr.Dataset(coords={name: value for name, value in dataset.coords.items()})
    return xr.Dataset(variables)


def combine_analysis(*datasets: xr.Dataset) -> xr.Dataset:
    """Merge independent analysis products while rejecting name conflicts."""

    non_empty = [dataset for dataset in datasets if dataset is not None]
    if not non_empty:
        return xr.Dataset()
    return xr.merge(non_empty, compat="identical", join="exact")
