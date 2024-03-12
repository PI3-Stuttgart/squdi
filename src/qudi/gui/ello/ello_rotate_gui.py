"""
Gui module to control a Thorlabs Ello rotation devices.


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
    ellogui:
        module.Class: 'ello.ello_rotate_gui.ElloGui'
        connect:
            ellologic: 'ello_logic'

"""

import os
from qtpy import uic
from PySide2 import QtCore, QtWidgets

from qudi.core.module import GuiBase
from qudi.core.connector import Connector



class ElloMainWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ello_rotate_gui.ui')

        # Load it
        uic.loadUi(ui_file, self)


class ElloGui(GuiBase):
    # declare connectors
    ellologic = Connector(name='ellologic', interface='ElloLogic')

    # signals
    sigRotateAbs = QtCore.Signal(float)
    sigHome = QtCore.Signal()
    sigRotateRel = QtCore.Signal(float)
    sigJog = QtCore.Signal(bool) # True if forward, False if backward
    sigSetStepSize = QtCore.Signal(float)
    sigGetRotorPosition = QtCore.Signal()
    sigGetStepSize = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        # connector
        self._ellologic = self.ellologic()

        self._mw = ElloMainWindow()
        self.show()

        # connect buttons
        self._mw.get_position_pushButton.clicked.connect(self.get_rotor_position_clicked)
        self._mw.move_abs_pushButton.clicked.connect(self.move_abs_clicked)
        self._mw.home_pushButton.clicked.connect(self.home_clicked)
        self._mw.move_rel_pushButton.clicked.connect(self.move_rel_clicked)
        self._mw.jog_forward_pushButton.clicked.connect(self.jog_forward_clicked)
        self._mw.jog_backwards_pushButton.clicked.connect(self.jog_backward_clicked)
        self._mw.set_jog_step_size_pushButton.clicked.connect(self.set_jog_size_clicked)
        self._mw.get_jog_step_size_pushButton.clicked.connect(self.get_jog_size_clicked)

        # connect signals
        self.sigRotateAbs.connect(self._ellologic.set_rotor_pos)
        self.sigHome.connect(self._ellologic.home_rotor)
        self.sigRotateRel.connect(self._ellologic.rotate_rel)
        self.sigJog.connect(self._ellologic.jog_rotor)
        self.sigSetStepSize.connect(self._ellologic.set_jog_size)

        self.sigGetRotorPosition.connect(self._ellologic.emit_rotor_pos)
        self.sigGetStepSize.connect(self._ellologic.emit_jog_size)

        #connect external signals
        self._ellologic.sigGotPosition.connect(self.change_displayed_rotor_position)
        self._ellologic.sigGotStepSize.connect(self.change_displayed_step_size)

        # get values
        self.get_rotor_position_clicked()
        self.get_jog_size_clicked()
        return

    def on_deactivate(self):
        self._mw.close()
        return

    def show(self):
        """Make main window visible and put it above all other windows. """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()
        return

    def get_rotor_position_clicked(self):
        """Gets the rotor position.
        
        Emits signal to logic. Logic emits signal with value.
        This signal is connected to function below."""
        self.sigGetRotorPosition.emit()
        return

    def change_displayed_rotor_position(self,position):
        """Changes the displayed rotor position to the value given by posotion.
        """
        self._mw.position_doubleSpinBox.setValue(position)
        return

    def move_abs_clicked(self):
        angle = self._mw.move_abs_doubleSpinBox.value()
        self.sigRotateAbs.emit(angle)
        self.get_rotor_position_clicked()
        return

    def home_clicked(self):
        self.sigHome.emit()
        self.get_rotor_position_clicked()
        return

    def move_rel_clicked(self):
        angle = self._mw.move_rel_doubleSpinBox.value()
        self.sigRotateRel.emit(angle)
        self.get_rotor_position_clicked()
        return

    def jog_forward_clicked(self):
        self.sigJog.emit(True)
        self.get_rotor_position_clicked()
        return

    def jog_backward_clicked(self):
        self.sigJog.emit(False)
        self.get_rotor_position_clicked()
        return

    def set_jog_size_clicked(self):
        jog_size = self._mw.jog_step_size_doubleSpinBox.value()
        self.sigSetStepSize.emit(jog_size)
        return

    def get_jog_size_clicked(self):
        self.sigGetStepSize.emit()
        return
    
    def change_displayed_step_size(self,jog_size):
        self._mw.jog_step_size_doubleSpinBox.setValue(jog_size)
        return