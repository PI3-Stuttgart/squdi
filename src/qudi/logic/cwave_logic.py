# -*- coding: utf-8 -*
from collections import OrderedDict
import datetime
import matplotlib.pyplot as plt
import numpy as np
import time
from time import sleep
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.core.module import LogicBase
from qudi.hardware.cwave.cwave_api import PiezoChannel, StatusBit, PiezoMode, ExtRampMode, StepperChannel, Log, ShutterChannel
from PySide2 import QtCore

# from qudi.core.pi3_utils import delay
from time import sleep
import numpy as np

class CwaveLogic(LogicBase):
    """This logic module controls scans of DC voltage on the fourth analog
    output channel of the NI Card.  It collects countrate as a function of voltage.
    """
    # declare connectors
    cwavelaser = Connector(interface='CWave')
  
    queryInterval = ConfigOption('query_interval', 500)

    sig_update_gui = QtCore.Signal()
    sig_update_cwave_states = QtCore.Signal()
    sig_cwave_connected = QtCore.Signal()
    sig_pause_updates = QtCore.Signal(bool)
    sig_update_guiPanelPlots = QtCore.Signal()
    sig_update_guiPlotsRefInt = QtCore.Signal()
    sig_update_guiPlotsOpoReg = QtCore.Signal()
    sig_update_guiPlotsRefExt = QtCore.Signal()

    def __init__(self, **kwargs):
        """ Create CwaveScannerLogic object with connectors.
          @param dict kwargs: optional parameters
        """
        super().__init__(**kwargs)
        self.shutters = {channel.value: False for channel in ShutterChannel}
        self.pump_state = False
        self.reg_modes = {channel.value : PiezoMode.Manual for channel in PiezoChannel}
        self.status_cwave = {}#self._cwavelaser.get_dial_done()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._cwavelaser = self.cwavelaser()
        self.connected = self._cwavelaser._connected
        self.sig_pause_updates.connect(self.pause_updates)
        # self.connect_cwave()
        return 

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        try:
            self._cwavelaser.disconnect()
        except:
            print("Oi oi")
        for i in range(5):
            QtCore.QCoreApplication.processEvents()
        return 
    

    
    def connect_cwave(self):
        
        self._cwavelaser.connect()
        self.connected = self._cwavelaser._connected
        if self.connected:
            self.shutters = self._cwavelaser.get_shutters()
            self.cwave_log = self._cwavelaser.get_log()
            self.pump_state = None

            self.sig_update_cwave_states.connect(self.update_cwave_states)
            self.sig_update_cwave_states.emit()
            # Initialie data matrix
            # delay timer for querying laser
            self.queryTimer = QtCore.QTimer()
            self.queryTimer.setInterval(self.queryInterval)
            self.queryTimer.setSingleShot(True)
            self.queryTimer.timeout.connect(self.loop_body)#, QtCore.Qt.QueuedConnection)     
            self.queryTimer.start(self.queryInterval)
        
        self.sig_update_cwave_states.emit()
        self.sig_cwave_connected.emit()
        self.sig_update_gui.emit()

    # @thread_safety
    def save_data(self):
        print("here we save")


    @QtCore.Slot()
    def loop_body(self):
        self.sig_update_cwave_states.emit()
        qi = self.queryInterval
        self.queryTimer.start(qi)
        self.sig_update_gui.emit()

    #! Laser control panel:
    @QtCore.Slot(str)
    def optimize_cwave(self, opt_command):
        if opt_command == 'etalon':
            self._cwavelaser.optimize_etalon()
        elif opt_command == 'temp':
            self._cwavelaser.optimize_shg_temperature()
        else:
            self._cwavelaser.optimize_stop()

    def pump_switched(self, state):
        state = True if state != 0 else False
        self._cwavelaser.set_laser(state)

    @QtCore.Slot(str, bool)
    def change_shutter_state(self, shutter, state):
        # self._cwavelaser.shutters.update({shutter: state})
        self._cwavelaser.set_shutter(shutter, state)
        # self.shutters = self._cwavelaser.get_shutters()
        self.sig_update_gui.emit()

    @QtCore.Slot()
    def update_cwave_states(self):
        

        self.connected = self._cwavelaser._connected
        if self.connected:
            self.shutters = self._cwavelaser.get_shutters()
            self.cwave_log = self._cwavelaser.get_log()
            self.pump_state = self._cwavelaser.get_laser()

        for idx, channel in enumerate(PiezoChannel):
            if channel != PiezoChannel.Galvo:
                self.reg_modes[channel.value] = self._cwavelaser.get_piezo_mode(channel)

        for idx, bit in enumerate(StatusBit):
            self.status_cwave[bit.name] = self._cwavelaser.test_status_bits([
            bit
        ]) if bit != StatusBit.LaserEmission else not self._cwavelaser.test_status_bits([
            bit
        ]) 
        
        self.sig_update_gui.emit()
    
    @QtCore.Slot(int, int, int)
    def ramp_opo(self, duration, start, stop):
        self._cwavelaser.set_opo_extramp_settings(period_milliseconds = duration,
        mode = ExtRampMode.Triangle,
        lower_limit_percent = start,
        upper_limit_percent = stop)
        self._cwavelaser.set_piezo_mode(PiezoChannel.Opo, PiezoMode.ExtRamp)
        return 

    @QtCore.Slot(bool)
    def connection_cwave(self, connect):
        """ Connect to the cwave """
        
        if connect:
            self.connect_cwave()
            
            # self._cwavelaser.connect()
            # self.queryTimer.start(self.queryInterval)
        else:
            self.queryTimer.stop()
            self._cwavelaser.disconnect()
            
        self.connected = self._cwavelaser._connected
        self.sig_update_cwave_states.emit()
        self.sig_update_gui.emit()

    @QtCore.Slot(int)
    def adj_thick_etalon(self, adj):
        # print("here_we_go", adj)
        self._cwavelaser.etalon_move(adj)
        # sleep(2)
        # delay(2)

    @QtCore.Slot(int)
    def adj_opo_lambda(self, adj):
       
        self._cwavelaser.elements_move(adj)
        # sleep(5)
    
    def get_piezo_output(self, channel: PiezoChannel) -> int:
        output = self._cwavelaser.get_piezo_manual_output(channel)
        return output
    
    def set_piezo_output(self, channel: PiezoChannel, value: float) -> None:
        # if (channel in [PiezoChannel.Opo, PiezoChannel.Shg]):
     
        #     self._cwavelaser.set_piezo_mode(channel, PiezoMode.Manual)
        
            
        value = int(65535 * value / 10)
        
        if channel.name == PiezoChannel.Etalon.name:
            self._cwavelaser.set_etalon_offset(value)
        elif channel.name == PiezoChannel.Galvo:
            self._cwavelaser.set_galvo_position(value)
        else:
            self._cwavelaser.set_piezo_manual_output(channel, value)
    
    @QtCore.Slot(bool)
    def pause_updates(self, pause):
        print(pause)
        if pause:
            self.queryTimer.stop()
        else:
            
            self.queryTimer.start(self.queryInterval)

    @QtCore.Slot(object, object)
    def change_lock_mode(self, stage, mode): 
      
        self._cwavelaser.set_piezo_mode(stage, mode)
       
