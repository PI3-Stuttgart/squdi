import os
from qtpy import QtWidgets, QtCore
import numpy as np
import inspect # for getting name of functions

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.util import uic

import logging

class GUIcolors():
    green = '#46994c' # At target
    yellow = '#e39d22' # Ramping
    blue = '#3d8ec9' # At zero
    purple = '#bf40bf' # Paused
    red = '#d6674f'
    

class MagnetMainWindow(QtWidgets.QMainWindow):
     
    
    def __init__(self, *args, **kwargs):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'magnet_ui_qudi.ui')

        # Load it
        super().__init__(*args, **kwargs)
        uic.loadUi(ui_file, self)
        

class MagnetWindow(GuiBase):
    magnet = Connector(interface = 'Magnet3D')
    magnetlogic = Connector(interface = 'MagnetLogic')
    gui_colors = GUIcolors()
    sigPauseRamp = QtCore.Signal()
    sigContinueRamp = QtCore.Signal()
    sigRamToZero = QtCore.Signal()
    sigRamp = QtCore.Signal(np.ndarray)
    
    update_current_values_interval = 1000 # ms
    
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = True
        
    
    def on_activate(self):
        # Instantiate QT5 Window and logic and hardware classes
        self._mw = MagnetMainWindow()
        self._magnet = self.magnet()
        self._magnetlogic = self.magnetlogic()

        # connect buttons
        self._mw.pushButton_Ramp.clicked.connect(self.start_ramp_pressed)
        self._mw.pushButton_ramp_to_zero.clicked.connect(self.start_ramp_to_zero_pressed)
        self._mw.pushButton_pause.clicked.connect(self.pause_ramp_pressed)
        self._mw.pushButton_continue.clicked.connect(self.continue_ramp_pressed)

        # connect checkbox
        self._mw.checkBox_debug_mode.stateChanged.connect(self.change_debug_mode)
        # connect signals
        self.sigPauseRamp.connect(self._magnetlogic.pause_ramp)
        self.sigContinueRamp.connect(self._magnetlogic.continue_ramp)
        self.sigRamToZero.connect(self._magnetlogic.ramp_to_zero)
        self.sigRamp.connect(self._magnetlogic.ramp)
        
        # Create timer for display updates
        self.update_current_values_timer = QtCore.QTimer()
        self.update_current_values_timer.timeout.connect(self._update_current_values, QtCore.Qt.QueuedConnection)
        self.update_current_values_timer.setInterval(self.update_current_values_interval)
        self.update_current_values_timer.start()
        
        # logging
        
        # create logging handler
        _qtpyhandler = QTPyHandler(self._mw.textBrowser_consol)# logging.StreamHandler(stream=QtPyStream(self._mw.textBrowser_consol))
        _qtpyhandler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(message)s', '%m-%d %H:%M:%S')
        _qtpyhandler.setFormatter(formatter)
        
        # add logging handler to the logs of gui, logic and hardware
        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(_qtpyhandler)
        self._magnet.log.setLevel(logging.DEBUG)
        self._magnet.log.addHandler(_qtpyhandler)
        self._magnetlogic.log.setLevel(logging.DEBUG)
        self._magnetlogic.log.addHandler(_qtpyhandler)
        
        # Show 
        self.show()
    

    def on_deactivate(self):
        """ Hide window
        """
        self._mw.close()
        
    def show(self):
        """Make sure that the window is visible and at the top.
        """
        self._mw.show()

    def change_debug_mode(self, debug: bool):
        if debug:
            log_level = logging.DEBUG  
        else:
            log_level = logging.INFO
                 
        for handler in self.log.handlers:
            if isinstance(handler, QTPyHandler):
                self.log.removeHandler(handler)
                handler.setLevel(log_level)
                self.log.addHandler(handler)
                
        for handler in self._magnet.log.handlers:
            if isinstance(handler, QTPyHandler):
                self._magnet.log.removeHandler(handler)
                handler.setLevel(log_level)
                self._magnet.log.addHandler(handler)
                
        for handler in self._magnetlogic.log.handlers:
            if isinstance(handler, QTPyHandler):
                self._magnetlogic.log.removeHandler(handler)
                handler.setLevel(log_level)
                self._magnetlogic.log.addHandler(handler)

    @QtCore.Slot()    
    def _update_current_values(self):
        
        # Set background color of current current values 
        # to ramping state of coil 

        ramp_states = self._magnet.get_ramping_state()
        colors = [self.gui_colors.blue, self.gui_colors.blue, self.gui_colors.blue]
        for i, ramp_state in enumerate(ramp_states):
            if ramp_state == 1:
                colors[i] = self.gui_colors.yellow
            elif ramp_state == 2:
                colors[i] = self.gui_colors.green
            elif ramp_state == 3:
                colors[i] = self.gui_colors.purple
            elif ramp_state == 8:
                colors[i] == self.gui_colors.blue
    
        self._mw.lcdNumber_meas_x_voltage.setStyleSheet(f"background-color : {colors[0]}")
        self._mw.lcdNumber_meas_y_voltage.setStyleSheet(f"background-color : {colors[1]}")
        self._mw.lcdNumber_meas_z_voltage.setStyleSheet(f"background-color : {colors[2]}")
        
        # Get target and current currents and bfield
        curr_amps = self._magnet.get_magnet_currents()
        target_amps = self._magnet.get_target_magnet_currents()
        curr_field_spherical = self._magnetlogic.cartesian_to_spherical(self._magnet.get_field())
        
        dec_digits = 2
        # Display measured magnet currents 
        self._mw.lcdNumber_meas_x_voltage.display(round(curr_amps[0], dec_digits))
        self._mw.lcdNumber_meas_y_voltage.display(round(curr_amps[1], dec_digits))
        self._mw.lcdNumber_meas_z_voltage.display(round(curr_amps[2], dec_digits))
        
        # Display target magnet currents
        self._mw.lcdNumber_target_x_voltage.display(round(target_amps[0], dec_digits)) 
        self._mw.lcdNumber_target_y_voltage.display(round(target_amps[1], dec_digits))
        self._mw.lcdNumber_target_z_voltage.display(round(target_amps[2], dec_digits))
        
        dec_digits = 1
        
        # Checks if bfield is roughly zero -> angles make no sense so set to zero
        if curr_field_spherical[0]*1e3 < 5:
            curr_field_spherical[1] = 0
            curr_field_spherical[2] = 0
        # Checks if theta roughly 0° or 180° -> phi makes no sense so set to zero
        if curr_field_spherical[1] < 0.5 or curr_field_spherical[1] > 179.5:
            curr_field_spherical[2] = 0
        
        # Display current bfield in sperical cooridantes
        self._mw.lcdNumber_curr_bfield.display(round(curr_field_spherical[0]*1e3, 0)) 
        self._mw.lcdNumber_curr_theta.display(round(curr_field_spherical[1], dec_digits)) 
        self._mw.lcdNumber_curr_phi.display(round(curr_field_spherical[2], dec_digits)) 
        

    def start_ramp_pressed(self):
        self.log.debug(f'{__name__}, {inspect.stack()[0][3]}') 
        ax0 = self._mw.doubleSpinBox_target_bfield.value() / 1e3 # T
        ax1 = self._mw.doubleSpinBox_target_theta.value() # °
        ax2 = self._mw.doubleSpinBox_target_phi.value() # °
        params = np.array([ax0, ax1, ax2])
        self.sigRamp.emit(params)
        return
    
    
    def start_ramp_to_zero_pressed(self):
        self.log.debug(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigRamToZero.emit()
        return
    
    
    def pause_ramp_pressed(self):
        self.log.debug(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigPauseRamp.emit()
        return
    
    
    def continue_ramp_pressed(self):
            # prints name of file and function
        self.log.debug(f'{__name__}, {inspect.stack()[0][3]}') 
        self.sigContinueRamp.emit()
        return

    
class QTPyHandler(logging.Handler):
    
    gui_colors = GUIcolors()
    
    def __init__(self, output)-> None:
        self.output = output
        logging.Handler.__init__(self=self)

    def emit(self, log_record) -> None:
        msg = self.formatter.format(log_record)
        if log_record.levelno == 30:
            self.output.append(f"<span style='color: {self.gui_colors.red}'>{msg}</span>".format())
        if log_record.levelno > 20:
            self.output.append(f"<span style='color: {self.gui_colors.red}'>{msg}</span>".format())
        else:
            self.output.append(msg)
        
    
    
    
    