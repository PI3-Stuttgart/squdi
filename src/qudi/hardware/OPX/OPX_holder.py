import json
from qm import SimulationConfig, LoopbackInterface
from qm.grpc.qua import QuaProgramArrayVarRefExpression, QuaProgramVarRefExpression
from qm.qua import *

# from qm import QuantumMachinesManager
from qm.quantum_machines_manager import QuantumMachinesManager
from qm.qua._expressions import QuaVariable

# from configuration import *
import importlib
from typing import Dict, Tuple, Any, Union

import qm.exceptions
from qualang_tools.control_panel import ManualOutputControl
import qm
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.core.module import Base
from qudi.hardware.OPX.configuration import *


# class OPXmanual(Base):
#   ### TODO manualoutputcontrol.


class OPX(Base):  # hardware, awg,
    """.
    Example config for copy-paste:
    OPX:
        module.Class: 'OPX_holder'
        options:
    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )

    _configuration: Any
    _qm_manual_output_control = None

    # TODO: Is this init function needed?
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = RecursiveMutex()
        self._channels = tuple()
        self.debug_mode = False
        self._qm = None
        self.mcas_dict = dict()
        self.cw_job = None
        self.cw_do_states = {}
        self.cw_ao_values = {}

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        # Establish connection to OPX+
        self._connect_to_OPX()

    def _volt2amp(self, voltage: float) -> float:
        # TODO: Nur für den aktuellen fall, das der Maximalwert von 0.5V nicht verändert wird
        return 1 * voltage

    def on_deactivate(self) -> None:
        self.cw_job.halt()
        """TODO: disconnect from OPX?"""

    def update_cw_do(self, switch: str, state):
        self.cw_do_states[switch] = state
        self.run_cw_mode()

    def update_cw_ao(self, channel, value):
        self.cw_ao_values[channel] = value
        self.run_cw_mode()

    def run_cw_mode(self) -> None:
        curr_do: list = [
            key for key, value in self.cw_do_states.items() if value == "on"
        ]
        curr_ao = {
            key: value for key, value in self.cw_ao_values.items() if value != 0.0
        }
        dict_curr_do = {
            key: (value == "on") for key, value in self.cw_do_states.items()
        }
        # check if any output should be set, if not stop the current qm program
        if not curr_do and not curr_ao:
            if self.cw_job:
                self.cw_job.halt()
        else:
            duration = 1 * u.us

            with program() as cw_program:
                with infinite_loop_():
                    for ao, power in curr_ao.items():
                        play(
                            "power" * amp(self._volt2amp(power)), ao, duration=duration
                        )
                    for do in curr_do:
                        play("active", do, duration=duration)

            # self.simulate(cw_program, plot=True)
            print(self._volt2amp(self.cw_ao_values["LaserScanner_red"]))
            self.cw_job = self.qm.execute(cw_program)

    def stop_cw_mode(self):
        pass

    @property
    def qm(self):
        return self._qm

    def simulate(self, sequence, save_path=None, plot=False, duration=1_000):
        """
        :param sequence: program() of the opx to simulate
        :return: opens a plotly html window with the sequence.
        """
        self.log.info("simulate")
        simulation_config = SimulationConfig(duration=duration)  # In clock cycles = 4ns
        job_sim = self.qmm.simulate(
            self._configuration.config, sequence, simulation_config
        )
        # Simulate blocks python until the simulation is done
        # job_sim.get_simulated_samples().con1
        # job_sim.get_simulated_samples().con1.plot()
        # plt.show()
        # get DAC and digital samples (optional).
        samples = job_sim.get_simulated_samples()
        # get the waveform report object
        waveform_report = job_sim.get_simulated_waveform_report()
        waveform_dict = waveform_report.to_dict()
        if not save_path is None:
            with open(os.path.join(save_path, "awg_file.json"), "w") as fp:
                json.dump(waveform_dict, fp)
        if plot:
            waveform_report.create_plot(
                samples, plot=plot, save_path="./" if save_path is None else save_path
            )

    def _connect_to_OPX(self) -> None:
        try:
            self.qmm = QuantumMachinesManager(
                host=self._configuration.qop_ip,
                cluster_name=self._configuration.cluster_name,
                octave=self._configuration.octave_config,
            )
            self._qm = self.qmm.open_qm(config=self._configuration.config)

        except qm.exceptions.OpenQmException:
            self.log.warning(
                "Could not connect to OPX with keeping previous connections. Previouse connections disconnected."
            )
            pass  # do nothing for now...

    @property
    def is_connected(self):
        is_connected = False if self._qm is None else True
        return is_connected

    def stop_awgs(self):
        """Stop all the tasks of the OPX..."""
        pass

    @property
    def name(self) -> str:
        """Name of the hardware as string.
        @return str: The name of the hardware
        """
        return self._configuration.cluster_name
