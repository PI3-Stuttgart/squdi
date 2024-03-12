
import numpy as np
import os
import pyqtgraph as pg
import time

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
# from gui.colordefs import ColorScaleInferno
from PySide2 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from qudi.hardware.cwave.cwave_api import PiezoChannel, StatusBit, PiezoMode, ExtRampMode, StepperChannel, Log
import qudi.util.uic as uic
# from core.pi3_utils import delay, wavelength_to_freq


class CwaveWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'cwave.ui')

        # Load it
        super(CwaveWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()

class CwaveGui(GuiBase):
    """
    """
    # declare connectors
    cwavelogic = Connector(interface='CwaveLogic')
    
    sig_adj_thick_etalon = QtCore.Signal(float)
    sig_adj_opo = QtCore.Signal(float)
    sig_set_piezo_output = QtCore.Signal(object, float)
    
    sig_connect_cwave = QtCore.Signal(bool)
    sig_set_shutter_state = QtCore.Signal(str, bool)
    sig_optimize_cwave = QtCore.Signal(str)
    sig_change_lock_mode = QtCore.Signal(object, object)
    sig_save_measurement = QtCore.Signal()
    

    def on_deactivate(self):
        """ Reverse steps of activation
        @return int: error code (0:OK, -1:error)
        """
        #turn off the regulation 
        self._mw.close()
        return 0

    def on_activate(self):
        """ 
        """
        self._cwavelogic = self.cwavelogic()
        self._mw = CwaveWindow()     
        #! Get the images from the logic
        self.set_up_cwave_control_panel()
        self._cwavelogic.sig_update_gui.connect(self.update_gui)
        self._cwavelogic.sig_cwave_connected.connect(self.cwave_connected)
        # self._cwavelogic.sig_cwave_connected.emit()
        #! set shutters initially and then consider button states synced with the laser
        #! update on connect
        for shutter, state in self._cwavelogic.shutters.items():
            eval(f"self._mw.checkBox_shtter_{shutter}.setChecked({state})")

        self._mw.show()

    def set_up_cwave_control_panel(self):
        self._mw.pushButton_connectCwave.clicked.connect(self.changeCwaveState)
        self._mw.updating_checkBox.stateChanged.connect(
            lambda: self._cwavelogic.sig_pause_updates.emit(not self._mw.updating_checkBox.isChecked())
        )
        for shutter in self._cwavelogic.shutters.keys():
            eval(f"self._mw.checkBox_shtter_{shutter}.stateChanged.connect(self.flip_shutter)")
         
        self._mw.pump_checkBox.stateChanged.connect(self.pump_switched)

        self._mw.pushButtonOpt_stop.clicked.connect(self.optimizing)
        self._mw.pushButtonOpt_temp.clicked.connect(self.optimizing)
        self._mw.pushButtonOpt_etalon.clicked.connect(self.optimizing)

        self._mw.shg_lock_checkBox.stateChanged.connect(self.change_lock_mode)
        self._mw.opo_lock_checkBox.stateChanged.connect(self.change_lock_mode)
        self._mw.thick_eta_doubleSpinBox.editingFinished.connect(self.adjust_thick_etalon)
        self._mw.opo_lambda_doubleSpinBox.editingFinished.connect(self.adjust_opo_lambda)
        self._mw.ramp_checkBox.stateChanged.connect(self.start_ramp)
        self._mw.piezo_comboBox.currentTextChanged.connect(self.piezo_channel_changed)
        for channel in PiezoChannel:
            self._mw.piezo_comboBox.addItem(channel.name)
        self._mw.piezo_doubleSpinBox.editingFinished.connect(self.update_setpoint)

        #? Connect signals
        self.sig_set_shutter_state.connect(self._cwavelogic.change_shutter_state)
        self.sig_optimize_cwave.connect(self._cwavelogic.optimize_cwave)
        self.sig_connect_cwave.connect(self._cwavelogic.connection_cwave)
        self.sig_change_lock_mode.connect(self._cwavelogic.change_lock_mode)
        self.sig_adj_thick_etalon.connect(self._cwavelogic.adj_thick_etalon)
        self.sig_adj_opo.connect(self._cwavelogic.adj_opo_lambda)
        self.sig_set_piezo_output.connect(self._cwavelogic.set_piezo_output)
    
    
    def show(self):
        """Make window visible and put it above all other windows. """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()
    
    @QtCore.Slot(str)
    def piezo_channel_changed(self, channel):
        self.piezo_channel = channel

    @QtCore.Slot()
    def update_gui(self):
        self.update_cwave_panel()

    @QtCore.Slot()
    def adjust_thick_etalon(self, delta_eta=None):
        if delta_eta is None:
            delta_eta = self._mw.thick_eta_doubleSpinBox.value()

        self.sig_adj_thick_etalon.emit(delta_eta) 
    @QtCore.Slot()
    def adjust_opo_lambda(self, delta_lam = None):
        if delta_lam is None:
            delta_lam = self._mw.opo_lambda_doubleSpinBox.value()
        self.sig_adj_opo.emit(delta_lam) 
    @QtCore.Slot()
    def update_setpoint(self, setpoint=None):
        if setpoint is None:
            setpoint = self._mw.piezo_doubleSpinBox.value()

        self.sig_set_piezo_output.emit(PiezoChannel[self.piezo_channel], setpoint)

    @QtCore.Slot(int)
    def start_ramp(self, state):
        duration = self._mw.duration_spinBox.value()
        start = self._mw.start_spinBox.value()
        stop = self._mw.stop_spinBox.value()

        if bool(state):
            self._cwavelogic.sig_pause_updates.emit(True)
            self._mw.opo_lock_checkBox.setChecked(False)
            self._mw.updating_checkBox.setChecked(False)
            self._cwavelogic.ramp_opo(duration, start, stop)
            #!DISABLE ALL
        else:
            self._cwavelogic.sig_pause_updates.emit(False)
            self._mw.updating_checkBox.setChecked(True)
            self._mw.opo_lock_checkBox.setChecked(True)
            self.change_lock_mode(PiezoChannel.Opo, PiezoMode.Control)
        return 

    @QtCore.Slot()
    def change_lock_mode(self, stage=None, mode=None):
        if (stage is None) or (mode is None):
            sender = self.sender()
  
            if "_lock_checkBox" in sender.objectName():
                    stage = sender.objectName().split('_lock_checkBox')[0].strip()
                    stage = PiezoChannel.Opo if stage == 'opo' else PiezoChannel.Shg
                    mode = PiezoMode.Control if sender.isChecked() else PiezoMode.Manual
            else:
                raise Exception("Wrong button for this function!")
                return
        self.sig_change_lock_mode.emit(stage, mode)
    
    @QtCore.Slot()
    def optimizing(self, opt_param = None):
       
        if opt_param is False: #SOme bug I do not know how to fix
            sender = self.sender()
            if "pushButtonOpt_" in sender.objectName():
                
                opt_param = sender.objectName().split('pushButtonOpt_')[-1].strip()
            else:
                raise Exception("Wrong button for this function!")
                return
        self.sig_optimize_cwave.emit(opt_param)
    
    @QtCore.Slot(bool)
    def pump_switched(self, state):
        self._cwavelogic.pump_switched(state)

    @QtCore.Slot()
    def flip_shutter(self, shutter=None, state=None):
        if (shutter is None) or (state is None):
            sender = self.sender()
            state = sender.isChecked()
            if "checkBox_shtter" in sender.objectName():
                shutter = sender.objectName().split('checkBox_shtter_')[-1].strip()
            elif "checkBox_laser_en" in sender.objectName():
                shutter = sender.objectName().split('checkBox_laser_en_')[-1].strip()
            else:
                raise Exception("Wrong button for this function!")
                return  
      
        self.sig_set_shutter_state.emit(shutter, state)
    @QtCore.Slot()
    def update_cwave_panel(self):
        """ Logic told us to update our button states, so set the buttons accordingly. """
        #! connect button 
        # if self._cwavelogic.connected == 0:
        #     self._mw.pushButton_connectCwave.setText('Connect')
        #     self._mw.radioButton_connectCwave.setChecked(False)
        # else:
        #     self._mw.pushButton_connectCwave.setText('Disconnect')
        #     self._mw.radioButton_connectCwave.setChecked(True)
        
        #! disalbed style 
        #https://stackoverflow.com/questions/66734842/setting-background-color-of-a-checkable-qpushbutton-for-button-is-disabled
        # #! shutters:
        # for shutter, state in self._cwavelogic.shutters.items():
        #     eval(f"self._mw.checkBox_shtter_{shutter}.setChecked({state})")
        #! states:
        for param, state in self._cwavelogic.status_cwave.items():
            if state is not None: #! FIX IT
                eval(f"self._mw.radioButton_{param}.setChecked({state})")

        #! wavelength
        #TODO: read wavelength from the wavelengthmeter
        # self._mw.pump_checkBox.setChecked(self._cwavelogic.pump_state)
        #! photodiodes  
        self._mw.label_laserPD.setText(f"{self._cwavelogic.cwave_log.pdPump}")
        self._mw.label_opoPD.setText(f"{self._cwavelogic.cwave_log.pdSignal}")
        self._mw.label_shgPD.setText(f"{self._cwavelogic.cwave_log.pdShg}")

    @QtCore.Slot()
    def changeCwaveState(self):
        if self._cwavelogic.connected == 0:
            self._mw.pushButton_connectCwave.setText('Disconnect')
            self._mw.radioButton_connectCwave.setChecked(True)
            self.sig_connect_cwave.emit(True)
        else:
            self._mw.pushButton_connectCwave.setText('Connect')
            self._mw.radioButton_connectCwave.setChecked(False)
            self.sig_connect_cwave.emit(False)
            #!DISABLE ALL

    
    @QtCore.Slot()
    def cwave_connected(self):
        self._mw.pushButton_connectCwave.setText('Disconnect')
        self._mw.radioButton_connectCwave.setChecked(True)
        
        for shutter, state in self._cwavelogic.shutters.items():
            eval(f"self._mw.checkBox_shtter_{shutter}.setChecked({state})")
        self._mw.pump_checkBox.setChecked(self._cwavelogic.pump_state)

        self._mw.shg_lock_checkBox.setChecked(True if self._cwavelogic.reg_modes['shg'].value == PiezoMode.Control.value else False)
        self._mw.opo_lock_checkBox.setChecked(True if self._cwavelogic.reg_modes['opo'].value == PiezoMode.Control.value else False)
