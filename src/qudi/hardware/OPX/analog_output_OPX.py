import importlib
from typing import Dict, Tuple, Any
import time

from qualang_tools.control_panel import ManualOutputControl
import qm

from qudi.core.configoption import ConfigOption
from qudi.interface.process_control_interface import (
    ProcessSetpointInterface,
    ProcessControlConstraints,
)


class AnalogOutputOPX(ProcessSetpointInterface, TriggeredAOInterface):
    """Module to set the manually set the Analog Outputs of the QuantumMachines OPX+.
    Channels are defined by the OPXs own config file and not using qudi.
    Example config for copy-paste:
    AO_OPX:
        module.Class: 'OPX.analog_output_OPX.AnalogOutputOPX'
        options:
            qm_config_file: "configuration"
    """

    _qm_config_file = ConfigOption(
        name="qm_config_file", default="configuration", missing="nothing"
    )
    _switch_time = ConfigOption(name="switch_time", default=1, missing="nothing")

    _configuration = None
    _qm_manual_output_control = None
    _constraints = None
    _scan_parameters = ()

    def on_activate(self) -> None:
        """Loads QM config and establishs connection to OPX+"""
        # import QuantumMachines configuration python file
        self._configuration = importlib.import_module(
            f"qudi.hardware.OPX.{self._qm_config_file}"
        )
        # Establish connection to OPX+
        self._set_constraints()
        self._connect_to_OPX()

    def on_deactivate(self) -> None:
        self._qm_manual_output_control.close()

    def _set_constraints(self):
        _channels: list = []
        for name, qm_element in self._configuration.config["elements"].items():
            if "singleInput" in qm_element.keys():
                _channels.append(name)

        self._constraints = ProcessControlConstraints(
            setpoint_channels=_channels,
            units={ch: "V" for ch in _channels},
            limits={ch: (-0.5, 0.5) for ch in _channels},
            dtypes={ch: float for ch in _channels},
        )

    def _connect_to_OPX(self) -> None:
        try:
            self._qm_manual_output_control = ManualOutputControl(
                self._configuration.config,
                host=self._configuration.qop_ip,
                close_previous=False,
                elements_to_control=self.constraints.setpoint_channels,
            )
        except qm.exceptions.OpenQmException:
            self.log.warning(
                "Could not connect to OPX with keeping previous connections. Previouse connections disconnected."
            )
            self._qm_manual_output_control = ManualOutputControl(
                self._configuration.config,
                host=self._configuration.qop_ip,
                close_previous=True,
                elements_to_control=self.constraints.setpoint_channels,
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
        OPX channels are always active, only setting the amplitude to zero deines them as
        inactive. Non the less, it can be that the connection to the Manual_mode is broken. Therefore by activating the state a new connection will be made.
        """
        if active:
            self.self._connect_to_OPX()
        if not active:
            # self._qm_manual_output_control.set_amplitude(channel, 0)

    def get_activity_state(self, channel: str) -> bool:
        """Get activity state for given channel.
        State is bool type and refers to active (True) and inactive (False).
        """
        ao_status: dict[str, dict[str, float]] = (
            self._qm_manual_output_control.analog_status()
        )

        if ao_status[channel]["amplitude"] == 0:
            return False
        else:
            return True

    def set_setpoint(self, channel: str, value: float) -> None:
        """Set new setpoint for a single channel"""
        try:
            self._qm_manual_output_control.set_amplitude(channel, value)
        except qm.exceptions.QMConnectionError:
            self.log.warning("Reconnecting OPX ...")
            self._connect_to_OPX()
            self._qm_manual_output_control.set_amplitude(channel, value)

        # time.sleep(self._switch_time)

    def get_setpoint(self, channel: str) -> float:
        """Get current setpoint for a single channel"""
        ao_status: dict[str, dict[str, float]] = (
            self._qm_manual_output_control.analog_status()
        )

        return ao_status[channel]["amplitude"]
    
    def set_scan_parameters(self, channel: str, 
                            voltage_start: _Real, 
                            voltage_stop: _Real,
                            sweep_duration: _Real) -> None:
        
        assert -0.5 < voltage_start < 0.5, f"voltage_start {voltage_start} is out of range [-0.5V, 0.5V]"
        assert -0.5 < voltage_stop < 0.5, f"voltage_stop {voltage_stop} is out of range [-0.5V, 0.5V]"
        assert voltage_start < voltage_stop, f"voltage_start needs to be smaller then voltage_stop"
        
        self._scan_parameters = (voltage_start, voltage_stop, sweep_duration)

    def get_scan_parameters(self, channel: str) -> (_Real, _Real, _Real):
        """ Get current setpoint for a single channel """
        return self._scan_parameters
    
    def start_scan(self, channel: str) -> None:
        """ Get current setpoint for a single channel """
        
        scan_freq = 0.1
        nr_amp_steps = 100
        volt_factor_vec = np.linspace(-1, 1, nr_amp_steps)
        step_len = 
        n_avg = 1_000  # number of averages
        i_avg = 1_000 # number of averages per voltage

        with program() as ple:
            v_fact = declare(float) # amplitude
            n = declare(int)  # number of iterations
            n_st = declare_stream()  # stream for number of iterations
            i = declare(int) # number of iterations per 

            # integrations of ehole scan
            with for_(n, 0, n < n_avg, n + 1):
                assign(i_amp, 0)
                # looping over voltages
                with for_(*from_array(v_fact, volt_factor_vec)):  
                    # Integration per voltage step
                    with for_(i, 0, i < i_avg, i + 1):
                        play("piezo_offset" * amp(v_fact), "LaserScanner_red", duration=step_len/i_avg * u.ns)
                    play("trigger_TT", "LaserScanner_red")
                # save(n, n_st)  # save number of iteration inside for_loop

            with stream_processing():
                # Cast the data into a 1D vector, average the 1D vectors together and store the results on the OPX processor
                # counts_st.buffer(len(v_vec)).average().save("counts")
                counts_st.buffer(len(amp_vec)).average().save("counts")
                n_st.save("iteration")

        #####################################
        #  Open Communication with the QOP  #
        #####################################
        qmm = QuantumMachinesManager(host=qop_ip, cluster_name=cluster_name, octave=octave_config)

        #######################
        # Simulate or execute #
        #######################
        simulate = False

        if simulate:
            # Simulates the QUA program for the specified duration
            simulation_config = SimulationConfig(duration=100_000)  # In clock cycles = 4ns
            job = qmm.simulate(config, ple, simulation_config)
            job.get_simulated_samples().con1.plot()
            plt.show()
        else:
            # Open the quantum machine
            qm = qmm.open_qm(config)
            # Send the QUA program to the OPX, which compiles and executes it
            job = qm.execute(ple)
            # Get results from QUA program
            # results = fetching_tool(job, data_list=["counts", "counts_dark", "iteration"], mode="live")
            # results = fetching_tool(job, data_list=["counts", "iteration"], mode="live")
            results = fetching_tool(job, data_list=["counts", "iteration"], mode="live")
            
            # Live plotting
            fig = plt.figure()
            interrupt_on_close(fig, job)
            
            

            while results.is_processing():
                # Fetch results
                #counts, counts_dark, iteration = results.fetch_all()
                # counts, iteration = results.fetch_all()
                counts, iteration = results.fetch_all()
                
                progress_counter(iteration, n_avg, start_time=results.get_start_time())
                # Plot data
                plt.cla()
                plt.plot(amp_vec/0.5 * volt_factor, counts / 1000 / (readout_len * n_avg  * 1e-9), label="photon counts")
                #plt.plot((NV_LO_freq * 0 + f_vec) / u.MHz, counts_dark / 1000 / (readout_len * 1e-9), label="dark counts")
                plt.xlabel("Piezo Voltage [V]")
                plt.ylabel("Counts [kcps]")
                plt.title("PLE")
                plt.legend()
                plt.pause(0.1)
                
            plt.show()
            f = open("C:\\Data\\2024\\06\\odmr.txt", "w")
            for i in range(len(counts)):
                #f.write(str(counts[i])+ '\t' + str(counts_dark[i])+ '\n')
                f.write(str(counts[i] / 1000 / (readout_len * 1e-9)) + '\n')
            f.close()
        
    
    def stop_scan(self, channel: str) -> None:
        """ Get current setpoint for a single channel """
        pass
    
    
    
