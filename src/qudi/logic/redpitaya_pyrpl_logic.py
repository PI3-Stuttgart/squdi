import numpy as np
from PySide2 import QtCore
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.interface.redpitaya_interface import RedPitayaInterface


class RedPitayaPyrplLogic(LogicBase, RedPitayaInterface):
    """Logic module for Red Pitaya control using PyRPL."""

    # Connectors to hardware
    _redpitaya_hardware = Connector(name='redpitaya_hardware', interface='RedPitayaInterface')

    # Signals
    sigDataAcquired = QtCore.Signal(object, object, object)
    sigScopeStateChanged = QtCore.Signal(dict)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._redpitaya_hardware_instance = None

    def on_activate(self):
        self._redpitaya_hardware_instance = self._redpitaya_hardware()

    def on_deactivate(self):
        self._redpitaya_hardware_instance = None

    def setup_scope(self, input1=None, input2=None, trigger_source='ch1_positive_edge', 
                   trigger_level=0.0, trigger_hysteresis=0.01, trigger_delay=0,
                   decimation=64, average=False, **kwargs):
        """Configure the oscilloscope settings."""
        try:
            # Configure basic scope settings
            self._redpitaya_hardware().setup_scope(
                input1=input1, input2=input2, 
                trigger_source=trigger_source,
                trigger_level=trigger_level, 
                trigger_hysteresis=trigger_hysteresis,
                trigger_delay=trigger_delay, 
                decimation=decimation, 
                average=average
            )
            
            # Start rolling mode with 1 second buffer
            self._redpitaya_hardware().start_rolling_mode(1.0)
            
            # Emit updated scope state
            state = self.get_scope_status()
            self.sigScopeStateChanged.emit(state)
            
        except Exception as e:
            self.log.error(f"Error setting up scope: {e}")

    def get_scope_data(self, seconds):
        """Get data directly from hardware's get_last_seconds."""
        try:
            hw = self._redpitaya_hardware()
            if hw is None:
                return None, None, None
            
            return hw.get_last_seconds(float(seconds))
            
        except Exception as e:
            self.log.error(f"Error getting scope data: {e}")
            return None, None, None

    def get_voltage(self, channel):
        """Get current voltage on a channel.
        """
        if self._redpitaya_hardware_instance:
            return self._redpitaya_hardware_instance.get_voltage(channel)
        return 0.0

    def get_scope_status(self):
        """Get current scope status.
        """
        if self._redpitaya_hardware_instance:
            return self._redpitaya_hardware_instance.get_scope_status()
        return {}

    def get_histogram(self):
        """Get histogram data from hardware."""
        try:
            # Get 1 second of data from hardware
            return self._redpitaya_hardware().get_last_seconds(1.0)
        except Exception as e:
            self.log.error(f'Error getting histogram: {e}')
            return None, None, None
