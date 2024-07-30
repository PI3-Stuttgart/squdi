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


class AOMainWindow(QtWidgets.QMainWindow):
    """Main Window for the SwitchGui module"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("qudi: AO controller")
        # Create main layout and central widget
        self.main_layout = QtWidgets.QGridLayout()
        widget = QtWidgets.QWidget()
        widget.setLayout(self.main_layout)
        self.setCentralWidget(widget)

        # Create QActions and menu bar
        menu_bar = QtWidgets.QMenuBar()
        self.setMenuBar(menu_bar)

        menu = menu_bar.addMenu("Menu")
        self.action_close = QtWidgets.QAction("Close Window")
        self.action_close.setCheckable(False)
        self.action_close.setIcon(QtGui.QIcon("artwork/icons/application-exit.svg"))
        self.addAction(self.action_close)
        menu.addAction(self.action_close)

        menu = menu_bar.addMenu("View")
        self.action_periodic_state_check = QtWidgets.QAction("Periodic State Checking")
        self.action_periodic_state_check.setCheckable(True)
        menu.addAction(self.action_periodic_state_check)
        # close window upon triggering close action
        self.action_close.triggered.connect(self.close)
        return


class AOGui(GuiBase):
    """
    A graphical interface to switch a hardware by hand.

    Example config for copy-paste:

        AO_gui:
        module.Class: 'AO.AO_gui.AOGui'
        connect:
            AOlogic: 'AOlogic'

    """

    # declare connectors
    aologic = Connector(interface="AOLogic")

    # declare config options
    _slider_row_num_max = ConfigOption(name="_slider_row_num_max", default=None)
    _nr_slider_positions = 1000
    default_unit: str = "V"

    # declare signals
    sigSetpointChanged = QtCore.Signal(str, float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._widgets = dict()

    def on_activate(self):
        """Create all UI objects and show the window."""
        self._mw = AOMainWindow()

        self._populate_sliders()

        self.sigSetpointChanged.connect(
            self.aologic().set_setpoint, QtCore.Qt.QueuedConnection
        )
        self._mw.action_periodic_state_check.toggled.connect(
            self.aologic().toggle_watchdog, QtCore.Qt.QueuedConnection
        )
        self.aologic().sigWatchdogToggled.connect(
            self._watchdog_updated, QtCore.Qt.QueuedConnection
        )
        self.aologic().sigSetpointsChanged.connect(
            self._sliders_updated, QtCore.Qt.QueuedConnection
        )

        self._restore_window_geometry(self._mw)

        self._watchdog_updated(self.aologic().watchdog_active)
        self._sliders_updated(self.aologic().setpoints)
        self.show()

    def on_deactivate(self):
        """Hide window empty the GUI and disconnect signals"""
        self.aologic().sigSwitchesChanged.disconnect(self._sliders_updated)
        self.aologic().sigWatchdogToggled.disconnect(self._watchdog_updated)
        self._mw.action_view_highlight_state.triggered.disconnect()
        self._mw.action_view_alt_toggle_style.triggered.disconnect()
        self._mw.switch_view_action_group.triggered.disconnect()
        self._mw.action_periodic_state_check.toggled.disconnect()
        self.sigSetpointChanged.disconnect()

        self._save_window_geometry(self._mw)
        self._delete_switches()
        self._mw.close()

    def show(self):
        """Make sure that the window is visible and at the top."""
        self._mw.show()

    def _populate_sliders(self):
        """Dynamically build the gui"""
        self._widgets = dict()
        for ii, (channel, _) in enumerate(self.aologic().setpoints.items()):
            label: QtWidgets.QLabel = self._get_channel_label(channel)

            if self._slider_row_num_max is None:
                grid_pos = [ii, 0]
            else:
                grid_pos = [
                    int(ii % self._slider_row_num_max),
                    int(ii / self._slider_row_num_max) * 2,
                ]

            if self.aologic().use_conversion(channel):
                value_range = self.aologic().ao_parameters[channel]["conv_bounds"]
            else:
                value_range = self.aologic().constraints.channel_limits[channel]

            _curr_widget = QSliderWithSpinBox(value_range)

            self._widgets[channel] = (label, _curr_widget)
            self._mw.main_layout.addWidget(
                self._widgets[channel][0], grid_pos[0], grid_pos[1]
            )
            self._mw.main_layout.addWidget(_curr_widget, grid_pos[0], grid_pos[1] + 1)
            self._mw.main_layout.setColumnStretch(grid_pos[1], 0)
            self._mw.main_layout.setColumnStretch(grid_pos[1] + 1, 1)
            # Connect the correct function to update the analog output of a defined channel
            _curr_widget.sigValueChanged.connect(
                self.__get_setpoint_update_func(channel)
            )

    def _get_channel_label(self, channel: str) -> QtWidgets.QLabel:
        """Helper function to create a QLabel for a single switch.

        @param str switch: The name of the switch to create the label for
        @return QWidget: QLabel with switch name
        """

        if self.aologic().use_unit(channel):
            unit: str = self.aologic().ao_parameters[channel]["unit"]
        else:
            unit = self.default_unit

        label = QtWidgets.QLabel(f"{channel} [{unit}]:")
        font: QtGui.QFont = label.font()
        font.setBold(True)
        font.setPointSize(11)
        label.setFont(font)
        label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        label.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred
        )
        return label

    def _delete_sliders(self):
        """Delete all the buttons from the main layout."""
        self._widgets.clear()
        while True:
            item = self._mw.main_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            try:
                widget.sigStateChanged.disconnect()
            except AttributeError:
                pass
            widget.setParent(None)
            widget.deleteLater()

    @QtCore.Slot(dict)
    def _sliders_updated(self, setpoints):
        """Helper function to update the GUI on a change of the states in the logic.
        This function is connected to the signal coming from the switchlogic signaling a change in states.
        @param dict states: The state dict of the form {"switch": "state"}
        @return: None
        """
        for channel, setpoint in setpoints.items():
            self._widgets[channel][1].set_value(setpoint)

    @QtCore.Slot(bool)
    def _watchdog_updated(self, enabled):
        """Update the menu action accordingly if the watchdog has been (de-)activated.

        @param bool enabled: Watchdog active (True) or inactive (False)
        """
        if enabled != self._mw.action_periodic_state_check.isChecked():
            self._mw.action_periodic_state_check.blockSignals(True)
            self._mw.action_periodic_state_check.setChecked(enabled)
            self._mw.action_periodic_state_check.blockSignals(False)

    def __get_setpoint_update_func(self, channel):
        def update_func(setpoint: float):
            self.sigSetpointChanged.emit(channel, float(setpoint))

        return update_func


class QSliderWithSpinBox(QtWidgets.QWidget):
    """
    A custom widget combining a QSlider and a QDoubleSpinBox that syncs their values.

    Attributes:
        unit (str): The unit of measurement (default is 'V').
        slider (QtWidgets.QSlider): The slider widget for integer values.
        spin_box (QtWidgets.QDoubleSpinBox): The spin box widget for float values.

    Signals:
        sigStateChanged(float): Emitted when the value changes in either the slider or the spin box.
    """

    sigValueChanged = QtCore.Signal(float)

    def __init__(
        self,
        value_range: tuple[float, float],
        num_slider_points: int = int(1e3),
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """
        Initialize the SliderWithSpinBox widget.

        Args:
            value_range (tuple[float, float]): Min and Max value for value range of spinbox
            parent (QtWidgets.QWidget, optional): The parent widget. Defaults to None.
            num_slider_points (int, optional): The number of discrete points for the slider. Defaults to 100.
        """
        super().__init__(parent)

        self.value_range: tuple[float, float] = value_range
        self.num_slider_points: int = num_slider_points

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.slider.setRange(0, self.num_slider_points)
        self.slider.setSingleStep(1)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider.setTickInterval(1)

        self.spin_box = QtWidgets.QDoubleSpinBox(self)
        self.spin_box.setDecimals(2)
        self.spin_box.setRange(value_range[0], value_range[1])
        self.spin_box.setSingleStep(0.01)

        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self.slider)
        layout.addWidget(self.spin_box)
        self.setLayout(layout)

        self.slider.valueChanged.connect(self.slider_value_changed)
        self.spin_box.valueChanged.connect(self.spin_box_value_changed)

    def slider_value_changed(self, value: int) -> None:
        """Slot to handle changes in the slider's value."""
        float_value = self.slider_value_to_float(value)
        self.spin_box.setValue(float_value)
        self.sigValueChanged.emit(float_value)

    def spin_box_value_changed(self, value: float) -> None:
        """Slot to handle changes in the spin box's value."""
        slider_value = self.float_to_slider_value(value)
        self.slider.setValue(slider_value)
        self.sigValueChanged.emit(value)

    def slider_value_to_float(self, value: int) -> float:
        """Convert the slider's integer value to a float."""
        min_value, max_value = self.value_range
        float_range = max_value - min_value
        return (value / self.num_slider_points) * float_range + min_value

    def float_to_slider_value(self, value: float) -> int:
        """Convert a float value to the slider's integer scale."""
        min_value, max_value = self.value_range
        float_range: float = max_value - min_value
        return int((value - min_value) / float_range * self.num_slider_points)

    @property
    def value(self) -> float:
        """Get the current value from the spin box."""
        return self.spin_box.value()

    @value.setter
    def value(self, value: float) -> None:
        """Set the value for both the slider and the spin box."""
        self.set_value(value)

    @QtCore.Slot(str)
    def set_value(self, value: float) -> None:
        """Sets value of spinbox and slider"""
        print(f"slider set: {value}")
        slider_value: int = self.float_to_slider_value(value)
        self.slider.setValue(slider_value)
        self.spin_box.setValue(value)
