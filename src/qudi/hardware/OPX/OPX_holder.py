# from configuration import *
import importlib
import json
import sys
import time
from typing import Any

import qm
import qm.exceptions
from qm import SimulationConfig
from qm.qua import *

# from qm import QuantumMachinesManager
from qm.quantum_machines_manager import QuantumMachinesManager
from qudi.core.configoption import ConfigOption
from qudi.core.module import Base
from qudi.util.mutex import RecursiveMutex

# from qudi.hardware.OPX.configuration import *

config_module = importlib.import_module("qudi.hardware.OPX.configuration")
globals().update(
    {name: getattr(config_module, name) for name in dir(config_module) if not name.startswith("_")}
)


# class OPXmanual(Base):
# TODO manualoutputcontrol.


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
    config: Any

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
        self.prev_LaserScanner_red_voltge = 0

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(f"qudi.hardware.OPX.{self._qm_config_file}")
        globals().update(
            {
                name: getattr(self._configuration, name)
                for name in dir(self._configuration)
                if not name.startswith("_")
            }
        )

        # Establish connection to OPX+

        self._connect_to_OPX()
        self.config = self._configuration.config

    def _volt2amp(self, voltage: float) -> float:
        return 2 * voltage

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
        """Runs a continuous wave program on the OPX that sets the digital and analog outputs as specified in the dictionaries."""
        ls_curr_do: list = [key for key, value in self.cw_do_states.items() if value == "on"]
        dict_curr_ao = {
            key: value
            for key, value in self.cw_ao_values.items()
            if key not in ["SPCM1", "SPCM2", "RF"]
        }
        # check if any output should be set, if not stop the current qm program
        if not ls_curr_do and not dict_curr_ao:
            if self.cw_job:
                self.cw_job.halt()
        else:
            duration = 1 * u.us
            with program() as cw_program:
                if ("LaserScanner_red" in dict_curr_ao.keys()) and (
                    dict_curr_ao["LaserScanner_red"] != self.prev_LaserScanner_red_voltge
                ):
                    # self.log.warning(
                    #     f"Setting LaserScanner_red voltage to {dict_curr_ao['LaserScanner_red']} V (Prev voltage: {self.prev_LaserScanner_red_voltge} V)"
                    # )
                    self.prev_LaserScanner_red_voltge = dict_curr_ao["LaserScanner_red"]
                    set_dc_offset(
                        "LaserScanner_red",
                        "single",
                        dict_curr_ao["LaserScanner_red"],
                    )
                    dict_curr_ao.pop("LaserScanner_red", None)
                with infinite_loop_():
                    for ao, power in dict_curr_ao.items():
                        # checks if same element also has active digital output
                        if ao in self.cw_do_states.keys():
                            if ao in ls_curr_do:
                                play(
                                    "pulse" * amp(self._volt2amp(power)),
                                    ao,
                                    duration=duration,
                                )
                        else:
                            play(
                                "power" * amp(self._volt2amp(power)),
                                ao,
                                duration=duration,
                            )

                    for do in ls_curr_do:
                        if do not in dict_curr_ao.keys():
                            play("active", do, duration=duration)

            # self.simulate(cw_program, plot=True)
            try:
                self.cw_job = self.qm.execute(cw_program)
            except BaseException:
                self._connect_to_OPX()
                self.cw_job = self.qm.execute(cw_program)

    def stop_cw_mode(self):
        self.cw_job.halt()

    @property
    def qm(self):
        return self._qm

    def simulate(self, sequence, save_path=None, plot=False, duration=10_000):
        """
        :param sequence: program() of the opx to simulate
        :return: opens a plotly html window with the sequence.
        """
        t0 = time.time()

        self.log.info("simulate")
        simulation_config = SimulationConfig(duration=duration)  # In clock cycles = 4ns
        job_sim = self.qmm.simulate(self._configuration.config, sequence, simulation_config)
        # Simulate blocks python until the simulation is done
        # job_sim.get_simulated_samples().con1
        # job_sim.get_simulated_samples().con1.plot()
        # plt.show()
        # get DAC and digital samples (optional).
        samples = job_sim.get_simulated_samples()
        # get the waveform report object

        waveform_report = job_sim.get_simulated_waveform_report()
        waveform_dict = waveform_report.to_dict()
        if save_path is not None:
            with open(os.path.join(save_path, "awg_file.json"), "w") as fp:
                json.dump(waveform_dict, fp)
        if plot:
            waveform_report.create_plot(
                samples, plot=plot, save_path="./" if save_path is None else save_path
            )
        t1 = time.time()
        print("simulation", t1 - t0)

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
        # TODO: implement stopping all awgs

    def update_config(self):
        if self._configuration in sys.modules:
            del sys.modules[self._configuration]
        self._configuration = importlib.import_module(f"qudi.hardware.OPX.{self._qm_config_file}")
        globals().update(
            {
                name: getattr(self._configuration, name)
                for name in dir(self._configuration)
                if not name.startswith("_")
            }
        )

    @property
    def name(self) -> str:
        """Name of the hardware as string.
        @return str: The name of the hardware
        """
        return self._configuration.cluster_name
