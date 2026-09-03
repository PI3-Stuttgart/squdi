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


def calculate_pid_wrap_preview(
    snapshot,
    vpi=0.36,
    min_value=-0.6,
    max_value=0.6,
    margin=0.05,
    output_tolerance=1e-3,
    state_tolerance=0.01,
):
    """Calculate a P-aware wrap from one coherent PID snapshot."""
    output = float(snapshot['output'])
    integrator_before = float(snapshot['integrator_before'])
    integrator = float(snapshot['integrator_after'])
    integrator_change = float(snapshot['integrator_change_during_read'])
    proportional_gain = float(snapshot['proportional_gain'])
    setpoint = float(snapshot['setpoint'])
    pid_minimum = float(snapshot['pid_minimum'])
    pid_maximum = float(snapshot['pid_maximum'])
    minimum = float(min_value)
    maximum = float(max_value)
    output_tolerance = float(output_tolerance)
    state_tolerance = float(state_tolerance)

    values = (
        output,
        integrator_before,
        integrator,
        integrator_change,
        proportional_gain,
        setpoint,
        pid_minimum,
        pid_maximum,
        minimum,
        maximum,
        output_tolerance,
        state_tolerance,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("PID wrap snapshot values must be finite.")
    if output_tolerance < 0 or state_tolerance < 0:
        raise ValueError("PID wrap tolerances must not be negative.")
    if minimum >= maximum:
        raise ValueError("min_value must be smaller than max_value.")
    if pid_minimum >= pid_maximum:
        raise ValueError("PID snapshot contains invalid output limits.")

    decision_output = output
    if minimum - output_tolerance <= output < minimum:
        decision_output = minimum
    elif maximum < output <= maximum + output_tolerance:
        decision_output = maximum

    if decision_output < minimum or decision_output > maximum:
        return {
            **dict(snapshot),
            'decision_output': decision_output,
            'should_wrap': False,
            'action_mode': None,
            'action_reason': 'output_outside_expected_range',
            'manual_write_ready': False,
            'target_output': None,
            'target_integrator': None,
        }

    decision = calculate_wrap(
        current_value=decision_output,
        vpi=vpi,
        min_value=minimum,
        max_value=maximum,
        margin=margin,
    )
    preview = {
        **dict(snapshot),
        'decision_output': decision_output,
        'should_wrap': decision.should_wrap,
        'periods': decision.periods,
        'reason': decision.reason,
        'vpi': float(vpi),
        'period': 2.0 * float(vpi),
        'minimum': minimum,
        'maximum': maximum,
        'safe_minimum': minimum + float(margin),
        'safe_maximum': maximum - float(margin),
        'target_output': decision.target if decision.should_wrap else None,
        'target_integrator': None,
        'proportional_term': None,
        'p_model_ready': False,
        'manual_write_ready': False,
    }
    if not decision.should_wrap:
        preview.update(action_mode=None, action_reason=decision.reason)
        return preview

    action_mode = (
        'windup_recovery'
        if integrator < pid_minimum or integrator > pid_maximum
        else 'normal_wrap'
    )
    preview['action_mode'] = action_mode

    input_filter = [float(value) for value in snapshot['input_filter']]
    filters_are_off = all(abs(value) <= 1e-12 for value in input_filter)
    differential_mode = bool(snapshot.get('differential_mode_enabled', False))
    source_output = snapshot.get('input_source_output')

    if abs(proportional_gain) <= 1e-12:
        proportional_term = 0.0
    elif source_output is None:
        preview['action_reason'] = 'pid_input_source_not_readable'
        return preview
    elif not filters_are_off:
        preview['action_reason'] = 'pid_input_filter_not_supported'
        return preview
    elif differential_mode:
        preview['action_reason'] = 'differential_pid_not_supported'
        return preview
    else:
        source_output = float(source_output)
        if not math.isfinite(source_output):
            preview['action_reason'] = 'pid_input_source_not_finite'
            return preview
        proportional_term = proportional_gain * (source_output - setpoint)

    target_integrator = decision.target - proportional_term
    preview.update(
        proportional_term=proportional_term,
        p_model_ready=True,
        target_integrator=target_integrator,
    )
    if abs(integrator_change) > state_tolerance:
        preview['action_reason'] = 'integrator_changed_during_snapshot'
        return preview
    if not -4.0 <= target_integrator <= 4.0:
        preview['action_reason'] = 'target_integrator_outside_hardware_range'
        return preview

    preview.update(
        manual_write_ready=True,
        action_reason='confirmation_required',
    )
    return preview
