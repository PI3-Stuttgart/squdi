import time
import qm
from qm import SimulationConfig
from qudi.logic.nuclear_ops_opx_utils import NuclearOpsOPXUtils


"""
This is a moku of MCAS basic functions for program to have some object oriented stuff. 
"""


class MultiChSeq:

    ou: NuclearOpsOPXUtils

    def __init__(self, name, awg, ou):
        self._name = name
        self._qm = awg.qm
        self._qmm = awg.qmm
        self.ou = ou
        self._config = awg._configuration
        self.ch_dict = None  # Here in principle the config ch_dict could be used of used channels.
        self._job = None
        self._initialized = False
        self._debug_info_cache = None
        self._simulation_plotted = False

    @property
    def name(self):
        return self._name

    # def asc()
    #

    @property
    def program(self):
        return self._program

    @program.setter
    def program(self, val):
        self._program = val

    @property
    def qm(self):
        """
        Quantum machine instance, obtained as QuantumMachineManager.open_qm method
        :return:
        """
        return self._qm

    @property
    def qmm(self):
        """
        Quantum machine manager,
        :return:
        """
        return self._qmm

    def initialize(self):
        """
        Runs the programm and stops it.
        :return:
        """
        if self._initialized:
            return
        self._job = self.qm.execute(self.program)
        time.sleep(0.1)
        self._job.halt()
        self._initialized = True

    def run(self):
        """
        Runs the programm.
        :return:
        """
        self._job = self.qm.execute(self.program)

    def status(self):
        """
        Asks if it is running
        :return:
        """
        pass

    def debug_info(self):
        """
        Some debug infor regarding the sequence in a form of a json.
        """
        if self._debug_info_cache is not None:
            return self._debug_info_cache

        t0 = time.time()
        simulation_config = SimulationConfig(duration=1_000)  # In clock cycles = 4ns
        job_sim = self.qmm.simulate(self._config.config, self.program, simulation_config)
        # Simulate blocks python until the simulation is done
        # job_sim.get_simulated_samples().con1
        # job_sim.get_simulated_samples().con1.plot()

        # get DAC and digital samples (optional).
        samples = job_sim.get_simulated_samples()
        # get the waveform report object
        waveform_report = job_sim.get_simulated_waveform_report()
        waveform_dict = waveform_report.to_dict()
        t1 = time.time()
        print("OPX_debug_info time:", t1 - t0)
        self._debug_info_cache = waveform_dict
        return waveform_dict

    def stop(self):
        """
        Stops the programm.
        :return:
        """
        self._job.halt()

    @property
    def job(self):
        return self._job
