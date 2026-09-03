# -*- coding: utf-8 -*-
"""
Logic module for the CRC (Charge Resonance Check) STM32 controller.

ON/OFF is implemented by setting kick = 0 (OFF) or kick = <configured value> (ON).
This requires no special firmware command and works reliably on any STM32 CRC firmware
that supports the K command.

Example config:

crc_logic:
    module.Class: 'crc_logic.CRCLogic'
    connect:
        crc: 'stm32_crc'
"""

from PySide2 import QtCore

from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar


class CRCLogic(LogicBase):
    """Logic layer between the CRC STM32 hardware and the GUI.

    Enabling/disabling works by sending K0 (disabled) or K<kick> (enabled).
    No special E/D firmware command is required.
    """

    _crc = Connector(name='crc', interface='STM32CRC')

    # Persist last-known parameters across restarts
    _threshold = StatusVar('threshold', default=1)
    _kick      = StatusVar('kick',      default=10)
    _interval  = StatusVar('interval',  default=500)
    _enabled   = StatusVar('enabled',   default=False)

    # Signals
    sigStatusUpdated    = QtCore.Signal(object)   # dict with full state → GUI

    def on_activate(self):
        self._hw = self._crc()
        # Push saved parameters to hardware
        # Threshold: 0 if disabled. Since CRC triggers when counts < threshold, 
        # 0 ensures it never triggers.
        self._hw.set_threshold(self._threshold if self._enabled else 0)
        self._hw.set_interval(self._interval)
        # Kick: 0 if disabled, configured value if enabled
        self._hw.set_kick(self._kick if self._enabled else 0)
        self._emit_status()

    def on_deactivate(self):
        pass  # serial port managed by hardware module

    # ------------------------------------------------------------------
    # Slots called from GUI via queued signals
    # ------------------------------------------------------------------

    @QtCore.Slot(bool)
    def set_enabled(self, enabled: bool):
        """Enable/disable CRC by setting kick to 0 and threshold high (OFF) or restoring them (ON)."""
        self._enabled = bool(enabled)
        kick_to_send = self._kick if self._enabled else 0
        thresh_to_send = self._threshold if self._enabled else 0
        
        # Always set threshold high first if disabling, or restore kick first if enabling
        if not self._enabled:
            self._hw.set_threshold(thresh_to_send)
            self._hw.set_kick(kick_to_send)
        else:
            self._hw.set_kick(kick_to_send)
            self._hw.set_threshold(thresh_to_send)
            
        self.log.info(
            f"CRC {'enabled' if self._enabled else 'disabled'} "
            f"(kick sent: {kick_to_send} µs, threshold sent: {thresh_to_send})"
        )
        self._emit_status()

    @QtCore.Slot(int, int, int)
    def apply_parameters(self, threshold: int, kick: int, interval: int):
        """Apply all three parameters atomically (GUI Apply button)."""
        self._threshold = int(threshold)
        self._kick      = int(kick)
        self._interval  = int(interval)
        self._hw.set_interval(self._interval)
        
        # Only send the configured kick/threshold if currently enabled
        kick_to_send = self._kick if self._enabled else 0
        thresh_to_send = self._threshold if self._enabled else 0
        
        self._hw.set_threshold(thresh_to_send)
        self._hw.set_kick(kick_to_send)
        
        self.log.info(
            f"CRC parameters applied: threshold={self._threshold}, "
            f"kick={self._kick} µs, interval={self._interval} µs"
        )
        self._emit_status()

    @QtCore.Slot()
    def request_status(self):
        """Re-emit the current status (GUI refresh)."""
        self._emit_status()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _emit_status(self):
        self.sigStatusUpdated.emit({
            'enabled':   self._enabled,
            'threshold': self._threshold,
            'kick':      self._kick,
            'interval':  self._interval,
        })
