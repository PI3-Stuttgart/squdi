"""
Qudi logic module for automatic polarization optimization.

Ported from polarization_optimizer.py while preserving the optimization
algorithm. Only the hardware interface has been adapted for Qudi.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import numpy as np
from scipy.optimize import minimize
from qtpy.QtCore import Signal

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.interface.process_control_interface import ProcessValueInterface

print("Loaded:", __file__)


class FoundMinimum(Exception):
    pass


class OptimizationTimeout(Exception):
    pass


class PolarizationOptimizerLogic(LogicBase):
    """
    Automatic polarization optimizer.

    This is a Qudi port of the standalone PolarizationOptimizer.
    """

    mpc = mpc = Connector(interface="Base")
    powermeter = Connector(interface="ProcessValueInterface")

    sigOptimizationStarted = Signal()
    sigOptimizationFinished = Signal(object, float)

    sigLockStarted = Signal()
    sigLockStopped = Signal()

    sigLoggingStarted = Signal()
    sigLoggingStopped = Signal()

    sigPowerUpdated = Signal(float)

    sigLogSample = Signal(float, float)
    sigLogStateChanged = Signal(bool)
    sigLockStateChanged = Signal(bool)
    sigOperationStatusChanged = Signal(str)

    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)

        self._lock_threshold_nw = 2.5
        self._lock_interval_s = 1
        self._lock_consecutive_bad = 3

        # optimization target
        self.threshold = 2.5

        self.best_power = np.inf
        self.best_angles = None

        self.pause_logging = threading.Event()

        # Separate events
        self._stop_lock_event = threading.Event()
        self._stop_log_event = threading.Event()

        self.io_lock = threading.RLock()

        self._deadline = None

        self._lock_thread = None
        self._log_thread = None
        self._lock_threshold_nw = 2.5
        self._lock_interval_s = 1.0

    def on_activate(self):
        self._mpc = self.mpc()
        self._pm = self.powermeter()

    def on_deactivate(self):
        self.stop_locking()

        if self._log_thread is not None:
            self._log_thread.join(timeout=2)

    # ------------------------------------------------------------------
    # Hardware helpers
    # ------------------------------------------------------------------

    def read_power_nw(self):
        """
        Read optical power in nW.
        """
        return float(self._pm.get_power() * 1e9)

    def _check_deadline(self):
        if (
            self._deadline is not None
            and time.monotonic() >= self._deadline
        ):
            raise OptimizationTimeout

    def measure(self):
        self._check_deadline()

        if self._stop_lock_event.wait(0.02):
            raise OptimizationTimeout

        return self.read_power_nw()

    def measure_power(self, samples=5, delay=0.05):
        values = []

        for _ in range(samples):
            self._check_deadline()

            values.append(self.read_power_nw())

            self._check_deadline()

            if self._stop_lock_event.wait(delay):
                raise OptimizationTimeout

        power = float(np.mean(values))

        self.sigPowerUpdated.emit(power)

        return power
    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def coarse_search(self, center, step=20):
        """
        Coordinate coarse scan, bounded by the active optimization deadline.
        """
        with self.io_lock:
            best_angles = np.clip(np.asarray(center, dtype=float), 0, 160)

            self._mpc.set_angles(*best_angles)

            best_power = self.measure()

            for paddle_idx in range(3):

                current = best_angles[paddle_idx]

                for angle in np.arange(
                    max(0, current - 80),
                    min(160, current + 80) + 1,
                    step,
                ):

                    self._check_deadline()

                    test = best_angles.copy()
                    test[paddle_idx] = angle

                    self._mpc.set_angles(*test)

                    power = self.measure()

                    if power < best_power:
                        best_power = power
                        best_angles = test.copy()

                        self.best_angles = best_angles.copy()
                        self.best_power = best_power

                        self.log.info(
                            f"Coarse best: "
                            f"{np.round(best_angles,2)} "
                            f"{best_power:.1f} nW"
                        )

            self.best_angles = best_angles.copy()
            self.best_power = best_power

            self._mpc.set_angles(*best_angles)

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

        self._mpc.set_angles(
            *ang,
            timeout=timeout,
        )

        if self._stop_lock_event.wait(0.10 if fast else 0.30):
            raise OptimizationTimeout

        power = self.measure_power(
            samples=3 if fast else 5,
            delay=0.005 if fast else 0.01,
        )

        if power < self.best_power:

            self.best_power = power
            self.best_angles = ang.copy()

            self.log.info(
                f"New best: "
                f"{np.round(ang,2)} "
                f"{power:.1f} nW"
            )

        if power < self.threshold:
            raise FoundMinimum

        return power
    def find_minimum(
        self,
        start,
        fallback_coarse=True,
        coarse_start=None,
        coarse_step=5,
        max_restarts=3,
        fast=False,
        timeout_seconds=30,
    ):
        """
        Run a bounded local search and always return to the best known point.
        """
        self.sigOperationStatusChanged.emit("Optimizing")


        # Retained for compatibility with the original interface.
        del max_restarts

        self.best_power = np.inf
        self.best_angles = None

        start = np.clip(np.asarray(start, dtype=float), 0, 160)

        previous_deadline = self._deadline
        self._deadline = time.monotonic() + timeout_seconds

        self.log.info(
            f"Starting bounded optimization from: "
            f"{np.round(start, 2)}"
        )

        self.sigOptimizationStarted.emit()

        try:

            with self.io_lock:

                try:

                    minimize(
                        lambda x: self.objective(x, fast=fast),
                        start,
                        method="Nelder-Mead",
                        options={
                            "xatol": 0.5 if fast else 0.2,
                            "fatol": 5 if fast else 2,
                            "maxfev": 50 if fast else 100,
                        },
                    )

                except FoundMinimum:
                    self.log.info("Target power reached")

                except OptimizationTimeout:
                    self.log.warning(
                        f"Optimization stopped after "
                        f"{timeout_seconds}s"
                    )

                except TimeoutError as exc:
                    self.log.warning(
                        f"Motor timeout: {exc}"
                    )

                # Recovery using a coarse scan if no usable point was found.
                if self.best_angles is None and fallback_coarse:

                    try:

                        self.coarse_search(
                            coarse_start
                            if coarse_start is not None
                            else start,
                            step=coarse_step,
                        )

                    except OptimizationTimeout:

                        self.log.warning(
                            "Coarse recovery timed out"
                        )

                if self.best_angles is not None:

                    self._mpc.set_angles(
                        *self.best_angles
                    )

                    self.log.info(
                        f"Best: "
                        f"{np.round(self.best_angles,2)} "
                        f"{self.best_power:.1f} nW"
                    )

        finally:

            self._deadline = previous_deadline

            self.sigOptimizationFinished.emit(
                self.best_angles,
                float(self.best_power),
            )
            self.sigOperationStatusChanged.emit("Idle")
        return self.best_angles, self.best_power

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

    def lock(
                self,
                threshold=110,
                interval=5,
                consecutive_bad=3,
            ):

        self.log.info("Starting polarization lock")

        self.sigLockStarted.emit()

        bad_reads = 0

        while not self._stop_lock_event.is_set():

            with self.io_lock:
                power = self.read_power_nw()

            if power > threshold:
                bad_reads += 1
            else:
                bad_reads = 0

            self.sigPowerUpdated.emit(power)

            if bad_reads >= consecutive_bad:

                self.pause_logging.set()

                try:

                    # Only protect the hardware read
                    with self.io_lock:
                        current = self._mpc.positions()

                    self.log.info("Re-optimizing...")

                    self.find_minimum(
                        current,
                        coarse_step=2,
                        fast=True,
                        timeout_seconds=30,
                    )

                finally:
                    self.pause_logging.clear()

                bad_reads = 0

            self._stop_lock_event.wait(interval)

        self.sigLockStopped.emit()

        self.log.info("Polarization lock stopped")

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
            csv_path = (
                f"power_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
            )

        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(
                "timestamp,time_s,power_nW,"
                "paddle1,paddle2,paddle3\n"
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

                elapsed = time.monotonic() - started

                timestamp = datetime.now().isoformat(
                    timespec="seconds"
                )

                times.append(elapsed)
                powers.append(power)
                self.sigLogSample.emit(elapsed, power)

                self.sigPowerUpdated.emit(power)

                with open(csv_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"{timestamp},"
                        f"{elapsed:.3f},"
                        f"{power:.3f},"
                        f"{pos[0]:.2f},"
                        f"{pos[1]:.2f},"
                        f"{pos[2]:.2f}\n"
                    )

                self._stop_log_event.wait(interval)

        finally:

            self.sigLoggingStopped.emit()

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
        self._lock_threshold_nw = threshold
        self._lock_interval_s = interval
        self._lock_consecutive_bad = consecutive_bad

        if self._lock_thread is not None and self._lock_thread.is_alive():
            self.log.warning("Lock thread already running.")
            return

        self._stop_lock_event.clear()

        self._lock_thread = threading.Thread(
            target=self.lock,
            kwargs={
                "threshold": threshold,
                "interval": interval,
                "consecutive_bad": consecutive_bad,
            },
            daemon=True,
        )

        self._lock_thread.start()

    def stop_locking(self):

        self._stop_lock_event.set()

        if self._lock_thread is not None:
            self._lock_thread.join(timeout=5)

        self._lock_thread = None

    def start_logging(
        self,
        duration=300,
        interval=1,
        plot=False,
        csv_path=None,
    ):

        if self._log_thread is not None and self._log_thread.is_alive():
            self.log.warning("Logging already running.")
            return

        self._stop_log_event.clear()

        self._log_thread = threading.Thread(
            target=self.log_power,
            kwargs={
                "duration": duration,
                "interval": interval,
                "plot": plot,
                "csv_path": csv_path,
            },
            daemon=True,
        )

        self._log_thread.start()

    def stop_logging(self):

        self._stop_log_event.set()

        if self._log_thread is not None:
            self._log_thread.join(timeout=5)

        self._log_thread = None

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

    def current_angles(self):
        """
        Return the current paddle angles.
        """

        return np.asarray(
            self._mpc.positions(),
            dtype=float,
        )

    def start_log(
        self,
        duration=300,
        interval=1,
        continuous=False,
    ):

        if self._log_thread is not None and self._log_thread.is_alive():
            return

        self._stop_log_event.clear()

        if continuous:
            duration = float("inf")

        self.sigLogStateChanged.emit(True)

        self._log_thread = threading.Thread(
            target=self.log_power,
            kwargs={
                "duration": duration,
                "interval": interval,
                "plot": False,
                "csv_path": None,
            },
            daemon=True,
        )

        self._log_thread.start()

    def stop_log(self):

        self._stop_log_event.set()

        if self._log_thread is not None:
            self._log_thread.join(timeout=5)

        self._log_thread = None

        self.sigLogStateChanged.emit(False)

    def start_lock(
        self,
        threshold=110,
        interval=5,
        consecutive_bad=3,
    ):

        if self._lock_thread is not None and self._lock_thread.is_alive():
            return

        self._stop_lock_event.clear()

        self.sigLockStateChanged.emit(True)

        self._lock_thread = threading.Thread(
            target=self.lock,
            kwargs={
                "threshold": threshold,
                "interval": interval,
                "consecutive_bad": consecutive_bad,
            },
            daemon=True,
        )

        self._lock_thread.start()

    def stop_lock(self):

        self._stop_lock_event.set()

        if self._lock_thread is not None:
            self._lock_thread.join(timeout=5)

        self._lock_thread = None

        self.sigLockStateChanged.emit(False)


    def start_minimize(self, threshold=None):
        """
        Run one optimization in a background thread.
        """

        if threshold is not None:
            self.threshold = float(threshold)

        def worker():
            self.sigOperationStatusChanged.emit("Optimizing")
            try:
                start = self._mpc.positions()
                self.find_minimum(start)
            finally:
                self.sigOperationStatusChanged.emit("Idle")


        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

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

        self._lock_threshold_nw = float(threshold_nw)
        self._lock_interval_s = float(interval_s)

        self.threshold = float(threshold_nw)

        def worker():

            self.sigOperationStatusChanged.emit("Optimizing")

            try:
                start = self._mpc.positions()
                self.find_minimum(start)

                self.sigOperationStatusChanged.emit("Locking")

                self.start_lock(
                    threshold=self._lock_threshold_nw,
                    interval=self._lock_interval_s,
                )

                self.sigOperationStatusChanged.emit("Logging")

                duration = (
                    1e12 if continuous_log
                    else log_duration_s
                )

                self.start_log(
                    duration=duration,
                    interval=interval_s,
                    continuous=continuous_log,
                )

                if not continuous_lock:
                    time.sleep(lock_duration_s)
                    self.stop_lock()

            finally:
                self.sigOperationStatusChanged.emit("Idle")

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()
