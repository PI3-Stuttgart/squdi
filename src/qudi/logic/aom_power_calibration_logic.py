"""Utilities to calibrate AOM drive voltage against measured optical power.

This module contains the Qudi logic module that performs a calibration sweep
for configured AOM channels and a helper class that fits a voltage-to-power
transfer curve from the recorded data.
"""

import os
import time
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from lmfit import Model
from scipy.optimize import root_scalar

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.hardware.interfuse.process_setpoint_combiner_interfuse import (
    ProcessSetpointCombinerInterfuse as _AO,
)
from qudi.hardware.interfuse.switch_combiner_interfuse import (
    SwitchCombinerInterfuse as _DO,
)
from qudi.hardware.picoquant.ppg512 import PPG512 as _PPG
from qudi.hardware.powermeter.thorlabs_powermeter import ThorlabsPowermeter as _PM


class AOMPowerCalibrationLogic(LogicBase):
    """Logic module for measuring and fitting AOM power calibration curves.

    The module coordinates analog output, digital output, a powermeter, and an
    optional pulse generator to sweep an AOM control voltage, record the
    resulting optical power, and persist the measured calibration dataset.

    Example config for copy-paste:
    aom_power_calibration_logic:
        module.Class: 'aom_power_calibration_logic.AOMPowerCalibrationLogic'
        connect:
            analog_output_connector: 'process_setpoint_combiner'
            digital_output_connector: 'switch_combiner'
            power_meter_connector: 'powermeter'
            ppg_connector: 'ppg'
        options:
            aom_configs:
                AOM_520:
                    aom_do_channel: 'AOM_520'
                    laser_do_channel: 'Laser_520'
                AOM_620:
                    aom_do_channel: 'AOM_620'
                AOM_620_pi:
                    aom_do_channel: 'AOM_620_pi'
            save_path: "C:/Users/yy3/qudi/Data/Power_calibration/"
    """

    analog_output_connector: _AO = Connector(interface="ProcessSetpointCombinerInterfuse")
    digital_output_connector: _DO = Connector(interface="SwitchInterface")
    power_meter_connector: _PM = Connector(interface="ProcessValueInterface")
    ppg_connector: _PPG = Connector(interface="PPG512")

    analog_output: _AO
    digital_output: _DO
    power_meter: _PM
    ppg: _PPG

    aom_configs: dict[str, dict[str, Any]] = ConfigOption(name="aom_configs", default=1, missing="nothing")
    save_path: str = ConfigOption(name="save_path", default="./", missing="nothing")

    EOM_PULSING_ON_FRACTION: float = 1 / 10
    POWERMETER_FLIP_SETTLE_SECONDS = 2
    CALIBRATION_VOLTAGE_STEPS = 50
    POWER_MEASUREMENT_SETTLE_SECONDS = 0.2

    calibrated_channels: list[str] = []

    def on_activate(self) -> None:
        """Resolve hardware connectors and preload persisted calibration data."""
        self.digital_output = self.digital_output_connector()
        self.analog_output = self.analog_output_connector()
        self.power_meter = self.power_meter_connector()
        self.ppg = self.ppg_connector()

        for aom_channel in self.aom_configs.keys():
            self.load_latest_channel_calibration_data(aom_channel)

        self._update_calibrated_channels()

    def on_deactivate(self) -> None:
        """Handle module shutdown.

        No explicit cleanup is currently required during deactivation.
        """

    def save_channel_calibration_data(self, aom_channel: str) -> None:
        """Persist calibration data and a fit plot for one AOM channel.

        Args:
            aom_channel: Name of the configured AOM channel whose calibration
                dataset should be written to disk.

        The method writes the stored :class:`xarray.Dataset` to a NetCDF/HDF5
        file in ``self.save_path``, exports the current fit plot as a PNG file,
        and then reloads the newest calibration files for all configured
        channels so that in-memory fit results stay synchronized with the
        persisted data.
        """
        if aom_channel not in self.aom_configs or "data" not in self.aom_configs[aom_channel]:
            self.log.warning(f"No data found for AOM channel {aom_channel}.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dataset_filename = os.path.join(self.save_path, f"aom_{aom_channel}_calibration_{timestamp}.h5")
        plot_filename = os.path.join(self.save_path, f"aom_{aom_channel}_calibration_{timestamp}.png")

        self.aom_configs[aom_channel]["data"].to_netcdf(dataset_filename)
        self.aom_configs[aom_channel]["fit_helper"].plot_calibration_fit()
        plt.savefig(plot_filename)

        for configured_channel in self.aom_configs.keys():
            self.load_latest_channel_calibration_data(configured_channel)
        self._update_calibrated_channels()

        self.log.info(f"Calibration data for {aom_channel} saved to {dataset_filename}")

    def load_latest_channel_calibration_data(self, aom_channel: str) -> None:
        """Load the newest persisted calibration dataset for one channel.

        Args:
            aom_channel: Name of the AOM channel whose latest calibration file
                should be discovered and loaded from ``self.save_path``.

        If a matching file is found, the corresponding dataset is stored in
        ``self.aom_configs[aom_channel]["data"]`` and a fresh fit result is
        generated from the loaded measurement points.
        """
        matching_files = [file_name for file_name in os.listdir(self.save_path) if file_name.startswith(f"aom_{aom_channel}_calibration_") and file_name.endswith(".h5")]
        if not matching_files:
            self.log.warning(f"No calibration files found for AOM channel {aom_channel}.")
            return

        latest_file = max(matching_files, key=lambda file_name: os.path.getctime(os.path.join(self.save_path, file_name)))
        file_path = os.path.join(self.save_path, latest_file)
        calibration_dataset = xr.load_dataset(file_path)

        if aom_channel not in self.aom_configs:
            self.log.warning(f"Calibration file found of AOM ({aom_channel}) which is not defined in Qinu config!")
            return

        self.aom_configs[aom_channel]["data"] = calibration_dataset
        self.fit_channel_calibration(aom_channel)
        self.log.info(f"Loaded calibration data for {aom_channel} from {latest_file}")

    def _update_calibrated_channels(self) -> None:
        """Refresh the list of channels that currently have usable fit results."""
        self.calibrated_channels = [aom_channel for aom_channel, channel_config in self.aom_configs.items() if "fit_result" in channel_config]

    @property
    def channels_with_power_measurement(self) -> Iterable[str]:
        """Return all configured channels for which power measurement is possible."""
        return self.aom_configs.keys()

    def power_to_voltage(self, power: float, aom_channel: str) -> float:
        """Convert a requested optical power into the required AOM drive voltage.

        Args:
            power: Desired optical power in watts.
            aom_channel: Name of the calibrated AOM channel.

        Returns:
            The drive voltage that corresponds to the requested power according
            to the fitted transfer model. If no calibration fit is available
            for the channel, ``0`` is returned.

        Raises:
            ValueError: If the numerical root search fails despite a fit being
                present.
        """
        if aom_channel not in self.calibrated_channels:
            return 0

        fit_result = self.aom_configs[aom_channel]["fit_result"]
        model_function = fit_result.model.func
        best_fit_values = fit_result.best_values

        if "offset" in best_fit_values.keys():
            if best_fit_values["offset"] > power:
                self.log.warning("Set power is to low to reach with used AOM. Output voltage is set to 0.")
                return 0
        elif power == 0:
            return 0

        def voltage_to_power_difference(voltage: float) -> float:
            return model_function(voltage, **best_fit_values) - power

        root_result = root_scalar(
            voltage_to_power_difference,
            bracket=[
                self.analog_output.constraints.channel_limits[aom_channel][0],
                self.analog_output.constraints.channel_limits[aom_channel][1] + 0.1,  # TODO: This is a dirty workaround to avoid issues with max power
            ],
            method="brentq",
        )

        if root_result.converged:
            return root_result.root
        raise ValueError("Could not find a voltage for the given power.")

    def voltage_to_power(self, voltage: float, aom_channel: str) -> float:
        """Evaluate the fitted power model for a given drive voltage.

        Args:
            voltage: Analog output voltage applied to the AOM channel.
            aom_channel: Name of the calibrated AOM channel.

        Returns:
            Predicted optical power in watts. If no calibration fit is
            available for the channel, ``0`` is returned.
        """
        if aom_channel not in self.calibrated_channels:
            return 0

        fit_result = self.aom_configs[aom_channel]["fit_result"]
        return fit_result.model.func(voltage, **fit_result.best_values)

    def fit_channel_calibration(self, aom_channel: str) -> None:
        """Fit the stored voltage/power dataset for one AOM channel.

        Args:
            aom_channel: Name of the channel whose data in ``self.aom_configs``
                should be fitted.
        """
        fit_helper = AOMPowerCalibrationFit(
            voltage_data=self.aom_configs[aom_channel]["data"].voltage.values,
            power_data=self.aom_configs[aom_channel]["data"].power.values,
        )
        self.aom_configs[aom_channel]["fit_result"] = fit_helper.fit()
        self.aom_configs[aom_channel]["fit_helper"] = fit_helper
        # self.aom_configs[aom_channel]["data"].attrs["fit_result"] = fit_helper.fit()  # TODO: Fix this

    def calibrate_channel_power(self, aom_channel: str, return_measurement_data: bool = False) -> Optional[xr.Dataset]:
        """Run a full power calibration sweep for one AOM channel.

        Args:
            aom_channel: Name of the AOM channel to calibrate.
            return_measurement_data: If ``True``, return the measured dataset
                directly instead of storing, fitting, and saving it.

        Returns:
            The measured dataset when ``return_measurement_data`` is enabled,
            otherwise ``None``.

        The method temporarily reconfigures the setup, sweeps the analog output
        voltage over the allowed channel range, records the powermeter values,
        restores the previous digital output states, and optionally fits and
        persists the new calibration dataset.
        """
        channel_config: dict[str, Any] = self.aom_configs[aom_channel]
        original_digital_output_states = self.digital_output.states

        self.digital_output.set_state("flip_powermeter", "in")
        self.power_meter.set_activity_state("Power", True)
        self.log.info("Step 1: Flip Powermeter in")
        time.sleep(self.POWERMETER_FLIP_SETTLE_SECONDS)

        for digital_output_channel in self.digital_output.switch_names:
            if "aom" in digital_output_channel.lower() or "laser" in digital_output_channel.lower():
                # TODO: Not universal for all setups
                self.digital_output.set_state(digital_output_channel, "off")
        self.log.info("Step 2: All lasers off")

        if "laser_do_channel" in channel_config.keys():
            self.digital_output.set_state(channel_config["laser_do_channel"], "on")
            self.log.info(f"Step 3: Activate {channel_config['laser_do_channel']}")
        if "aom_do_channel" in channel_config.keys():
            self.digital_output.set_state(channel_config["aom_do_channel"], "on")
            self.log.info(f"Step 3: Activate {channel_config['aom_do_channel']}")
        if "eom_do_channel" in channel_config.keys():
            # Activates EOM (PPG) trigger of the QM if it is not the same as the AOM channel.
            # TODO: Might be vastly different in other setups. Fix this.
            if channel_config["eom_do_channel"] != channel_config["aom_do_channel"]:
                self.digital_output.set_state(channel_config["eom_do_channel"], "on")
                self.log.info(f"Step 3: Activate {channel_config['eom_do_channel']}")
            # TODO: Absolute bullshit of code. Make this more universal.
            self.log.info("Step 3.2: Write PPG waveform for EOM pulsing")
            self.ppg.write_pulse(
                pulse_width=int(256 * 0.2 * self.EOM_PULSING_ON_FRACTION),  # ns
                pulse_shape="square",
            )

        min_voltage, max_voltage = self.analog_output.constraints.channel_limits[aom_channel]
        voltage_values = np.linspace(min_voltage, max_voltage, self.CALIBRATION_VOLTAGE_STEPS)

        measured_powers: list[float] = []
        self.log.info("Step 4: Start power measurement")
        for voltage in voltage_values:
            self.analog_output.set_setpoint(aom_channel, voltage)
            time.sleep(self.POWER_MEASUREMENT_SETTLE_SECONDS)
            measured_powers.append(self.power_meter.get_process_value("Power"))

        try:
            self.digital_output.states = original_digital_output_states
            self.log.info("Step 5: Bring the setup back to initial state")

            calibration_dataset = xr.Dataset(
                data_vars=dict(
                    power=xr.Variable(
                        "power",
                        np.array(measured_powers) if "eom_do_channel" not in channel_config.keys() else np.array(measured_powers) / self.EOM_PULSING_ON_FRACTION,
                        dict(units=r"W", long_name="Power"),
                    ),
                ),
                coords=dict(
                    voltage=xr.Variable(
                        "voltage",
                        voltage_values,
                        attrs=dict(units=r"V", long_name="Voltage"),
                    ),
                ),
            )
            if return_measurement_data:
                return calibration_dataset

            self.aom_configs[aom_channel]["data"] = calibration_dataset
            self.log.info("Step 6: Fit ans save measured data")
            print("measured_powers:", measured_powers)
            self.fit_channel_calibration(aom_channel)
            self._update_calibrated_channels()
            self.save_channel_calibration_data(aom_channel)
        except Exception as error:
            self.log.error(error)
        return None


class AOMPowerCalibrationFit:
    """Fit and visualize a parametric voltage-to-power calibration curve.

    The class wraps an :mod:`lmfit` model tailored to the nonlinear saturation
    behavior commonly observed for AOM transfer functions. It stores the raw
    calibration arrays, derives initial fit guesses, performs the fit, and can
    plot or report the result.
    """

    def __init__(
        self,
        voltage_data: Sequence[float],
        power_data: Sequence[float],
        model: Optional["Model"] = None,
        initial_guess_function: Optional[Callable[[np.ndarray, np.ndarray], Mapping[str, Any]]] = None,
    ) -> None:
        """Store calibration samples and configure the fit model.

        Args:
            voltage_data: Measured AOM drive voltages.
            power_data: Measured optical powers corresponding to
                ``voltage_data``.
            model: Optional custom :class:`lmfit.Model` instance. The current
                implementation constructs the default model when this argument
                is not provided.
            initial_guess_function: Optional callable that returns lmfit
                parameter guesses from the stored voltage and power arrays.
        """
        self.voltage_data = np.array(voltage_data)
        self.power_data = np.array(power_data)
        self.initial_guess_function = initial_guess_function

        if not model:
            self.model = Model(self.voltage_to_power_model)
            self.initial_guess_function = self.estimate_initial_parameters

    @staticmethod
    def voltage_to_power_model(
        voltage: Union[np.ndarray, float],
        P_max: float,
        V_s: float,
        n_num: float,
        n_den: float,
        alpha: float,
        offset: float,
        v0: float,
        initial_guess_function: Optional[Callable[..., Mapping[str, Any]]] = None,
    ) -> Union[np.ndarray, float]:
        """Evaluate the asymmetric Hill-type saturation model.

        Args:
            voltage: Voltage value or array of voltages.
            P_max: Maximum power scaling factor of the model.
            V_s: Characteristic saturation voltage.
            n_num: Exponent controlling the onset steepness in the numerator.
            n_den: Exponent controlling the saturation tail in the denominator.
            alpha: Additional denominator shaping exponent.
            offset: Baseline power offset.
            v0: Voltage threshold below which the modeled output is clamped.
            initial_guess_function: Unused compatibility parameter kept in the
                function signature because :class:`lmfit.Model` inspects the
                callable signature directly.

        Returns:
            Modeled optical power for the supplied voltage input.
        """
        x = np.maximum(voltage - v0, 0.0)
        return offset + P_max * (x**n_num) / ((x**n_den + V_s**n_den) ** alpha)

    @staticmethod
    def estimate_initial_parameters(voltage: Sequence[float], power: Sequence[float]) -> Mapping[str, Any]:
        """Build heuristic initial parameters for the AOM power model.

        Args:
            voltage: Measured drive voltages.
            power: Measured optical powers.

        Returns:
            A mapping of parameter names to values or lmfit parameter
            constraint dictionaries suitable for ``Model.make_params``.
        """
        voltage, power = np.asarray(voltage, float), np.asarray(power, float)
        ymin, ymax = power.min(), power.max()
        initial_power_span = ymax - ymin
        initial_offset = ymin

        threshold_power = initial_offset + 0.02 * initial_power_span
        threshold_index = np.argmax(power >= threshold_power) if np.any(power >= threshold_power) else 0
        initial_threshold_voltage = voltage[threshold_index]

        half_max_power = initial_offset + 0.5 * initial_power_span
        half_max_index = np.argmin(np.abs(power - half_max_power))
        initial_saturation_voltage = max(1e-9, voltage[half_max_index] - initial_threshold_voltage)

        left_index = max(0, half_max_index - 1)
        right_index = min(len(voltage) - 1, half_max_index + 1)
        local_slope = (power[right_index] - power[left_index]) / max(1e-12, voltage[right_index] - voltage[left_index])
        initial_exponent = float(np.clip(4 * local_slope * initial_saturation_voltage / max(initial_power_span, 1e-12), 0.5, 6.0))

        return {
            "P_max": initial_power_span,
            "V_s": initial_saturation_voltage,
            "n_num": initial_exponent,
            "n_den": initial_exponent,
            "alpha": 1.0,
            "offset": {"value": initial_offset, "min": 0, "max": np.inf},
            "v0": initial_threshold_voltage,
        }

    def get_initial_parameter_guesses(self) -> Mapping[str, Any]:
        """Generate fit start values from the stored calibration arrays."""
        return self.initial_guess_function(self.voltage_data, self.power_data)

    def fit(self) -> Any:
        """Fit the configured model to the stored calibration samples.

        Returns:
            The lmfit fit result object produced by ``Model.fit``.
        """
        if self.initial_guess_function:
            params = self.model.make_params(**self.get_initial_parameter_guesses())
        else:
            params = self.model.make_params()

        self.result = self.model.fit(self.power_data, params, voltage=self.voltage_data)
        return self.result

    def plot_calibration_fit(self) -> None:
        """Plot the measured calibration points together with the fitted curve.

        Raises:
            ValueError: If no fit result is available yet.
        """
        if not hasattr(self, "result"):
            raise ValueError("Fit the data first using `fit()`.")

        fit_voltage = np.linspace(min(self.voltage_data), max(self.voltage_data), 500)
        fit_power = self.model.func(fit_voltage, **self.result.best_values)

        plt.figure(figsize=(8, 6))
        plt.plot(fit_voltage, fit_power * 1e3, label="Fitted Curve", color="orange", linewidth=1, zorder=1)
        plt.scatter(self.voltage_data, self.power_data * 1e3, label="Measured Data", color="blue", s=30, zorder=3)
        plt.xlabel("Voltage [V]")
        plt.ylabel("Power [mW]")
        plt.title("Voltage to Power Calibration")
        plt.legend()
        plt.grid()

    def print_fit_report(self) -> None:
        """Print the lmfit report for the most recent fit result.

        Raises:
            ValueError: If no fit result is available yet.
        """
        if not hasattr(self, "result"):
            raise ValueError("Fit the data first using `fit()`.")
        print(self.result.fit_report())
