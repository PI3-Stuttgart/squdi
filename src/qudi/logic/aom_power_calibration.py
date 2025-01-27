import importlib
import time
import numpy as np
import xarray as xr
import os
from datetime import datetime

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.hardware.interfuse.process_setpoint_combiner_interfuse import (
    ProcessSetpointCombinerInterfuse as _AO,
)
from qudi.hardware.interfuse.switch_combiner_interfuse import (
    SwitchCombinerInterfuse as _DO,
)
from qudi.hardware.powermeter.thorlabs_powermeter import ThorlabsPowermeter as _PM
import matplotlib.pyplot as plt
from typing import Iterable, Mapping, Union, Optional, Tuple, Type, Dict
from scipy.optimize import root_scalar


class AomPowerCalibration(LogicBase):
    """
    Example config for copy-paste:
    aom_power_calibration:
        module.Class: 'aom_power_calibration.AomPowerCalibration'
        connect:
            AO: 'process_setpoint_combiner'
            DO: 'switch_combiner'
            Powermeter: 'powermeter'
        options:
            aoms:
                AOM_520:
                    aom_do_channel: 'AOM_520'
                    laser_do_channel: 'Laser_520'
                AOM_620:
                    aom_do_channel: 'AOM_620'
            save_path: "C:/Users/yy3/qudi/Data/Power_calibration/"
    """

    AO: _AO = Connector(interface="ProcessSetpointInterface")
    DO: _DO = Connector(interface="SwitchInterface")
    Powermeter: _PM = Connector(interface="ProcessValueInterface")
    aoms: dict = ConfigOption(name="aoms", default=1, missing="nothing")
    save_path: str = ConfigOption(name="save_path", default="./", missing="nothing")

    SEC_POWERMETER_FLIP = 2
    VOLTAGE_STEPS = 50
    SEC_BEFORE_POWER_MEAS = 0.2

    channels_w_conversion = []

    def on_activate(self) -> None:
        self.do: _DO = self.DO()
        self.ao: _AO = self.AO()
        self.powermeter: _PM = self.Powermeter()

        # Load in latest calibration data
        for aom_channel in self.aoms.keys():
            self.load_latest_calibration_data(aom_channel)

        self._generate_convertion_list()

    def on_deactivate(self) -> None:
        pass

    def save_calibration_data(self, aom_channel: str) -> None:
        """
        Save the calibration data for a specific AOM channel as an HDF5 file.

        Args:
            aom_channel (str): Name of the AOM channel.
            save_path (str): Directory where the file will be saved.
        """
        if aom_channel not in self.aoms or "data" not in self.aoms[aom_channel]:
            self.log.warning(f"No data found for AOM channel {aom_channel}.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self.save_path, f"aom_{aom_channel}_calibration_{timestamp}.h5"
        )
        filename_plot = os.path.join(
            self.save_path, f"aom_{aom_channel}_calibration_{timestamp}.png"
        )
        # Save the xr.Dataset directly as an HDF5 file
        self.aoms[aom_channel]["data"].to_netcdf(filename)
        self.aoms[aom_channel]["fit"].plot_fit()
        plt.savefig(filename_plot)
        self.log.info(f"Calibration data for {aom_channel} saved to {filename}")

    def load_latest_calibration_data(self, aom_channel: str) -> None:
        """
        Load the latest calibration data for a specific AOM channel from an HDF5 file.

        Args:
            aom_channel (str): Name of the AOM channel.
        """
        # Search for the latest HDF5 file for the specific channel
        files = [
            file
            for file in os.listdir(self.save_path)
            if file.startswith(f"aom_{aom_channel}_calibration_")
            and file.endswith(".h5")
        ]
        if not files:
            self.log.warning(
                f"No calibration files found for AOM channel {aom_channel}."
            )
            return

        latest_file = max(
            files, key=lambda f: os.path.getctime(os.path.join(self.save_path, f))
        )
        file_path = os.path.join(self.save_path, latest_file)

        # Load the xr.Dataset directly from the HDF5 file
        xr_data = xr.load_dataset(file_path)

        # Update the aoms dictionary
        if aom_channel not in self.aoms:
            self.log.warning(
                f"Calibration file found of AOM ({aom_channel}) which is not defined in Qinu config!"
            )
        else:
            self.aoms[aom_channel]["data"] = xr_data
            self.fit_powers(aom_channel)

            self.log.info(
                f"Loaded calibration data for {aom_channel} from {latest_file}"
            )

    def _generate_convertion_list(self) -> None:
        channels_w_conversion = []
        for aom_channel, aom in self.aoms.items():
            if "fit_res" in aom.keys():
                channels_w_conversion.append(aom_channel)
        self.channels_w_conversion = channels_w_conversion

    @property
    def channels_w_power_measurement(self) -> list[str]:
        "Returns a list of all channels for which the power can be measured"
        return self.aoms.keys()

    def convert_power_to_voltage(self, power: float, aom_channel: str) -> float:
        if aom_channel in self.channels_w_conversion:
            # Get the model function and best fit parameters

            result = self.aoms[aom_channel]["fit_res"]
            model_func = result.model.func
            best_values = result.best_values

            # Check if this low power is reachable with
            if "offset" in best_values.keys():
                if best_values["offset"] > power:
                    self.log.warning(
                        "Set power is to low to reach with used AOM. Output voltage is set to 0."
                    )
                    return 0
            elif power == 0:
                return 0

            # Define the function to find the root of
            def voltage_to_power_difference(voltage):
                return model_func(voltage, **best_values) - power

            # Use root_scalar to find the voltage that gives the desired power
            root_result = root_scalar(
                voltage_to_power_difference,
                bracket=[
                    self.ao.constraints.channel_limits[aom_channel][0],
                    self.ao.constraints.channel_limits[aom_channel][1]
                    + 0.1,  # TODO: This is a dirty workaround to avoid issues with max power
                ],
                method="brentq",
            )

            if root_result.converged:
                return root_result.root
            else:
                raise ValueError("Could not find a voltage for the given power.")
        else:
            return 0

    def convert_voltage_to_power(self, voltage: float, aom_channel: str) -> float:
        if aom_channel in self.channels_w_conversion:
            result = self.aoms[aom_channel]["fit_res"]
            return result.model.func(voltage, **result.best_values)
        else:
            return 0

    def fit_powers(self, aom_channel) -> None:
        fit = AOMPowerFit(
            V_data=self.aoms[aom_channel]["data"].voltage.values,
            P_data=self.aoms[aom_channel]["data"].power.values,
        )
        self.aoms[aom_channel]["fit_res"] = fit.fit_data()
        self.aoms[aom_channel]["fit"] = fit
        # self.aoms[aom_channel]["data"].attrs["fit_res"] = fit.fit_data() # TODO: Fix this

    def calibrate_power(self, aom_channel: str) -> None:

        aom_config: dict = self.aoms[aom_channel]

        # Safe current setup configuration (AO and DO setpoints)
        curr_do_states = self.do.states
        # self._curr_ao_setpoints = self.ao.setpoints

        # Flip powermeter in and activate it (is poropably different in other setups)
        self.do.set_state("flip_powermeter", "in")
        self.powermeter.set_activity_state("Power", True)
        self.log.info("Step 1: Flip Powermeter in")
        time.sleep(self.SEC_POWERMETER_FLIP)

        # Deactivate all lasers and aoms
        for do_channel in self.do.switch_names:
            if "aom" in do_channel.lower() or "laser" in do_channel.lower():
                # TODO: Not universal for all setups
                self.do.set_state(do_channel, "off")
        self.log.info("Step 2: All lasers off")
        # Activate laser and/or AOM which will be measured
        if "laser_do_channel" in aom_config.keys():
            self.do.set_state(aom_config["laser_do_channel"], "on")
            self.log.info(f"Step 3: Activate {aom_config['laser_do_channel']}")
        if "aom_do_channel" in aom_config.keys():
            self.do.set_state(aom_config["aom_do_channel"], "on")
            self.log.info(f"Step 3: Activate {aom_config['aom_do_channel']}")

        # Define voltage sweep
        min_v, max_v = self.ao.constraints.channel_limits[aom_channel]
        voltages = np.linspace(min_v, max_v, self.VOLTAGE_STEPS)

        # Do the measurement
        powers = []
        self.log.info(f"Step 4: Start power measurement")
        for voltage in voltages:
            self.ao.set_setpoint(aom_channel, voltage)
            time.sleep(self.SEC_BEFORE_POWER_MEAS)
            powers.append(self.powermeter.get_process_value("Power"))

        try:
            self.do.states = curr_do_states
            self.log.info("Step 5: Bring the setup back to initial state")

            xr_data = xr.Dataset(
                data_vars=dict(
                    power=xr.Variable(
                        "power",
                        np.array(powers),
                        dict(units=r"W", long_name="Power"),
                    ),
                ),
                coords=dict(
                    voltage=xr.Variable(
                        "voltage",
                        voltages,
                        attrs=dict(units=r"V", long_name="Voltage"),
                    ),
                ),
            )
            self.aoms[aom_channel]["data"] = xr_data

            self.log.info("Step 6: Fit ans save measured data")
            self.fit_powers(aom_channel)
            self._generate_convertion_list()
            self.save_calibration_data(aom_channel)
        except Exception as e:
            self.log.error(e)


