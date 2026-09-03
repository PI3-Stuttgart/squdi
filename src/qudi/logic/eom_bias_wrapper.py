"""Pure calculations for keeping a periodic EOM bias inside a safe range.

This module deliberately contains no Qudi, PyRPL, GUI, or hardware access.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class WrapDecision:
    """Result of evaluating one PID integrator value."""

    should_wrap: bool
    target: float
    periods: int
    reason: str


def calculate_wrap(
    current_value,
    vpi=0.36,
    min_value=-0.6,
    max_value=0.6,
    margin=0.05,
):
    """Return an optically equivalent bias target inside the safe range.

    Equivalent EOM operating points differ by ``2 * vpi``.  No value is
    changed here; the function only calculates a decision.
    """
    current = float(current_value)
    vpi = float(vpi)
    minimum = float(min_value)
    maximum = float(max_value)
    margin = float(margin)

    values = (current, vpi, minimum, maximum, margin)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("All bias-wrapper values must be finite.")
    if vpi <= 0:
        raise ValueError("Vpi must be greater than zero.")
    if minimum >= maximum:
        raise ValueError("min_value must be smaller than max_value.")
    if margin < 0:
        raise ValueError("margin must not be negative.")

    safe_minimum = minimum + margin
    safe_maximum = maximum - margin
    if safe_minimum >= safe_maximum:
        raise ValueError("margin leaves no usable bias range.")

    comparison_tolerance = 1e-12 * max(
        1.0,
        abs(current),
        abs(minimum),
        abs(maximum),
        abs(safe_minimum),
        abs(safe_maximum),
    )
    if (
        current < minimum - comparison_tolerance
        or current > maximum + comparison_tolerance
    ):
        return WrapDecision(
            False,
            current,
            0,
            "integrator_outside_output_range",
        )

    if (
        safe_minimum - comparison_tolerance
        <= current
        <= safe_maximum + comparison_tolerance
    ):
        return WrapDecision(False, current, 0, "inside_safe_range")

    period = 2.0 * vpi
    lowest_periods = math.ceil((safe_minimum - current) / period)
    highest_periods = math.floor((safe_maximum - current) / period)
    if lowest_periods > highest_periods:
        return WrapDecision(
            False,
            current,
            0,
            "no_equivalent_target_in_safe_range",
        )

    centre = 0.5 * (safe_minimum + safe_maximum)
    ideal_periods = (centre - current) / period
    candidates = {
        lowest_periods,
        highest_periods,
        max(lowest_periods, min(highest_periods, math.floor(ideal_periods))),
        max(lowest_periods, min(highest_periods, math.ceil(ideal_periods))),
    }
    periods = min(
        candidates,
        key=lambda count: (
            abs((current + count * period) - centre),
            abs(count),
        ),
    )
    target = current + periods * period
    return WrapDecision(True, target, periods, "outside_safe_range")


def calculate_wrap_preview(
    current_value,
    vpi=0.36,
    min_value=-0.6,
    max_value=0.6,
    margin=0.05,
):
    """Return a serializable preview without changing any hardware value."""
    decision = calculate_wrap(
        current_value=current_value,
        vpi=vpi,
        min_value=min_value,
        max_value=max_value,
        margin=margin,
    )
    vpi = float(vpi)
    minimum = float(min_value)
    maximum = float(max_value)
    margin = float(margin)
    preview = {
        "current": float(current_value),
        "should_wrap": decision.should_wrap,
        "target": decision.target,
        "periods": decision.periods,
        "reason": decision.reason,
        "vpi": vpi,
        "period": 2.0 * vpi,
        "minimum": minimum,
        "maximum": maximum,
        "safe_minimum": minimum + margin,
        "safe_maximum": maximum - margin,
    }

    if decision.reason == "integrator_outside_output_range":
        saturated_output = minimum if float(current_value) < minimum else maximum
        recovery = calculate_wrap(
            current_value=saturated_output,
            vpi=vpi,
            min_value=minimum,
            max_value=maximum,
            margin=margin,
        )
        preview.update(
            recovery_required=True,
            saturated_output=saturated_output,
            recovery_available=recovery.should_wrap,
            recovery_target=recovery.target if recovery.should_wrap else None,
            recovery_periods=recovery.periods if recovery.should_wrap else 0,
            recovery_assumes_p_zero=True,
        )
    else:
        preview.update(
            recovery_required=False,
            saturated_output=None,
            recovery_available=False,
            recovery_target=None,
            recovery_periods=0,
            recovery_assumes_p_zero=False,
        )

    return preview
