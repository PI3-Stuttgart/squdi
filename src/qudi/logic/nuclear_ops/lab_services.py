"""Hardware-service orchestration retained from the original NuclearOPs loop."""

import math
import time
from datetime import datetime
from typing import Any, Mapping

import numpy as np

from .execution_engine import RunServices
from .models import AcquisitionMode


class NuclearLabServices(RunServices):
    """Apply outer scan values and periodic stabilization through Qudi services.

    All dependencies are optional at construction time, but a dependency is
    required as soon as an experiment requests the corresponding feature.
    """

    IDLE_LASER_SCANNER_VOLTAGE = 60.0

    def __init__(
        self,
        quantum_machine=None,
        magnet=None,
        microwave=None,
        external_counter=None,
        confocal=None,
        confocal_optimizer=None,
        ple_optimizer=None,
        wavemeter=None,
        laser_controller=None,
        transition_tracker=None,
        analog_output=None,
        switches=None,
        ppg=None,
        log=None,
    ):
        self.quantum_machine = quantum_machine
        self.magnet = magnet
        self.microwave = microwave
        self.external_counter = external_counter
        self.confocal = confocal
        self.confocal_optimizer = confocal_optimizer
        self.ple_optimizer = ple_optimizer
        self.wavemeter = wavemeter
        self.laser_controller = laser_controller
        self.transition_tracker = transition_tracker
        self.analog_output = analog_output
        self.switches = switches
        self.ppg = ppg
        self.log = log
        self._last_values = {}
        self._last_refocus = {"green": 0.0, "red": 0.0, "ple": 0.0}
        self._laser_locked = False

    def _message(self, level, message):
        target = getattr(self.log, level, None)
        if callable(target):
            target(message)

    @staticmethod
    def _require(value, feature):
        if value is None:
            raise RuntimeError("{} was requested but its Qudi connector is not configured".format(feature))
        return value

    def before_run(self, experiment, control):
        self._last_values = {}
        now = time.monotonic()
        self._last_refocus = {"green": now, "red": now, "ple": now}
        if (
            experiment.execution.acquisition_mode == AcquisitionMode.EXTERNAL_COUNTER
            and self.external_counter is not None
        ):
            setup = getattr(self.external_counter, "set_counter", None)
            if callable(setup):
                setup()
        if experiment.stabilization.lock_laser_to_wavemeter and experiment.stabilization.ple_refocus_interval_s is None:
            self.start_laser_lock(control=control)
        self._ensure_default_microwave(experiment.parameters)

    def before_block(self, experiment, block, control) -> Mapping[str, Any]:
        self._wait_for_quiet_hours(experiment.execution, control)
        values = dict(experiment.parameters)
        values.update(block.host_values)
        values.update(block.recompile_values)
        action_names = {
            "click_channel",
            "B_amp",
            "B_theta",
            "B_phi",
            "smiq_freq",
            "smiq_power_dbm",
            "pulse_shape_ppg",
            "pulse_width_ppg",
            "pulse_delay_ppg",
            "pulse_amplitude_ppg",
        }
        changed = {
            name
            for name in action_names.intersection(values)
            if name not in self._last_values
            or not self._values_equal(self._last_values[name], values[name])
        }

        if "click_channel" in changed:
            counter = self._require(self.external_counter, "External click-channel selection")
            device = getattr(
                counter,
                "_fast_counter_device",
                getattr(counter, "fast_counter_device", counter),
            )
            settings = getattr(device, "_count_between_markers", None)
            if settings is None:
                raise RuntimeError("External counter does not expose click-channel settings")
            settings["click_channel"] = values["click_channel"]
        if "B_amp" in values and changed.intersection(("B_amp", "B_theta", "B_phi")):
            self._ramp_magnet(values, experiment.stabilization.use_defect_frame, control)
        if "smiq_freq" in values and changed.intersection(("smiq_freq", "smiq_power_dbm")):
            self._set_microwave(values)
        if "pulse_shape_ppg" in values and changed.intersection(
            ("pulse_shape_ppg", "pulse_width_ppg", "pulse_delay_ppg", "pulse_amplitude_ppg")
        ):
            self._update_ppg(values)

        policy = experiment.stabilization
        self._maybe_refocus("green", policy.green_interval_s, control)
        self._maybe_refocus("ple", policy.ple_refocus_interval_s, control, lock_after=policy.lock_laser_to_wavemeter)
        self._maybe_refocus("red", policy.red_interval_s, control)
        self._last_values = values
        return self._observations()

    @staticmethod
    def _values_equal(left, right):
        try:
            return bool(np.array_equal(left, right))
        except (TypeError, ValueError):
            return left == right

    @staticmethod
    def is_quiet_time(policy, current_time):
        if policy.quiet_hours_start is None:
            return False
        start_hour, start_minute = (int(part) for part in policy.quiet_hours_start.split(":"))
        end_hour, end_minute = (int(part) for part in policy.quiet_hours_end.split(":"))
        current = current_time.hour * 60 + current_time.minute
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _wait_for_quiet_hours(self, policy, control):
        reported = False
        while self.is_quiet_time(policy, datetime.now().time()):
            if not reported:
                self._message("info", "Nuclear experiment paused for configured quiet hours")
                reported = True
            control.wait(30.0)
        if reported:
            self._message("info", "Nuclear experiment continuing after quiet hours")

    def after_run(self, experiment, status):
        if self._laser_locked:
            try:
                self.stop_laser_lock()
            except Exception as exc:
                self._message("error", "Unable to stop laser lock: {}".format(exc))

    def _ensure_default_microwave(self, parameters):
        if self.microwave is None or "smiq_freq" in parameters:
            return
        frequency = parameters.get("smiq_default_frequency_hz")
        power = parameters.get("smiq_default_power_dbm")
        if frequency is None or power is None:
            return
        self._set_microwave({"smiq_freq": frequency, "smiq_power_dbm": power})

    def _set_microwave(self, values):
        microwave = self._require(self.microwave, "SMIQ frequency scan")
        frequency = float(values["smiq_freq"])
        power = float(values.get("smiq_power_dbm", getattr(microwave, "cw_power", 0.0)))
        if getattr(microwave, "is_scanning", False):
            raise RuntimeError("Cannot update the SMIQ while it is in scan mode")
        live = getattr(microwave, "set_cw_parameters_live", None)
        if callable(live):
            live(frequency=frequency, power=power)
        else:
            if getattr(microwave, "module_state")() != "idle":
                microwave.off()
            microwave.set_cw(frequency=frequency, power=power)
        if getattr(microwave, "module_state")() == "idle":
            microwave.cw_on()

    @staticmethod
    def _spherical_to_cartesian(vector):
        radius, theta_deg, phi_deg = vector
        theta = math.radians(theta_deg)
        phi = math.radians(phi_deg)
        return np.asarray(
            [radius * math.sin(theta) * math.cos(phi), radius * math.sin(theta) * math.sin(phi), radius * math.cos(theta)]
        )

    def _ramp_magnet(self, values, use_defect_frame, control):
        magnet = self._require(self.magnet, "Magnet scan")
        requested = np.asarray(
            [float(values["B_amp"]) * 1e-3, float(values.get("B_theta", 0)), float(values.get("B_phi", 0))]
        )
        if use_defect_frame:
            cartesian = self._spherical_to_cartesian(requested)
            cartesian = magnet.rotate_vector(cartesian, 55, 225)
            requested = magnet.cartesian_to_spherical(cartesian)
        magnet.ramp(requested)
        control.wait(0.5)
        hardware = getattr(magnet, "_magnet", magnet)
        get_state = getattr(hardware, "get_ramping_state", None)
        while callable(get_state) and min(get_state()) == 1:
            control.wait(0.1)
        control.wait(3.0)

    def _update_ppg(self, values):
        ppg = self._require(self.ppg, "PPG waveform scan")
        if "pulse_width_ppg" not in values:
            raise ValueError("pulse_width_ppg is required when pulse_shape_ppg is scanned")
        kwargs = {
            "pulse_shape": values["pulse_shape_ppg"],
            "pulse_width": values["pulse_width_ppg"],
        }
        if "pulse_delay_ppg" in values:
            kwargs["pulse_delay"] = values["pulse_delay_ppg"]
        if "pulse_amplitude_ppg" in values:
            kwargs["pulse_amplitude"] = values["pulse_amplitude_ppg"]
        if ppg.write_pulse(**kwargs) is False:
            raise RuntimeError("PPG rejected waveform update")

    def _maybe_refocus(self, kind, interval_s, control, lock_after=False):
        if interval_s is None or time.monotonic() - self._last_refocus[kind] < interval_s:
            return
        if kind == "ple":
            self._refocus_ple(control, lock_after)
        else:
            self._refocus_confocal(control, red=(kind == "red"))
        self._last_refocus[kind] = time.monotonic()

    def _stop_qm_job(self):
        if self.quantum_machine is not None:
            stop = getattr(self.quantum_machine, "stop_current_job", None)
            if callable(stop):
                stop()

    def _refocus_confocal(self, control, red):
        optimizer = self._require(self.confocal_optimizer, "Confocal refocus")
        switches = self._require(self.switches, "Confocal refocus switches")
        self._stop_qm_job()
        laser = "Laser_620" if red else "Laser_520"
        switches.set_state(laser, "on")
        try:
            optimizer.toggle_optimize(True)
            while optimizer.optimizer_running:
                control.wait(0.1)
        finally:
            switches.set_state(laser, "off")
        control.wait(0.5)

    def _refocus_ple(self, control, lock_after):
        optimizer = self._require(self.ple_optimizer, "PLE refocus")
        self._stop_qm_job()
        if self._laser_locked:
            self.stop_laser_lock()
        optimizer.toggle_optimize(True)
        while optimizer.optimizer_running:
            control.wait(0.1)
        control.wait(0.5)
        if lock_after:
            self.start_laser_lock(control=control)
            control.wait(2.0)

    def start_laser_lock(self, wavelength_nm=None, control=None):
        wavemeter = self._require(self.wavemeter, "Wavemeter laser lock")
        laser = self._require(self.laser_controller, "Wavemeter laser lock")
        if wavelength_nm is None:
            wavelength_nm = wavemeter.get_current_wavelength(kind="nm")
        voltage = laser.get_pc_voltage_act()
        laser.set_slew_rate(0.0008)
        laser.use_analog_remote_control(False)
        laser.set_pc_voltage(voltage + 0.2)
        laser.set_slew_rate(10)
        if control is None:
            time.sleep(1.0)
        else:
            control.wait(1.0)
        wavemeter.start_lock(wavelength_nm)
        if self.transition_tracker is not None:
            update = getattr(self.transition_tracker, "update_ple", None)
            if callable(update):
                update(wavelength_nm)
        self._laser_locked = True

    def stop_laser_lock(self):
        self._require(self.wavemeter, "Wavemeter laser lock").stop_lock()
        laser = self._require(self.laser_controller, "Wavemeter laser lock")
        laser.set_slew_rate(0.0008)
        laser.set_pc_voltage(self.IDLE_LASER_SCANNER_VOLTAGE)
        laser.use_analog_remote_control(True)
        laser.set_slew_rate(10)
        self._laser_locked = False

    def _observations(self):
        result = {}
        tracker = self.transition_tracker
        if tracker is not None:
            for name in (
                "mw_mixing_frequency_L",
                "mw_mixing_frequency_R",
                "current_local_oscillator_freq",
                "ple_A1",
                "ple_A2",
            ):
                if hasattr(tracker, name):
                    result[name] = getattr(tracker, name)
        if self.confocal is not None:
            position = getattr(self.confocal, "scanner_position", {})
            for axis in ("x", "y", "z"):
                if axis in position:
                    result["confocal_{}".format(axis)] = position[axis]
        return result
