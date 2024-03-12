"""
Logic module that controls Thorlabs Ello devices.


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


Example config:
    ello_logic:
        module.Class: 'ello_logic.ElloLogic'
        connect:
            ellodevices: 'ello_devices'

"""


from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from PySide2 import QtCore

class ElloLogic(LogicBase):
    #connectors
    ellodevices = Connector(name='ellodevices', interface='ThorlabsElloDevices')

    # signals
    sigGotPosition = QtCore.Signal(float)
    sigGotStepSize = QtCore.Signal(float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        return

    def on_activate(self):
        # connectors
        self._ellodevices = self.ellodevices()
        try:
            self._rotor = self._ellodevices.ello_rotor
        except:
            self._rotor = False
            print('No rotor connected.')
        try:
            self._flip = self._ellodevices.ello_flip
        except:
            self._flip = False
            print('No flipper connected.')
        return

    def on_deactivate(self):
        pass

    def home_rotor(self):
        """Homes the rotor.
        """
        self._rotor.home()
        return

    def get_rotor_pos(self):
        """Gets the rotor position.
        
        @return float: angle (in degree) of the rotor.
        """
        try:
            pos = self._rotor.get_pos()
        except:
            pos = -1
        self.sigGotPosition.emit(pos)
        return pos

    def emit_rotor_pos(self):
        """Emits the current position of the rotor (in deg).
        """
        pos = self.get_rotor_pos()
        self.sigGotPosition.emit(pos)
        return

    def set_rotor_pos(self,angle):
        """Makes the rotor rotate to a set position (angle).
        
        @param float angle: target angle of the rotor.
        """
        self._rotor.move_abs(angle)
        return

    def rotate_rel(self,angle):
        """Rotates the rotor by a certain angle.
        
        @param float angle: angle (in degree) of the relative rotation.
        """
        self._rotor.move_rel(angle)
        return

    def get_jog_size(self):
        """Gets the jog step size in degree.

        Sometimes this funtion produces an Value Error. This error is not persistent.
        Run it a second time and all should be good.
        """
        try:
            size = self._rotor.get_jog_size()
        except:
            size=-1
        return size

    def emit_jog_size(self):
        """Emits the current jog step size of the rotor in degree.
        """
        size = self.get_jog_size()
        self.sigGotStepSize.emit(size)
        return

    def set_jog_size(self,angle):
        """Sets the jog step size in degrees.
        """
        self._rotor.set_jog_size(angle)
        return

    def jog_rotor(self,forward=True):
        """Jogs the rotor by the specified angle.
        """
        if forward:
            self._rotor.move_forward()
        else:
            self._rotor.move_backward()
        return