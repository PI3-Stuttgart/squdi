# -*- coding: utf-8 -*-
"""
This file contains the qudi switch GUI module.

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

from enum import IntEnum
from PySide2 import QtWidgets, QtCore, QtGui

from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.module import GuiBase
from qudi.core.configoption import ConfigOption
from qudi.gui.switch.switch_gui import SwitchGui

from .switch_state_widgets import SwitchRadioButtonWidget, ToggleSwitchWidget


class SwitchStyle(IntEnum):
    TOGGLE_SWITCH = 0
    RADIO_BUTTON = 1


class StateColorScheme(IntEnum):
    DEFAULT = 0
    HIGHLIGHT = 1


class SetupControlMainWindow(QtWidgets.QMainWindow):
    """Main Window for the setup control"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("qudi: Setup Control QINU")
        # Create main layout and central widget
        self.main_layout = QtWidgets.QGridLayout()
        widget = QtWidgets.QWidget()
        widget.setLayout(self.main_layout)
        self.setCentralWidget(widget)
        self.setDockNestingEnabled(True)


class SetupControlGui(GuiBase):
    """
    A graphical interface to switch a hardware by hand.

    Example config for copy-paste:

    SetupControl_gui:
        module.Class: 'setup_control.setup_control.SetupControlGui'
        options:
            switch_gui: 'switchgui'
            ao_gui: ''
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mw = SetupControlMainWindow()
        self.switch_gui = SwitchGui()

        # switch gui
        switch_dock = QtWidgets.QDockWidget("Switch GUI", self._mw)
        switch_dock.setWidget(self.switch_gui()._widgets)
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, switch_dock)

    def on_activate(self) -> None:
        print(self._mw)
        self.show()

    def on_deactivate(self) -> None:
        pass

    def show(self) -> None:
        """Make sure that the window is visible and at the top."""
        self._mw.show()
