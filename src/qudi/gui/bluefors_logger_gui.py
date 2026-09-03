# -*- coding: utf-8 -*-
"""
GUI module for controlling the Bluefors API logger.
"""

from PySide2 import QtWidgets, QtCore
import json

from qudi.core.module import GuiBase
from qudi.core.connector import Connector

class BlueforsLoggerWindow(QtWidgets.QWidget):
    def __init__(self, logic_module, parent=None):
        super().__init__(parent)
        self.setWindowTitle("qudi: Bluefors Logger")
        self._logic = logic_module
        
        layout = QtWidgets.QVBoxLayout()
        
        self.toggle_button = QtWidgets.QPushButton("Start Logging")
        self.toggle_button.clicked.connect(self._toggle_logging)
        layout.addWidget(self.toggle_button)
        
        self.status_label = QtWidgets.QLabel("Status: Not Logging")
        layout.addWidget(self.status_label)
        
        self.data_display = QtWidgets.QTextEdit()
        self.data_display.setReadOnly(True)
        layout.addWidget(self.data_display)
        
        self.setLayout(layout)

        # Connect signals
        if self._logic:
            self._logic.sig_logging_changed.connect(self._update_button_state)
            self._logic.sig_latest_data.connect(self._update_data_display)
            self._update_button_state(self._logic.is_logging)
            self._update_data_display(self._logic.latest_data)

    def closeEvent(self, event):
        if self._logic:
            self._logic.sig_logging_changed.disconnect(self._update_button_state)
            self._logic.sig_latest_data.disconnect(self._update_data_display)
        super().closeEvent(event)

    @QtCore.Slot()
    def _toggle_logging(self):
        if not self._logic:
            return
        if self._logic.is_logging:
            self._logic.stop_logging()
        else:
            self._logic.start_logging()

    @QtCore.Slot(bool)
    def _update_button_state(self, is_logging):
        if is_logging:
            self.toggle_button.setText("Stop Logging")
            self.status_label.setText("Status: Logging")
        else:
            self.toggle_button.setText("Start Logging")
            self.status_label.setText("Status: Not Logging")

    @QtCore.Slot(dict)
    def _update_data_display(self, data):
        text = "Latest Data:\n"
        for k, v in data.items():
            text += f"{k}: {v}\n"
        self.data_display.setText(text)


class BlueforsLoggerGui(GuiBase):
    """
    GUI to start/stop the Bluefors logger and display the latest readings.
    """
    
    logic = Connector(interface='BlueforsLoggerLogic')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._mw = None

    def on_activate(self):
        self._mw = BlueforsLoggerWindow(self.logic())
        self.show()

    def on_deactivate(self):
        if self._mw:
            self._mw.close()
            self._mw = None

    def show(self):
        if self._mw:
            self._mw.show()
