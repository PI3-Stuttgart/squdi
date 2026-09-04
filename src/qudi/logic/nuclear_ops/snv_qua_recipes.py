"""Finite native-QUA recipes for the common SnV nuclear experiment family."""

from enum import Enum

import numpy as np

from .models import AxisExecution
from .recipes import AcquisitionResult, ProgramBundle, QmStreamRecipe, StreamOutput


class SnVProtocol(str, Enum):
    RABI = "rabi"
    RAMSEY = "ramsey"
    HAHN_ECHO = "hahn_echo"
    T1 = "t1"
    PULSED_ODMR = "pulsed_odmr"
    SSR_CALIBRATION = "ssr_calibration"


class SnVQuaRecipe(QmStreamRecipe):
    """Shared CRC/init/manipulation/SSR/CSR sequence with native streams."""

    protocol = None
    axis_policies = {
        "sweeps": AxisExecution.QUA,
        "pulse_length": AxisExecution.QUA,
        "MW_pulse_len": AxisExecution.QUA,
        "tau": AxisExecution.QUA,
        "readout_delay": AxisExecution.QUA,
        "MW_f": AxisExecution.QUA,
        "last_phase": AxisExecution.QUA,
        "B_amp": AxisExecution.HOST,
        "B_theta": AxisExecution.HOST,
        "B_phi": AxisExecution.HOST,
        "smiq_freq": AxisExecution.HOST,
        "smiq_power_dbm": AxisExecution.HOST,
        "click_channel": AxisExecution.HOST,
        "init_state": AxisExecution.RECOMPILE,
        "SSR_state": AxisExecution.RECOMPILE,
        "pulse_shape_ppg": AxisExecution.HOST,
        "pulse_width_ppg": AxisExecution.HOST,
        "pulse_delay_ppg": AxisExecution.HOST,
        "pulse_amplitude_ppg": AxisExecution.HOST,
    }
    stream_outputs = (
        StreamOutput("crc_counts", "crc_counts", unit="counts"),
        StreamOutput("initial_counts", "initial_counts", unit="counts"),
        StreamOutput("result_counts", "result_counts", unit="counts"),
        StreamOutput("csr_counts", "csr_counts", unit="counts"),
        StreamOutput("crc_success_fraction", "crc_success_fraction"),
    )

    def validate(self, experiment):
        super().validate(experiment)
        if self.protocol is None:
            raise ValueError("SnVQuaRecipe subclasses must define a protocol")
        for axis in experiment.scan_axes:
            if axis.execution == AxisExecution.QUA or (
                axis.execution == AxisExecution.AUTO
                and self.axis_policies.get(axis.name) == AxisExecution.QUA
            ):
                values = np.asarray(axis.values)
                if not (
                    np.issubdtype(values.dtype, np.integer)
                    or np.issubdtype(values.dtype, np.floating)
                ):
                    raise TypeError("QUA axis {!r} must be numeric".format(axis.name))

    @staticmethod
    def _cycles(value):
        if isinstance(value, (int, float, np.number)):
            cycles = int(round(float(value) / 4.0))
            if cycles < 4:
                raise ValueError("QUA pulse/wait durations must be at least 16 ns")
            return cycles
        return value / 4

    @staticmethod
    def _compare(value, rule):
        if rule.comparison == ">":
            return value > rule.counts
        if rule.comparison == ">=":
            return value >= rule.counts
        if rule.comparison == "<":
            return value < rule.counts
        return value <= rule.counts

    def build_program(self, context):
        from qm import qua

        parameters = context.parameters
        point_count = context.block.qua_points
        integrations = int(parameters.get("integrations", 1))
        if integrations < 1:
            raise ValueError("integrations must be positive")
        max_time_tags = int(parameters.get("max_time_tags", 4_096))
        if max_time_tags < 1:
            raise ValueError("max_time_tags must be positive")
        spcm = str(parameters.get("spcm_element", "SPCM1"))
        mw_element = str(parameters.get("mw_element", "MW"))
        mw_pulse = str(parameters.get("mw_pulse", "x"))
        init_state = str(parameters.get("init_state", "e1"))
        ssr_state = str(parameters.get("SSR_state", "e1"))
        if init_state not in ("e1", "e2") or ssr_state not in ("e1", "e2"):
            raise ValueError("init_state and SSR_state must be 'e1' or 'e2'")

        crc_accept = context.thresholds.profile.resolve("crc_accept")
        crc_repump = context.thresholds.profile.resolve("crc_repump")

        with qua.program() as program:
            counts = qua.declare(int)
            crc_attempts = qua.declare(int)
            crc_success = qua.declare(bool)
            times = qua.declare(int, size=max_time_tags)
            integration_index = qua.declare(int)
            streams = {
                name: qua.declare_stream()
                for name in (
                    "crc_counts",
                    "initial_counts",
                    "result_counts",
                    "csr_counts",
                    "crc_success_fraction",
                )
            }

            axis_variables = {}
            for axis in context.block.qua_axes:
                values = np.asarray(axis.values)
                qua_type = int if np.issubdtype(values.dtype, np.integer) else qua.fixed
                axis_variables[axis.name] = qua.declare(qua_type)

            def value(*names, default=None):
                for name in names:
                    if name in axis_variables:
                        return axis_variables[name]
                    if name in parameters:
                        return parameters[name]
                return default

            def pulse(laser, duration_ns):
                qua.play("active", laser, duration=self._cycles(duration_ns))

            def readout(lasers, duration_ns):
                lasers = tuple(lasers)
                qua.align(spcm, *lasers)
                qua.measure(
                    "readout",
                    spcm,
                    None,
                    qua.time_tagging.analog(times, int(duration_ns), counts),
                )
                for laser in lasers:
                    pulse(laser, duration_ns)
                qua.align(spcm, *lasers)

            def save_readout(stream_name, lasers, duration_ns):
                readout(lasers, duration_ns)
                qua.save(counts, streams[stream_name])

            def crc():
                qua.assign(counts, 0)
                qua.assign(crc_attempts, 0)
                maximum = int(parameters.get("crc_max_attempts", 1_000))
                with qua.while_((~self._compare(counts, crc_accept)) & (crc_attempts < maximum)):
                    readout(
                        ("Laser_620", "Laser_620_det"),
                        int(parameters.get("crc_probe_duration_ns", 1_000_000)),
                    )
                    with qua.if_(self._compare(counts, crc_repump)):
                        pulse(
                            "Laser_520",
                            int(parameters.get("crc_repump_duration_ns", 100_000)),
                        )
                    qua.assign(crc_attempts, crc_attempts + 1)
                    qua.wait(self._cycles(int(parameters.get("crc_wait_ns", 50_000))))
                qua.assign(crc_success, self._compare(counts, crc_accept))
                qua.save(counts, streams["crc_counts"])
                qua.save(crc_success, streams["crc_success_fraction"])

            def electron_initialize():
                laser = "Laser_620" if init_state == "e1" else "Laser_620_det"
                pulse(laser, int(parameters.get("electron_init_duration_ns", 3_000_000)))
                qua.align()

            def mw(duration_ns, pulse_name=mw_pulse):
                amplitude = float(parameters.get("mw_amplitude", parameters.get("MW_amp", 1.0)))
                if abs(amplitude) > 2:
                    amplitude /= 100.0
                qua.play(
                    pulse_name * qua.amp(amplitude),
                    mw_element,
                    duration=self._cycles(duration_ns),
                )
                qua.align()

            def manipulate():
                pi_ns = value("electron_pi_duration_ns", default=parameters.get("electron_pi_duration_ns", 1620))
                pi_half_ns = pi_ns / 2
                if self.protocol == SnVProtocol.RABI:
                    mw(value("pulse_length", "MW_pulse_len", default=pi_ns))
                elif self.protocol == SnVProtocol.RAMSEY:
                    mw(pi_half_ns)
                    qua.wait(self._cycles(value("tau", default=100)))
                    phase = value("last_phase", default=parameters.get("last_phase", 0.0))
                    qua.frame_rotation_2pi(phase, mw_element)
                    mw(pi_half_ns)
                    qua.reset_frame(mw_element)
                elif self.protocol == SnVProtocol.HAHN_ECHO:
                    tau = value("tau", default=100)
                    mw(pi_half_ns)
                    qua.wait(self._cycles(tau))
                    mw(pi_ns)
                    qua.wait(self._cycles(tau))
                    phase = value("last_phase", default=parameters.get("last_phase", 0.0))
                    qua.frame_rotation_2pi(phase, mw_element)
                    mw(pi_half_ns)
                    qua.reset_frame(mw_element)
                elif self.protocol == SnVProtocol.T1:
                    qua.wait(self._cycles(value("readout_delay", "tau", default=1_000)))
                elif self.protocol == SnVProtocol.PULSED_ODMR:
                    qua.update_frequency(
                        mw_element,
                        value("MW_f", "mw_frequency", default=202_360_000),
                    )
                    mw(value("MW_pulse_len", "pulse_length", default=1_000))
                elif self.protocol == SnVProtocol.SSR_CALIBRATION:
                    return

            def point():
                crc()
                electron_initialize()
                initial_laser = "Laser_620_det" if init_state == "e1" else "Laser_620"
                result_laser = "Laser_620_det" if ssr_state == "e1" else "Laser_620"
                ssr_duration = int(parameters.get("ssr_duration_ns", 300_000))
                save_readout("initial_counts", (initial_laser,), ssr_duration)
                manipulate()
                save_readout("result_counts", (result_laser,), ssr_duration)
                save_readout(
                    "csr_counts",
                    ("Laser_620", "Laser_620_det"),
                    int(parameters.get("csr_duration_ns", 1_000_000)),
                )
                qua.wait(self._cycles(int(parameters.get("cooldown_time", 100_000))))

            def nested_axis_loop(index):
                if index == len(context.block.qua_axes):
                    point()
                    return
                axis = context.block.qua_axes[index]
                values = [
                    int(item) if isinstance(item, (int, np.integer)) else float(item)
                    for item in axis.values
                ]
                with qua.for_each_(axis_variables[axis.name], values):
                    nested_axis_loop(index + 1)

            with qua.for_(
                integration_index,
                0,
                integration_index < integrations,
                integration_index + 1,
            ):
                nested_axis_loop(0)

            with qua.stream_processing():
                for name in ("crc_counts", "initial_counts", "result_counts", "csr_counts"):
                    streams[name].buffer(point_count).average().save(name)
                streams["crc_success_fraction"].boolean_to_int().buffer(point_count).average().save(
                    "crc_success_fraction"
                )

        return ProgramBundle(
            program=program,
            metadata={
                "recipe": self.name,
                "protocol": self.protocol.value,
                "points": point_count,
                "integrations": integrations,
                "spcm_element": spcm,
                "mw_element": mw_element,
            },
        )

    def acquire(self, job, context, timeout_s):
        result = super().acquire(job, context, timeout_s)
        fractions = np.asarray(result.batch.dataset["crc_success_fraction"].values)
        if np.any(fractions < 1.0):
            return AcquisitionResult(
                result.batch,
                valid=False,
                invalid_reason="CRC did not succeed for every integration",
            )
        return result


class NuclearRabiRecipe(SnVQuaRecipe):
    name = "nuclear_rabi"
    protocol = SnVProtocol.RABI


class RamseyRecipe(SnVQuaRecipe):
    name = "ramsey"
    protocol = SnVProtocol.RAMSEY


class HahnEchoRecipe(SnVQuaRecipe):
    name = "hahn_echo"
    protocol = SnVProtocol.HAHN_ECHO


class T1Recipe(SnVQuaRecipe):
    name = "t1"
    protocol = SnVProtocol.T1


class PulsedOdmrRecipe(SnVQuaRecipe):
    name = "pulsed_odmr"
    protocol = SnVProtocol.PULSED_ODMR


class SsrCalibrationRecipe(SnVQuaRecipe):
    name = "ssr_calibration"
    protocol = SnVProtocol.SSR_CALIBRATION


def register_recipes(registry):
    for recipe in (
        NuclearRabiRecipe(),
        RamseyRecipe(),
        HahnEchoRecipe(),
        T1Recipe(),
        PulsedOdmrRecipe(),
        SsrCalibrationRecipe(),
    ):
        registry.register(recipe)
