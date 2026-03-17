# -*- coding: utf-8 -*-
"""
This file contains a Qudi logic module for controlling scans of the
fourth analog output channel.  It was originally written for
scanning laser frequency, but it can be used to control any parameter
in the experiment that is voltage controlled.  The hardware
range is typically -10 to +10 V.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

# TODO when scan stopped plot the last complete scan.
# TODO refresh matrix when settings change
# TODO resolution
#!ValueError: all the input array dimensions for the concatenation axis must match exactly, but along dimension 1, the array at index 0 has size 50 and the array at index 1 has size 100

from PySide2 import QtCore
import copy as cp
from qudi.logic.scanning.probe_logic import ScanningProbeLogic

from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar

from qudi.util.widgets.fitting import FitConfigurationDialog, FitWidget

from qudi.util.delay import delay
from time import sleep

from qudi.util.datastorage import TextDataStorage
from qudi.util.datafitting import FitContainer, FitConfigurationsModel
import numpy as np
import os
import xarray as xr
import matplotlib.pyplot as plt
from datetime import datetime


class PLEScannerLogic(ScanningProbeLogic):
    """This logic module controls scans of DC voltage on the fourth analog
    output channel of the NI Card.  It collects countrate as a function of voltage.
    """

    # declare connectors
    _scanner = Connector(name="scanner", interface="ScanningProbeInterface")
    _wavemeter = Connector(
        name="wavemeter", interface="HighFinesseWavemeter", optional=True
    )  # FIX it to make more generatal and talk to the Wavemeter interfafce
    _calibration_factor = 1  # calibrate the wavelength
    _wavelength_range = [0, 0]
    _frequency_calibration_path = ConfigOption(
        name="frequency_calibration_path", default=None, missing="nothing"
    )
    _frequency_calibration_points = ConfigOption(
        name="frequency_calibration_points", default=11, missing="nothing"
    )
    _frequency_calibration_averages = ConfigOption(
        name="frequency_calibration_averages", default=5, missing="nothing"
    )
    _frequency_calibration_settle_time = ConfigOption(
        name="frequency_calibration_settle_time", default=3, missing="nothing"
    )
    _frequency_calibration_poly_degree = ConfigOption(
        name="frequency_calibration_poly_degree", default=2, missing="nothing"
    )

    #! We should refactor it to the hardware scanner interface
    _scan_axis = ConfigOption(name="scan_axis", default="a")
    _channel = StatusVar(name="channel", default=None)

    # status vars
    _scan_ranges = StatusVar(name="scan_ranges", default=None)
    _scan_resolution = StatusVar(name="scan_resolution", default=None)
    _scan_frequency = StatusVar(name="scan_frequency", default=None)

    _number_of_repeats = StatusVar(default=10)
    _repeated = 0
    display_repeated = 0
    # config options
    _fit_config = StatusVar(name="fit_config", default=None)
    _fit_region = StatusVar(name="fit_region", default=[0, 1])
    _scan_poll_interval = 100
    _default_fit_configs = (
        {
            "name": "Lorentzian",
            "model": "Lorentzian",
            "estimator": "Peak",
            "custom_parameters": None,
        },
        {
            "name": "DoubleLorentzian",
            "model": "DoubleLorentzian",
            "estimator": "Peaks",
            "custom_parameters": None,
        },
        {
            "name": "Gaussian",
            "model": "Gaussian",
            "estimator": "Peak",
            "custom_parameters": None,
        },
    )

    accumulated = None
    sigRepeatScan = QtCore.Signal(bool, tuple)
    sigFitUpdated = QtCore.Signal(object, str)
    sigToggleScan = QtCore.Signal(bool, tuple, object)
    sigSetScannerTarget = QtCore.Signal(dict)
    sigUpdateAccumulated = QtCore.Signal(object, object)
    sigScanningDone = QtCore.Signal()
    sigFrequencyCalibrationUpdated = QtCore.Signal(object)

    def __init__(self, config, **kwargs):
        super(PLEScannerLogic, self).__init__(config=config, **kwargs)

        """ Create VoltageScanningLogic object with connectors.

          @param dict kwargs: optional parameters
        """
        self._thread_lock = RecursiveMutex()

        # Took some from the spectrometer program, beacuse it's graaape
        self.refractive_index_air = 1.00028823
        self.speed_of_light = 2.99792458e8 / self.refractive_index_air
        self._fit_container = None
        self._fit_config_model = None
        self._fit_results = None

        self._wavelength = None
        self._fit_method = ""
        self.__scan_poll_timer = None
        self.__scan_poll_interval = 100
        self.__scan_stop_requested = True
        self._curr_caller_id = self.module_uuid

        self.data_accumulated = None
        self._scan_id = 0
        self._fit_results = dict()
        self._fit_results["fluorescence"] = [None] * 1
        self._frequency_calibration_data = None
        self._frequency_calibration_coefficients = None
        self._frequency_offset_thz = None
        self._frequency_calibration_voltage_range = None
        self._frequency_axis_relative_hz = None
        self._frequency_calibration_file = None

    def on_activate(self):
        """Initialisation performed during activation of the module."""
        # self._scanning_device = self.scanning_device()
        if self._wavemeter():
            self._wavemeter().start_acquisition()
        self._fit_config_model = FitConfigurationsModel(parent=self)
        self._fit_config_model.load_configs(self._fit_config)
        self._fit_container = FitContainer(
            parent=self, config_model=self._fit_config_model
        )
        self.fit_region = self._fit_region
        self.sigSetScannerTarget.connect(self.set_target_position)
        constr = self.scanner_constraints
        self._channel = (
            list(constr.channels.keys())[0] if self._channel is None else self._channel
        )
        self._scan_saved_to_hist = True
        self.log.debug(
            f"Scanner settings at startup, type {type(self._scan_ranges)} {self._scan_ranges, self._scan_resolution}"
        )
        # scanner settings loaded from StatusVar or defaulted
        new_settings = self.check_sanity_scan_settings(self.scan_settings)
        if new_settings != self.scan_settings:
            self._scan_ranges = new_settings["range"]
            self._scan_resolution = new_settings["resolution"]
            self._scan_frequency = new_settings["frequency"]

        if not self._min_poll_interval:
            # defaults to maximum scan frequency of scanner
            self._min_poll_interval = 1 / np.max(
                [constr.axes[ax].frequency_range for ax in constr.axes]
            )

        """
        if not isinstance(self._scan_ranges, dict):
            self._scan_ranges = {ax.name: ax.value_range for ax in constr.axes.values()}
        if not isinstance(self._scan_resolution, dict):
            self._scan_resolution = {ax.name: max(ax.min_resolution, min(128, ax.max_resolution))  # TODO Hardcoded 128?
                                     for ax in constr.axes.values()}
        if not isinstance(self._scan_frequency, dict):
            self._scan_frequency = {ax.name: ax.max_frequency for ax in constr.axes.values()}
        """
        self.sigRepeatScan.connect(self.toggle_scan, QtCore.Qt.QueuedConnection)
        self.__scan_poll_interval = 100
        self.__scan_stop_requested = True
        self._curr_caller_id = self.module_uuid

        if not self._min_poll_interval:
            # defaults to maximum scan frequency of scanner
            self._min_poll_interval = 1 / np.max(
                [
                    self.scanner_constraints.axes[ax].frequency_range
                    for ax in self.scanner_constraints.axes
                ]
            )

        self.__scan_poll_timer = QtCore.QTimer()
        self.__scan_poll_timer.setSingleShot(True)
        self.__scan_poll_timer.timeout.connect(
            self.__scan_poll_loop, QtCore.Qt.QueuedConnection
        )
        self.load_latest_frequency_calibration()

        return

    def on_deactivate(self):
        """Deinitialisation performed during deactivation of the module."""
        self._fit_config = self._fit_config_model.dump_configs()
        """ 
        Reverse steps of activation
        """
        self.__scan_poll_timer.stop()
        self.__scan_poll_timer.timeout.disconnect()
        if self.module_state() != "idle":
            self._scanner().stop_scan()

        return

    def calibrate_scan(self):
        self.scan_ranges_wavemeter = [0, 0]
        if self._wavemeter():
            for i in range(5):
                start, stop = self.run_calibration()
                self.scan_ranges_wavemeter[1] = (
                    self.scan_ranges_wavemeter[1] + stop
                ) / 2
        else:
            self.log.warning("No wavemeter connected, cannot calibrate scan ranges.")
            # self._scan_ranges.update({"a": [i*1e3 for i in self.scan_ranges_wavemeter]}) #in GHzs
        self._calibration_factor = (
            1e12
            * self.scan_ranges_wavemeter[-1]
            / self._scan_ranges[self._scan_axis][-1]
        )

    def run_calibration(self):
        self.set_target_position(
            {self._scan_axis: self.scan_ranges[self._scan_axis][0]}, move_blocking=True
        )
        new_pos = self._scanner().get_target()
        sleep(2)  # in mu sec
        self.wavelength_start = self._wavemeter().get_current_wavelength()

        self.set_target_position(
            {self._scan_axis: self.scan_ranges[self._scan_axis][-1]}, move_blocking=True
        )
        new_pos = self._scanner().get_target()
        sleep(2)  # in mu sec
        self.wavelength_stop = self._wavemeter().get_current_wavelength()

        return 0, self.wavelength_stop - self.wavelength_start

    @property
    def has_frequency_calibration(self):
        coeff = self._frequency_calibration_coefficients
        return coeff is not None and np.size(coeff) > 0 and np.all(np.isfinite(coeff))

    @property
    def frequency_offset_thz(self):
        return self._frequency_offset_thz

    @property
    def frequency_calibration_dir(self):
        if self._frequency_calibration_path:
            return self._frequency_calibration_path
        return os.path.join(self.module_default_data_dir, "ple_frequency_calibration")

    def _get_frequency_calibration_voltage_range(self):
        if self._frequency_calibration_voltage_range is not None:
            scan_range = tuple(self._frequency_calibration_voltage_range)
            if np.all(np.isfinite(scan_range)) and scan_range[0] != scan_range[1]:
                return float(min(scan_range)), float(max(scan_range))
        if self._frequency_calibration_data is not None:
            scan_range = self._frequency_calibration_data.attrs.get("scan_range")
            if scan_range is not None:
                scan_range = (float(min(scan_range)), float(max(scan_range)))
                if np.all(np.isfinite(scan_range)) and scan_range[0] != scan_range[1]:
                    return scan_range
            if "voltage" in self._frequency_calibration_data.coords:
                voltage = self._frequency_calibration_data.voltage.values
                scan_range = (float(np.min(voltage)), float(np.max(voltage)))
                if np.all(np.isfinite(scan_range)) and scan_range[0] != scan_range[1]:
                    return scan_range
        axis_range = self.scanner_constraints.axes[self._scan_axis].value_range
        return float(min(axis_range)), float(max(axis_range))

    def _get_frequency_offset_thz(self):
        if self._frequency_offset_thz is None:
            center_voltage = float(
                np.mean(self._get_frequency_calibration_voltage_range())
            )
            self._frequency_offset_thz = float(
                self._evaluate_frequency_fit_thz(center_voltage)
            )
        if not np.isfinite(self._frequency_offset_thz):
            raise ValueError("Frequency calibration offset is invalid.")
        return float(self._frequency_offset_thz)

    def _clear_frequency_calibration(self):
        self._frequency_calibration_data = None
        self._frequency_calibration_coefficients = None
        self._frequency_offset_thz = None
        self._frequency_calibration_voltage_range = None
        self._frequency_calibration_file = None

    def _read_wavemeter_frequency_thz(self):
        reading = self._wavemeter().get_current_wavelength(kind="freq")
        if reading is None:
            raise ValueError("Wavemeter returned no reading.")

        reading = float(reading)
        if reading <= 0:
            raise ValueError(f"Invalid wavemeter reading: {reading}")

        # Different wavemeter backends in this codebase return either wavelength
        # in nm, absolute frequency in Hz, or directly a THz-like value.
        if reading > 1e9:
            return reading / 1e12
        if reading > 1e3:
            return reading / 1e3
        return self.speed_of_light / (reading * 1e-9) / 1e12

    def _sample_wavemeter_frequency_thz(self, averages=None):
        averages = (
            self._frequency_calibration_averages if averages is None else averages
        )
        values = []
        for _ in range(max(1, int(averages))):
            values.append(self._read_wavemeter_frequency_thz())
            sleep(0.05)
        return float(np.mean(values))

    def _fit_frequency_calibration(self, voltages, frequency_thz):
        degree = min(int(self._frequency_calibration_poly_degree), len(voltages) - 1)
        self._frequency_calibration_coefficients = np.polyfit(
            voltages, frequency_thz, degree
        )

    def _evaluate_frequency_fit_thz(self, voltage):
        if self._frequency_calibration_coefficients is None:
            raise RuntimeError("No frequency calibration available.")
        return np.polyval(self._frequency_calibration_coefficients, voltage)

    def _relative_frequency_axis_hz_from_voltage(self, voltage_axis):
        frequency_axis_thz = np.asarray(
            self._evaluate_frequency_fit_thz(voltage_axis), dtype=float
        )
        offset_thz = self._get_frequency_offset_thz()
        return (frequency_axis_thz - offset_thz) * 1e12

    def get_scan_x_data(self, scan_data=None):
        if scan_data is None:
            scan_range = self.scan_ranges[self._scan_axis]
            resolution = int(self.scan_resolution[self._scan_axis])
        else:
            scan_range = scan_data.scan_range[0]
            resolution = int(scan_data.scan_resolution[0])

        voltage_axis = np.linspace(scan_range[0], scan_range[1], resolution)
        if not self.has_frequency_calibration:
            return voltage_axis
        x_data = self._relative_frequency_axis_hz_from_voltage(voltage_axis)
        if not np.all(np.isfinite(x_data)):
            return voltage_axis
        return x_data

    def get_scan_x_range(self, scan_data=None):
        x_data = self.get_scan_x_data(scan_data)
        return float(x_data[0]), float(x_data[-1])

    def get_scan_x_label(self):
        if self.has_frequency_calibration:
            return "Frequency", "Hz"
        axis = self.scanner_constraints.axes[self._scan_axis]
        return axis.name.title(), axis.unit

    def display_to_voltage(self, value):
        if not self.has_frequency_calibration:
            return float(value)

        scan_range = self._get_frequency_calibration_voltage_range()
        voltage_axis = np.linspace(scan_range[0], scan_range[1], 2000)
        frequency_axis_hz = self._relative_frequency_axis_hz_from_voltage(voltage_axis)
        mask = np.isfinite(voltage_axis) & np.isfinite(frequency_axis_hz)
        if np.count_nonzero(mask) < 2:
            return float(value)
        voltage_axis = voltage_axis[mask]
        frequency_axis_hz = frequency_axis_hz[mask]
        order = np.argsort(frequency_axis_hz)
        return float(np.interp(value, frequency_axis_hz[order], voltage_axis[order]))

    def voltage_to_display(self, value):
        if not self.has_frequency_calibration:
            return float(value)
        display_value = float(
            self._relative_frequency_axis_hz_from_voltage(np.asarray([value]))[0]
        )
        if not np.isfinite(display_value):
            return float(value)
        return display_value

    def get_frequency_calibration_metadata(self):
        metadata = {
            "frequency_axis_mode": (
                "calibrated_hz" if self.has_frequency_calibration else "scanner_axis"
            ),
            "frequency_axis_label": self.get_scan_x_label()[0],
            "frequency_axis_unit": self.get_scan_x_label()[1],
        }
        if self.has_frequency_calibration:
            metadata.update(
                {
                    "frequency_axis_offset_thz": self._frequency_offset_thz,
                    "frequency_calibration_voltage_range": self._get_frequency_calibration_voltage_range(),
                    "frequency_calibration_file": self._frequency_calibration_file,
                    "frequency_calibration_coefficients": list(
                        self._frequency_calibration_coefficients
                    ),
                }
            )
        return metadata

    def save_frequency_calibration_data(self):
        if self._frequency_calibration_data is None:
            self.log.warning("No PLE frequency calibration data to save.")
            return

        os.makedirs(self.frequency_calibration_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self.frequency_calibration_dir,
            f"ple_{self._scan_axis}_frequency_calibration_{timestamp}.h5",
        )
        filename_plot = os.path.join(
            self.frequency_calibration_dir,
            f"ple_{self._scan_axis}_frequency_calibration_{timestamp}.png",
        )

        self._frequency_calibration_data.to_netcdf(filename)

        voltage = self._frequency_calibration_data.voltage.values
        freq = self._frequency_calibration_data.frequency_thz.values
        voltage_fit = np.linspace(voltage.min(), voltage.max(), 400)
        freq_fit = self._evaluate_frequency_fit_thz(voltage_fit)

        plt.figure(figsize=(8, 6))
        plt.scatter(voltage, freq, label="Measured Data", color="blue", s=30, zorder=3)
        plt.plot(
            voltage_fit,
            freq_fit,
            label="Calibration Fit",
            color="orange",
            linewidth=1,
            zorder=1,
        )
        plt.xlabel("Voltage [V]")
        plt.ylabel("Frequency [THz]")
        plt.title("PLE Voltage to Frequency Calibration")
        plt.grid()
        plt.legend()
        plt.savefig(filename_plot)
        plt.close()

        self._frequency_calibration_file = filename
        self.log.info(f"PLE frequency calibration saved to {filename}")

    def load_latest_frequency_calibration(self):
        if not os.path.isdir(self.frequency_calibration_dir):
            return

        files = [
            file
            for file in os.listdir(self.frequency_calibration_dir)
            if file.startswith(f"ple_{self._scan_axis}_frequency_calibration_")
            and file.endswith(".h5")
        ]
        if not files:
            return

        latest_file = max(
            files,
            key=lambda f: os.path.getctime(
                os.path.join(self.frequency_calibration_dir, f)
            ),
        )
        file_path = os.path.join(self.frequency_calibration_dir, latest_file)
        try:
            dataset = xr.load_dataset(file_path)
            self._frequency_calibration_data = dataset
            self._frequency_calibration_coefficients = np.asarray(
                dataset.attrs.get("poly_coefficients", []), dtype=float
            )
            if self._frequency_calibration_coefficients.size == 0:
                voltage = dataset.voltage.values
                frequency_thz = dataset.frequency_thz.values
                self._fit_frequency_calibration(voltage, frequency_thz)
            self._frequency_calibration_voltage_range = (
                self._get_frequency_calibration_voltage_range()
            )
            offset_attr = dataset.attrs.get("frequency_offset_thz")
            if offset_attr is None:
                center_voltage = float(
                    np.mean(self._get_frequency_calibration_voltage_range())
                )
                self._frequency_offset_thz = float(
                    self._evaluate_frequency_fit_thz(center_voltage)
                )
            else:
                self._frequency_offset_thz = float(offset_attr)

            if (not self.has_frequency_calibration) or (
                not np.isfinite(self._frequency_offset_thz)
            ):
                raise ValueError("Loaded frequency calibration is invalid.")
        except Exception:
            self.log.exception("Ignoring invalid PLE frequency calibration file:")
            self._clear_frequency_calibration()
            return

        self._frequency_calibration_file = file_path
        self.sigFrequencyCalibrationUpdated.emit(
            self.get_frequency_calibration_metadata()
        )

    @QtCore.Slot()
    def calibrate_frequency_axis(self):
        if self.module_state() != "idle":
            self.log.warning(
                "Cannot calibrate PLE frequency axis while a scan is running."
            )
            return
        if not self._wavemeter():
            self.log.warning(
                "No wavemeter connected, cannot calibrate PLE frequency axis."
            )
            return

        scan_range = tuple(self.scanner_constraints.axes[self._scan_axis].value_range)
        voltages = np.linspace(
            scan_range[0], scan_range[1], int(self._frequency_calibration_points)
        )
        original_target = dict(self.scanner_target)
        frequencies_thz = []
        self._frequency_calibration_voltage_range = (
            float(min(scan_range)),
            float(max(scan_range)),
        )

        try:
            for voltage in voltages:
                self.set_target_position(
                    {self._scan_axis: float(voltage)}, move_blocking=True
                )
                sleep(float(self._frequency_calibration_settle_time))
                frequencies_thz.append(self._sample_wavemeter_frequency_thz())
        finally:
            if isinstance(original_target, dict) and self._scan_axis in original_target:
                self.set_target_position(
                    {self._scan_axis: original_target[self._scan_axis]},
                    move_blocking=True,
                )

        frequencies_thz = np.asarray(frequencies_thz, dtype=float)
        self._fit_frequency_calibration(voltages, frequencies_thz)
        self._frequency_offset_thz = float(
            self._evaluate_frequency_fit_thz(
                np.mean(self._frequency_calibration_voltage_range)
            )
        )
        relative_frequency_hz = self._relative_frequency_axis_hz_from_voltage(voltages)

        self._frequency_calibration_data = xr.Dataset(
            data_vars=dict(
                frequency_thz=xr.Variable(
                    "voltage",
                    frequencies_thz,
                    attrs=dict(units="THz", long_name="Absolute Frequency"),
                ),
                relative_frequency_hz=xr.Variable(
                    "voltage",
                    relative_frequency_hz,
                    attrs=dict(units="Hz", long_name="Relative Frequency"),
                ),
            ),
            coords=dict(
                voltage=xr.Variable(
                    "voltage", voltages, attrs=dict(units="V", long_name="Voltage")
                ),
            ),
            attrs=dict(
                scan_axis=self._scan_axis,
                frequency_offset_thz=float(self._frequency_offset_thz),
                poly_coefficients=list(
                    np.asarray(self._frequency_calibration_coefficients, dtype=float)
                ),
                calibration_points=int(self._frequency_calibration_points),
                calibration_averages=int(self._frequency_calibration_averages),
                scan_range=list(scan_range),
            ),
        )
        self.save_frequency_calibration_data()
        self.sigFrequencyCalibrationUpdated.emit(
            self.get_frequency_calibration_metadata()
        )
        self.set_full_scan_ranges()
        self.sigScannerTargetChanged.emit(self.scanner_target, self.module_uuid)

    def set_full_scan_ranges(self):
        if self.has_frequency_calibration:
            scan_range = {
                ax: axis.value_range
                for ax, axis in self.scanner_constraints.axes.items()
            }
            scan_range[self._scan_axis] = (
                self._get_frequency_calibration_voltage_range()
            )
            return self.set_scan_range(scan_range)
        return super().set_full_scan_ranges()

    def get_average(self, scan_data):
        averaged_data = {}
        for channel, data in scan_data.accumulated.items():
            data_new = data[~np.all(data == 0, axis=1)]
            if data_new.size > 1:
                last_row = data_new[-1, :]
                mask = np.ones_like(data_new, dtype=bool)  # Initialize a full True mask
                mask[-1, :] = last_row != 0
                averaged_data[channel] = np.sum(mask * data_new, axis=0) / np.sum(
                    mask, axis=0
                )
            else:
                averaged_data[channel] = data.mean(axis=0)
        return averaged_data

    @QtCore.Slot(str, str)
    def do_fit(self, fit_config, channel, averaged=False):
        """
        Execute the currently configured fit on the measurement data. Optionally on passed data
        """

        if (
            fit_config != "No Fit"
            and fit_config not in self._fit_config_model.configuration_names
        ):
            self.log.error(f'Unknown fit configuration "{fit_config}" encountered.')
            return

        if self.scan_data is None:
            return

        y_data = (
            self.get_average(self.scan_data)[self._channel]
            if averaged
            else self.scan_data.data[self._channel]
        )
        x_data = self.get_scan_x_data(self.scan_data)
        try:
            fit_config, fit_result = self._fit_container.fit_data(
                fit_config, x_data, y_data
            )
        except:
            self.log.exception("Data fitting failed:")
            return

        if fit_result is not None:
            self._fit_results[self._channel] = (fit_config, fit_result)
        else:
            self._fit_results[self._channel] = None

        self.sigFitUpdated.emit(self._fit_results[self._channel], self._channel)

    @_fit_config.representer
    def __repr_fit_configs(self, value):
        configs = self.fit_config_model.dump_configs()
        if len(configs) < 1:
            configs = None
        return configs

    @_fit_config.constructor
    def __constr_fit_configs(self, value):
        if not value:
            return self._default_fit_configs
        return value

    @property
    def fit_results(self):
        return self._fit_results.copy()

    @property
    def fit_config_model(self):
        return self._fit_config_model

    @property
    def fit_container(self):
        return self._fit_container

    @property
    def fit_results(self):
        return self._fit_results.copy()

    def stack_data(self):
        if (self.scan_data is not None) and (self.scan_data.scan_dimension == 1):

            if self.accumulated is None:

                self.accumulated = {
                    channel: data_i[np.newaxis, :]
                    for channel, data_i in self.scan_data.data.items()
                }

            else:
                if len(list(self.scan_data.data.values())[0]) > 0:
                    self.accumulated = {
                        channel: np.vstack((self.accumulated[channel], data_i))[
                            -self._number_of_repeats :
                        ]
                        for channel, data_i in self.scan_data.data.items()
                    }
                else:
                    return
            self._scanner()._scan_data.accumulated = self.accumulated
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
            # self.sigUpdateAccumulated.emit(self.accumulated, self.scan_data)

    @QtCore.Slot(dict)
    def set_scan_settings(self, settings):
        with self._thread_lock:
            if "range" in settings:
                self.set_scan_range(settings["range"])
            if "resolution" in settings:
                self.set_scan_resolution(settings["resolution"])
            if "frequency" in settings:
                self.set_scan_frequency(settings["frequency"])
            if "save_to_history" in settings:
                self._scan_saved_to_hist = settings["save_to_history"]
            # self.reset_accumulated()

    def update_number_of_repeats(self, number_of_repeats):
        self._number_of_repeats = number_of_repeats

    def set_target_position(self, pos_dict, caller_id=None, move_blocking=False):
        with self._thread_lock:
            if self.module_state() != "idle":
                # self.log.error('Unable to change scanner target position while a scan is running.')
                new_pos = self._scanner().get_target()
                self.sigScannerTargetChanged.emit(new_pos, self.module_uuid)
                return new_pos

            ax_constr = self.scanner_constraints.axes
            new_pos = pos_dict.copy()
            for ax, pos in pos_dict.items():
                if ax not in ax_constr:
                    self.log.error('Unknown scanner axis: "{0}"'.format(ax))
                    new_pos = self._scanner().get_target()
                    self.sigScannerTargetChanged.emit(new_pos, self.module_uuid)
                    return new_pos

                new_pos[ax] = ax_constr[ax].clip_value(pos)
                if pos != new_pos[ax]:
                    self.log.warning(
                        'Scanner position target value out of bounds for axis "{0}". '
                        "Clipping value to {1:.3e}.".format(ax, new_pos[ax])
                    )

            new_pos = self._scanner().move_absolute(new_pos, blocking=move_blocking)
            if any(pos != new_pos[ax] for ax, pos in pos_dict.items()):
                caller_id = None
            # self.log.debug(f"Logic set target with id {caller_id} to new: {new_pos}")
            self.sigScannerTargetChanged.emit(
                new_pos, self.module_uuid if caller_id is None else caller_id
            )
            return new_pos

    def toggle_scan(self, start, scan_axes, caller_id=None):
        self._toggled_scan_axes = scan_axes
        with self._thread_lock:
            if start:
                # if self._repeated == 0:
                #     self.display_repeated = 0
                return self.start_scan(self._toggled_scan_axes, caller_id)
            return self.stop_scan()

    def start_scan(self, scan_axes, caller_id=None):
        self._curr_caller_id = self.module_uuid if caller_id is None else caller_id
        self.display_repeated = self._repeated

        with self._thread_lock:

            if self.module_state() != "idle":
                self.sigScanStateChanged.emit(
                    True, self.scan_data, self._curr_caller_id
                )
                return 0

            scan_axes = tuple(scan_axes)

            self.module_state.lock()
            settings = {
                "axes": scan_axes,
                "range": tuple(self._scan_ranges[ax] for ax in scan_axes),
                "resolution": tuple(self._scan_resolution[ax] for ax in scan_axes),
                "frequency": self._scan_frequency[scan_axes[0]],
                "lines_to_scan": self._number_of_repeats,
            }
            fail, new_settings = self._scanner().configure_scan(settings)

            print(fail)
            if fail:
                self.module_state.unlock()
                self.stop_scan()
                self.sigScanStateChanged.emit(False, None, self._curr_caller_id)
                return -1

            self._update_scan_settings(scan_axes, new_settings)
            # Calculate poll time to check for scan completion. Use line scan time estimate.
            line_points = (
                self._scan_resolution[scan_axes[0]] if len(scan_axes) > 1 else 1
            )
            # self.__scan_poll_interval = max(self._min_poll_interval,
            #                                 line_points / self._scan_frequency[scan_axes[0]])
            self.__scan_poll_timer.setInterval(
                int(round(self._scan_poll_interval))
            )  # * 1000)))
            print("test_2")
            if (
                self._scanner().start_scan() < 0
            ):  # TODO Current interface states that bool is returned from start_scan

                self.module_state.unlock()
                self.sigScanStateChanged.emit(False, None, self._curr_caller_id)
                return -1
            print("test_3")
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
            print("test_3")
            self.__start_timer()
            return 0

    @QtCore.Slot()
    def stop_scan(self):
        with self._thread_lock:
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)

            if self.module_state() == "idle":
                self.sigScanStateChanged.emit(
                    False, self.scan_data, self._curr_caller_id
                )
                return 0

            self.__stop_timer()

            err = (
                self._scanner().stop_scan()
                if self._scanner().module_state() != "idle"
                else 0
            )

            self.module_state.unlock()

            # if self.scan_settings['save_to_history']:
            #     # module_uuid signals data-ready to data logic
            #     self.sigScanStateChanged.emit(False, self.scan_data, self.module_uuid)
            # else:
            self.sigScanStateChanged.emit(False, self.scan_data, self._curr_caller_id)

            return err

    def reset_accumulated(self):
        self.accumulated = None
        # if self.scan_data is not None:
        #    self.scan_data._accumulated = None

    def _update_scan_settings(self, scan_axes, settings):
        for ax_index, ax in enumerate(scan_axes):
            # Update scan ranges if needed
            new = tuple(settings["range"][ax_index])
            if self._scan_ranges[ax] != new:
                self._scan_ranges[ax] = new
                self.sigScanSettingsChanged.emit({"range": {ax: self._scan_ranges[ax]}})

            # Update scan resolution if needed
            new = int(settings["resolution"][ax_index])
            if self._scan_resolution[ax] != new:
                self._scan_resolution[ax] = new
                self.sigScanSettingsChanged.emit(
                    {"resolution": {ax: self._scan_resolution[ax]}}
                )

        # Update scan frequency if needed
        new = float(settings["frequency"])
        if self._scan_frequency[scan_axes[0]] != new:
            self._scan_frequency[scan_axes[0]] = new
            self.sigScanSettingsChanged.emit({"frequency": {scan_axes[0]: new}})

    @QtCore.Slot()
    def __scan_poll_loop(self):
        with self._thread_lock:
            try:
                if self.module_state() == "idle":
                    return
                # if self._scanner().
                # lines_to_scan = self._number_of_repeats
                # elif hasattr(self._scanner(), "_triggered_ao") and self._repeated > 0:
                #             self.sigScanningDone.emit()
                #             self.sigRepeatScan.emit(False, self._toggled_scan_axes)
                #             self._repeated = 0
                if self._scanner().module_state() == "idle":

                    self.stop_scan()

                    if hasattr(
                        self._scanner(), "_triggered_ao"
                    ):  #  and self._repeated > 0:
                        self.sigScanningDone.emit()
                        self.sigRepeatScan.emit(False, self._toggled_scan_axes)
                        self._repeated = 0
                        return

                    if (self._curr_caller_id == self._scan_id) or (
                        self._curr_caller_id == self.module_uuid
                    ):
                        self._repeated += 1
                        self.display_repeated += 1

                        self.stack_data()

                        if (
                            self._number_of_repeats > self._repeated
                            or self._number_of_repeats == 0
                        ):
                            self.sigRepeatScan.emit(True, self._toggled_scan_axes)
                        else:
                            # if self._scanner()._scanned_lines > self._scanner().lines_to_scan or self._number_of_repeats == 0:
                            self.sigScanningDone.emit()
                            self.sigRepeatScan.emit(False, self._toggled_scan_axes)
                            self._repeated = 0
                    return

                # TODO Added the following line as a quick test; Maybe look at it with more caution if correct
                # self._scanner().sigNextDataChunk.emit()
                self.sigScanStateChanged.emit(
                    True, self.scan_data, self._curr_caller_id
                )

                # Queue next call to this slot
                self.__scan_poll_timer.start()
            except TimeoutError:
                self.log.exception("Timed out while waiting for scan data:")
            except:
                self.log.exception("An exception was raised while polling the scan:")
            return

    def __start_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(
                self.__scan_poll_timer, "start", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.__scan_poll_timer.start()

    def __stop_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(
                self.__scan_poll_timer, "stop", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.__scan_poll_timer.stop()