import numpy as np
import matplotlib.pyplot as plt
from lmfit import Model


# Create the lmfit-based class
class AOMPowerFit:
    """
    Class to handle AOM power fitting using the refined model with lmfit.
    """

    def __init__(self, V_data, P_data, model=None, init_guess_func=None):
        """
        Initialize with voltage and power data.
        """
        self.V_data = np.array(V_data)
        self.P_data = np.array(P_data)
        self.init_guess_func = init_guess_func

        if not model:
            self.model = Model(self.aom_power)  # Initialize the model
            self.init_guess_func = self.aom_power_init_guess_func

    @staticmethod
    def aom_power(V, P_max, V_s, n, alpha, offset, init_guess_func=None):
        """
        AOM power output model with additional saturation flexibility.
        """
        return P_max * (V**n) / ((V**n + V_s**n) ** alpha) + offset

    @staticmethod
    def aom_power_init_guess_func(V_data, P_data):
        """"""

        P_max_guess = max(P_data)  # Max observed power
        V_s_guess = V_data[np.argmax(P_data)] / 2  # Voltage at half power
        n_guess = 2.0  # Start with quadratic behavior
        alpha_guess = 1.0  # Default sharpness factor
        offset_guess = min(P_data)  # Baseline offset
        return {
            "P_max": P_max_guess,
            "V_s": V_s_guess,
            "n": n_guess,
            "alpha": alpha_guess,
            "offset": offset_guess,
        }

    def get_initial_guesses(self):
        """
        Generate initial guesses dynamically based on the input data.
        """
        return self.init_guess_func(self.V_data, self.P_data)

    def fit_data(self):
        """
        Fit the AOM power model to the data using lmfit.
        """
        if self.init_guess_func:
            params = self.model.make_params(**self.get_initial_guesses())
        else:
            params = self.model.make_params()

        # Perform the fit
        self.result = self.model.fit(self.P_data, params, V=self.V_data)
        return self.result

    def plot_fit(self):
        """
        Plot the measured data and the fitted curve.
        """
        if not hasattr(self, "result"):
            raise ValueError("Fit the data first using `fit_data()`.")

        # Generate the fitted curve
        V_fit = np.linspace(min(self.V_data), max(self.V_data), 500)
        P_fit = self.model.func(V_fit, **self.result.best_values)

        # Plot
        plt.figure(figsize=(8, 6))
        plt.plot(V_fit, P_fit, label="Fitted Curve", color="orange", linewidth=1)
        plt.scatter(self.V_data, self.P_data, label="Measured Data", color="blue", s=5)
        plt.xlabel("Voltage [V]")
        plt.ylabel("Power [mW]")
        plt.title("Voltage to Power Calibration")
        plt.legend()
        plt.grid()
        # plt.show()

    def print_fit_report(self):
        """
        Print the fit report.
        """
        if not hasattr(self, "result"):
            raise ValueError("Fit the data first using `fit_data()`.")
        print(self.result.fit_report())
