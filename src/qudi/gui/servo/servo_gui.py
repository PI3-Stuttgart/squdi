# -*- coding: utf-8 -*-

"""
This file contains a GUI for the servo controller logic.

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

import os
from core.connector import Connector
from gui.guibase import GUIBase
from qtpy import QtCore
from qtpy import QtWidgets
from qtpy import uic


class ServoWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_servo.ui')

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)
        self.show()


class ServoGui(GUIBase):
    """ Main GUI for servo control """

    # declare connectors
    servo_logic = Connector(interface='servo_logic')

    # declare signals
    sigMoveServo = QtCore.Signal(str, float)  # servo_id, position
    sigChangeServo = QtCore.Signal(str)  # servo_id

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._last_update_time = 0
        self._update_interval = 50  # milliseconds between updates
        self._pending_move = None  # (servo_id, position)
        self._update_timer = QtCore.QTimer()
        self._update_timer.timeout.connect(self._process_pending_update)

    def on_activate(self):
        """ Definition and initialisation of the GUI plus starting the measurement.
        """
        self._servo_logic = self.servo_logic()

        # Use the inherited class 'ServoWindow' to create the GUI window
        self._mw = ServoWindow()
        
        # Set window size to be more compact
        self._mw.resize(400, 300)  # Width: 400px, Height: 300px
        
        # Set control dock widget size
        self._mw.controlDockWidget.setMinimumWidth(350)  # Make controls wider
        self._mw.controlDockWidget.setMinimumHeight(250)  # Make controls taller

        # Setup dock widgets
        self._mw.setDockNestingEnabled(True)
        self._mw.actionReset_View.triggered.connect(self.restoreDefaultView)

        # Connect signals
        self._mw.servoSelector.currentTextChanged.connect(self.change_servo)
        self._mw.positionSpinBox.editingFinished.connect(self.update_from_spinbox)
        self._mw.moveButton.clicked.connect(self.move_servo)
        self._mw.incrementButton.clicked.connect(self.increment_position)
        self._mw.decrementButton.clicked.connect(self.decrement_position)

        # Connect logic signals
        self.sigMoveServo.connect(self._servo_logic.move_servo_to)
        self.sigChangeServo.connect(self._servo_logic.change_servo_id)
        self._servo_logic.sigUpdate.connect(self.update_gui)

        # Start the update timer
        self._update_timer.start(self._update_interval)

        # Initial GUI update
        self.update_gui()

        # Read initial position after a short delay to ensure connection is established
        QtCore.QTimer.singleShot(1000, self.read_initial_position)

        # Set initial spinbox range for unlimited servo
        min_pos, max_pos = self._servo_logic.get_position_limits(self._servo_logic.servo_id)
        if min_pos is None or max_pos is None:
            self._mw.positionSpinBox.setRange(-1e9, 1e9)
        else:
            self._mw.positionSpinBox.setRange(min_pos, max_pos)

    def read_initial_position(self):
        """ Read and display the initial position of the servo """
        try:
            # Get current servo ID
            servo_id = self._servo_logic.servo_id
            
            # Read position from servo
            position = self._servo_logic.get_last_position()
            
            if position is not None:
                self.log.info(f"Initial position for servo {servo_id}: {position}")
                self._mw.positionSpinBox.setValue(float(position))
            else:
                self.log.warning(f"Could not read initial position for servo {servo_id}")
        except Exception as e:
            self.log.error(f"Error reading initial position: {str(e)}")

    def on_deactivate(self):
        """ Deactivate the module properly.
        """
        self._update_timer.stop()
        self._mw.close()

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
        self._mw.controlDockWidget.show()

        # re-dock any floating dock widgets
        self._mw.controlDockWidget.setFloating(False)

        # Arrange docks widgets
        self._mw.addDockWidget(QtCore.Qt.DockWidgetArea(1), self._mw.controlDockWidget)

    @QtCore.Slot(str)
    def change_servo(self, servo_name):
        """ Handle servo selection change """
        servo_id = '1' if "Servo 1" in servo_name else '2'
        self.sigChangeServo.emit(servo_id)
        min_pos, max_pos = self._servo_logic.get_position_limits(servo_id)
        if min_pos is None or max_pos is None:
            self._mw.positionSpinBox.setRange(-1e9, 1e9)
        else:
            self._mw.positionSpinBox.setRange(min_pos, max_pos)
        
        # Read position of newly selected servo
        position = self._servo_logic.get_last_position()
        if position is not None:
            self._mw.positionSpinBox.setValue(float(position))

    @QtCore.Slot()
    def update_from_spinbox(self):
        """ Update spinbox value """
        try:
            value = float(self._mw.positionSpinBox.value())
            # Don't move servo, just update the value
        except Exception as e:
            self.log.error(f"GUI: Error in update_from_spinbox: {str(e)}")

    def _schedule_move(self, servo_id, position):
        """ Schedule a move to the specified position """
        self._pending_move = (servo_id, position)

    def _process_pending_update(self):
        """ Process any pending position updates """
        if self._pending_move is not None:
            current_time = QtCore.QDateTime.currentMSecsSinceEpoch()
            if current_time - self._last_update_time >= self._update_interval:
                servo_id, position = self._pending_move
                self.move_servo_to_position(servo_id, position)
                self._last_update_time = current_time
                self._pending_move = None

    def move_servo_to_position(self, servo_id, position):
        """ Move servo to specified position """
        try:
            self.sigMoveServo.emit(servo_id, position)
        except Exception as e:
            self.log.error(f"GUI: Error in move_servo_to_position: {str(e)}")

    @QtCore.Slot()
    def move_servo(self):
        """ Move servo to selected position """
        try:
            position = float(self._mw.positionSpinBox.value())
            servo_id = self._servo_logic.servo_id
            self.move_servo_to_position(servo_id, position)
        except Exception as e:
            self.log.error(f"GUI: Error in move_servo: {str(e)}")

    @QtCore.Slot()
    def increment_position(self):
        """ Increment position by step size and move servo """
        try:
            current = float(self._mw.positionSpinBox.value())
            step = float(self._mw.stepSpinBox.value())
            new_position = current + step
            self._mw.positionSpinBox.setValue(new_position)
            self._schedule_move(self._servo_logic.servo_id, new_position)
        except Exception as e:
            self.log.error(f"GUI: Error in increment_position: {str(e)}")

    @QtCore.Slot()
    def decrement_position(self):
        """ Decrement position by step size and move servo """
        try:
            current = float(self._mw.positionSpinBox.value())
            step = float(self._mw.stepSpinBox.value())
            new_position = current - step
            self._mw.positionSpinBox.setValue(new_position)
            self._schedule_move(self._servo_logic.servo_id, new_position)
        except Exception as e:
            self.log.error(f"GUI: Error in decrement_position: {str(e)}")

    @QtCore.Slot()
    def update_gui(self):
        """ Update GUI elements with current values """
        try:
            # Update servo selector
            available_servos = self._servo_logic.get_available_servos()
            current_servo = self._servo_logic.servo_id
            
            # Update position display
            position = self._servo_logic.get_last_position()
            if position is not None:
                current_value = self._mw.positionSpinBox.value()
                
                # Only update the display if the servo has actually moved
                if abs(float(position) - current_value) > 0.1:  # Allow small floating point differences
                    self._mw.positionSpinBox.setValue(float(position))
            
            # Update status
            if self._servo_logic.servo.is_connected():
                self._mw.statusLabel.setText("Status: Connected")
                self._mw.statusLabel.setStyleSheet("color: green;")
            else:
                self._mw.statusLabel.setText("Status: Disconnected")
                self._mw.statusLabel.setStyleSheet("color: red;")
        except Exception as e:
            self.log.error(f"GUI: Error in update_gui: {str(e)}")
