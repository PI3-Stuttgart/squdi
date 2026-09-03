import os
from qtpy import QtWidgets, QtCore
import numpy as np
import inspect # for getting name of functions

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.util import uic

class MagnetmainWindow(QtWidgets.QMainWindow):
    """Creates the Magnet GUI window.
    """

    def __init__(self, *args, **kwargs):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_vectormagnet_prelim.ui')

        # Load it
        super().__init__(*args, **kwargs)
        uic.loadUi(ui_file, self)


class MagnetWindow(GuiBase):
    ## declare connectors
    magnetlogic = Connector(interface = 'MagnetLogic')

    ## signals
    # internal signals

    # external signals
    # array: params [[axis0_start, axis0_stop, axis0_steps], [axis1_start, axis1_stop, axis1_steps], [axis2_start, axis2_stop, axis2_steps]]
    # float: integration time
    sigStartScanPressed = QtCore.Signal(np.ndarray, float)
    sigStopScanPressed = QtCore.Signal()
    # int: psw status. Either 0 (turn off) or 1 (turn on)
    sigChangePswStatus = QtCore.Signal(int)
    sigPauseRamp = QtCore.Signal()
    sigContinueRamp = QtCore.Signal()
    sigRamToZero = QtCore.Signal()
    sigRamp = QtCore.Signal(np.ndarray)
    sigRequestRampSettings = QtCore.Signal()
    sigApplyRampSettings = QtCore.Signal(object)


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = True


    def on_activate(self):
        self._mw = MagnetmainWindow()
        self._magnetlogic = self.magnetlogic()

        # Define GUI Colors
        self.colors_green = "#46994c"
        self.colors_yellow = "#e39d22"
        self.colors_blue = "#3d8ec9"
        self.colors_purple = "#bf40bf"
        self.colors_red = "#d6674f"
        self.colors_default = "#333333"

        # Shift items in gridLayout_4 down to make room at row 0 for QComboBox
        # gridLayout_4 has 7 rows (0 to 6) and 2 columns
        widgets_to_move = {}
        for row in range(7):
            for col in range(2):
                item = self._mw.gridLayout_4.itemAtPosition(row, col)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widgets_to_move[(row, col)] = widget
                        self._mw.gridLayout_4.removeWidget(widget)
                        
        for (row, col), widget in widgets_to_move.items():
            self._mw.gridLayout_4.addWidget(widget, row + 1, col)
            
        # Add Input Mode ComboBox to row 0 of gridLayout_4
        self.label_input_mode = QtWidgets.QLabel("Input Mode:")
        self._mw.comboBox_input_mode = QtWidgets.QComboBox()
        self._mw.comboBox_input_mode.addItems([
            "Spherical (B, θ, φ)",
            "Deacrt (Bx, By, Bz)",
            "XY Plane",
            "XZ Plane",
            "YZ Plane"
        ])
        self._mw.comboBox_input_mode.currentIndexChanged.connect(self.input_mode_changed)
        
        self._mw.gridLayout_4.addWidget(self.label_input_mode, 0, 0)
        self._mw.gridLayout_4.addWidget(self._mw.comboBox_input_mode, 0, 1)

        # Hide the scan parameters and start/stop scan buttons
        self._mw.verticalLayoutWidget_4.setVisible(False)
        
        # Set up QTabWidget to wrap our layouts
        self.tab_widget = QtWidgets.QTabWidget()
        self.control_tab = QtWidgets.QWidget()
        self.settings_tab = QtWidgets.QWidget()
        
        self.tab_widget.addTab(self.control_tab, "Control & Monitor")
        self.tab_widget.addTab(self.settings_tab, "Settings")

        # Reparent gridLayoutWidget (ramp controls) to control_tab
        self._mw.gridLayoutWidget.setParent(self.control_tab)

        # Set up layouts for Control Tab to allow dynamic resizing/repositioning
        control_layout = QtWidgets.QHBoxLayout(self.control_tab)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(10)

        left_column_layout = QtWidgets.QVBoxLayout()
        left_column_layout.setSpacing(10)

        # Create Coordinate Explanation Group Box below manual controls
        self.explanation_group = QtWidgets.QGroupBox("Coordinate Info", self.control_tab)
        expl_layout = QtWidgets.QVBoxLayout(self.explanation_group)
        expl_layout.setContentsMargins(8, 8, 8, 8)
        
        self.lbl_explanation = QtWidgets.QLabel(self.explanation_group)
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setTextFormat(QtCore.Qt.RichText)
        self.update_explanation_text("Spherical")
        expl_layout.addWidget(self.lbl_explanation)

        # Add manual controls and explanation group to left column
        left_column_layout.addWidget(self._mw.gridLayoutWidget)
        left_column_layout.addWidget(self.explanation_group)

        # Keep left column controls at a nice, readable fixed width
        self._mw.gridLayoutWidget.setFixedWidth(180)
        self.explanation_group.setFixedWidth(180)

        # Create Monitor Group Box
        self.monitor_group = QtWidgets.QGroupBox("Magnet Monitor", self.control_tab)
        
        # Add columns to main Control Tab layout
        control_layout.addLayout(left_column_layout)
        control_layout.addWidget(self.monitor_group)
        
        # Resize window to fit compact layout initially
        self._mw.resize(850, 480)

        monitor_layout = QtWidgets.QGridLayout(self.monitor_group)
        monitor_layout.setContentsMargins(10, 10, 10, 10)
        monitor_layout.setSpacing(8)
        
        # Headers
        lbl_field = QtWidgets.QLabel("<b>Field</b>")
        lbl_target_hdr = QtWidgets.QLabel("<b>Target</b>")
        lbl_target_hdr.setAlignment(QtCore.Qt.AlignCenter)
        lbl_meas_hdr = QtWidgets.QLabel("<b>Measured</b>")
        lbl_meas_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        monitor_layout.addWidget(lbl_field, 0, 0)
        monitor_layout.addWidget(lbl_target_hdr, 0, 1)
        monitor_layout.addWidget(lbl_meas_hdr, 0, 2)
        
        # B-field LCDs
        self.lbl_b_field_name = QtWidgets.QLabel("B Field (mT):")
        self.lcd_target_bfield = QtWidgets.QLCDNumber()
        self.lcd_curr_bfield = QtWidgets.QLCDNumber()
        self.lcd_target_bfield.setDigitCount(5)
        self.lcd_curr_bfield.setDigitCount(5)
        monitor_layout.addWidget(self.lbl_b_field_name, 1, 0)
        monitor_layout.addWidget(self.lcd_target_bfield, 1, 1)
        monitor_layout.addWidget(self.lcd_curr_bfield, 1, 2)
        
        # Theta LCDs
        self.lbl_theta_name = QtWidgets.QLabel("Theta (°):")
        self.lcd_target_theta = QtWidgets.QLCDNumber()
        self.lcd_curr_theta = QtWidgets.QLCDNumber()
        self.lcd_target_theta.setDigitCount(5)
        self.lcd_curr_theta.setDigitCount(5)
        monitor_layout.addWidget(self.lbl_theta_name, 2, 0)
        monitor_layout.addWidget(self.lcd_target_theta, 2, 1)
        monitor_layout.addWidget(self.lcd_curr_theta, 2, 2)
        
        # Phi LCDs
        self.lbl_phi_name = QtWidgets.QLabel("Phi (°):")
        self.lcd_target_phi = QtWidgets.QLCDNumber()
        self.lcd_curr_phi = QtWidgets.QLCDNumber()
        self.lcd_target_phi.setDigitCount(5)
        self.lcd_curr_phi.setDigitCount(5)
        monitor_layout.addWidget(self.lbl_phi_name, 3, 0)
        monitor_layout.addWidget(self.lcd_target_phi, 3, 1)
        monitor_layout.addWidget(self.lcd_curr_phi, 3, 2)
        
        # Spacer/separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        monitor_layout.addWidget(line, 4, 0, 1, 6)
        
        # Axis Table Headers
        lbl_axis_hdr = QtWidgets.QLabel("<b>Axis</b>")
        
        lbl_target_curr_hdr = QtWidgets.QLabel("<b>I Target (A)</b>")
        lbl_target_curr_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        lbl_meas_curr_hdr = QtWidgets.QLabel("<b>I Meas (A)</b>")
        lbl_meas_curr_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        lbl_target_field_hdr = QtWidgets.QLabel("<b>B Target (mT)</b>")
        lbl_target_field_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        lbl_meas_field_hdr = QtWidgets.QLabel("<b>B Meas (mT)</b>")
        lbl_meas_field_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        lbl_status_hdr = QtWidgets.QLabel("<b>Ramping State</b>")
        lbl_status_hdr.setAlignment(QtCore.Qt.AlignCenter)
        
        monitor_layout.addWidget(lbl_axis_hdr, 5, 0)
        monitor_layout.addWidget(lbl_target_curr_hdr, 5, 1)
        monitor_layout.addWidget(lbl_meas_curr_hdr, 5, 2)
        monitor_layout.addWidget(lbl_target_field_hdr, 5, 3)
        monitor_layout.addWidget(lbl_meas_field_hdr, 5, 4)
        monitor_layout.addWidget(lbl_status_hdr, 5, 5)
        
        # X Axis
        self.lbl_curr_x_name = QtWidgets.QLabel("X Axis:")
        self.lcd_target_curr_x = QtWidgets.QLCDNumber()
        self.lcd_meas_curr_x = QtWidgets.QLCDNumber()
        self.lcd_target_bx = QtWidgets.QLCDNumber()
        self.lcd_meas_bx = QtWidgets.QLCDNumber()
        self.lbl_state_x = QtWidgets.QLabel("Unknown")
        self.lbl_state_x.setAlignment(QtCore.Qt.AlignCenter)
        
        self.lcd_target_curr_x.setDigitCount(5)
        self.lcd_meas_curr_x.setDigitCount(5)
        self.lcd_target_bx.setDigitCount(5)
        self.lcd_meas_bx.setDigitCount(5)
        
        monitor_layout.addWidget(self.lbl_curr_x_name, 6, 0)
        monitor_layout.addWidget(self.lcd_target_curr_x, 6, 1)
        monitor_layout.addWidget(self.lcd_meas_curr_x, 6, 2)
        monitor_layout.addWidget(self.lcd_target_bx, 6, 3)
        monitor_layout.addWidget(self.lcd_meas_bx, 6, 4)
        monitor_layout.addWidget(self.lbl_state_x, 6, 5)
        
        # Y Axis
        self.lbl_curr_y_name = QtWidgets.QLabel("Y Axis:")
        self.lcd_target_curr_y = QtWidgets.QLCDNumber()
        self.lcd_meas_curr_y = QtWidgets.QLCDNumber()
        self.lcd_target_by = QtWidgets.QLCDNumber()
        self.lcd_meas_by = QtWidgets.QLCDNumber()
        self.lbl_state_y = QtWidgets.QLabel("Unknown")
        self.lbl_state_y.setAlignment(QtCore.Qt.AlignCenter)
        
        self.lcd_target_curr_y.setDigitCount(5)
        self.lcd_meas_curr_y.setDigitCount(5)
        self.lcd_target_by.setDigitCount(5)
        self.lcd_meas_by.setDigitCount(5)
        
        monitor_layout.addWidget(self.lbl_curr_y_name, 7, 0)
        monitor_layout.addWidget(self.lcd_target_curr_y, 7, 1)
        monitor_layout.addWidget(self.lcd_meas_curr_y, 7, 2)
        monitor_layout.addWidget(self.lcd_target_by, 7, 3)
        monitor_layout.addWidget(self.lcd_meas_by, 7, 4)
        monitor_layout.addWidget(self.lbl_state_y, 7, 5)
        
        # Z Axis
        self.lbl_curr_z_name = QtWidgets.QLabel("Z Axis:")
        self.lcd_target_curr_z = QtWidgets.QLCDNumber()
        self.lcd_meas_curr_z = QtWidgets.QLCDNumber()
        self.lcd_target_bz = QtWidgets.QLCDNumber()
        self.lcd_meas_bz = QtWidgets.QLCDNumber()
        self.lbl_state_z = QtWidgets.QLabel("Unknown")
        self.lbl_state_z.setAlignment(QtCore.Qt.AlignCenter)
        
        self.lcd_target_curr_z.setDigitCount(5)
        self.lcd_meas_curr_z.setDigitCount(5)
        self.lcd_target_bz.setDigitCount(5)
        self.lcd_meas_bz.setDigitCount(5)
        
        monitor_layout.addWidget(self.lbl_curr_z_name, 8, 0)
        monitor_layout.addWidget(self.lcd_target_curr_z, 8, 1)
        monitor_layout.addWidget(self.lcd_meas_curr_z, 8, 2)
        monitor_layout.addWidget(self.lcd_target_bz, 8, 3)
        monitor_layout.addWidget(self.lcd_meas_bz, 8, 4)
        monitor_layout.addWidget(self.lbl_state_z, 8, 5)

        # Style target LCDs differently
        for lcd in (self.lcd_target_bfield, self.lcd_target_theta, self.lcd_target_phi,
                    self.lcd_target_curr_x, self.lcd_target_curr_y, self.lcd_target_curr_z,
                    self.lcd_target_bx, self.lcd_target_by, self.lcd_target_bz):
            lcd.setStyleSheet("background-color : #222222; color : #ffffff;")

        # Settings Layout
        settings_layout = QtWidgets.QFormLayout(self.settings_tab)
        settings_layout.setContentsMargins(20, 20, 20, 20)
        settings_layout.setSpacing(12)
        
        # ADwin settings:
        self.label_adwin_freq = QtWidgets.QLabel("ADwin Ramp Frequency (Hz):")
        self.spinbox_adwin_freq = QtWidgets.QDoubleSpinBox()
        self.spinbox_adwin_freq.setRange(0.1, 1000.0)
        self.spinbox_adwin_freq.setDecimals(1)
        self.spinbox_adwin_freq.setSingleStep(1.0)
        
        self.label_adwin_step = QtWidgets.QLabel("ADwin Voltage Step Size (V):")
        self.spinbox_adwin_step = QtWidgets.QDoubleSpinBox()
        self.spinbox_adwin_step.setRange(0.0001, 10.0)
        self.spinbox_adwin_step.setDecimals(4)
        self.spinbox_adwin_step.setSingleStep(0.001)
        
        # AMI settings:
        self.label_ami_rate_x = QtWidgets.QLabel("X Ramp Rate:")
        self.spinbox_ami_rate_x = QtWidgets.QDoubleSpinBox()
        self.spinbox_ami_rate_x.setRange(0.0, 100.0)
        self.spinbox_ami_rate_x.setDecimals(4)
        
        self.label_ami_rate_y = QtWidgets.QLabel("Y Ramp Rate:")
        self.spinbox_ami_rate_y = QtWidgets.QDoubleSpinBox()
        self.spinbox_ami_rate_y.setRange(0.0, 100.0)
        self.spinbox_ami_rate_y.setDecimals(4)
        
        self.label_ami_rate_z = QtWidgets.QLabel("Z Ramp Rate:")
        self.spinbox_ami_rate_z = QtWidgets.QDoubleSpinBox()
        self.spinbox_ami_rate_z.setRange(0.0, 100.0)
        self.spinbox_ami_rate_z.setDecimals(4)
        
        settings_layout.addRow(self.label_adwin_freq, self.spinbox_adwin_freq)
        settings_layout.addRow(self.label_adwin_step, self.spinbox_adwin_step)
        settings_layout.addRow(self.label_ami_rate_x, self.spinbox_ami_rate_x)
        settings_layout.addRow(self.label_ami_rate_y, self.spinbox_ami_rate_y)
        settings_layout.addRow(self.label_ami_rate_z, self.spinbox_ami_rate_z)
        
        # Refresh and Apply buttons for settings
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_refresh_settings = QtWidgets.QPushButton("Refresh Settings")
        self.btn_apply_settings = QtWidgets.QPushButton("Apply Settings")
        self.btn_refresh_settings.clicked.connect(self.load_ramp_settings)
        self.btn_apply_settings.clicked.connect(self.apply_ramp_settings)
        btn_layout.addWidget(self.btn_refresh_settings)
        btn_layout.addWidget(self.btn_apply_settings)
        settings_layout.addRow(btn_layout)
        
        self.update_settings_ui_visibility("none")
        
        # Set QTabWidget as central widget
        self._mw.setCentralWidget(self.tab_widget)

        ## connect buttons
        self._mw.start_scan_pushButton.clicked.connect(self.start_scan_pressed)
        self._mw.stop_scan_pushButton.clicked.connect(self.stop_scan_pressed)
        self._mw.heat_psw_pushButton.clicked.connect(self.heat_psw_pressed)
        self._mw.cool_psw_pushButton.clicked.connect(self.cool_psw_pressed)
        self._mw.pause_ramp_pushButton.clicked.connect(self.pause_ramp_pressed)
        self._mw.continue_ramp_pushButton.clicked.connect(self.continue_ramp_pressed)
        self._mw.ramp_to_zero_pushButton.clicked.connect(self.ramp_to_zero_pressed)
        self._mw.start_ramp_pushButton.clicked.connect(self.ramp_pressed)

        ## connect signals — ALL use QueuedConnection so hardware calls run in the logic thread
        self.sigStartScanPressed.connect(
            self._magnetlogic.set_up_scan, QtCore.Qt.QueuedConnection
        )
        self.sigChangePswStatus.connect(
            self._magnetlogic.set_psw_status, QtCore.Qt.QueuedConnection
        )
        self.sigPauseRamp.connect(
            self._magnetlogic.pause_ramp, QtCore.Qt.QueuedConnection
        )
        self.sigContinueRamp.connect(
            self._magnetlogic.continue_ramp, QtCore.Qt.QueuedConnection
        )
        self.sigRamToZero.connect(
            self._magnetlogic.ramp_to_zero, QtCore.Qt.QueuedConnection
        )
        self.sigRamp.connect(
            self._magnetlogic.ramp, QtCore.Qt.QueuedConnection
        )
        self.sigRequestRampSettings.connect(
            self._magnetlogic.get_ramp_settings, QtCore.Qt.QueuedConnection
        )
        self.sigApplyRampSettings.connect(
            self._magnetlogic.set_ramp_settings, QtCore.Qt.QueuedConnection
        )

        self._magnetlogic.sigStatusUpdated.connect(
            self._update_current_values, QtCore.Qt.QueuedConnection
        )
        self._magnetlogic.sigRampSettingsReady.connect(
            self._apply_ramp_settings_to_ui, QtCore.Qt.QueuedConnection
        )

        self.input_mode_changed()
        self.load_ramp_settings()
        self.show()


    def on_deactivate(self):
        """ Hide window
        """
        try:
            self._magnetlogic.sigStatusUpdated.disconnect(self._update_current_values)
        except RuntimeError:
            pass
        self._mw.close()

    def show(self):
        """Make sure that the window is visible and at the top.
        """
        self._mw.show()

    
    def start_scan_pressed(self):
        # TODO: (de)activate buttons
        if self.debug:
            print('start_scan_pressed')
        # get scanning parameters from gui
        # B_abs
        ax0_start = self._mw.axis0_start_value_doubleSpinBox.value()
        ax0_stop = self._mw.axis0_stop_value_doubleSpinBox.value()
        ax0_steps = self._mw.axis0_steps_doubleSpinBox.value()
        ax0_steps = int(ax0_steps)
        # theta
        ax1_start = self._mw.axis1_start_value_doubleSpinBox.value()
        ax1_stop = self._mw.axis1_stop_value_doubleSpinBox.value()
        ax1_steps = self._mw.axis1_steps_doubleSpinBox.value()
        ax1_steps = int(ax1_steps)
        # phi
        ax2_start = self._mw.axis2_start_value_doubleSpinBox.value()
        ax2_stop = self._mw.axis2_stop_value_doubleSpinBox.value()
        ax2_steps = self._mw.axis2_steps_doubleSpinBox.value()
        ax2_steps = int(ax2_steps)
        # put them in an array
        params = np.array([[ax0_start,ax0_stop,ax0_steps],
                            [ax1_start,ax1_stop,ax1_steps],
                            [ax2_start,ax2_stop,ax2_steps]
                        ])
        # get integration time from gui
        int_time = self._mw.integration_time_doubleSpinBox.value()
        # emit the signal
        self.sigStartScanPressed.emit(params,int_time)
        return

    
    def stop_scan_pressed(self):
        # TODO: (de)activate buttons
        self.sigStopScanPressed.emit()
        return


    def heat_psw_pressed(self):
        # TODO: (de)activate buttons
        if self.debug:
            print('heat_psw_pressed')
        self.sigChangePswStatus.emit(1)
        return


    def cool_psw_pressed(self):
        # TODO: (de)activate buttons
        if self.debug:
            print('cool_psw_pressed')
        self.sigChangePswStatus.emit(0)
        return


    def pause_ramp_pressed(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigPauseRamp.emit()
        return


    def continue_ramp_pressed(self):
        if self.debug:
            # prints name of file and function
            print(f'{__name__}, {inspect.stack()[0][3]}') 
        self.sigContinueRamp.emit()
        return

    
    def ramp_to_zero_pressed(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.sigRamToZero.emit()
        return


    def ramp_pressed(self):
        if self.debug:
            # prints name of file and function
            print(f'{__name__}, {inspect.stack()[0][3]}') 
            
        mode = self._mw.comboBox_input_mode.currentText()
        if "Spherical" in mode:
            ax0 = self._mw.axis0_doubleSpinBox.value()
            ax1 = self._mw.axis1_doubleSpinBox.value()
            ax2 = self._mw.axis2_doubleSpinBox.value()
            params = np.array([ax0,ax1,ax2])
            self.sigRamp.emit(params)
        elif "Cartesian" in mode or "Deacrt" in mode or "Decart" in mode:
            bx = self._mw.axis0_doubleSpinBox.value()
            by = self._mw.axis1_doubleSpinBox.value()
            bz = self._mw.axis2_doubleSpinBox.value()
            
            # Convert [bx, by, bz] back to spherical
            radius = np.sqrt(bx**2 + by**2 + bz**2)
            if radius == 0.0:
                theta = 0.0
                phi = 0.0
            else:
                theta = np.rad2deg(np.arccos(bz / radius))
                phi = np.rad2deg(np.arctan2(by, bx))
                if phi < 0:
                    phi += 360.0
            params = np.array([radius, theta, phi])
            self.sigRamp.emit(params)
        else:
            b_amp = self._mw.axis0_doubleSpinBox.value()
            angle_deg = self._mw.axis1_doubleSpinBox.value()
            angle_rad = np.radians(angle_deg)
            
            if "XY" in mode:
                bx = b_amp * np.cos(angle_rad)
                by = b_amp * np.sin(angle_rad)
                bz = 0.0
            elif "XZ" in mode:
                bx = b_amp * np.sin(angle_rad)
                by = 0.0
                bz = b_amp * np.cos(angle_rad)
            elif "YZ" in mode:
                bx = 0.0
                by = b_amp * np.sin(angle_rad)
                bz = b_amp * np.cos(angle_rad)
                
            # Convert [bx, by, bz] back to spherical
            radius = np.sqrt(bx**2 + by**2 + bz**2)
            if radius == 0.0:
                theta = 0.0
                phi = 0.0
            else:
                theta = np.rad2deg(np.arccos(bz / radius))
                phi = np.rad2deg(np.arctan2(by, bx))
                if phi < 0:
                    phi += 360.0
            params = np.array([radius, theta, phi])
            self.sigRamp.emit(params)
        return


    def input_mode_changed(self):
        mode = self._mw.comboBox_input_mode.currentText()
        if "Spherical" in mode:
            self._mw.label_14.setText("B (T)")
            self._mw.label_15.setText("Theta (°)")
            self._mw.label_16.setText("Phi (°)")
            
            self._mw.axis0_doubleSpinBox.setRange(0.0, 10.0)
            self._mw.axis0_doubleSpinBox.setDecimals(4)
            self._mw.axis0_doubleSpinBox.setSingleStep(0.001)
            
            self._mw.axis1_doubleSpinBox.setRange(0.0, 180.0)
            self._mw.axis1_doubleSpinBox.setDecimals(2)
            self._mw.axis1_doubleSpinBox.setSingleStep(1.0)
            self._mw.axis1_doubleSpinBox.setEnabled(True)
            
            self._mw.axis2_doubleSpinBox.setRange(0.0, 360.0)
            self._mw.axis2_doubleSpinBox.setDecimals(2)
            self._mw.axis2_doubleSpinBox.setSingleStep(1.0)
            self._mw.axis2_doubleSpinBox.setEnabled(True)
        elif "Cartesian" in mode or "Deacrt" in mode or "Decart" in mode:
            self._mw.label_14.setText("Bx (T)")
            self._mw.label_15.setText("By (T)")
            self._mw.label_16.setText("Bz (T)")
            
            self._mw.axis0_doubleSpinBox.setRange(-10.0, 10.0)
            self._mw.axis0_doubleSpinBox.setDecimals(4)
            self._mw.axis0_doubleSpinBox.setSingleStep(0.001)
            
            self._mw.axis1_doubleSpinBox.setRange(-10.0, 10.0)
            self._mw.axis1_doubleSpinBox.setDecimals(4)
            self._mw.axis1_doubleSpinBox.setSingleStep(0.001)
            self._mw.axis1_doubleSpinBox.setEnabled(True)
            
            self._mw.axis2_doubleSpinBox.setRange(-10.0, 10.0)
            self._mw.axis2_doubleSpinBox.setDecimals(4)
            self._mw.axis2_doubleSpinBox.setSingleStep(0.001)
            self._mw.axis2_doubleSpinBox.setEnabled(True)
        else:
            self._mw.label_14.setText("B Amp (T)")
            self._mw.label_15.setText("Angle (°)")
            self._mw.label_16.setText("Disabled")
            
            self._mw.axis0_doubleSpinBox.setRange(0.0, 10.0)
            self._mw.axis0_doubleSpinBox.setDecimals(4)
            self._mw.axis0_doubleSpinBox.setSingleStep(0.001)
            
            self._mw.axis1_doubleSpinBox.setRange(-360.0, 360.0)
            self._mw.axis1_doubleSpinBox.setDecimals(2)
            self._mw.axis1_doubleSpinBox.setSingleStep(1.0)
            self._mw.axis1_doubleSpinBox.setEnabled(True)
            
            self._mw.axis2_doubleSpinBox.setEnabled(False)
        self.update_explanation_text(mode)

    def update_explanation_text(self, mode):
        if "Spherical" in mode:
            text = (
                "<b>Spherical:</b><br/>"
                "• <b>B:</b> Amplitude (T)<br/>"
                "• <b>θ (Theta):</b> Polar angle from Z-axis<br/>"
                "• <b>φ (Phi):</b> Azimuthal angle from X-axis"
            )
        elif "Cartesian" in mode or "Deacrt" in mode or "Decart" in mode:
            text = (
                "<b>Deacrt (Cartesian):</b><br/>"
                "• <b>Bx:</b> Field component X (T)<br/>"
                "• <b>By:</b> Field component Y (T)<br/>"
                "• <b>Bz:</b> Field component Z (T)"
            )
        elif "XY" in mode:
            text = (
                "<b>XY Plane:</b><br/>"
                "• <b>B Amp:</b> Amplitude in XY<br/>"
                "• <b>Angle (α):</b> Angle from X-axis<br/>"
                "• <i>Bx = B·cos(α), By = B·sin(α)</i>"
            )
        elif "XZ" in mode:
            text = (
                "<b>XZ Plane:</b><br/>"
                "• <b>B Amp:</b> Amplitude in XZ<br/>"
                "• <b>Angle (α):</b> Angle from Z-axis<br/>"
                "• <i>Bx = B·sin(α), Bz = B·cos(α)</i>"
            )
        elif "YZ" in mode:
            text = (
                "<b>YZ Plane:</b><br/>"
                "• <b>B Amp:</b> Amplitude in YZ<br/>"
                "• <b>Angle (α):</b> Angle from Z-axis<br/>"
                "• <i>By = B·sin(α), Bz = B·cos(α)</i>"
            )
        else:
            text = ""
        self.lbl_explanation.setText(text)


    def update_settings_ui_visibility(self, hw_type):
        is_adwin = (hw_type == "adwin")
        is_ami = (hw_type == "ami")
        
        self.label_adwin_freq.setVisible(is_adwin)
        self.spinbox_adwin_freq.setVisible(is_adwin)
        self.label_adwin_step.setVisible(is_adwin)
        self.spinbox_adwin_step.setVisible(is_adwin)
        
        self.label_ami_rate_x.setVisible(is_ami)
        self.spinbox_ami_rate_x.setVisible(is_ami)
        self.label_ami_rate_y.setVisible(is_ami)
        self.spinbox_ami_rate_y.setVisible(is_ami)
        self.label_ami_rate_z.setVisible(is_ami)
        self.spinbox_ami_rate_z.setVisible(is_ami)


    def load_ramp_settings(self):
        """Request ramp settings from logic via signal (non-blocking)."""
        self.sigRequestRampSettings.emit()

    @QtCore.Slot(object)
    def _apply_ramp_settings_to_ui(self, settings):
        """Slot called by logic when ramp settings are ready."""
        if not isinstance(settings, dict):
            return
        hw_type = settings.get("type", "unknown")
        self.update_settings_ui_visibility(hw_type)
        if hw_type == "adwin":
            self.spinbox_adwin_freq.setValue(settings.get("ramp_freq", 0.0))
            self.spinbox_adwin_step.setValue(settings.get("voltage_step_size", 0.0))
        elif hw_type == "ami":
            rate_units = settings.get("rate_units", "min")
            field_units = settings.get("field_units", "T")
            self.label_ami_rate_x.setText(f"X Ramp Rate ({field_units}/{rate_units}):")
            self.label_ami_rate_y.setText(f"Y Ramp Rate ({field_units}/{rate_units}):")
            self.label_ami_rate_z.setText(f"Z Ramp Rate ({field_units}/{rate_units}):")
            self.spinbox_ami_rate_x.setValue(settings.get("rate_x", 0.0))
            self.spinbox_ami_rate_y.setValue(settings.get("rate_y", 0.0))
            self.spinbox_ami_rate_z.setValue(settings.get("rate_z", 0.0))

    def apply_ramp_settings(self):
        """Send new ramp settings to logic via signal (non-blocking)."""
        settings = {}
        if self.spinbox_adwin_freq.isVisible():
            settings["type"] = "adwin"
            settings["ramp_freq"] = self.spinbox_adwin_freq.value()
            settings["voltage_step_size"] = self.spinbox_adwin_step.value()
        elif self.spinbox_ami_rate_x.isVisible():
            settings["type"] = "ami"
            settings["rate_x"] = self.spinbox_ami_rate_x.value()
            settings["rate_y"] = self.spinbox_ami_rate_y.value()
            settings["rate_z"] = self.spinbox_ami_rate_z.value()
        else:
            return
        self.sigApplyRampSettings.emit(settings)


    @QtCore.Slot(object)
    def _update_current_values(self, status):
        """Update all displayed values and colors based on MagnetLogic status payload."""
        if not isinstance(status, dict):
            return

        # Ramping states X, Y, Z
        ramp_states = list(status.get("ramping_state", []))
        
        state_names = {
            1: "Ramping",
            2: "Holding",
            3: "Paused",
            4: "Manual Up",
            5: "Manual Down",
            6: "Zeroing",
            7: "Quenched",
            8: "At Zero",
            9: "Heating PSW",
            10: "Cooling PSW"
        }
        
        # Helper to get state description and stylesheet color
        def get_state_info(state):
            name = state_names.get(state, "Unknown")
            if state == 1:
                return name, self.colors_yellow
            elif state == 2:
                return name, self.colors_green
            elif state == 3:
                return name, self.colors_purple
            elif state == 8:
                return name, self.colors_blue
            elif state in (7, 9, 10):
                return name, self.colors_red
            else:
                return name, self.colors_default

        colors = [self.colors_default] * 3
        states = ["Unknown"] * 3
        for i in range(3):
            state_val = ramp_states[i] if i < len(ramp_states) else None
            state_name, color = get_state_info(state_val)
            states[i] = state_name
            colors[i] = color
            
        # Update ramping status labels
        self.lbl_state_x.setText(states[0])
        self.lbl_state_y.setText(states[1])
        self.lbl_state_z.setText(states[2])
        
        # Style status labels with color
        self.lbl_state_x.setStyleSheet(f"color: {colors[0]}; font-weight: bold;")
        self.lbl_state_y.setStyleSheet(f"color: {colors[1]}; font-weight: bold;")
        self.lbl_state_z.setStyleSheet(f"color: {colors[2]}; font-weight: bold;")
        
        # Style measured LCD backgrounds based on status
        self.lcd_meas_curr_x.setStyleSheet(f"background-color: {colors[0]}; color: #ffffff;")
        self.lcd_meas_curr_y.setStyleSheet(f"background-color: {colors[1]}; color: #ffffff;")
        self.lcd_meas_curr_z.setStyleSheet(f"background-color: {colors[2]}; color: #ffffff;")
        
        self.lcd_meas_bx.setStyleSheet(f"background-color: {colors[0]}; color: #ffffff;")
        self.lcd_meas_by.setStyleSheet(f"background-color: {colors[1]}; color: #ffffff;")
        self.lcd_meas_bz.setStyleSheet(f"background-color: {colors[2]}; color: #ffffff;")

        # Update currents
        curr_amps = np.asarray(status.get("magnet_currents", [0, 0, 0]), dtype=float)
        target_amps = np.asarray(status.get("target_currents", [0, 0, 0]), dtype=float)
        
        dec_digits = 3
        self.lcd_meas_curr_x.display(round(curr_amps[0], dec_digits))
        self.lcd_meas_curr_y.display(round(curr_amps[1], dec_digits))
        self.lcd_meas_curr_z.display(round(curr_amps[2], dec_digits))
        
        self.lcd_target_curr_x.display(round(target_amps[0], dec_digits))
        self.lcd_target_curr_y.display(round(target_amps[1], dec_digits))
        self.lcd_target_curr_z.display(round(target_amps[2], dec_digits))

        # Update Cartesian fields
        curr_field_cart = np.asarray(status.get("field_cartesian", [0, 0, 0]), dtype=float)
        target_field_cart = np.asarray(status.get("target_field", [0, 0, 0]), dtype=float)
        
        dec_digits_field = 1
        self.lcd_meas_bx.display(round(curr_field_cart[0] * 1e3, dec_digits_field))
        self.lcd_meas_by.display(round(curr_field_cart[1] * 1e3, dec_digits_field))
        self.lcd_meas_bz.display(round(curr_field_cart[2] * 1e3, dec_digits_field))
        
        self.lcd_target_bx.display(round(target_field_cart[0] * 1e3, dec_digits_field))
        self.lcd_target_by.display(round(target_field_cart[1] * 1e3, dec_digits_field))
        self.lcd_target_bz.display(round(target_field_cart[2] * 1e3, dec_digits_field))

        # Update fields — use pre-computed spherical from the status payload (no logic call)
        curr_field_sph = np.asarray(status.get("field_spherical", [0, 0, 0]), dtype=float)
        target_field_sph = np.asarray(status.get("target_field_spherical", [0, 0, 0]), dtype=float)

        # Round & Display Field (in mT for B, degrees for Theta/Phi)
        # Multiply radius by 1e3 for mT
        self.lcd_curr_bfield.display(round(curr_field_sph[0] * 1e3, 1))
        self.lcd_curr_theta.display(round(curr_field_sph[1], 1))
        self.lcd_curr_phi.display(round(curr_field_sph[2], 1))

        self.lcd_target_bfield.display(round(target_field_sph[0] * 1e3, 1))
        self.lcd_target_theta.display(round(target_field_sph[1], 1))
        self.lcd_target_phi.display(round(target_field_sph[2], 1))

        