import importlib
import sys
from typing import Dict, Tuple, Any
import time

from qualang_tools.control_panel import ManualOutputControl
import qm
import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)
from qudi.interface.triggered_ao_interface import TriggeredAOInterface

from qudi.core.connector import Connector
from qudi.hardware.OPX.OPX_holder import OPX as _OPX
from qudi.hardware.picoquant.ppg512 import PPG512 as _PPG
from qudi.hardware.OPX.configuration import *
from PySide2.QtCore import QTimer

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict

from qudi.hardware.OPX.OPX_utils import crc

_Real = Union[int, float]


class AnalogOutputOPX(ProcessSetpointInterface):
    """Module to set the manually set the Analog Outputs of the QuantumMachines OPX+.
    Channels are defined by the OPXs own config file and not using qudi.
    Example config for copy-paste:
    AO_OPX:
        module.Class: 'OPX.analog_output_OPX.AnalogOutputOPX'
        connect:
            OPX: "OPX"
        options:
            qm_config_file: "configuration"
    """

    OPX: _OPX = Connector(interface="OPX")
    PPG: _PPG = Connector(interface="PPG512")

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )
    _switch_time = ConfigOption(name="switch_time", default=1, missing="nothing")
    _ao_options = ConfigOption(name="analog_outputs", default={}, missing="nothing")
    _configuration = None
    _qm_manual_output_control = None
    _constraints = None
    _opx = None
    _ppg = None
    _scan_parameters = None
    _ple_job = None
    qm_prog_file_name = "qudi.hardware.OPX.PLE_program"

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        globals().update(vars(self._configuration))

        # Establish connection to OPX+
        self._set_constraints()
        # Check connection to OPX+
        self._opx = self.OPX()
        self._ppg = self.PPG()
        if not self._opx.is_connected:
            self.log.error("no connection to OPX")

        self._opx.cw_ao_values = {ao: 0 for ao in self.constraints.setpoint_channels}
        self.qm_scan_module = importlib.import_module(self.qm_prog_file_name)

        self._scan_timer = None
        self._res_handles = None
        self._counts_handle = None

    def on_deactivate(self) -> None:
        pass

    def _set_constraints(self):
        _channels: list = []
        for name, qm_element in self._configuration.config["elements"].items():
            if (
                "singleInput" in qm_element.keys()
                or "multipleInputs" in qm_element.keys()
            ):
                _channels.append(name)

        # add limits from qudi config if defined
        _limits = {}
        for ch in _channels:
            if ch in self._ao_options.keys():
                _limits[ch] = tuple(self._ao_options[ch]["limits"])
            else:
                _limits[ch] = (
                    -0.5,
                    0.5,
                )  # default full voltage range OPX+

        self._constraints = ProcessControlConstraints(
            setpoint_channels=_channels,
            units={ch: "V" for ch in _channels},
            limits=_limits,
            dtypes={ch: float for ch in _channels},
        )

    @property
    def constraints(self) -> ProcessControlConstraints:
        """Read-Only property holding the constraints for this hardware module.
        See class ProcessControlConstraints for more details.
        """
        return self._constraints

    def set_activity_state(self, channel: str, active: bool) -> None:
        """Set activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        OPX channels are always active, only setting the amplitude to zero sets them as
        inactive. This means it the active input is False, the amplitude is set to zero,
        but if it is set to True a warning is raised, as with this method no amplitude
        value is defined.
        """
        if active:
            self.log.warning(
                "OPX AO is always active, amplitude only can be set to zero for inactive state"
            )
        if not active:
            self.set_setpoint(channel, 0)

    def get_activity_state(self, channel: str) -> bool:
        """Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        if self._opx.cw_ao_values[channel] == 0:
            return False
        else:
            return True

    def set_setpoint(self, channel: str, value: float) -> None:
        """Set new setpoint for a single channel"""
        self._opx.update_cw_ao(channel, value)
        # if channel == "LaserScanner_red":
        #    self.log.warning("Changing the setpoint of the laser scanner")

    def get_setpoint(self, channel: str) -> float:
        """Get current setpoint for a single channel"""
        return self._opx.cw_ao_values[channel]

    def set_scan_parameters(
        self,
        voltage_start: _Real,
        voltage_stop: _Real,
        sweep_duration: _Real,
        nr_of_scans: int,
        nr_steps: int = 1000,
        back_scan_duration: float = 1,
    ) -> None:
        self._scan_parameters = {
            "channel": "LaserScanner_red",
            "voltage_start": voltage_start,
            "voltage_stop": voltage_stop,
            "sweep_duration": sweep_duration,
            "nr_amp_steps": nr_steps,
            "nr_of_scans": nr_of_scans,
            "back_scan_duration": back_scan_duration,
        }

    def get_scan_parameters(self, channel: str) -> (_Real, _Real, _Real):
        if channel == self._scan_parameters["channel"]:
            scan_parameters = (
                self._scan_parameters["voltage_start"],
                self._scan_parameters["voltage_stop"],
                self._scan_parameters["sweep_duration"],
            )
            return scan_parameters
        else:
            self.log.error("For this channel no scan parameters are defined")

    def get_opx_counts(self):
        if self._ple_job is None:
            return None
        try:
            return self._ple_job.result_handles.get("counts").fetch_all()["value"]
        except Exception:
            return None

    def start_scan(self, simulate=False):
        self.log.info("Starting scan... 2")
        if simulate:
            self._opx.simulate(self.get_qm_scan_program(), plot=True)
        else:
            self._ple_job = self._opx.qm.execute(self.get_qm_scan_program())
            # self._res_handles = self._ple_job.result_handles
            # self._counts_handle = self._res_handles.get("counts")
            # self._counts_handle.wait_for_values(1)

    # res_handles = self._ple_job.result_handles
    # counts_handle = res_handles.get("counts")
    # counts_handle.wait_for_values(1)
    # while res_handles.is_processing():
    # print(counts_handle.fetch_all()["value"])

    def stop_scan(self):
        if self._ple_job is not None:
            self._ple_job.halt()

    def get_qm_scan_program(self):
        importlib.reload(self.qm_scan_module)
        return self.qm_scan_module.qm_scan_program(self)

    def pulses_definition(
        self,
        pulse_width: float,
        pulse_shape: str,
        pulse_delay: float,
        pulse_amplitude: int = 255,
    ):
        return self._ppg.write_pulse(
            pulse_width, pulse_shape, pulse_delay, pulse_amplitude
        )

    def run_arb_puls(
        self,
        pulse_width: float,
        pulse_shape: str,
        pulse_amplitude: int = 255,
        ppg_pulse_delay: float = 0,
        counting_delay: float = 0,
        wait_between_pulses: float = 1000,
        AOM_end_buffer: float = 0,  # ns
        res_power=1,
        vccrf=None,
        vref=None,
        green_power=0.02,
    ):
        """Writes a pulse defined by the input parameters to the PPG and triggers it using the OPX.
        Args:
            pulse_width (float): Width of the Puls (FWHM for Gaussian) in ns.
            pulse_shape (str): Right now only "gaussian" and "square" are implemented.
            pulse_amplitude (int, optional): Pulse amplitude in units of 1/255 of the maximum voltage supplied by the PPG. Defaults to 255.
            ppg_pulse_delay (float, optional): Delay of the PPG puls relative to the AOM in ns. Defaults to 0.
            counting_delay (float, optional): Delay of the counting (Trigger to TT) relative to the PPG pulse in ns. Defaults to 0.
            res_power (int, optional): Power of the AOM in V (TODO: power in W)
        """
        PPG_write_status: bool = self.pulses_definition(
            pulse_width, pulse_shape, ppg_pulse_delay, pulse_amplitude
        )
        if vccrf is not None:
            self._ppg.set_vccrf(vccrf)
        if vref is not None:
            self._ppg.set_vref(vref)

        self._opx.update_config()
        with program() as arb_pulse:
            set_dc_offset(
                "LaserScanner_red", "single", self.get_setpoint("LaserScanner_red")
            )
            set_dc_offset("620_pi_w_power", "single", res_power)

            with infinite_loop_():
                align()
                if green_power > 0:
                    play(
                        "pulse" * amp(green_power),
                        "Laser_520",
                        duration=(
                            (pulse_width + AOM_end_buffer) * u.ns
                            if (pulse_width + AOM_end_buffer) > 16
                            else 16 * u.ns
                        ),
                    )
                play(
                    pulse="trigit",
                    element="620_pi",
                    duration=(
                        (pulse_width + AOM_end_buffer) * u.ns
                        if (pulse_width + AOM_end_buffer) > 16
                        else 16 * u.ns
                    ),
                )
                play("trigit", "Gate_Trigger", duration=20 * u.ns)
                wait(wait_between_pulses * u.ns)

        self._arb_job = self._opx.qm.execute(arb_pulse)

    def run_arb_puls_crc(
        self,
        pulse_width: float,
        pulse_shape: str,
        pulse_amplitude: int = 255,
        ppg_pulse_delay: float = 0,
        counting_delay: float = 0,
        wait_between_pulses: float = 1000,
        AOM_end_buffer: float = 0,  # ns
        res_power=1,
        vccrf=None,
        vref=None,
        green_power=0.02,
    ):
        """Writes a pulse defined by the input parameters to the PPG and triggers it using the OPX.
        Args:
            pulse_width (float): Width of the Puls (FWHM for Gaussian) in ns.
            pulse_shape (str): Right now only "gaussian" and "square" are implemented.
            pulse_amplitude (int, optional): Pulse amplitude in units of 1/255 of the maximum voltage supplied by the PPG. Defaults to 255.
            ppg_pulse_delay (float, optional): Delay of the PPG puls relative to the AOM in ns. Defaults to 0.
            counting_delay (float, optional): Delay of the counting (Trigger to TT) relative to the PPG pulse in ns. Defaults to 0.
            res_power (int, optional): Power of the AOM. between 0, 1. Defaults to 0.
        """
        PPG_write_status: bool = self.pulses_definition(
            pulse_width, pulse_shape, ppg_pulse_delay, pulse_amplitude
        )
        if vccrf is not None:
            self._ppg.set_vccrf(vccrf)
        if vref is not None:
            self._ppg.set_vref(vref)

        self._opx.update_config()
        with program() as arb_pulse:
            set_dc_offset(
                "LaserScanner_red", "single", self.get_setpoint("LaserScanner_red")
            )
            set_dc_offset("620_pi_w_power", "single", res_power)

            with for_():
                align()
                if green_power > 0:
                    play(
                        "pulse" * amp(green_power),
                        "Laser_520",
                        duration=(
                            (pulse_width + AOM_end_buffer) * u.ns
                            if (pulse_width + AOM_end_buffer) > 16
                            else 16 * u.ns
                        ),
                    )
                play(
                    pulse="trigit",
                    element="620_pi",
                    duration=(
                        (pulse_width + AOM_end_buffer) * u.ns
                        if (pulse_width + AOM_end_buffer) > 16
                        else 16 * u.ns
                    ),
                )
                play("trigit", "Gate_Trigger", duration=20 * u.ns)
                wait(wait_between_pulses * u.ns)

        self._arb_job = self._opx.qm.execute(arb_pulse)

    def stop_curr_pulses(self):
        self._arb_job.halt()

    def run_rabi(self, simulate=False):
        self._opx.update_config()
        # self._configuration.config["elements"]["Gate_Trigger"]["digitalInputs"]["trigger"]["delay"] = 543 * u.ns
        aom_pulse_len = 30 * u.ns
        with program() as pi_pulse:
            set_dc_offset(
                "LaserScanner_red", "single", self.get_setpoint("LaserScanner_red")
            )
            with infinite_loop_():
                align()
                play("pulse" * amp(0.02), "Laser_520", duration=300 * u.ns)
                # play("active", "Laser_450", duration=1000 * u.ns)
                play(pulse="trigit", element="620_pi", duration=aom_pulse_len * u.ns)
                play("trigit", "Gate_Trigger", duration=20 * u.ns)
        self._rabi_job = self._opx.qm.execute(pi_pulse)

    def stop_rabi(self):
        self._rabi_job.halt()

    def run_gauss(self, simulate=False):
        self._opx.update_config()
        # self._configuration.config["elements"]["Gate_Trigger"]["digitalInputs"]["trigger"]["delay"] = 543 * u.ns
        aom_pulse_len = 10 * u.ns
        with program() as gauss_pulse:
            set_dc_offset(
                "LaserScanner_red", "single", self.get_setpoint("LaserScanner_red")
            )
            with infinite_loop_():
                align()
                play("pulse" * amp(0.02), "Laser_520", duration=300 * u.ns)
                # play("active", "Laser_450", duration=1000 * u.ns)
                play(pulse="trigit", element="620_pi", duration=aom_pulse_len * u.ns)
                play("trigit", "Gate_Trigger", duration=20 * u.ns)
        self._gauss_job = self._opx.qm.execute(gauss_pulse)

    def stop_gauss(self):
        self._gauss_job.halt()
