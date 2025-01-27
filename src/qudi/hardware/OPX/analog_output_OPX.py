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

from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict

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
    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )
    _switch_time = ConfigOption(name="switch_time", default=1, missing="nothing")
    _ao_options = ConfigOption(name="analog_outputs", default={}, missing="nothing")
    _configuration = None
    _qm_manual_output_control = None
    _constraints = None
    _opx = None
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
        if not self._opx.is_connected:
            self.log.error("no connection to OPX")

        self._opx.cw_ao_values = {ao: 0 for ao in self.constraints.setpoint_channels}
        self.qm_scan_module = importlib.import_module(self.qm_prog_file_name)

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
        print(self._ao_options)
        for ch in _channels:
            if ch in self._ao_options.keys():
                _limits[ch] = tuple(self._ao_options[ch]["limits"])
            else:
                _limits[ch] = (
                    -1,
                    1,
                )  # V (It should be 0.5, but for what ever reason it is 1

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

    def start_scan(self):
        self._ple_job = self._opx.qm.execute(self.get_qm_scan_program())

        # res_handles = self._ple_job.result_handles
        # counts_handle = res_handles.get("counts")
        # counts_handle.wait_for_values(1)
        # while res_handles.is_processing():
        # print(counts_handle.fetch_all()["value"])
        # self._opx.simulate(self.get_qm_scan_program(), plot=True)

    def stop_scan(self):
        self._ple_job.halt()

    def get_qm_scan_program(self):
        importlib.reload(self.qm_scan_module)
        return self.qm_scan_module.qm_scan_program(self)
