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

import time
import numpy as np
from PySide2 import QtCore
from fysom import FysomError
from qudi.util.mutex import Mutex
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.anolog_and_digital_io import AnalogAndDigitalIO
from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase
from qudi.interface.process_control_interface import ProcessControlConstraints
from qudi.interface.process_control_interface import ProcessSetpointInterface
from qudi.interface.mixins.process_control_switch import ProcessControlSwitchMixin
from qudi.core.statusvariable import StatusVar
from qudi.core import Base

from qudi.util.helpers import natural_sort, in_range
from qudi.hardware.jaeger_computer_technik.helpers_adwin import (
    sanitize_device_name,
    normalize_channel_name,
)
from qudi.hardware.jaeger_computer_technik.helpers_adwin import (
    ao_channel_names,
    ao_voltage_range,
)

import os
import ADwin

from typing import Union


class Magnet3D(AdwinBase):  # TODO see towards - ProcessSetpointInterface

    ramp_freq = ConfigOption(name="ramp_freq", missing="warn")
    voltage_step_size = ConfigOption(name="voltage_step_size", missing="warn")
    timerIntervals = ConfigOption(name="timerIntervals", missing="warn")

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
    sigRampFinished = QtCore.Signal()

    has_persistence = False

    target_voltages: list = [0, 0, 0]

    def on_activate(self):
        self.boot_adwin()
        # Start relevent adwin process for magnet control
        self.start_adwin_processes(["magnet_control.TB2"])

        # Set ramp frequency and voltage step size on adwin
        self.write_fpar(13, self.voltage_step_size)
        self.write_fpar(14, self.ramp_freq)

        self.debug = True

        self._abortRampLoop = False
        self._abortRampToZeroLoop = False

        ## set up timers
        # fast ramp
        self.fastRampTimer = QtCore.QTimer()
        self.fastRampTimer.setSingleShot(True)
        self.fastRampTimer.timeout.connect(
            self._fast_ramp_loop_body, QtCore.Qt.QueuedConnection
        )
        self.fastRampTimer.setInterval(self.timerIntervals["fastRamp"])

        # ramp to zero
        self.zeroRampTimer = QtCore.QTimer()
        self.zeroRampTimer.setSingleShot(True)
        self.zeroRampTimer.timeout.connect(
            self._ramp_to_zero_loop_body, QtCore.Qt.QueuedConnection
        )
        self.zeroRampTimer.setInterval(self.timerIntervals["rampToZero"])

        self.target_voltages = self._get_voltages()

    def on_deactivate(self):
        """Stops all adwin process needed for the script"""
        # TODO

        # stop timers, don't know if this is really necessary
        self.fastRampTimer.stop()
        self.fastRampTimer.timeout.disconnect()
        self.zeroRampTimer.stop()
        self.zeroRampTimer.timeout.disconnect()
        self.clear_adwin_processes(["magnet_control.TB2"])

    def _field2amp(
        self, b_field: Union[float, list[float], np.ndarray[float]], axis: str = None
    ) -> Union[float, list[float]]:
        """Converts B-filed in (T) to current in (A).

        Args:
            b_field (Union[float, list, np.ndarray]): Input as single value
            of vector type list or np.ndarray in the form of [x_value, y_value, z_value]
            axis (str, optional): _description_. Defaults to None.

        Raises:
            ValueError: Wrong input datatype
            ValueError: _description_

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

    def _amp2field(
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

    @staticmethod
    def _volt2amp(
        voltage: Union[float, list[float], np.ndarray[float]]
    ) -> Union[float, list[float], np.ndarray[float]]:
        return voltage  # A

    @staticmethod
    def _amp2volt(
        current: Union[float, list[float], np.ndarray[float]]
    ) -> Union[float, list[float], np.ndarray[float]]:
        return current  # V

    def _volt2field(self, voltage):
        return self._amp2field(self._volt2amp(voltage))

    def _field2volt(self, b_field):
        return self._amp2volt(self._field2amp(b_field))

    def _set_voltages(self, ls_voltages: list[float]) -> None:
        """Changes Fpars to give new set voltages out by the adwin to the magnet controlers.
        (Set voltages get slowly approched by adbasic script)

        Args:
            ls_voltages (list[float]): Set voltages for x,y,z axis of magnet.
        """

        self.write_fpar(self.fpar_idx_set_volt_x, ls_voltages[0])
        self.write_fpar(self.fpar_idx_set_volt_y, ls_voltages[1])
        self.write_fpar(self.fpar_idx_set_volt_z, ls_voltages[2])

    def _get_voltages(self) -> list[Union[float, None]]:
        """
        Reads the Fpars, giving the measured voltage supplied by
        the adwin tho the x, y, z axsis magnet controlers

        Returns:
            list[float,float,float]: supplied voltages to the [x, y, z] axis
        """
        volt_x, _ = self.read_fpar(self.fpar_idx_volt_x)
        volt_y, _ = self.read_fpar(self.fpar_idx_volt_y)
        volt_z, _ = self.read_fpar(self.fpar_idx_volt_z)
        print
        return [volt_x, volt_y, volt_z]

    def get_target_magnet_currents(self):
        return self._volt2amp(self.target_voltages)

    def get_target_field(self) -> list[float]:
        return self._volt2field(self.target_voltages)

    def get_field(self) -> list[float, float, float]:
        """Returns field in x, y, z direction

        Returns:
            list[float, float, float]: [x, y, z] b-field strengths
        """
        field_x, field_y, field_z = self._volt2field(self._get_voltages())

        return [field_x, field_y, field_z]

    def _get_curr_set_voltages(self) -> list[float, float, float]:
        """Reads the Fpars, giving the current set voltages approched by the adwin
        to be supplied to the x,y, and x axsis magnet controlers

        Returns:
            list[float, float, float]: set voltages to the [x, y, z] axis
        """

        set_voltage_x, _ = self.read_fpar(self.fpar_idx_set_volt_x)
        set_voltage_y, _ = self.read_fpar(self.fpar_idx_set_volt_y)
        set_voltage_z, _ = self.read_fpar(self.fpar_idx_set_volt_z)
        
        return [set_voltage_x, set_voltage_y, set_voltage_z]

    def get_magnet_currents(self) -> list[float, float, float]:
        """Returns the supplied currents to the x, y z axis of the magnet.

        Returns:
            list[float, float, float]: [x, y, z] currents.
        """
        amp_x, amp_y, amp_z = self._volt2amp(self._get_voltages())

        return [amp_x, amp_y, amp_z]

    def ramp(
        self,
        field_target: list[float] = [None, None, None],
        enter_persistent: bool = False,
    ) -> None:
        """Initiates ramp to target b-field.

        Args:
            field_target (list[float,float,float], optional): [x, y, z] component of target b-field. Defaults to [None, None, None].
            enter_persistent (bool, optional): if persistent mode is used. Not implemented for used magnet. Defaults to False.

        Raises:
            RuntimeError: _
            RuntimeError: _
        """
        # Check for rounding errors leading to allmost, but no quite zero values
        for i, value in enumerate(field_target):
            if abs(value) < 1e-5:
                field_target[i] = 0

        # Check if persistent mode is used, if so, raise error, as the used magnet does not support it.
        if enter_persistent:
            self.log.error("Magnet does not have a persistent mode")
            return

        # check if the target field is within constraints
        if self.check_field_amplitude(field_target) != 0:
            self.log.error("Entered field is too strong.")
            return

        self.target_voltages = self._field2volt(field_target)
        # ramp according to the result from the check
        self._abortRampLoop = False
        self._abortRampToZeroLoop = True
        self.fast_ramp(field_target=field_target)
        self._start_fastRampTimer()

    def abort_ramp(self) -> None:
        """Aborts the ramp.

        Aborts the ramp loops and pauses the ramp.
        """
        self._abortRampLoop = True
        # self.pause_ramp()
        return

    def continue_ramp(self) -> None:
        """Resumes ramping."""
        self._set_voltages(self.target_voltages)
        self.log.info("Ramp continue")

    def pause_ramp(self):
        """Pauses the ramping process.

        The current/field will stay at the level it has now.
        """
        self._set_voltages(self._get_voltages())
        self.log.info("Ramp paused")

    def check_field_amplitude(
        self, target_field: Union[list[float], np.ndarray[float]]
    ) -> int:
        """Checks if the given field exceeds the constraints.

        Args:
            target_field (list[float]): [x, y, z] component of target b-field.

        Returns:
            int: 0 if everything is okay, -1 if field is too strong.
        """
        print(target_field)
        if isinstance(target_field, np.ndarray):

            if np.count_nonzero(target_field == 0) >= 1:
                max_amp = 10  # A

            elif np.count_nonzero(target_field == 0) == 0:
                max_amp = 7  # A

            else:
                return -1

        elif isinstance(target_field, list):

            if target_field.count(0) >= 1:
                max_amp = 10  # A

            elif target_field.count(0) == 0:
                max_amp = 7  # A

            else:
                return -1

        else:
            raise ValueError("Target_field must be numpy array or list")

        if max(self._field2amp(target_field)) <= max_amp:
            return 0
        else:
            return -1

    def fast_ramp(self, field_target: list[float, float, float]) -> None:
        self._set_voltages(self._field2volt(field_target))

    def _start_fastRampTimer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            self.log.info("Start ramping, thread is not currentThread")
            QtCore.QMetaObject.invokeMethod(
                self.fastRampTimer, "start", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.log.info("Start ramping")
            self.fastRampTimer.start()

    @QtCore.Slot()
    def _fast_ramp_loop_body(self):
        """Loop that controls the ramping of the magnet.

        If target field has been reached and magnet is in holding mode, sigRampFinished is emitted.
        Otherwise it is called again later.
        """
        self.log.debug("_fast_ramp_loop_body")
        # abort ramp loop if requested
        if self._abortRampLoop:
            self.pause_ramp()
            return
        ramping_state = self.get_ramping_state()
        print(ramping_state)
        if (
            ramping_state.count(2) + ramping_state.count(8) == 3
        ):  # might be a problem with pause?
            self._abortRampLoop = True
            self.log.info("Ramp finished")

            self.sigRampFinished.emit()
            return

        else:
            self.log.debug("fast ramping not finished")
            self.fastRampTimer.start()
            return

    def get_ramping_state(self) -> list[int]:
        """Returns the ramping state of all three 1D magnets.

        integers mean the following:
            1:  RAMPING to target field/current
            2:  HOLDING at the target field/current
            3:  PAUSED
            4:  [not implemented] Ramping in MANUAL UP mode
            5:  [not implemented] Ramping in MANUAL DOWN mode
            6:  [not implemented] ZEROING CURRENT (in progress)
            7:  [not implemented] Quench detected
            8:  At ZERO current
            9:  [not implemented] Heating persistent switch
            10: [not implemented] Cooling persistent switch

        Returns:
            list[int,int,int]: list of ints with ramping status [status_x,status_y,status_z]
        """

        set_voltages = self._get_curr_set_voltages()
        curr_voltages = self._get_voltages()

        ls_status = []

        for set_voltage, curr_voltage, target_voltage in zip(
            set_voltages, curr_voltages, self.target_voltages
        ):
            if (
                abs(set_voltage - curr_voltage) < 0.01
            ):  # self.ve_step_size/2: # max meas diffoltag
                if round(target_voltage, 3) == round(set_voltage, 3):
                    if set_voltage == 0:
                        ls_status.append(8)
                    else:
                        ls_status.append(2)

                else:
                    ls_status.append(3)

            else:
                ls_status.append(1)

        return ls_status

    def ramp_to_zero(self):
        """Ramps the magnet to zero field and turns off the PSW heaters."""
        self._abortRampLoop = True
        self._abortRampToZeroLoop = False

        self._set_voltages([0, 0, 0])
        self.target_voltages = [0, 0, 0]
        self._start_zeroRampTimer()

    def _start_zeroRampTimer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            self.log.info("Start ramping to Zero, thread is not currentThread")
            QtCore.QMetaObject.invokeMethod(
                self.zeroRampTimer, "start", QtCore.Qt.BlockingQueuedConnection
            )
        else:
            self.log.info("Start ramping to Zero")
            self.zeroRampTimer.start()

    @QtCore.Slot()
    def _ramp_to_zero_loop_body(self):
        self.log.debug("_ramp_to_zero_loop_body")
        if self._abortRampToZeroLoop:
            self.pause_ramp()
            return
        ramping_state = self.get_ramping_state()
        currents = self.get_magnet_currents()
        # ramping to zero sometimes ends up in HOLDING (2) or PAUSED (3) or ZERO (8)
        # no iddea why but this should fix it.
        boolean = (
            (ramping_state == [8, 8, 8])
            or (
                (ramping_state == [2, 2, 2])
                and (np.allclose(currents, [0, 0, 0], atol=0.1))
            )
            or (
                (ramping_state == [3, 3, 3])
                and (np.allclose(currents, [0, 0, 0], atol=0.1))
            )
        )

        self.log.debug(f"boolean turned out to be {boolean}")
        if boolean:
            self.log.info("Ramping to zero finished")
            self.sigRampFinished.emit()
            return
        else:
            self.log.debug("still ramping to zero")
            self.zeroRampTimer.start()
            return
