# -*- coding: utf-8 -*-
from PySide2 import QtCore
import numpy as np

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.util.mutex import RecursiveMutex


class PPG512Logic(LogicBase):
    """
    Logic module for the PicoQuant PPG512 hardware.
    
    ppg512_logic:
        module.Class: 'ppg512_logic.PPG512Logic'
        connect:
            hardware: 'picoquant_ppg512'
    """
    
    hardware = Connector(interface='PPG512')
    
    sigVrefChanged = QtCore.Signal(float)
    sigVccrfChanged = QtCore.Signal(float)
    sigWaveformWritten = QtCore.Signal()
    sigStandbyToggled = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_lock = RecursiveMutex()
        self._standby_active = False
        self._saved_state = {'vref': 400, 'vccrf': 15000, 'waveform': np.zeros(512)}

    def on_activate(self):
        pass

    def on_deactivate(self):
        # Safety fallback
        if not self._standby_active:
            self.toggle_standby(True)

    @QtCore.Slot(float)
    def set_vref(self, vref):
        with self._thread_lock:
            self._saved_state['vref'] = vref
            if not self._standby_active:
                self.hardware().set_vref(vref)
            self.sigVrefChanged.emit(vref)

    @QtCore.Slot()
    def get_vref(self):
        with self._thread_lock:
            if self._standby_active:
                return self._saved_state['vref']
            return self.hardware().get_vref()

    @QtCore.Slot(float)
    def set_vccrf(self, vccrf):
        with self._thread_lock:
            self._saved_state['vccrf'] = vccrf
            if not self._standby_active:
                self.hardware().set_vccrf(vccrf)
            self.sigVccrfChanged.emit(vccrf)

    @QtCore.Slot()
    def get_vccrf(self):
        with self._thread_lock:
            if self._standby_active:
                return self._saved_state['vccrf']
            return self.hardware().get_vccrf()

    @QtCore.Slot(bool)
    def toggle_standby(self, enable):
        with self._thread_lock:
            if self._standby_active == enable:
                return
            self._standby_active = enable
            if enable:
                self.hardware().set_vccrf(12000)
                self.hardware().set_vref(0)
                self.hardware().constant_output()
                self.log.info("Entered Standby Mode.")
            else:
                self.hardware().set_vccrf(self._saved_state['vccrf'])
                self.hardware().set_vref(self._saved_state['vref'])
                if self._saved_state['waveform'] is not None:
                    self.hardware().write_waveform_from_array(self._saved_state['waveform'])
                self.log.info("Exited Standby Mode.")
            self.sigStandbyToggled.emit(enable)

    def create_and_write_waveform(self, shape, **kwargs):
        with self._thread_lock:
            wg = self.hardware().wg
            voltages = None
            if shape == 'square': voltages = wg.create_square(**kwargs)
            elif shape == 'gauss': voltages = wg.create_gauss(**kwargs)
            elif shape == 'train': voltages = wg.create_gaussian_train(**kwargs)
            elif shape == 'pulses': voltages = wg.create_pulses(**kwargs)
            elif shape == 'ramp': voltages = wg.create_ramp(**kwargs)
            elif shape == 'triangle': voltages = wg.create_triangle(**kwargs)
            elif shape == 'sine': voltages = wg.create_sine(**kwargs)
            elif shape == 'zero': voltages = wg.create_zero()
            else:
                self.log.error(f"Unknown waveform shape: {shape}")
                return None

            self._saved_state['waveform'] = voltages
            if not self._standby_active:
                self.hardware().write_waveform_from_array(voltages)
            self.sigWaveformWritten.emit()
            return voltages

    def write_custom_waveform(self, voltages):
        with self._thread_lock:
            self._saved_state['waveform'] = voltages
            ans = None
            if not self._standby_active:
                ans = self.hardware().write_waveform_from_array(voltages)
            self.sigWaveformWritten.emit()
            return ans

    def save_waveform_to_file(self, voltages, fname):
        with self._thread_lock:
            self.hardware().wg.create_a_waveform_file(voltages, fname)

    def load_waveform_from_file(self, fname):
        with self._thread_lock:
            voltages = self.hardware().wg.get_waveform_from_file(fname)
            return voltages
