# -*- coding: utf-8 -*-
"""
Hardware module for controlling a Charge Resonance Check (CRC) STM32 microcontroller over Serial.
"""

import serial
import time
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption

class STM32CRC(Base):
    """
    Control an STM32 device via serial to manage CRC (Charge Resonance Check) thresholds,
    kick parameters, and intervals.
    """
    
    _port = ConfigOption('port', default='COM8', missing='warn')
    _baudrate = ConfigOption('baudrate', default=115200, missing='warn')
    _timeout = ConfigOption('timeout', default=1.0, missing='warn')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._serial = None
        self._threshold = 1
        self._kick = 150
        self._interval = 2000
        self._enabled = False

    def on_activate(self):
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout
            )
            self.log.info(f"Connected to STM32 CRC at {self._port} ({self._baudrate} baud).")
            # Set default values from internal state
            self.set_threshold(self._threshold)
            self.set_kick(self._kick)
            self.set_interval(self._interval)
            
            # Flush input buffer just in case
            time.sleep(0.1)
            if self._serial.in_waiting:
                self._serial.reset_input_buffer()
        except serial.SerialException as err:
            self.log.error(f"Failed to open Serial port {self._port}: {err}")
            raise

    def on_deactivate(self):
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            self._serial = None
            self.log.info(f"Disconnected from STM32 CRC.")

    def _send_command(self, command_char, value):
        """Helper to send a command and read the reply."""
        if self._serial is None or not self._serial.is_open:
            self.log.warning("Serial connection is not active.")
            return None

        command_str = f"{command_char}{int(value)}\n"
        self._serial.write(command_str.encode('utf-8'))
        
        # Wait a tiny bit for the STM32 to reply
        time.sleep(0.1)
        
        response = ""
        while self._serial.in_waiting:
            reply = self._serial.readline().decode('utf-8', errors='ignore').strip()
            if reply:
                response = reply
                self.log.debug(f"STM32 Replied: {reply}")
        return response

    def set_threshold(self, value):
        """Set the CRC photon count threshold."""
        self._threshold = int(value)
        self._send_command('T', self._threshold)

    def set_kick(self, value):
        """Set the CRC kick parameter length."""
        self._kick = int(value)
        self._send_command('K', self._kick)

    def set_interval(self, value):
        """Set the CRC interval."""
        self._interval = int(value)
        self._send_command('I', self._interval)

    @property
    def crc_enabled(self):
        return self._enabled

    @crc_enabled.setter
    def crc_enabled(self, state):
        self._enabled = bool(state)

    @property
    def threshold(self):
        return self._threshold

    @property
    def kick(self):
        return self._kick

    @property
    def interval(self):
        return self._interval
