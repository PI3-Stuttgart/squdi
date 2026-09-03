# -*- coding: utf-8 -*-
import os
import numpy as np
from PySide2 import QtCore, QtWidgets

from qudi.core.module import GuiBase
from qudi.core.connector import Connector

class PPG512Window(QtWidgets.QWidget):
    def __init__(self, logic_module, parent=None):
        super().__init__(parent)
        self.setWindowTitle("qudi: PPG512 Control")
        self._logic = logic_module
        
        self._current_waveform = np.zeros(512)

        layout = QtWidgets.QVBoxLayout()

        # Standby
        sb_group = QtWidgets.QGroupBox("Safety")
        sb_layout = QtWidgets.QHBoxLayout()
        self.btn_standby = QtWidgets.QPushButton("Enable Standby")
        self.btn_standby.setCheckable(True)
        self.btn_standby.setToolTip("Drops VREF/VCCRF and zeros output.")
        sb_layout.addWidget(self.btn_standby)
        sb_group.setLayout(sb_layout)
        layout.addWidget(sb_group)

        # Voltages
        volt_group = QtWidgets.QGroupBox("Voltages (mV)")
        v_layout = QtWidgets.QGridLayout()
        
        v_layout.addWidget(QtWidgets.QLabel("VREF (max 2000):"), 0, 0)
        self.vref_spin = QtWidgets.QDoubleSpinBox()
        self.vref_spin.setRange(0, 2000)
        self.vref_spin.setValue(400)
        v_layout.addWidget(self.vref_spin, 0, 1)
        self.btn_set_vref = QtWidgets.QPushButton("Set VREF")
        v_layout.addWidget(self.btn_set_vref, 0, 2)
        
        v_layout.addWidget(QtWidgets.QLabel("VCCRF (12000-24000):"), 1, 0)
        self.vccrf_spin = QtWidgets.QDoubleSpinBox()
        self.vccrf_spin.setRange(12000, 24000)
        self.vccrf_spin.setValue(15000)
        v_layout.addWidget(self.vccrf_spin, 1, 1)
        self.btn_set_vccrf = QtWidgets.QPushButton("Set VCCRF")
        v_layout.addWidget(self.btn_set_vccrf, 1, 2)
        
        volt_group.setLayout(v_layout)
        layout.addWidget(volt_group)

        # Waveforms
        wv_group = QtWidgets.QGroupBox("Waveform")
        w_layout = QtWidgets.QGridLayout()
        
        w_layout.addWidget(QtWidgets.QLabel("Shape:"), 0, 0)
        self.shape_combo = QtWidgets.QComboBox()
        self.shape_combo.addItems(["square", "gauss", "ramp", "triangle", "sine", "zero"])
        w_layout.addWidget(self.shape_combo, 0, 1)
        
        w_layout.addWidget(QtWidgets.QLabel("Param (length/width):"), 1, 0)
        self.param_spin = QtWidgets.QSpinBox()
        self.param_spin.setRange(1, 512)
        self.param_spin.setValue(50)
        w_layout.addWidget(self.param_spin, 1, 1)
        
        w_layout.addWidget(QtWidgets.QLabel("Amplitude:"), 2, 0)
        self.amp_spin = QtWidgets.QSpinBox()
        self.amp_spin.setRange(0, 255)
        self.amp_spin.setValue(255)
        w_layout.addWidget(self.amp_spin, 2, 1)

        self.btn_send_wv = QtWidgets.QPushButton("Generate && Send")
        w_layout.addWidget(self.btn_send_wv, 3, 0, 1, 2)
        
        wv_group.setLayout(w_layout)
        layout.addWidget(wv_group)

        # File I/O
        file_group = QtWidgets.QGroupBox("File I/O")
        f_layout = QtWidgets.QHBoxLayout()
        self.btn_save = QtWidgets.QPushButton("Save Current")
        self.btn_load = QtWidgets.QPushButton("Load && Send")
        f_layout.addWidget(self.btn_save)
        f_layout.addWidget(self.btn_load)
        file_group.setLayout(f_layout)
        layout.addWidget(file_group)

        self.setLayout(layout)

        # Connections
        self.btn_standby.toggled.connect(self._on_standby_toggled)
        self.btn_set_vref.clicked.connect(self._on_set_vref)
        self.btn_set_vccrf.clicked.connect(self._on_set_vccrf)
        self.btn_send_wv.clicked.connect(self._on_send_waveform)
        self.btn_save.clicked.connect(self._on_save_file)
        self.btn_load.clicked.connect(self._on_load_file)
        
        if self._logic:
            self._logic.sigVrefChanged.connect(self.vref_spin.setValue)
            self._logic.sigVccrfChanged.connect(self.vccrf_spin.setValue)
            self._logic.sigStandbyToggled.connect(self._update_standby_ui)

    @QtCore.Slot(bool)
    def _on_standby_toggled(self, checked):
        if self._logic:
            self._logic.toggle_standby(checked)

    @QtCore.Slot(bool)
    def _update_standby_ui(self, is_standby):
        self.btn_standby.setChecked(is_standby)
        self.btn_standby.setText("Disable Standby" if is_standby else "Enable Standby")
        self.btn_standby.setStyleSheet("background-color: orange; font-weight: bold;" if is_standby else "")
        
        # Disable controls when in standby
        self.vref_spin.setDisabled(is_standby)
        self.vccrf_spin.setDisabled(is_standby)
        self.btn_set_vref.setDisabled(is_standby)
        self.btn_set_vccrf.setDisabled(is_standby)
        self.shape_combo.setDisabled(is_standby)
        self.param_spin.setDisabled(is_standby)
        self.amp_spin.setDisabled(is_standby)
        self.btn_send_wv.setDisabled(is_standby)
        self.btn_load.setDisabled(is_standby)

    @QtCore.Slot()
    def _on_set_vref(self):
        if self._logic:
            self._logic.set_vref(self.vref_spin.value())

    @QtCore.Slot()
    def _on_set_vccrf(self):
        if self._logic:
            self._logic.set_vccrf(self.vccrf_spin.value())

    @QtCore.Slot()
    def _on_send_waveform(self):
        if not self._logic:
            return
        shape = self.shape_combo.currentText()
        param = self.param_spin.value()
        amp = self.amp_spin.value()
        
        kwargs = {'amp': amp}
        if shape in ('square', 'ramp'):
            kwargs['length'] = param
        elif shape in ('gauss',):
            kwargs['width'] = param
            
        voltages = self._logic.create_and_write_waveform(shape, **kwargs)
        if voltages is not None:
            self._current_waveform = voltages

    @QtCore.Slot()
    def _on_save_file(self):
        if not self._logic: return
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Waveform", "", "Text Files (*.txt);;All Files (*)")
        if fname:
            self._logic.save_waveform_to_file(self._current_waveform, fname)

    @QtCore.Slot()
    def _on_load_file(self):
        if not self._logic: return
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Waveform", "", "Text Files (*.txt);;All Files (*)")
        if fname:
            voltages = self._logic.load_waveform_from_file(fname)
            self._current_waveform = voltages
            self._logic.write_custom_waveform(voltages)

class PPG512Gui(GuiBase):
    """
    GUI for controlling the PPG512.
    
    ppg512_gui:
        module.Class: 'ppg512_gui.PPG512Gui'
        connect:
            logic: 'ppg512_logic'
    """
    
    logic = Connector(interface='PPG512Logic')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._mw = None

    def on_activate(self):
        self._mw = PPG512Window(self.logic())
        self.show()

    def on_deactivate(self):
        if self._mw:
            self._mw.close()
            self._mw = None

    def show(self):
        if self._mw:
            self._mw.show()
