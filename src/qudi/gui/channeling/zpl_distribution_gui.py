# -*- coding: utf-8 -*-
"""
GUI module for ZPL distribution measurement.
"""

from qtpy import QtWidgets, QtCore
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from qudi.core.module import GuiBase
from qudi.core.connector import Connector

class ZPLDistributionGui(GuiBase):
    """
    GUI Class for ZPL Distribution.
    """
    
    _logic = Connector(name='logic', interface='ZPLDistributionLogic')

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self._mw = QtWidgets.QWidget()
        self._mw.setWindowTitle('ZPL Distribution')
        self._init_ui()

    def on_activate(self):
        self._logic().sigUpdatePlot.connect(self.update_plot)
        self._logic().sigMeasurementFinished.connect(self.on_finished)
        
    def on_deactivate(self):
        self._logic().sigUpdatePlot.disconnect(self.update_plot)
        self._logic().sigMeasurementFinished.disconnect(self.on_finished)

    def show(self):
        """Make the window visible."""
        if self._mw:
            self._mw.show()
            self._mw.raise_()

    def _init_ui(self):
        # Main Layout
        layout = QtWidgets.QVBoxLayout()
        self._mw.setLayout(layout)

        # Controls
        control_layout = QtWidgets.QHBoxLayout()
        
        self.start_spin = QtWidgets.QDoubleSpinBox()
        self.start_spin.setPrefix("Start: ")
        self.start_spin.setSuffix(" V")
        self.start_spin.setRange(0, 150)
        self.start_spin.setValue(0)
        
        self.stop_spin = QtWidgets.QDoubleSpinBox()
        self.stop_spin.setPrefix("Stop: ")
        self.stop_spin.setSuffix(" V")
        self.stop_spin.setRange(0, 150)
        self.stop_spin.setValue(100)
        
        self.step_spin = QtWidgets.QDoubleSpinBox()
        self.step_spin.setPrefix("Step: ")
        self.step_spin.setSuffix(" V")
        self.step_spin.setRange(0.001, 100)
        self.step_spin.setValue(5)
        
        self.start_btn = QtWidgets.QPushButton("Start Measurement")
        self.start_btn.clicked.connect(self.start_measurement)
        
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_measurement)
        self.stop_btn.setEnabled(False)

        control_layout.addWidget(self.start_spin)
        control_layout.addWidget(self.stop_spin)
        control_layout.addWidget(self.step_spin)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        
        layout.addLayout(control_layout)
        
        # Plot
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Number of Spots")
        self.ax.set_title("ZPL Distribution")
        
        layout.addWidget(self.canvas)
        
        # Progress
        self.status_label = QtWidgets.QLabel("Status: Idle")
        layout.addWidget(self.status_label)

    def start_measurement(self):
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        step = self.step_spin.value()
        
        self._logic().start_measurement(start, stop, step)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Status: Running...")

    def stop_measurement(self):
        self._logic().stop_measurement()
        self.status_label.setText("Status: Stopping...")

    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Finished")

    def update_plot(self, data):
        self.ax.clear()
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Number of Spots")
        self.ax.set_title("ZPL Distribution")
        
        if len(data['voltage']) > 0:
            self.ax.bar(data['voltage'], data['counts'], width=self.step_spin.value()*0.8)
            
        self.canvas.draw()
