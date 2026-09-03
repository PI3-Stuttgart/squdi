# -*- coding: utf-8 -*-
"""
Power Controller GUI — Qudi style.

Follows standard Qudi GUI conventions:
  - QMainWindow with dock widgets
  - No custom stylesheet (inherits Qudi application theme)
  - All hardware calls routed through queued signals (no GUI freezing)
  - Direct numeric spinbox input as well as slider

Enter key on the spinbox or clicking "Set" sends the value to hardware.

Example config:

power_controller_gui:
    module.Class: 'power_controller.powercontroller_gui.PowerControllerGui'
    connect:
        powercontrollerlogic: 'powercontrollerlogic'
"""

import numpy as np
from PySide2 import QtCore, QtGui, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.core.statusvariable import StatusVar


class PowerControllerMainWindow(QtWidgets.QMainWindow):
    """Main window for the power controller GUI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('qudi: Power Controller')
        self.setMinimumWidth(360)
        self.setDockNestingEnabled(True)

        self._build_menu()
        self._build_control_dock()
        self._build_calibration_dock()
        self._build_status_bar()

        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.calibration_dock)
        self.splitDockWidget(self.control_dock, self.calibration_dock, QtCore.Qt.Vertical)

    # ------------------------------------------------------------------
    def _build_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu('&File')
        self.action_close = QtWidgets.QAction('&Close', self)
        self.action_close.triggered.connect(self.close)
        file_menu.addAction(self.action_close)

        view_menu = menu_bar.addMenu('&View')
        self.action_restore = QtWidgets.QAction('Restore default view', self)
        view_menu.addAction(self.action_restore)

        options_menu = menu_bar.addMenu('&Options')
        self.action_set_zero = QtWidgets.QAction('Set current position as zero', self)
        options_menu.addAction(self.action_set_zero)

    # ------------------------------------------------------------------
    def _build_control_dock(self):
        self.control_dock = QtWidgets.QDockWidget('Power Control', self)
        self.control_dock.setObjectName('power_control_dock')
        self.control_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable
        )

        contents = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(contents)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Channel & mode ───────────────────────────────────────────
        channel_group = QtWidgets.QGroupBox('Channel')
        channel_form = QtWidgets.QFormLayout(channel_group)
        channel_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        channel_form.setSpacing(6)

        self.channel_combo = QtWidgets.QComboBox()
        channel_form.addRow('Motor channel:', self.channel_combo)

        self.use_calibration_checkbox = QtWidgets.QCheckBox('Use power calibration')
        self.use_calibration_checkbox.setToolTip(
            'When checked, enter power in physical units.\n'
            'Requires a completed calibration run.'
        )
        channel_form.addRow(self.use_calibration_checkbox)
        layout.addWidget(channel_group)

        # ── Current position display ──────────────────────────────────
        pos_group = QtWidgets.QGroupBox('Current Position')
        pos_layout = QtWidgets.QHBoxLayout(pos_group)

        self.position_label = QtWidgets.QLabel('—')
        font = QtGui.QFont()
        font.setPointSize(14)
        font.setBold(True)
        font.setFamily('Consolas, Courier New, monospace')
        self.position_label.setFont(font)
        self.position_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        pos_layout.addWidget(self.position_label, stretch=1)

        self.position_unit_label = QtWidgets.QLabel('deg')
        pos_layout.addWidget(self.position_unit_label)
        layout.addWidget(pos_group)

        # ── Set value ────────────────────────────────────────────────
        set_group = QtWidgets.QGroupBox('Set Position / Power')
        set_layout = QtWidgets.QVBoxLayout(set_group)
        set_layout.setSpacing(6)

        # Spinbox row
        entry_row = QtWidgets.QHBoxLayout()

        self.value_spinbox = QtWidgets.QDoubleSpinBox()
        self.value_spinbox.setDecimals(2)
        self.value_spinbox.setRange(0.0, 360.0)
        self.value_spinbox.setSingleStep(1.0)
        self.value_spinbox.setToolTip('Type a value and press Enter or click Set.')
        entry_row.addWidget(self.value_spinbox, stretch=1)

        self.unit_combo = QtWidgets.QComboBox()
        self.unit_combo.addItems(['deg', 'nW', 'µW', 'mW'])
        self.unit_combo.setFixedWidth(64)
        self.unit_combo.setToolTip(
            'deg  — raw motor angle (no calibration needed)\n'
            'nW / µW / mW — physical power (calibration required)'
        )
        entry_row.addWidget(self.unit_combo)

        self.set_button = QtWidgets.QPushButton('Set')
        self.set_button.setToolTip('Send value to hardware  [Enter]')
        self.set_button.setFixedWidth(60)
        entry_row.addWidget(self.set_button)
        set_layout.addLayout(entry_row)

        # Slider (deg mode only)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 3600)   # ×10 for 0.1° resolution
        self.slider.setToolTip('Drag slider and release to apply (deg mode only).')
        set_layout.addWidget(self.slider)

        layout.addWidget(set_group)
        layout.addStretch()

        # Allow Enter to trigger Set
        self.value_spinbox.installEventFilter(self)

        self.control_dock.setWidget(contents)

    # ------------------------------------------------------------------
    def _build_calibration_dock(self):
        self.calibration_dock = QtWidgets.QDockWidget('Calibration', self)
        self.calibration_dock.setObjectName('power_calibration_dock')
        self.calibration_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable |
            QtWidgets.QDockWidget.DockWidgetClosable
        )

        contents = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(contents)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info = QtWidgets.QLabel(
            'Insert power meter, then click Run.\n'
            'The motor will rotate 0 → 360° and\n'
            'record power at each step (~5 min).'
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QtWidgets.QHBoxLayout()
        self.calibrate_button = QtWidgets.QPushButton('Run Calibration')
        self.calibrate_button.setToolTip(
            'Rotate wheel through 360° and record power.\n'
            'Insert powermeter before starting.'
        )
        btn_row.addWidget(self.calibrate_button)

        self.set_zero_button = QtWidgets.QPushButton('Set as Zero')
        self.set_zero_button.setToolTip('Define the current motor position as angle zero.')
        btn_row.addWidget(self.set_zero_button)
        layout.addLayout(btn_row)
        layout.addStretch()

        self.calibration_dock.setWidget(contents)

    # ------------------------------------------------------------------
    def _build_status_bar(self):
        status_bar = QtWidgets.QStatusBar(self)
        status_bar.setStyleSheet('QStatusBar::item { border: 0px }')
        self.setStatusBar(status_bar)

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        """Forward Enter key on spinbox to Set button."""
        if obj is self.value_spinbox and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.set_button.click()
                return True
        return super().eventFilter(obj, event)


class PowerControllerGui(GuiBase):
    """Responsive, Qudi-style GUI for the power controller.

    All hardware calls are routed through queued signals so the GUI never
    freezes during motor moves. Power can be entered as a raw angle (deg) or
    in physical units (nW/µW/mW) when a calibration is available.
    """

    powercontrollerlogic = Connector(interface='PowerControllerLogic')

    _last_unit = StatusVar('last_unit', default='deg')

    # GUI → Logic (all queued)
    sigSetPower  = QtCore.Signal(float, int, bool)   # value, motor, calibrated
    sigZeroMotor = QtCore.Signal(int)                # motor channel

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._mw = None
        self._logic = None
        self._slider_updating = False   # re-entrancy guard

    def on_activate(self):
        self._logic = self.powercontrollerlogic()
        self._mw = PowerControllerMainWindow()
        self._restore_window_geometry(self._mw)

        # Populate channel combo
        for ch in np.array(self._logic.channels).astype(str):
            self._mw.channel_combo.addItem(ch)

        # Restore last unit selection
        idx = self._mw.unit_combo.findText(self._last_unit)
        if idx >= 0:
            self._mw.unit_combo.setCurrentIndex(idx)
        self._apply_unit(self._mw.unit_combo.currentText())

        # Connect GUI signals
        self._mw.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self._mw.use_calibration_checkbox.toggled.connect(self._calibration_toggled)
        self._mw.unit_combo.currentTextChanged.connect(self._apply_unit)
        self._mw.set_button.clicked.connect(self._set_clicked)
        self._mw.slider.sliderReleased.connect(self._slider_released)
        self._mw.slider.valueChanged.connect(self._slider_moved)
        self._mw.calibrate_button.clicked.connect(self._calibrate_clicked)
        self._mw.set_zero_button.clicked.connect(self._zero_clicked)
        self._mw.action_set_zero.triggered.connect(self._zero_clicked)
        self._mw.action_restore.triggered.connect(self._restore_view)

        # GUI → Logic (queued — hardware never in GUI thread)
        self.sigSetPower.connect(self._logic.set_power,  QtCore.Qt.QueuedConnection)
        self.sigZeroMotor.connect(
            lambda motor: self._logic._motor_pi3.zeroMotor(motor=motor),
            QtCore.Qt.QueuedConnection,
        )

        self._refresh_position_display()
        self.show()

    def on_deactivate(self):
        self._save_window_geometry(self._mw)
        for sig in (self.sigSetPower, self.sigZeroMotor):
            try:
                sig.disconnect()
            except RuntimeError:
                pass
        self._mw.close()
        self._mw = None

    def show(self):
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_motor(self) -> int:
        try:
            return int(self._mw.channel_combo.currentText())
        except (ValueError, AttributeError):
            return 0

    def _is_calibrated_mode(self) -> bool:
        return self._mw.use_calibration_checkbox.isChecked()

    def _has_calibration(self, motor: int) -> bool:
        cal = self._logic.power_calibration.get(motor, np.array([]))
        return len(cal) > 0

    def _power_to_watts(self, value: float, unit: str) -> float:
        factors = {'nW': 1e-9, 'µW': 1e-6, 'mW': 1e-3, 'deg': 1.0}
        return value * factors.get(unit, 1.0)

    @staticmethod
    def _best_power_unit(power_w: float):
        """Return (unit_str, scaled_value) for the most readable representation."""
        if power_w < 1e-6:
            return 'nW', power_w * 1e9
        elif power_w < 1e-3:
            return 'µW', power_w * 1e6
        else:
            return 'mW', power_w * 1e3

    def _refresh_position_display(self):
        motor = self._current_motor()
        pos   = self._logic._current_positions.get(motor, 0.0)

        if self._is_calibrated_mode() and self._has_calibration(motor):
            cal         = self._logic.power_calibration[motor]
            angles_cal  = cal[:, 0]
            powers_cal  = cal[:, 1]
            power_w     = powers_cal[np.argmin(np.abs(angles_cal - pos))]
            unit, val   = self._best_power_unit(power_w)
            self._mw.position_label.setText(f'{val:.3f}')
            self._mw.position_unit_label.setText(unit)
        else:
            self._mw.position_label.setText(f'{pos:.1f}')
            self._mw.position_unit_label.setText('deg')

    def _sync_slider_to_spinbox(self):
        """Update slider to match current spinbox value (no feedback loop)."""
        unit = self._mw.unit_combo.currentText()
        val  = self._mw.value_spinbox.value()
        self._slider_updating = True
        if unit == 'deg':
            self._mw.slider.setValue(int(val * 10))
        else:
            motor = self._current_motor()
            if self._has_calibration(motor):
                cal        = self._logic.power_calibration[motor]
                power_w    = self._power_to_watts(val, unit)
                angle      = cal[:, 0][np.argmin(np.abs(cal[:, 1] - power_w))]
                self._mw.slider.setValue(int(angle * 10))
        self._slider_updating = False

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _channel_changed(self):
        motor = self._current_motor()
        pos   = self._logic._current_positions.get(motor, 0.0)
        self._slider_updating = True
        self._mw.slider.setValue(int(pos * 10))
        self._slider_updating = False
        self._refresh_position_display()

    def _calibration_toggled(self, checked: bool):
        if checked:
            motor = self._current_motor()
            if not self._has_calibration(motor):
                self._mw.use_calibration_checkbox.setChecked(False)
                self._mw.statusBar().showMessage(
                    'No calibration data for this channel — run calibration first.', 5000
                )
                return
            # Switch unit combo to a power unit
            self._mw.unit_combo.setCurrentText('µW')
        else:
            self._mw.unit_combo.setCurrentText('deg')
        self._refresh_position_display()

    def _apply_unit(self, unit: str):
        """Adjust spinbox range, step, decimals, and slider enable for the unit."""
        self._last_unit = unit
        sb = self._mw.value_spinbox
        if unit == 'deg':
            sb.setDecimals(1)
            sb.setRange(0.0, 360.0)
            sb.setSingleStep(1.0)
            self._mw.slider.setEnabled(True)
        elif unit == 'nW':
            sb.setDecimals(1)
            sb.setRange(0.0, 1_000_000.0)
            sb.setSingleStep(10.0)
            self._mw.slider.setEnabled(False)
        elif unit == 'µW':
            sb.setDecimals(3)
            sb.setRange(0.0, 10_000.0)
            sb.setSingleStep(1.0)
            self._mw.slider.setEnabled(False)
        elif unit == 'mW':
            sb.setDecimals(4)
            sb.setRange(0.0, 100.0)
            sb.setSingleStep(0.1)
            self._mw.slider.setEnabled(False)

    def _slider_moved(self, slider_val: int):
        if self._slider_updating:
            return
        unit = self._mw.unit_combo.currentText()
        if unit == 'deg':
            self._slider_updating = True
            self._mw.value_spinbox.setValue(slider_val / 10.0)
            self._slider_updating = False

    def _slider_released(self):
        if self._mw.unit_combo.currentText() == 'deg':
            self._set_clicked()

    def _set_clicked(self):
        motor = self._current_motor()
        unit  = self._mw.unit_combo.currentText()
        val   = self._mw.value_spinbox.value()

        if unit == 'deg':
            self.sigSetPower.emit(val, motor, False)
            self._mw.statusBar().showMessage(
                f'Moving motor {motor} → {val:.1f}°  (queued)', 5000
            )
            self._logic._current_positions[motor] = val
        else:
            if not self._has_calibration(motor):
                self._mw.statusBar().showMessage(
                    'No calibration for this channel. '
                    'Switch to deg mode or run calibration first.', 6000
                )
                return
            power_w = self._power_to_watts(val, unit)
            self.sigSetPower.emit(power_w, motor, True)
            self._mw.statusBar().showMessage(
                f'Setting motor {motor} → {val:.3f} {unit}  (queued)', 5000
            )

        self._sync_slider_to_spinbox()
        self._refresh_position_display()

    def _calibrate_clicked(self):
        motor = self._current_motor()
        self._mw.statusBar().showMessage(
            f'Calibration started for motor {motor}. '
            'Rotating 0→360°, recording power… (~5 min, do not move motor)',
            0   # persistent until next message
        )
        self._logic.stopRequested = False
        self._logic.sig_run_calibration.emit(motor)

    def _zero_clicked(self):
        motor = self._current_motor()
        self.sigZeroMotor.emit(motor)
        self._logic._current_positions[motor] = 0.0
        self._slider_updating = True
        self._mw.slider.setValue(0)
        self._slider_updating = False
        self._mw.value_spinbox.setValue(0.0)
        self._mw.statusBar().showMessage(
            f'Zeroing motor {motor}…  (queued, hardware running in background)', 5000
        )
        self._refresh_position_display()

    def _restore_view(self):
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self._mw.control_dock)
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self._mw.calibration_dock)
        self._mw.splitDockWidget(
            self._mw.control_dock, self._mw.calibration_dock, QtCore.Qt.Vertical
        )
        self._mw.control_dock.show()
        self._mw.calibration_dock.show()
