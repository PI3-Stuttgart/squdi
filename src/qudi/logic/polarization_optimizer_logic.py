"""
Qudi logic module for automatic polarization optimization.

Ported from polarization_optimizer.py while preserving the optimization
algorithm. Only the hardware interface has been adapted for Qudi.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from itertools import product

import numpy as np
from qtpy.QtCore import Signal

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption


class FoundMinimum(Exception):
    pass


class OptimizationTimeout(Exception):
    pass


class PolarizationOptimizerLogic(LogicBase):
    """
    Automatic polarization optimizer.

    This is a Qudi port of the standalone PolarizationOptimizer.
    """

    mpc = Connector(interface="Base")
    powermeter = Connector(interface="ProcessValueInterface")

    _power_channel = ConfigOption("power_channel", default="Power")
    _target_power_nw = ConfigOption("target_power_nw", default=2.5)
    _lock_threshold_nw = ConfigOption("lock_threshold_nw", default=2.5)
    _hold_threshold_nw = ConfigOption("hold_threshold_nw", default=1.5)
    _lock_interval_s = ConfigOption("lock_interval_s", default=1.0)
    _lock_consecutive_bad = ConfigOption("consecutive_bad_reads", default=3)
    _samples = ConfigOption("samples", default=5)
    _coarse_samples = ConfigOption("coarse_samples", default=3)
    _coarse_step_deg = ConfigOption("coarse_step_deg", default=5.0)
    _coarse_timeout_s = ConfigOption("coarse_timeout_s", default=180.0)
    _optimization_timeout_s = ConfigOption("optimization_timeout_s", default=30.0)
    _edge_margin_deg = ConfigOption("edge_margin_deg", default=10.0)
    _edge_recenter_step_deg = ConfigOption("edge_recenter_step_deg", default=0.5)
    _fine_initial_step_deg = ConfigOption("fine_initial_step_deg", default=1.5)
    _fine_final_step_deg = ConfigOption("fine_final_step_deg", default=0.05)
    _fine_step_levels = ConfigOption("fine_step_levels", default=6)
    # One-based paddle number. Paddle 2 is the expected lambda/2 plate.
    _equivalent_relocation_paddle = ConfigOption("equivalent_relocation_paddle", default=2)
    _equivalent_period_guess_deg = ConfigOption("equivalent_period_guess_deg", default=90.0)
    _equivalent_period_fit_window_deg = ConfigOption("equivalent_period_fit_window_deg", default=25.0)

    sigOptimizationStarted = Signal()
    sigOptimizationFinished = Signal(object, float)

    sigLockStarted = Signal()
    sigLockStopped = Signal()

    sigLoggingStarted = Signal()
    sigLoggingStopped = Signal()

    sigPowerUpdated = Signal(float)
    sigBestPowerUpdated = Signal(float)
    sigPaddlePositionsUpdated = Signal(float, float, float)

    # Unix timestamp, power, [paddle1, paddle2, paddle3], polarization state
    sigLogSample = Signal(float, float, object, str)
    sigLogStateChanged = Signal(bool)
    sigLockStateChanged = Signal(bool)
    sigCombinedStateChanged = Signal(bool)
    sigOperationStatusChanged = Signal(str)
    # phase, completion percentage, human-readable progress detail
    sigOptimizationProgress = Signal(str, int, str)
    # User-facing operation, current low-level action, and elapsed-time progress.
    sigProcessStateChanged = Signal(str)
    sigCurrentActionChanged = Signal(str)
    # Lock priority is intentionally a compact machine-readable state for the GUI.
    sigLockPriorityChanged = Signal(str)
    # Zero-based paddle indices currently commanded to move.
    sigActivePaddlesChanged = Signal(object)
    sigElapsedProgress = Signal(int, float, float)
    sigError = Signal(str)

    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)

        self.threshold = 2.5  # Upper/master threshold.
        self.hold_threshold = 1.5  # Lower threshold for gentle trimming.

        self.best_power = np.inf
        self.best_angles = None

        self.pause_logging = threading.Event()

        # Separate events
        self._stop_lock_event = threading.Event()
        self._stop_log_event = threading.Event()
        self._stop_combined_event = threading.Event()
        self._stop_optimization_event = threading.Event()

        self.io_lock = threading.RLock()

        self._deadline = None
        self._progress_started = None
        self._progress_duration = None
        self._process_started = None
        self._process_budget = None
        self._process_name = "Idle"
        self._lock_correction_active = False
        self._edge_margin_override = None
        self._fine_initial_step_override = None
        self._fine_final_step_override = None
        self._fine_step_levels_override = None
        # Coarse-scan evidence is retained per paddle for equivalent-minimum relocation.
        self._coarse_basin_angles = [np.empty(0, dtype=float) for _ in range(3)]
        self._fitted_periods_deg = [None, None, None]

        self._lock_thread = None
        self._log_thread = None
        self._optimization_thread = None
        self._combined_thread = None
        self._power_channel_was_active = False

    def on_activate(self):
        self._mpc = self.mpc()
        self._pm = self.powermeter()
        self.threshold = float(self._lock_threshold_nw)
        self.hold_threshold = min(float(self._hold_threshold_nw), self.threshold - 1e-6)
        self._power_channel_was_active = self._pm.get_activity_state(self._power_channel)
        if not self._power_channel_was_active:
            self._pm.set_activity_state(self._power_channel, True)

    def on_deactivate(self):
        self._stop_combined_event.set()
        self._stop_optimization_event.set()
        self.stop_lock()
        self.stop_log()
        for thread in (self._optimization_thread, self._combined_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
        if not self._power_channel_was_active and self._pm.get_activity_state(self._power_channel):
            self._pm.set_activity_state(self._power_channel, False)

    # ------------------------------------------------------------------
    # Hardware helpers
    # ------------------------------------------------------------------

    def read_power_nw(self):
        """
        Read optical power in nW.
        """
        power = float(self._pm.get_process_value(self._power_channel) * 1e9)
        if not np.isfinite(power):
            raise ValueError(f"Power meter returned a non-finite value: {power!r}")
        return power

    def _check_deadline(self):
        self._emit_timeout_progress()
        self._emit_elapsed_progress()
        if self._stop_optimization_event.is_set():
            raise OptimizationTimeout
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise OptimizationTimeout

    def _begin_process(self, name, budget_seconds=None):
        self._process_name = name
        self._process_started = time.monotonic()
        self._process_budget = (
            max(0.001, float(budget_seconds)) if budget_seconds is not None else None
        )
        self.sigProcessStateChanged.emit(name)
        self.sigElapsedProgress.emit(0, 0.0, self._process_budget or 0.0)

    def _emit_elapsed_progress(self, complete=False):
        if self._process_started is None:
            return
        elapsed = time.monotonic() - self._process_started
        if complete:
            percent = 100
        elif self._process_budget is None:
            percent = 0
        else:
            percent = min(99, round(100 * elapsed / self._process_budget))
        self.sigElapsedProgress.emit(percent, elapsed, self._process_budget or 0.0)

    def _end_process(self):
        self._emit_elapsed_progress(complete=True)
        self._process_started = None
        self._process_budget = None
        self._process_name = "Idle"
        self.sigActivePaddlesChanged.emit(())
        self.sigLockPriorityChanged.emit("idle")
        self.sigCurrentActionChanged.emit("Waiting")
        self.sigProcessStateChanged.emit("Idle")

    def _polarization_state(self, power):
        if self._process_name in {
            "Coarse optimisation",
            "Fine optimisation",
            "Coarse + fine optimisation",
        } or self._lock_correction_active:
            return "Polarisation optimizing"
        if power < self.threshold:
            return "Polarisation okay"
        return "Polarisation drifting"

    def _start_progress_phase(self, phase, duration, detail=""):
        self._progress_started = time.monotonic()
        self._progress_duration = max(float(duration), 0.001)
        self.sigOptimizationProgress.emit(phase, 0, detail)

    def _emit_timeout_progress(self):
        """Update timeout-based phases without relying on a GUI-side timer."""
        if self._progress_started is None or self._progress_duration is None:
            return
        elapsed = time.monotonic() - self._progress_started
        percent = min(99, max(0, round(100 * elapsed / self._progress_duration)))
        remaining = max(0.0, self._progress_duration - elapsed)
        self.sigOptimizationProgress.emit(
            "Fine polarization adjustment", percent, f"Up to {remaining:.0f} s remaining"
        )

    def measure(self):
        self._check_deadline()

        if self._stop_optimization_event.wait(0.02):
            raise OptimizationTimeout

        self.sigCurrentActionChanged.emit("Reading optical power")
        power = self.read_power_nw()
        self.sigPowerUpdated.emit(power)
        return power

    def _move_to_angles(self, angles, timeout=None):
        """Move paddles and publish both active axes and confirmed positions."""
        target = np.asarray(angles, dtype=float)
        try:
            before = np.asarray(self._mpc.positions(), dtype=float)
            active_axes = tuple(np.flatnonzero(np.abs(target - before) > 1e-3).tolist())
        except Exception:
            # The command still proceeds; the GUI can simply show an unknown/all-axis move.
            active_axes = (0, 1, 2)
        self.sigActivePaddlesChanged.emit(active_axes)
        self._mpc.set_angles(*target, timeout=timeout)
        positions = np.asarray(self._mpc.positions(), dtype=float)
        self.sigPaddlePositionsUpdated.emit(*positions.tolist())
        return positions

    def _edge_margin(self):
        """Return the active forbidden-edge width, constrained to a valid range."""
        value = self._edge_margin_deg if self._edge_margin_override is None else self._edge_margin_override
        return min(79.9, max(0.0, float(value)))

    def _safe_angle_bounds(self):
        margin = self._edge_margin()
        return margin, 160.0 - margin

    def _clamp_to_safe_range(self, angles):
        lower, upper = self._safe_angle_bounds()
        return np.clip(np.asarray(angles, dtype=float), lower, upper)

    def _edge_directions(self, angles):
        """Return inward directions for paddles inside a forbidden edge zone."""
        lower, upper = self._safe_angle_bounds()
        directions = np.zeros(3, dtype=float)
        angles = np.asarray(angles, dtype=float)
        directions[angles <= lower] = 1.0
        directions[angles >= upper] = -1.0
        return directions

    def _edge_clearance(self, angles):
        """Smallest distance of any paddle from a physical travel limit."""
        angles = np.asarray(angles, dtype=float)
        return float(np.min(np.minimum(angles, 160.0 - angles)))

    def _edge_urgency(self, angles):
        """0 outside the margin and 1 at a hard edge, used for prioritisation."""
        margin = self._edge_margin()
        if margin <= 0:
            return 0.0
        return float(np.clip((margin - self._edge_clearance(angles)) / margin, 0.0, 1.0))

    def _store_coarse_basins(self, paddle_idx, candidates):
        """Extract local basins and fit an observed repeat distance when possible."""
        angles = np.asarray([item[1][paddle_idx] for item in candidates], dtype=float)
        powers = np.asarray([item[0] for item in candidates], dtype=float)
        order = np.argsort(angles)
        angles, powers = angles[order], powers[order]
        if angles.size < 3:
            self._coarse_basin_angles[paddle_idx] = np.empty(0, dtype=float)
            self._fitted_periods_deg[paddle_idx] = None
            return

        basin_indices = [
            index for index in range(1, len(angles) - 1)
            if powers[index] <= powers[index - 1] and powers[index] <= powers[index + 1]
        ]
        if powers[0] <= powers[1]:
            basin_indices.insert(0, 0)
        if powers[-1] <= powers[-2]:
            basin_indices.append(len(angles) - 1)
        basins = np.unique(angles[basin_indices])
        self._coarse_basin_angles[paddle_idx] = basins

        if basins.size < 2:
            self._fitted_periods_deg[paddle_idx] = None
            self.log.info('Coarse scan paddle %d found %d basin(s); no repeat fit',
                          paddle_idx + 1, basins.size)
            return

        separations = np.array([
            abs(right - left) for left_index, left in enumerate(basins)
            for right in basins[left_index + 1:]
        ])
        if paddle_idx == int(self._equivalent_relocation_paddle) - 1:
            guess = float(self._equivalent_period_guess_deg)
            window = max(1.0, float(self._equivalent_period_fit_window_deg))
            supported = separations[np.abs(separations - guess) <= window]
        else:
            supported = np.diff(basins)
            if supported.size > 1:
                median = float(np.median(supported))
                supported = supported[np.abs(supported - median) <= max(2.0, 0.2 * median)]

        if supported.size:
            period = float(np.median(supported))
            self._fitted_periods_deg[paddle_idx] = period
            self.log.info('Coarse scan fitted paddle %d repeat distance: %.3f degrees from %d basin(s)',
                          paddle_idx + 1, period, basins.size)
        else:
            self._fitted_periods_deg[paddle_idx] = None
            self.log.info('Coarse scan paddle %d basins do not support a repeat fit', paddle_idx + 1)

    def _equivalent_relocation_target(self, positions):
        """Return (paddle index, safe equivalent angle, fitted period), or None."""
        paddle_idx = int(self._equivalent_relocation_paddle) - 1
        if not 0 <= paddle_idx < 3:
            self.log.warning('Equivalent relocation paddle %r is invalid', self._equivalent_relocation_paddle)
            return None
        period = self._fitted_periods_deg[paddle_idx]
        if period is None or period <= 0.0:
            return None
        positions = np.asarray(positions, dtype=float)
        # Relocate only when the configured lambda/2 paddle itself is at an edge.
        if self._edge_directions(positions)[paddle_idx] == 0.0:
            return None
        lower, upper = self._safe_angle_bounds()
        candidates = [
            candidate for candidate in (positions[paddle_idx] - period, positions[paddle_idx] + period)
            if lower < candidate < upper
        ]
        if not candidates:
            return None
        target = max(candidates, key=lambda candidate: min(candidate - lower, upper - candidate))
        return paddle_idx, float(target), float(period)

    def _relocate_to_equivalent_minimum(self, positions):
        """Directly jump to an interior equivalent, then run bounded fine recovery."""
        predicted = self._equivalent_relocation_target(positions)
        if predicted is None:
            return False
        paddle_idx, target_angle, period = predicted
        target = np.asarray(positions, dtype=float).copy()
        target[paddle_idx] = target_angle
        self.sigLockPriorityChanged.emit('equivalent_relocation')
        self.sigCurrentActionChanged.emit(
            f'Equivalent-minimum relocation: paddle {paddle_idx + 1} to {target_angle:.2f} degrees '
            f'(fitted period {period:.2f} degrees)'
        )
        with self.io_lock:
            self._move_to_angles(target)
        # The jump is intentionally direct. Fine search then performs only
        # small safe corrections for the real, non-ideal optical train.
        self.sigCurrentActionChanged.emit('Refining relocated equivalent minimum')
        self.find_minimum(
            target,
            fallback_coarse=False,
            fast=True,
            timeout_seconds=min(30.0, float(self._optimization_timeout_s)),
        )
        return True
    def _candidate_is_acceptable(self, candidate_power, current_power, master_threshold):
        """Do not retain a move that violates the master safety threshold."""
        if current_power <= master_threshold:
            return candidate_power <= master_threshold
        # If already above the master threshold, only keep a strict improvement.
        return candidate_power < current_power
    def _fine_steps(self):
        initial = self._fine_initial_step_deg if self._fine_initial_step_override is None else self._fine_initial_step_override
        final = self._fine_final_step_deg if self._fine_final_step_override is None else self._fine_final_step_override
        levels = self._fine_step_levels if self._fine_step_levels_override is None else self._fine_step_levels_override
        initial, final = float(initial), float(final)
        levels = max(2, int(levels))
        if final <= 0 or initial <= 0:
            raise ValueError("Fine step sizes must be greater than zero")
        if final > initial:
            initial, final = final, initial
        return np.geomspace(initial, final, levels)
    def measure_power(self, samples=5, delay=0.05):
        values = []
        self.sigCurrentActionChanged.emit(f"Averaging {samples} power readings")

        for _ in range(samples):
            self._check_deadline()

            values.append(self.read_power_nw())

            self._check_deadline()

            if self._stop_optimization_event.wait(delay):
                raise OptimizationTimeout

        power = float(np.mean(values))

        self.sigPowerUpdated.emit(power)

        return power
    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def coarse_search(self, center, step=20):
        """Sweep the full range and select only a safe final coarse minimum.

        Edge-zone angles are measured normally. They are excluded only when a
        stage chooses its retained candidate, so a lower-power edge minimum is
        replaced by the next-lowest candidate with usable paddle travel.
        """
        del center
        step = float(step)
        if step <= 0:
            raise ValueError("Coarse scan step must be greater than zero")
        scan_angles = np.unique(np.append(np.arange(0.0, 160.0, step), 160.0))

        with self.io_lock:
            best_angles = np.clip(np.asarray(self._mpc.positions(), dtype=float), 0.0, 160.0)
            self.sigPaddlePositionsUpdated.emit(*best_angles.tolist())
            best_power = self.measure_power(samples=int(self._coarse_samples), delay=0.01)
        self.best_angles, self.best_power = best_angles.copy(), best_power
        self.sigBestPowerUpdated.emit(best_power)

        for paddle_idx in range(3):
            candidates = []
            for angle in scan_angles:
                self._check_deadline()
                test = best_angles.copy()
                test[paddle_idx] = angle
                self.sigCurrentActionChanged.emit(
                    f"Coarse scan: paddle {paddle_idx + 1} at {angle:.1f}°"
                )
                with self.io_lock:
                    self._move_to_angles(test)
                    power = self.measure_power(samples=int(self._coarse_samples), delay=0.01)
                candidates.append((power, test.copy()))

            self._store_coarse_basins(paddle_idx, candidates)

            # Prefer complete safe configurations. During earlier coordinate
            # stages another paddle may still be in the margin, so retain an
            # intermediate candidate that is at least safe for this axis; all
            # three axes are safe after the final stage.
            safe = [item for item in candidates if not np.any(self._edge_directions(item[1]))]
            axis_safe = [item for item in candidates if not self._edge_directions(item[1])[paddle_idx]]
            pool = safe or axis_safe
            if not pool:
                raise RuntimeError("No coarse candidate remains outside the edge margin")
            raw_power, raw_angles = min(candidates, key=lambda item: item[0])
            best_power, best_angles = min(pool, key=lambda item: item[0])
            self.best_angles, self.best_power = best_angles.copy(), best_power
            self.sigBestPowerUpdated.emit(best_power)
            if raw_power < best_power:
                self.log.info(
                    "Ignored edge-zone coarse minimum %s at %.2f nW; selected safe %s at %.2f nW",
                    np.round(raw_angles, 2), raw_power, np.round(best_angles, 2), best_power,
                )

        if np.any(self._edge_directions(best_angles)):
            raise RuntimeError("Coarse scan could not construct a final edge-safe configuration")
        with self.io_lock:
            self._move_to_angles(best_angles)
        return best_angles, best_power
    def objective(self, ang, fast=False):
        """
        Objective function used by scipy.optimize.minimize().
        """

        self._check_deadline()

        ang = np.asarray(ang, dtype=float)

        if np.any((ang < 0) | (ang > 160)):
            return 1e9

        remaining = (
            max(1.0, self._deadline - time.monotonic())
            if self._deadline
            else 10.0
        )

        # keep the timeout calculation from the original implementation
        timeout = min(10.0, remaining)

        self.sigCurrentActionChanged.emit(
            f"Moving paddles to {np.round(ang, 1).tolist()}°"
        )
        # Serialize one complete evaluation, then release the hardware so the
        # independent logger can record before the next scipy evaluation.
        with self.io_lock:
            self._move_to_angles(ang, timeout=timeout)

            if self._stop_optimization_event.wait(0.10 if fast else 0.30):
                raise OptimizationTimeout

            power = self.measure_power(
                samples=3 if fast else int(self._samples),
                delay=0.005 if fast else 0.01,
            )

        # Yield after releasing the hardware transaction so a due logging
        # sample can acquire io_lock before scipy requests the next point.
        if self._stop_optimization_event.wait(0.01):
            raise OptimizationTimeout

        if power < self.best_power:

            self.best_power = power
            self.best_angles = ang.copy()
            self.sigBestPowerUpdated.emit(power)

            self.log.info(
                f"New best: "
                f"{np.round(ang,2)} "
                f"{power:.1f} nW"
            )

        if power < self.threshold:
            raise FoundMinimum

        return power
    def _fine_coordinate_search(self, start, fast=False):
        """Refine with small coordinate moves and logarithmically shrinking steps."""
        best_angles = self._clamp_to_safe_range(start)
        sample_count = 3 if fast else int(self._samples)
        settle_time = 0.05 if fast else 0.15
        with self.io_lock:
            self._move_to_angles(best_angles)
            if self._stop_optimization_event.wait(settle_time):
                raise OptimizationTimeout
            best_power = self.measure_power(samples=sample_count, delay=0.01)
        self.best_angles, self.best_power = best_angles.copy(), best_power
        self.sigBestPowerUpdated.emit(best_power)

        for step in self._fine_steps():
            # Two local passes allow a gentle path along a tilted minimum while
            # still capping every physical movement at the current step size.
            for _ in range(2):
                improved = False
                for axis in range(3):
                    base = best_angles.copy()
                    for direction in (-1.0, 1.0):
                        self._check_deadline()
                        candidate = base.copy()
                        candidate[axis] = np.clip(base[axis] + direction * step,
                                                  *self._safe_angle_bounds())
                        if np.isclose(candidate[axis], base[axis]):
                            continue
                        self.sigCurrentActionChanged.emit(
                            f"Fine adjustment: paddle {axis + 1} by {direction * step:+.3f}°"
                        )
                        with self.io_lock:
                            self._move_to_angles(candidate)
                            if self._stop_optimization_event.wait(settle_time):
                                raise OptimizationTimeout
                            power = self.measure_power(samples=sample_count, delay=0.01)
                        if power < best_power:
                            best_angles, best_power, improved = candidate, power, True
                            self.best_angles, self.best_power = best_angles.copy(), best_power
                            self.sigBestPowerUpdated.emit(best_power)
                            self.log.info("Fine best: %s %.2f nW", np.round(best_angles, 3), best_power)
                            base = best_angles.copy()
                        else:
                            # Return immediately to the known good point before
                            # trying another direction, preventing accumulated jumps.
                            with self.io_lock:
                                self._move_to_angles(best_angles)
                    if best_power <= self.threshold:
                        break
                if best_power <= self.threshold or not improved:
                    break
            if best_power <= self.threshold:
                break

        with self.io_lock:
            self._move_to_angles(best_angles)
        return best_angles, best_power

    def find_minimum(
        self, start, fallback_coarse=True, coarse_start=None, coarse_step=None,
        max_restarts=3, fast=False, timeout_seconds=None,
    ):
        """Run bounded, edge-aware logarithmic fine optimization."""
        del max_restarts
        timeout_seconds = float(self._optimization_timeout_s if timeout_seconds is None else timeout_seconds)
        coarse_step = float(self._coarse_step_deg if coarse_step is None else coarse_step)
        previous_deadline = self._deadline
        self._deadline = time.monotonic() + timeout_seconds
        self.best_power, self.best_angles = np.inf, None
        self.sigOptimizationStarted.emit()
        self._start_progress_phase("Fine polarization adjustment", timeout_seconds,
                                   f"Up to {timeout_seconds:.0f} s remaining")
        try:
            self._fine_coordinate_search(start, fast=fast)
        except OptimizationTimeout:
            self.log.info("Fine optimization stopped after %.1f s", timeout_seconds)
        except TimeoutError as exc:
            self.log.warning("Motor timeout during fine optimization: %s", exc)

        if self.best_angles is None and fallback_coarse:
            try:
                self._deadline = time.monotonic() + float(self._coarse_timeout_s)
                self.coarse_search(coarse_start if coarse_start is not None else start, coarse_step)
            except OptimizationTimeout:
                self.log.warning("Coarse recovery timed out")
        if self.best_angles is not None:
            with self.io_lock:
                self._move_to_angles(self.best_angles)
        self._deadline = previous_deadline
        self._progress_started = self._progress_duration = None
        self.sigOptimizationFinished.emit(self.best_angles, float(self.best_power))
        return self.best_angles, self.best_power
    def coarse_then_fine_minimum(self, start=None):
        """Run the same coarse-then-fine acquisition used by the notebook."""
        if start is None:
            start = self._mpc.positions()
        start = np.clip(np.asarray(start, dtype=float), 0, 160)

        self.best_power = np.inf
        self.best_angles = None
        previous_deadline = self._deadline
        self._deadline = time.monotonic() + float(self._coarse_timeout_s)
        self.sigOperationStatusChanged.emit("Coarse paddle scan")
        try:
            try:
                self.coarse_search(start, step=float(self._coarse_step_deg))
            except OptimizationTimeout:
                if self._stop_optimization_event.is_set():
                    return self.best_angles, self.best_power
                self.log.warning("Coarse paddle scan reached its time limit")
        finally:
            self._deadline = previous_deadline

        if self._stop_optimization_event.is_set():
            return self.best_angles, self.best_power

        fine_start = self.best_angles.copy() if self.best_angles is not None else start
        self.sigOperationStatusChanged.emit("Fine polarization adjustment")
        return self.find_minimum(fine_start, fallback_coarse=False)

    def _start_optimization_operation(self, name, budget_seconds, target, threshold=None):
        """Start exactly one user-selected optimization operation."""
        if self._optimization_thread is not None and self._optimization_thread.is_alive():
            self.log.warning("An optimization is already running.")
            return False
        if self._lock_thread is not None and self._lock_thread.is_alive():
            self.log.warning("Stop polarization lock before starting a manual optimization.")
            return False
        if threshold is not None:
            self.threshold = float(threshold)
        self._stop_optimization_event.clear()

        def worker():
            self._begin_process(name, budget_seconds)
            try:
                target()
            except OptimizationTimeout:
                self.log.info("%s stopped", name)
            except Exception as exc:
                self.log.exception("%s failed", name)
                self.sigError.emit(str(exc))
            finally:
                self._deadline = None
                self._end_process()

        self._optimization_thread = threading.Thread(target=worker, daemon=True)
        self._optimization_thread.start()
        return True

    def start_coarse_optimization(self, threshold=None):
        def run():
            self.best_power, self.best_angles = np.inf, None
            self._deadline = time.monotonic() + float(self._coarse_timeout_s)
            start = self._mpc.positions()
            try:
                self.coarse_search(start, float(self._coarse_step_deg))
            finally:
                if self.best_angles is not None:
                    self.sigCurrentActionChanged.emit(
                        f"Moving to coarse minimum ({self.best_power:.2f} nW)"
                    )
                    with self.io_lock:
                        self._move_to_angles(self.best_angles)

        return self._start_optimization_operation(
            "Coarse optimisation", self._coarse_timeout_s, run, threshold
        )

    def start_fine_optimization(self, threshold=None):
        def run():
            self.find_minimum(
                self._mpc.positions(),
                fallback_coarse=False,
                timeout_seconds=float(self._optimization_timeout_s),
            )

        return self._start_optimization_operation(
            "Fine optimisation", self._optimization_timeout_s, run, threshold
        )

    def start_coarse_fine_optimization(self, threshold=None):
        budget = float(self._coarse_timeout_s) + float(self._optimization_timeout_s)
        return self._start_optimization_operation(
            "Coarse + fine optimisation",
            budget,
            lambda: self.coarse_then_fine_minimum(self._mpc.positions()),
            threshold,
        )

    # ------------------------------------------------------------------
    # Locking and logging
    # ------------------------------------------------------------------

    def read_for_log(self):
        """
        Atomically read power and all paddle positions for one log entry.
        """

        with self.io_lock:

            if self.pause_logging.is_set():
                return None

            return (
                self.read_power_nw(),
                self._mpc.positions(),
            )

    def _gently_recentre_from_edge(self, positions, current_power, master_threshold):
        """Try tiny coordinated edge-recovery moves without retaining unsafe power."""
        positions = np.asarray(positions, dtype=float)
        directions = self._edge_directions(positions)
        if not np.any(directions):
            return False, current_power

        inward_step = max(0.01, float(self._edge_recenter_step_deg))
        compensation_step = float(self._fine_steps()[-1])
        free_axes = [index for index, direction in enumerate(directions) if not direction]
        baseline_clearance = self._edge_clearance(positions)
        urgency = self._edge_urgency(positions)
        accepted = []

        # The edge-bound paddle always moves inward. The two remaining paddles
        # explore small compensating offsets, exploiting the three-paddle
        # polarization freedom without a large jump.
        for offsets in product((-1.0, 0.0, 1.0), repeat=len(free_axes)):
            candidate = positions.copy()
            candidate += directions * inward_step
            for axis, offset in zip(free_axes, offsets):
                candidate[axis] += offset * compensation_step
            candidate = np.clip(candidate, 0.0, 160.0)
            if np.allclose(candidate, positions):
                continue

            with self.io_lock:
                self._move_to_angles(candidate)
                candidate_power = self.measure_power(samples=int(self._coarse_samples), delay=0.01)
                self._move_to_angles(positions)
            if not self._candidate_is_acceptable(candidate_power, current_power, master_threshold):
                continue
            clearance = self._edge_clearance(candidate)
            if clearance > baseline_clearance + 1e-6:
                accepted.append((candidate_power, clearance, candidate))

        if not accepted:
            self.sigCurrentActionChanged.emit('Edge recovery paused: no safe micro-move found')
            return False, current_power

        # Near a hard limit, clearance dominates. Near the outer edge of the
        # margin, preserve the lower-power compensation path when possible.
        if urgency >= 0.5:
            selected_power, _, selected = max(accepted, key=lambda item: (item[1], -item[0]))
        else:
            selected_power, _, selected = min(accepted, key=lambda item: (item[0], -item[1]))
        self.sigCurrentActionChanged.emit(
            f'Edge recovery: {np.round(positions, 3).tolist()}° → '
            f'{np.round(selected, 3).tolist()}°'
        )
        with self.io_lock:
            self._move_to_angles(selected)
        return True, selected_power

    def _micro_trim_to_hold(self, positions, current_power, hold_threshold, master_threshold):
        """Use exactly the smallest fine step to pull power back below the hold threshold."""
        if current_power <= hold_threshold:
            return False, current_power
        step = float(self._fine_steps()[-1])
        best_power, best_angles = current_power, np.asarray(positions, dtype=float).copy()
        for axis in range(3):
            for direction in (-1.0, 1.0):
                candidate = best_angles.copy()
                candidate[axis] = np.clip(candidate[axis] + direction * step, *self._safe_angle_bounds())
                if np.isclose(candidate[axis], best_angles[axis]):
                    continue
                self.sigCurrentActionChanged.emit(
                    f'Hold-threshold trim: paddle {axis + 1} by {direction * step:+.3f}°'
                )
                with self.io_lock:
                    self._move_to_angles(candidate)
                    power = self.measure_power(samples=int(self._coarse_samples), delay=0.01)
                if self._candidate_is_acceptable(power, current_power, master_threshold) and power < best_power:
                    best_power, best_angles = power, candidate
                else:
                    with self.io_lock:
                        self._move_to_angles(best_angles)
        with self.io_lock:
            self._move_to_angles(best_angles)
        return not np.allclose(best_angles, positions), best_power

    def lock(self, threshold=110, interval=5, consecutive_bad=3, hold_threshold=None):
        """Prioritize edge protection, then gentle trimming, then full recovery."""
        master_threshold = float(threshold)
        hold_threshold = self.hold_threshold if hold_threshold is None else float(hold_threshold)
        if not 0.0 <= hold_threshold < master_threshold:
            raise ValueError('Hold threshold must be lower than the master threshold')
        self.log.info('Starting polarization lock: hold %.3f nW, master %.3f nW',
                      hold_threshold, master_threshold)
        self.sigLockStarted.emit()
        bad_reads = 0
        while not self._stop_lock_event.is_set():
            self.sigLockPriorityChanged.emit('monitoring')
            self.sigCurrentActionChanged.emit('Monitoring optical power and paddle margins')
            with self.io_lock:
                power = self.read_power_nw()
                positions = np.asarray(self._mpc.positions(), dtype=float)
            self.sigPowerUpdated.emit(power)
            self.sigPaddlePositionsUpdated.emit(*positions.tolist())

            if np.any(self._edge_directions(positions)):
                # A fitted lambda/2 equivalent is much faster than walking out
                # of an edge region. Without a reliable fit, retain the
                # conservative coordinated micro-recovery fallback.
                self._lock_correction_active = True
                try:
                    if not self._relocate_to_equivalent_minimum(positions):
                        self.sigLockPriorityChanged.emit('edge_recovery')
                        self._gently_recentre_from_edge(positions, power, master_threshold)
                finally:
                    self._lock_correction_active = False
                bad_reads = 0
            elif power >= master_threshold:
                bad_reads += 1
                if bad_reads >= consecutive_bad:
                    self.sigLockPriorityChanged.emit('master_recovery')
                    self._lock_correction_active = True
                    try:
                        self.sigCurrentActionChanged.emit('Master threshold exceeded; full fine recovery')
                        self.find_minimum(positions, fallback_coarse=False, fast=True,
                                          timeout_seconds=min(30.0, float(self._optimization_timeout_s)))
                    finally:
                        self._lock_correction_active = False
                    bad_reads = 0
                else:
                    self.sigLockPriorityChanged.emit('master_debounce')
            elif power > hold_threshold:
                self.sigLockPriorityChanged.emit('hold_trim')
                # Middle band: only the smallest log-step is used.
                self._lock_correction_active = True
                try:
                    self._micro_trim_to_hold(positions, power, hold_threshold, master_threshold)
                finally:
                    self._lock_correction_active = False
                bad_reads = 0
            else:
                bad_reads = 0
                self.sigLockPriorityChanged.emit('monitoring')
                self.sigCurrentActionChanged.emit('Power below hold threshold; monitoring only')
            self._stop_lock_event.wait(interval)
        self.sigLockStopped.emit()
        self.log.info('Polarization lock stopped')
    def log_power(
        self,
        duration=300,
        interval=1,
        plot=False,
        csv_path=None,
    ):

        times = []
        powers = []

        if csv_path is None:
            csv_path = os.path.join(
                self.module_default_data_dir,
                f"power_log_{datetime.now():%Y%m%d_%H%M%S}.csv",
            )
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

        created_at = datetime.now().isoformat(timespec="milliseconds")
        duration_text = (
            "continuous" if not np.isfinite(duration) else f"{float(duration):g}"
        )
        metadata = (
            ("format", "qudi-polarization-log-v2"),
            ("created_at", created_at),
            ("master_threshold_nW", f"{float(self.threshold):.6g}"),
                ("hold_threshold_nW", f"{float(self.hold_threshold):.6g}"),
                ("edge_margin_deg", f"{float(self._edge_margin()):.6g}"),
            ("power_channel", self._power_channel),
            ("power_unit", "nW"),
            ("paddle_angle_unit", "deg"),
            ("log_interval_s", f"{float(interval):g}"),
            ("requested_log_duration_s", duration_text),
            ("fine_power_samples", int(self._samples)),
            ("coarse_power_samples", int(self._coarse_samples)),
            ("coarse_step_deg", f"{float(self._coarse_step_deg):g}"),
            ("coarse_timeout_s", f"{float(self._coarse_timeout_s):g}"),
            ("fine_timeout_s", f"{float(self._optimization_timeout_s):g}"),
            ("lock_interval_s", f"{float(self._lock_interval_s):g}"),
            ("lock_consecutive_bad_reads", int(self._lock_consecutive_bad)),
        )

        with open(csv_path, "w", encoding="utf-8") as f:
            for key, value in metadata:
                f.write(f"# {key}: {value}\n")
            f.write(
                "timestamp,power_nW,threshold_nW,"
                "paddle1_deg,paddle2_deg,paddle3_deg,state\n"
            )

        self.sigLoggingStarted.emit()

        started = time.monotonic()

        try:

            while (
                time.monotonic() - started <= duration
                and not self._stop_log_event.is_set()
            ):

                sample = self.read_for_log()

                if sample is None:

                    self._stop_log_event.wait(
                        min(0.2, interval)
                    )

                    continue

                power, pos = sample
                state = self._polarization_state(power)

                sampled_at = datetime.now()
                timestamp = sampled_at.isoformat(timespec="milliseconds")
                timestamp_epoch = sampled_at.timestamp()

                times.append(timestamp)
                powers.append(power)
                self.sigLogSample.emit(timestamp_epoch, power, list(pos), state)

                self.sigPowerUpdated.emit(power)

                with open(csv_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"{timestamp},"
                        f"{power:.3f},"
                        f"{float(self.threshold):.6g},"
                        f"{pos[0]:.2f},"
                        f"{pos[1]:.2f},"
                        f"{pos[2]:.2f},"
                        f"{state}\n"
                    )

                self._stop_log_event.wait(interval)

        finally:
            self.sigLoggingStopped.emit()
            self.sigLogStateChanged.emit(False)

        self.log.info(f"Saved log: {csv_path}")

        return times, powers

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    def start_locking(
        self,
        threshold=5,
        interval=1,
        consecutive_bad=3,
    ):
        return self.start_lock(threshold=threshold, interval=interval, consecutive_bad=consecutive_bad)

    def stop_locking(self):
        self.stop_lock()

    def stop_optimization(self):
        """Request cancellation without blocking the GUI thread."""
        self._stop_optimization_event.set()

    def stop_combined_run(self):
        """Request cancellation of every part of a combined workflow."""
        self._stop_combined_event.set()
        self._stop_optimization_event.set()
        self._stop_lock_event.set()
        self._stop_log_event.set()

    def start_logging(
        self,
        duration=300,
        interval=1,
        plot=False,
        csv_path=None,
    ):

        if plot or csv_path is not None:
            if self._log_thread is not None and self._log_thread.is_alive():
                self.log.warning("Logging already running.")
                return False
            self._stop_log_event.clear()
            self.sigLogStateChanged.emit(True)
            self._log_thread = threading.Thread(
                target=self.log_power,
                kwargs={"duration": duration, "interval": interval, "plot": plot, "csv_path": csv_path},
                daemon=True,
            )
            self._log_thread.start()
            return True
        return self.start_log(duration, interval)

    def stop_logging(self):
        self.stop_log()

    def request_stop_log(self):
        """Request logging cancellation without waiting in the GUI thread."""
        self._stop_log_event.set()

    # ------------------------------------------------------------------
    # Convenience API
    # ------------------------------------------------------------------

    def optimize(
        self,
        start_angles=None,
        **kwargs,
    ):
        """
        Convenience wrapper around find_minimum().
        """

        if start_angles is None:
            start_angles = self._mpc.positions()

        return self.find_minimum(
            start=start_angles,
            **kwargs,
        )

    def current_power(self):
        """
        Return the current power in nW.
        """

        return self.read_power_nw()

    def set_edge_margin(self, margin_deg):
        margin = float(margin_deg)
        if not 0.0 <= margin < 80.0:
            raise ValueError("Edge margin must be between 0 and 80 degrees")
        self._edge_margin_override = margin

    def set_fine_step_settings(self, initial_deg, final_deg, levels):
        initial, final, levels = float(initial_deg), float(final_deg), int(levels)
        if initial <= 0 or final <= 0 or levels < 2:
            raise ValueError("Fine steps must be positive and contain at least two levels")
        self._fine_initial_step_override = max(initial, final)
        self._fine_final_step_override = min(initial, final)
        self._fine_step_levels_override = levels
    def set_threshold(self, threshold_nw):
        """Set the upper/master lock threshold in nanowatts."""
        self.threshold = float(threshold_nw)
        if self.threshold <= 0.0:
            raise ValueError("The master threshold must be positive.")
        if self.hold_threshold >= self.threshold:
            self.hold_threshold = max(0.0, self.threshold - 1e-6)

    def set_hold_threshold(self, threshold_nw):
        """Set the lower hold threshold in nanowatts."""
        threshold_nw = float(threshold_nw)
        if not 0.0 <= threshold_nw < self.threshold:
            raise ValueError("The hold threshold must be non-negative and lower than the master threshold.")
        self.hold_threshold = threshold_nw

    def current_angles(self):
        """
        Return the current paddle angles.
        """

        positions = np.asarray(
            self._mpc.positions(),
            dtype=float,
        )
        self.sigPaddlePositionsUpdated.emit(*positions.tolist())
        return positions

    def start_log(
        self,
        duration=300,
        interval=1,
        continuous=False,
    ):

        if self._log_thread is not None and self._log_thread.is_alive():
            self.log.warning("Logging already running.")
            return False

        self._stop_log_event.clear()

        if continuous:
            duration = float("inf")

        self.sigLogStateChanged.emit(True)

        def worker():
            try:
                self.log_power(duration=duration, interval=interval)
            except Exception as exc:
                self.log.exception("Polarization logging failed")
                self.sigError.emit(str(exc))

        self._log_thread = threading.Thread(target=worker, daemon=True)

        self._log_thread.start()
        return True

    def stop_log(self):

        self._stop_log_event.set()

        if self._log_thread is not None and self._log_thread is not threading.current_thread():
            self._log_thread.join(timeout=5)

        self._log_thread = None

        self.sigLogStateChanged.emit(False)

    def start_lock(self, threshold=None, hold_threshold=None, interval=None, consecutive_bad=None):
        """Start the non-blocking polarisation locking worker.

        ``threshold`` is the upper/master threshold.  ``hold_threshold`` is
        the lower set-point used for small corrections in the middle band.
        """
        if self._lock_thread is not None and self._lock_thread.is_alive():
            raise RuntimeError("Polarisation lock is already running.")

        threshold = float(self.threshold if threshold is None else threshold)
        hold_threshold = float(self.hold_threshold if hold_threshold is None else hold_threshold)
        if not 0.0 <= hold_threshold < threshold:
            raise ValueError("The hold threshold must be non-negative and lower than the master threshold.")
        interval = float(self._lock_interval_s if interval is None else interval)
        consecutive_bad = int(self._lock_consecutive_bad if consecutive_bad is None else consecutive_bad)

        self._stop_lock_event.clear()
        self._stop_optimization_event.clear()
        self._lock_active = True
        self.sigLockStateChanged.emit(True)

        def worker():
            self._begin_process("Polarisation lock", None)
            try:
                self.lock(threshold, interval, consecutive_bad, hold_threshold)
            except Exception as exc:
                self.log.exception("Polarisation lock stopped after an error")
                self.sigError.emit(str(exc))
            finally:
                self._lock_active = False
                self.sigLockStateChanged.emit(False)
                self._end_process()

        self._lock_thread = threading.Thread(target=worker, name="polarization-lock", daemon=True)
        self._lock_thread.start()
        return True
    def stop_lock(self):

        self._stop_combined_event.set()
        self._stop_lock_worker()

    def request_stop_lock(self):
        """Request lock cancellation without blocking the GUI thread."""
        self.sigLockPriorityChanged.emit("stopping")
        self.sigCurrentActionChanged.emit("Stopping polarisation lock")
        self._stop_lock_event.set()
        self._stop_optimization_event.set()

    def _stop_lock_worker(self):
        """Stop only the lock worker, without cancelling a combined run."""
        self._stop_lock_event.set()

        self._stop_optimization_event.set()
        if self._lock_thread is not None and self._lock_thread is not threading.current_thread():
            self._lock_thread.join(timeout=5)

        self._lock_thread = None

        self.sigLockStateChanged.emit(False)


    def start_minimize(self, threshold=None):
        """Compatibility alias for the former combined optimization button."""
        return self.start_coarse_fine_optimization(threshold)

    def start_minimize_lock_log(
        self,
        log_duration_s,
        lock_duration_s,
        interval_s,
        continuous_log,
        continuous_lock,
        threshold_nw,
    ):
        """
        Optimize once, then start locking and logging.
        """

        self.threshold = float(threshold_nw)

        if self._combined_thread is not None and self._combined_thread.is_alive():
            self.log.warning("Combined polarization run already active.")
            return False
        if ((self._lock_thread is not None and self._lock_thread.is_alive()) or
                (self._log_thread is not None and self._log_thread.is_alive())):
            self.log.warning("Stop the active lock/log run before starting a combined run.")
            return False
        self._stop_combined_event.clear()
        self._stop_optimization_event.clear()

        def worker():

            self.sigCombinedStateChanged.emit(True)
            self.sigOperationStatusChanged.emit("Coarse paddle scan")

            try:
                self.coarse_then_fine_minimum(self._mpc.positions())

                if self._stop_combined_event.is_set():
                    return

                self.sigOperationStatusChanged.emit("Starting stabilization and recording")
                lock_started = self.start_lock(
                    threshold=float(threshold_nw),
                    interval=float(interval_s),
                )

                duration = (
                    1e12 if continuous_log
                    else log_duration_s
                )

                log_started = self.start_log(
                    duration=duration,
                    interval=interval_s,
                    continuous=continuous_log,
                )
                if not lock_started or not log_started:
                    raise RuntimeError("Could not start both lock and logging workers")

                run_started = time.monotonic()
                lock_stopped = False
                phase = "Stabilizing and recording"
                self.sigOperationStatusChanged.emit(phase)
                initial_detail = " | ".join((
                    "lock: continuous" if continuous_lock else
                    f"lock: {float(lock_duration_s):.0f} s left",
                    "log: continuous" if continuous_log else
                    f"log: {float(log_duration_s):.0f} s left",
                ))
                self.sigOptimizationProgress.emit(
                    phase, -1 if (continuous_lock or continuous_log) else 0, initial_detail
                )

                while not self._stop_combined_event.wait(0.2):
                    elapsed = time.monotonic() - run_started

                    if not continuous_lock and not lock_stopped and elapsed >= lock_duration_s:
                        self._stop_lock_worker()
                        lock_stopped = True

                    log_running = self._log_thread is not None and self._log_thread.is_alive()
                    lock_running = self._lock_thread is not None and self._lock_thread.is_alive()

                    if lock_running and log_running:
                        new_phase = "Stabilizing and recording"
                    elif lock_running:
                        new_phase = "Stabilizing polarization"
                    elif log_running:
                        new_phase = "Recording power"
                    else:
                        break

                    if new_phase != phase:
                        phase = new_phase
                        self.sigOperationStatusChanged.emit(phase)

                    if continuous_lock or continuous_log:
                        percent = -1
                    else:
                        total = max(float(lock_duration_s), float(log_duration_s), 0.001)
                        percent = min(99, round(100 * elapsed / total))

                    details = []
                    if lock_running:
                        details.append(
                            "lock: continuous" if continuous_lock else
                            f"lock: {max(0, lock_duration_s - elapsed):.0f} s left"
                        )
                    if log_running:
                        details.append(
                            "log: continuous" if continuous_log else
                            f"log: {max(0, log_duration_s - elapsed):.0f} s left"
                        )
                    self.sigOptimizationProgress.emit(phase, percent, " | ".join(details))

            except Exception as exc:
                self.log.exception("Combined polarization run failed")
                self.sigError.emit(str(exc))
                self._stop_combined_event.set()
            finally:
                # Do not leave child workers behind after an error or explicit
                # cancellation. Normally finite workers have already stopped.
                if self._stop_combined_event.is_set():
                    self._stop_lock_worker()
                    self.stop_log()
                self.sigOperationStatusChanged.emit("Idle")
                self.sigOptimizationProgress.emit("Idle", 0, "Ready")
                self.sigCombinedStateChanged.emit(False)

        self._combined_thread = threading.Thread(
            target=worker,
            daemon=True,
        )
        self._combined_thread.start()
        return True
