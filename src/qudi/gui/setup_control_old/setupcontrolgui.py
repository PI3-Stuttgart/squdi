# -*- coding: utf-8 -*-

"""
This file contains a gui for the setupcontroll.

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

import numpy as np
import os
import pyqtgraph as pg
import time
from PySide2 import QtWidgets, QtCore
from qudi.core.connector import Connector
from qudi.core.module import GuiBase
# from interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from qtpy import uic


class SetupControlWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'setup_control.ui')

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)
        self.show()

class SetupControlGUI(GuiBase):

    ## declare connectors
    setupcontrollogic = Connector(interface='SetupControlLogicQINU')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
    
    def on_activate(self):
        """ Definition and initialisation of the GUI plus staring the measurement.
        """

        self._setupcontrol_logic = self.setupcontrollogic() 

        #####################
        # Configuring the dock widgets
        # Use the inherited class 'CounterMainWindow' to create the GUI window
        self._mw = SetupControlWindow()
        # Setup dock widgets
        self._mw.setDockNestingEnabled(True)
        self.updateButtonsEnabled()

        self._mw.Lamp_Button.setCheckable(True)
        self._mw.Green_Button.setCheckable(True)
        self._mw.Flipmirror_Button.setCheckable(True)

        self._mw.Green_Button.clicked.connect(self.green_laser_button_pressed)
        self._mw.Lamp_Button.clicked.connect(self.lamp_button_pressed)
        self._mw.green_attenuation.valueChanged.connect(self.green_power_slider_moved)

        self._mw.Flipmirror_Button.clicked.connect(self.flip_powermeter_button_pressed)


    def toggle_switch(self, button, color='rgb(61, 142, 201)'):
        if button.isChecked():
            button.setStyleSheet(f"background-color : {color}")
        else:
            button.setStyleSheet("background-color : transparent")

    def on_deactivate(self):
        """ Deactivate the module properly.
        """
        self._mw.Lamp_Button.clicked.disconnect()
        self._mw.Green_Button.clicked.disconnect()
        self._mw.Flipmirror_Button.clicked.disconnect()
        self._mw.green_attenuation.valueChanged.disconnect()

    def green_power_slider_moved(self, power):
        self._setupcontrol_logic.set_green_power(power)

    def green_laser_button_pressed(self, active):
        self._setupcontrol_logic.activate_green_laser(active)
        self.toggle_switch(self._mw.Green_Button, color='rgb(31, 255, 0)')

    def lamp_button_pressed(self, active):
        self._setupcontrol_logic.activate_lamp(active)
        self.toggle_switch(self._mw.Lamp_Button, color='rgb(130, 0, 200)')

    def flip_powermeter_button_pressed(self, active):
        self._setupcontrol_logic.flip_powermeter(active)
        self.toggle_switch(self._mw.Flipmirror_Button)

    def show(self):
        """Make window visible and put it above all other windows.
        """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()
    
    def restoreDefaultView(self):
        """ Restore the arrangement of DockWidgets to the default
        """
        # Show any hidden dock widgets
        self._mw.adjustDockWidget.show()
        self._mw.plotDockWidget.show()

        # re-dock any floating dock widgets
        self._mw.adjustDockWidget.setFloating(False)
        self._mw.plotDockWidget.setFloating(False)

        # Arrange docks widgets
        self._mw.addDockWidget(QtCore.Qt.DockWidgetArea(1), self._mw.adjustDockWidget)
        self._mw.addDockWidget(QtCore.Qt.DockWidgetArea(2), self._mw.plotDockWidget)
    

    @QtCore.Slot()
    def updateButtonsEnabled(self):
        print('test')
        # """ Logic told us to update our button states, so set the buttons accordingly. """

        # self._mw.laserButton.setEnabled(self._laser_logic.laser_can_turn_on)
        # if self._laser_logic.laser_state == LaserState.ON:
        #     self._mw.laserButton.setText('Laser: ON')
        #     self._mw.laserButton.setChecked(True)
        #     self._mw.laserButton.setStyleSheet('')
        # elif self._laser_logic.laser_state == LaserState.OFF:
        #     self._mw.laserButton.setText('Laser: OFF')
        #     self._mw.laserButton.setChecked(False)
        # elif self._laser_logic.laser_state == LaserState.LOCKED:
        #     self._mw.laserButton.setText('INTERLOCK')
        # else:
        #     self._mw.laserButton.setText('Laser: ?')

        # self._mw.shutterButton.setEnabled(self._laser_logic.has_shutter)
        # if self._laser_logic.laser_shutter == ShutterState.OPEN:
        #     self._mw.shutterButton.setText('Shutter: OPEN')
        # elif self._laser_logic.laser_shutter == ShutterState.CLOSED:
        #     self._mw.shutterButton.setText('Shutter: CLOSED')
        # elif self._laser_logic.laser_shutter == ShutterState.NOSHUTTER:
        #     self._mw.shutterButton.setText('No shutter.')
        # else:
        #     self._mw.shutterButton.setText('Shutter: ?')

        # self._mw.currentRadioButton.setEnabled(self._laser_logic.laser_can_current)
        # self._mw.powerRadioButton.setEnabled(self._laser_logic.laser_can_power)


# TODO: Remove POIs button
# "scannerlogic.pois = np.array([])"

# TODO: Start automized measurement
# "automationlogic.start()"