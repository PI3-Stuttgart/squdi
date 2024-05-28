"""
This file contains the Qudi dummy module for the confocal scanner.

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

from typing import Union
from enum import Enum
import numpy as np

from PySide2 import QtCore

from qudi.core.configoption import ConfigOption

from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase
from qudi.interface.coil_magnet_interface import CoilMagnetInterface


class MagnetStatus(Enum):
    """Status of Magnet"""

    RAMPING = 1  # ramping to target field/current
    HOLDING = 2  # holding at the target field/current
    PAUSED = 3
    ZERO = 8  # At zero current
    #  4:  [not implemented] Ramping in MANUAL UP mode
    #  5:  [not implemented] Ramping in MANUAL DOWN mode
    #  6:  [not implemented] ZEROING CURRENT (in progress)
    #  7:  [not implemented] Quench detected
    #  9:  [not implemented] Heating persistent switch
    # 10: [not implemented] Cooling persistent switch


class Magnet3D(AdwinBase):
    """Controles analog voltage output of the ADwin to the Qinu magnet coils"""

    debug = True
    has_persistence = False

    _abort_ramp_loop = False
    _abort_ramp_to_zero_loop = False

    target_voltages: list = [0, 0, 0]

    ramp_freq: float = ConfigOption(name="ramp_freq", missing="warn")
    voltage_step_size: float = ConfigOption(name="voltage_step_size", missing="warn")
    timer_intervals: dict[str, int] = ConfigOption(
        name="timerIntervals", missing="warn"
    )

    fpar_idx_volt_x: int = 15
    fpar_idx_volt_y: int = 16
    fpar_idx_volt_z: int = 17

    fpar_idx_set_volt_x: int = 10
    fpar_idx_set_volt_y: int = 11
    fpar_idx_set_volt_z: int = 12

    CONV_FACTOR_X: float = 0.0542  # T/A
    CONV_FACTOR_Y: float = 0.0534  # T/A
    CONV_FACTOR_Z: float = 0.0644  # T/A

    # external signals
    sig_ramp_finished = QtCore.Signal()

    ## set up timers
    fast_ramp_timer = QtCore.QTimer()
    zero_ramp_Timer = QtCore.QTimer()

    def on_activate(self) -> None:
        """Boots adwin and sets ramp step size and frequency."""
        self.boot_adwin()
        # Start relevent adwin process for magnet control
        self.start_adwin_processes(["magnet_control.TB2"])

        # Set ramp frequency and voltage step size on adwin
        self.write_fpar(idx=13, value=self.voltage_step_size)
        self.write_fpar(idx=14, value=self.ramp_freq)

        ## set up timers
        # fast ramp
        self.fast_ramp_timer = QtCore.QTimer()
        self.fast_ramp_timer.setSingleShot(True)
        self.fast_ramp_timer.timeout.connect(
            self._fast_ramp_loop_body, QtCore.Qt.QueuedConnection
        )
        self.fast_ramp_timer.setInterval(self.timer_intervals["fastRamp"])

        # ramp to zero
        self.zero_ramp_Timer.setSingleShot(True)
        self.zero_ramp_Timer.timeout.connect(
            self._ramp_to_zero_loop_body, QtCore.Qt.QueuedConnection
        )
        self.zero_ramp_Timer.setInterval(self.timer_intervals["rampToZero"])

        self.target_voltages = self._get_voltages()

    def on_deactivate(self):
        """Stops all adwin process needed for the script"""

        # stop timers, don't know if this is really necessary
        self.fast_ramp_timer.stop()
        self.fast_ramp_timer.timeout.disconnect()
        self.zero_ramp_timer.stop()
        self.zero_ramp_timer.timeout.disconnect()

        # Stop and clear used adwin process
        self.clear_adwin_processes(["magnet_control.TB2"])

    def _b_field2current(
        self,
        b_field: Union[float, list[float], np.ndarray[float]],
        axis: Union[str, None] = None,
    ) -> Union[float, list[float], None]:
        """Converts B-filed in (T) to current in (A).

        Args:
            b_field (Union[float, list, np.ndarray]): Input as single value
            of vector type list or np.ndarray in the form of [x_value, y_value, z_value]
            axis (str, optional): _description_. Defaults to None.

        Returns:
            list[str]: Current as vector in the form of [x_value, y_value, z_value]
            or single float
        """

        if isinstance(b_field, float):
            if axis == "x":
                conv_factor = self.CONV_FACTOR_X
            elif axis == "y":
                conv_factor = self.CONV_FACTOR_Y
            elif axis == "z":
                conv_factor = self.CONV_FACTOR_Z
            else:
                self.log.error("Axis not defined")

            return b_field / conv_factor  # A

        if isinstance(b_field, list) or isinstance(b_field, np.ndarray):
            return [
                b_field[0] / self.CONV_FACTOR_X,
                b_field[1] / self.CONV_FACTOR_Y,
                b_field[2] / self.CONV_FACTOR_Z,
            ]

        else:
            self.log.error("Input must be of type float, np.ndarray or list")

    def _current2b_field(
        self,
        voltage: Union[float, list[float], np.ndarray[float]],
        axis: Union[str, None] = None,
    ) -> Union[float, list[float], None]:

        if isinstance(voltage, float):

            if axis == "x":
                conv_factor = self.CONV_FACTOR_X
            elif axis == "y":
                conv_factor = self.CONV_FACTOR_Y
            elif axis == "z":
                conv_factor = self.CONV_FACTOR_Z
            else:
                self.log.error("Axis not defined")

            return voltage * conv_factor  # T

        if isinstance(voltage, list) or isinstance(voltage, np.ndarray):
            return [
                voltage[0] * self.CONV_FACTOR_X,
                voltage[1] * self.CONV_FACTOR_Y,
                voltage[2] * self.CONV_FACTOR_Z,
            ]

        else:
            self.log.error("Input must be of type float, np.ndarray or list")
            return None

    @staticmethod
    def _voltage2current(
        voltage: Union[float, list[float], np.ndarray[float]]
    ) -> Union[float, list[float], np.ndarray[float]]:
        return voltage  # A

    @staticmethod
    def _current2voltage(
        current: Union[float, list[float], np.ndarray[float]]
    ) -> Union[float, list[float], np.ndarray[float]]:
        return current  # V

    def _voltage2b_field(self, voltage):
        return self._current2b_field(self._voltage2current(voltage))

    def _b_field2voltage(self, b_field):
        return self._current2voltage(self._b_field2current(b_field))

    def _set_voltages(self, voltages: list[float]) -> None:
        """Changes Fpars to give new set voltages out by the adwin to the magnet controlers.
        (Set voltages get slowly approched by adbasic script)

        Args:
            ls_voltages (list[float]): Set voltages for x,y,z axis of magnet.
        """
        self.write_fpar(idx=self.fpar_idx_set_volt_x, value=voltages[0])
        self.write_fpar(idx=self.fpar_idx_set_volt_y, value=voltages[1])
        self.write_fpar(idx=self.fpar_idx_set_volt_z, value=voltages[2])

    def _get_voltages(self) -> list[float]:
        """
        Reads the Fpars, giving the measured voltage supplied by
        the adwin tho the x, y, z axsis magnet controlers

        Returns:
            list[float,float,float]: supplied voltages to the [x, y, z] axis
        """
        volt_x, _ = self.read_fpar(self.fpar_idx_volt_x)
        volt_y, _ = self.read_fpar(self.fpar_idx_volt_y)
        volt_z, _ = self.read_fpar(self.fpar_idx_volt_z)

        if volt_x and volt_y and volt_z:
            return [volt_x, volt_y, volt_z]
        else:
            self.log.error("Setting magnet voltages failed")

    def get_target_magnet_currents(self):
        return self._voltage2current(self.target_voltages)

    def get_target_b_field(self) -> float | list[float] | None:
        return self._voltage2b_field(self.target_voltages)

    def get_b_field(self) -> list[float]:
        """Returns field in x, y, z direction

        Returns:
            list[float, float, float]: [x, y, z] b-field strengths
        """
        field_x, field_y, field_z = self._voltage2b_field(self._get_voltages())

        return [field_x, field_y, field_z]

    def _get_curr_set_voltages(self) -> list[float]:
        """Reads the Fpars, giving the current set voltages approched by the adwin
        to be supplied to the x,y, and x axsis magnet controlers

        Returns:
            list[float, float, float]: set voltages to the [x, y, z] axis
        """

        set_voltage_x = self.adwin.Get_FPar(self.fpar_idx_set_volt_x)
        set_voltage_y = self.adwin.Get_FPar(self.fpar_idx_set_volt_y)
        set_voltage_z = self.adwin.Get_FPar(self.fpar_idx_set_volt_z)

        return [set_voltage_x, set_voltage_y, set_voltage_z]

    def get_magnet_currents(self) -> list[float]:
        """Returns the supplied currents to the x, y z axis of the magnet.

        Returns:
            list[float, float, float]: [x, y, z] currents.
        """
        amp_x, amp_y, amp_z = self._voltage2current(self._get_voltages())

        return [amp_x, amp_y, amp_z]

    def ramp(
        self,
        b_field_target: list[float],
        enter_persistent: bool = False,
    ) -> None:
        """Initiates ramp to target b-field.

        Args:
            b_field_target (list[float,float,float], optional): [x, y, z] component of target b-field. Defaults to [None, None, None].
            enter_persistent (bool, optional): if persistent mode is used. Not implemented for used magnet. Defaults to False.

        Raises:
            RuntimeError: _
            RuntimeError: _
        """
        # Check for rounding errors leading to allmost, but no quite zero values
        for i, value in enumerate(b_field_target):
            if abs(value) < 1e-5:
                b_field_target[i] = 0

        # Check if persistent mode is used, if so, raise error, as the used magnet does not support it.
        if enter_persistent:
            self.log.error("Magnet does not have a persistent mode")
            return

        # check if the target field is within constraints
        if self.check_b_field_amplitude(b_field_target) != 0:
            self.log.error("Entered field is too strong.")
            return

        self.target_voltages = self._b_field2voltage(b_field_target)
        # ramp according to the result from the check
        self._abort_ramp_loop = False
        self._abort_ramp_to_zero_loop = True
        self.fast_ramp(b_field_target=b_field_target)
        self._start_fast_ramp_timer()

    def abort_ramp(self) -> None:
        """Aborts the ramp.

        Aborts the ramp loops.
        """
        self._abort_ramp_loop = True
        return

    def continue_ramp(self) -> None:
        """Resumes ramping."""
        self._set_voltages(self.target_voltages)
        self.log.info("Ramp continue")

    def pause_ramp(self) -> None:
        """Pauses the ramping process.

        The current/field will stay at the level it has now.
        """
        self._set_voltages(self._get_voltages())
        self.log.info("Ramp paused")

    def check_b_field_amplitude(
        self, target_b_field: Union[list[float], np.ndarray[float]]
    ) -> int:
        """Checks if the given field exceeds the constraints.

        Args:
            target_b_field (list[float]): [x, y, z] component of target b-field.

        Returns:
            int: 0 if everything is okay, -1 if field is too strong.
        """
        if isinstance(target_b_field, np.ndarray):

            if np.count_nonzero(target_b_field == 0) >= 1:
                max_amp = 10  # A

            elif np.count_nonzero(target_b_field == 0) == 0:
                max_amp = 7  # A

            else:
                return -1

        elif isinstance(target_b_field, list):

            if target_b_field.count(0) >= 1:
                max_amp = 10  # A

            elif target_b_field.count(0) == 0:
                max_amp = 7  # A

            else:
                return -1

        else:
            raise ValueError("target_b_field must be numpy array or list")

        if max(self._b_field2current(target_b_field)) <= max_amp:
            return 0
        else:
            return -1

    def fast_ramp(self, b_field_target: list[float, float, float]) -> None:
        """Sets relevant Fpars of the adwin to the target voltages to start ramping"""
        self._set_voltages(self._b_field2voltage(b_field_target))

    def _start_fast_ramp_timer(self) -> None:
        """Starts QT Timer for fast ramp"""
        if self.thread() is not QtCore.QThread.currentThread():
            self.log.info("Start ramping, thread is not currentThread")
            QtCore.QMetaObject.invokeMethod(
                self.fast_ramp_timer, "start", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.log.info("Start ramping")
            self.fast_ramp_timer.start()

    @QtCore.Slot()
    def _fast_ramp_loop_body(self):
        """Loop that controls the ramping of the magnet.

        If target field has been reached and magnet is in holding mode, sigRampFinished is emitted.
        Otherwise it is called again later.
        """
        self.log.debug("_fast_ramp_loop_body")
        # abort ramp loop if requested
        if self._abort_ramp_loop:
            self.pause_ramp()
            return
        ramping_state: list[MagnetStatus] = self.get_ramping_state()
        if (
            ramping_state.count(MagnetStatus.HOLDING)
            + ramping_state.count(MagnetStatus.ZERO)
            == 3
        ):  # might be a problem with pause?
            self._abort_ramp_loop = True
            self.log.info("Ramp finished")

            self.sig_ramp_finished.emit()
            return

        else:
            self.log.debug("fast ramping not finished")
            self.fast_ramp_timer.start()
            return

    def get_ramping_state(self) -> list[MagnetStatus]:
        """Returns the ramping state of all three 1D magnets."""

        ls_set_voltages: list[float] = self._get_curr_set_voltages()
        ls_curr_voltages: list[float] = self._get_voltages()

        ls_status: list[MagnetStatus] = []

        for set_voltage, curr_voltage, target_voltage in zip(
            ls_set_voltages, ls_curr_voltages, self.target_voltages
        ):
            if (
                abs(set_voltage - curr_voltage) < 0.01
            ):  # self.ve_step_size/2: # max meas diffoltag
                if round(target_voltage, 3) == round(set_voltage, 3):
                    if set_voltage == 0:
                        ls_status.append(MagnetStatus.ZERO)
                    else:
                        ls_status.append(MagnetStatus.HOLDING)

                else:
                    ls_status.append(MagnetStatus.PAUSED)

            else:
                ls_status.append(MagnetStatus.RAMPING)

        return ls_status

    def ramp_to_zero(self):
        """Ramps the magnet to zero field and turns off the PSW heaters."""
        self._abort_ramp_loop = True
        self._abort_ramp_to_zero_loop = False

        self._set_voltages([0, 0, 0])
        self.target_voltages = [0, 0, 0]
        self._start_zero_ramp_timer()

    def _start_zero_ramp_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            self.log.info("Start ramping to Zero, thread is not currentThread")
            QtCore.QMetaObject.invokeMethod(
                self.zero_ramp_timer, "start", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.log.info("Start ramping to Zero")
            self.zero_ramp_timer.start()

    @QtCore.Slot()
    def _ramp_to_zero_loop_body(self):
        self.log.debug("_ramp_to_zero_loop_body")
        if self._abort_ramp_to_zero_loop:
            self.abort_ramp()
            return
        ramping_state: list[MagnetStatus] = self.get_ramping_state()
        currents: list[float] = self.get_magnet_currents()
        # ramping to zero sometimes ends up in HOLDING (2) or PAUSED (3) or ZERO (8)
        # no iddea why but this should fix it.
        boolean = (
            (ramping_state == [MagnetStatus.ZERO] * 3)
            or (
                (ramping_state == [MagnetStatus.HOLDING] * 3)
                and (np.allclose(currents, [0, 0, 0], atol=0.1))
            )
            or (
                (ramping_state == [MagnetStatus.PAUSED] * 3)
                and (np.allclose(currents, [0, 0, 0], atol=0.1))
            )
        )

        self.log.debug(f"boolean turned out to be {boolean}")
        if boolean:
            self.log.info("Ramping to zero finished")
            self.sig_ramp_finished.emit()
            return
        else:
            self.log.debug("still ramping to zero")
            self.zero_ramp_timer.start()
            return
