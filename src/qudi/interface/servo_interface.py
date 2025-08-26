# -*- coding: utf-8 -*-

"""
This file contains the Qudi Interface for servo control.


Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

from abc import abstractmethod
from core.interface import abstract_interface_method
from core.meta import InterfaceMetaclass


class servo_interface(metaclass=InterfaceMetaclass):
    """ Interface for controlling servo motors through serial communication """

    @abstract_interface_method
    def send_position(self, servo_id, position):
        """ Send a position command to a servo motor

        @param int servo_id: ID of the servo motor to control
        @param float position: Target position for the servo motor
        @return bool: Success of the operation
        """
        pass

    @abstract_interface_method
    def get_last_position(self, servo_id):
        """ Get the last known position of a servo motor

        @param int servo_id: ID of the servo motor
        @return float: Last known position of the servo motor
        """
        pass

    @abstract_interface_method
    def is_connected(self):
        """ Check if the serial connection to the servo controller is active

        @return bool: True if connected, False if not
        """
        pass

    @abstract_interface_method
    def get_available_servos(self):
        """ Get a list of available servo IDs that can be controlled

        @return list: List of available servo IDs
        """
        pass

    @abstract_interface_method
    def get_position_limits(self, servo_id):
        """ Get the minimum and maximum position limits for a servo

        @param int servo_id: ID of the servo motor
        @return tuple: (min_position, max_position) in the same units as position
        """
        pass
