import os
import inspect
import logging
import numpy as np
from qtpy import QtWidgets, QtCore

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.util import uic


class GUIcolors:
    green = "#46994c"   # At target
    yellow = "#e39d22"  # Ramping
    blue = "#3d8ec9"    # At zero
    purple = "#bf40bf"  # Paused
    red = "#d6674f"


class MagnetMainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, "magnet_ui_qudi.ui")
        super().__init__(*args, **kwargs)
        uic.loadUi(ui_file, self)


class MagnetWindow(GuiBase):
    magnet = Connector(interface="Magnet3D")
    magnetlogic = Connector(interface="MagnetLogic")
    gui_colors = GUIcolors()

    # Basic magnet control signals
    sigPauseRamp = QtCore.Signal()
    sigContinueRamp = QtCore.Signal()
    sigRamToZero = QtCore.Signal()
    sigRamp = QtCore.Signal(np.ndarray)

    # Optional controls that may be present depending on UI variant
    sigStartScanPressed = QtCore.Signal(np.ndarray, float)
    sigStopScanPressed = QtCore.Signal()
    sigChangePswStatus = QtCore.Signal(int)

    # Status polling (async via MagnetLogic)
    sigRequestStatusUpdate = QtCore.Signal()

    update_current_values_interval = 1000  # ms

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = True

    def on_activate(self):
        self._mw = MagnetMainWindow()
        self._magnet = self.magnet()
        self._magnetlogic = self.magnetlogic()

        # Basic controls
        self._mw.pushButton_Ramp.clicked.connect(self.start_ramp_pressed)
        self._mw.pushButton_ramp_to_zero.clicked.connect(self.start_ramp_to_zero_pressed)
        self._mw.pushButton_pause.clicked.connect(self.pause_ramp_pressed)
        self._mw.pushButton_continue.clicked.connect(self.continue_ramp_pressed)
        self._mw.checkBox_debug_mode.stateChanged.connect(self.change_debug_mode)

        # GUI -> logic
        self.sigPauseRamp.connect(self._magnetlogic.pause_ramp)
        self.sigContinueRamp.connect(self._magnetlogic.continue_ramp)
        self.sigRamToZero.connect(self._magnetlogic.ramp_to_zero)
        self.sigRamp.connect(self._magnetlogic.ramp)
        if self._magnet.has_persistence:
            self.sigChangePswStatus.connect(self._magnetlogic.set_psw_status)
        self.sigRequestStatusUpdate.connect(
            self._magnetlogic.request_status_update, QtCore.Qt.QueuedConnection
        )

        # logic -> GUI (status updates)
        self._magnetlogic.sigStatusUpdated.connect(
            self._update_current_values, QtCore.Qt.QueuedConnection
        )

        # Timer only requests status update. The actual hardware calls happen in logic.
        self.update_current_values_timer = QtCore.QTimer()
        self.update_current_values_timer.timeout.connect(
            self._request_status_update, QtCore.Qt.QueuedConnection
        )
        self.update_current_values_timer.setInterval(self.update_current_values_interval)
        self.update_current_values_timer.start()
        self.sigRequestStatusUpdate.emit()

        # Logging setup
        qtpy_handler = QTPyHandler(self._mw.textBrowser_consol)
        qtpy_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(message)s", "%m-%d %H:%M:%S")
        qtpy_handler.setFormatter(formatter)

        self.log.setLevel(logging.DEBUG)
        self.log.addHandler(qtpy_handler)
        self._magnet.log.setLevel(logging.DEBUG)
        self._magnet.log.addHandler(qtpy_handler)
        self._magnetlogic.log.setLevel(logging.DEBUG)
        self._magnetlogic.log.addHandler(qtpy_handler)

        self.show()

    def on_deactivate(self):
        if hasattr(self, "update_current_values_timer") and self.update_current_values_timer:
            self.update_current_values_timer.stop()
            try:
                self.update_current_values_timer.timeout.disconnect()
            except RuntimeError:
                pass

        try:
            self.sigRequestStatusUpdate.disconnect()
        except RuntimeError:
            pass
        try:
            self._magnetlogic.sigStatusUpdated.disconnect(self._update_current_values)
        except RuntimeError:
            pass

        self._mw.close()

    def show(self):
        self._mw.show()

    def change_debug_mode(self, debug: bool):
        log_level = logging.DEBUG if debug else logging.INFO

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
    def _request_status_update(self):
        self.sigRequestStatusUpdate.emit()

    @QtCore.Slot(object)
    def _update_current_values(self, status):
        """Update all displayed values and colors based on MagnetLogic status payload."""
        if not isinstance(status, dict):
            return

        ramp_states = list(status.get("ramping_state", []))
        colors = [self.gui_colors.blue] * 3
        for i, ramp_state in enumerate(ramp_states):
            if i > 2:
                break
            if ramp_state == 1:
                colors[i] = self.gui_colors.yellow
            elif ramp_state == 2:
                colors[i] = self.gui_colors.green
            elif ramp_state == 3:
                colors[i] = self.gui_colors.purple
            elif ramp_state == 8:
                colors[i] = self.gui_colors.blue

        self._mw.lcdNumber_meas_x_voltage.setStyleSheet(f"background-color : {colors[0]}")
        self._mw.lcdNumber_meas_y_voltage.setStyleSheet(f"background-color : {colors[1]}")
        self._mw.lcdNumber_meas_z_voltage.setStyleSheet(f"background-color : {colors[2]}")

        curr_amps = np.asarray(status.get("magnet_currents", [0, 0, 0]), dtype=float)
        curr_field_spherical = np.asarray(
            status.get("field_spherical", [0, 0, 0]), dtype=float
        )

        dec_digits = 2
        self._mw.lcdNumber_meas_x_voltage.display(round(curr_amps[0], dec_digits))
        self._mw.lcdNumber_meas_y_voltage.display(round(curr_amps[1], dec_digits))
        self._mw.lcdNumber_meas_z_voltage.display(round(curr_amps[2], dec_digits))

        self._mw.lcdNumber_target_x_voltage.display(0)
        self._mw.lcdNumber_target_y_voltage.display(0)
        self._mw.lcdNumber_target_z_voltage.display(0)

        if curr_field_spherical[0] * 1e3 < 5:
            curr_field_spherical[1] = 0
            curr_field_spherical[2] = 0
        elif curr_field_spherical[1] < 0.5 or curr_field_spherical[1] > 179.5:
            curr_field_spherical[2] = 0

        self._mw.lcdNumber_curr_bfield.display(round(curr_field_spherical[0] * 1e3, 0))
        self._mw.lcdNumber_curr_theta.display(round(curr_field_spherical[1], 1))
        self._mw.lcdNumber_curr_phi.display(round(curr_field_spherical[2], 1))

    def start_scan_pressed(self):
        if self.debug:
            self.log.debug("start_scan_pressed")

        ax0_start = self._mw.axis0_start_value_doubleSpinBox.value()
        ax0_stop = self._mw.axis0_stop_value_doubleSpinBox.value()
        ax0_steps = int(self._mw.axis0_steps_doubleSpinBox.value())

        ax1_start = self._mw.axis1_start_value_doubleSpinBox.value()
        ax1_stop = self._mw.axis1_stop_value_doubleSpinBox.value()
        ax1_steps = int(self._mw.axis1_steps_doubleSpinBox.value())

        ax2_start = self._mw.axis2_start_value_doubleSpinBox.value()
        ax2_stop = self._mw.axis2_stop_value_doubleSpinBox.value()
        ax2_steps = int(self._mw.axis2_steps_doubleSpinBox.value())

        params = np.array(
            [
                [ax0_start, ax0_stop, ax0_steps],
                [ax1_start, ax1_stop, ax1_steps],
                [ax2_start, ax2_stop, ax2_steps],
            ]
        )
        int_time = self._mw.integration_time_doubleSpinBox.value()
        self.sigStartScanPressed.emit(params, int_time)

    def stop_scan_pressed(self):
        self.log.debug("stop_scan_pressed")
        self.sigStopScanPressed.emit()

    def heat_psw_pressed(self):
        if self.debug:
            self.log.debug("heat_psw_pressed")
        self.sigChangePswStatus.emit(1)

    def cool_psw_pressed(self):
        if self.debug:
            self.log.debug("cool_psw_pressed")
        self.sigChangePswStatus.emit(0)

    def start_ramp_pressed(self):
        self.log.debug(f"{__name__}, {inspect.stack()[0][3]}")
        ax0 = self._mw.doubleSpinBox_target_bfield.value() / 1e3
        ax1 = self._mw.doubleSpinBox_target_theta.value()
        ax2 = self._mw.doubleSpinBox_target_phi.value()
        params = np.array([ax0, ax1, ax2])
        self.sigRamp.emit(params)

    def start_ramp_to_zero_pressed(self):
        self.log.debug(f"{__name__}, {inspect.stack()[0][3]}")
        self.sigRamToZero.emit()

    def pause_ramp_pressed(self):
        self.log.debug(f"{__name__}, {inspect.stack()[0][3]}")
        self.sigPauseRamp.emit()

    def continue_ramp_pressed(self):
        self.log.debug(f"{__name__}, {inspect.stack()[0][3]}")
        self.sigContinueRamp.emit()


class QTPyHandler(logging.Handler):
    gui_colors = GUIcolors()

    def __init__(self, output) -> None:
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
