# -*- coding: utf-8 -*-
"""
GUI module for the CRC (Charge Resonance Check) STM32 controller.

Follows standard Qudi GUI conventions:
  - QMainWindow with dock widgets
  - No custom stylesheet (inherits Qudi application theme)
  - All hardware calls routed through queued signals

ON/OFF works by setting kick = 0 (OFF) or restoring the configured kick (ON).

Example config:

crc_gui:
    module.Class: 'crc.crc_gui.CRCGui'
    connect:
        crc_logic: 'crc_logic'
"""

from PySide2 import QtCore, QtGui, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.core.statusvariable import StatusVar


class CRCMainWindow(QtWidgets.QMainWindow):
    """Main window for the CRC controller GUI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('qudi: CRC Controller')
        self.setMinimumWidth(340)
        self.setDockNestingEnabled(True)

        self._build_menu()
        self._build_control_dock()
        self._build_status_bar()

        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock)

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

    # ------------------------------------------------------------------
    def _build_control_dock(self):
        self.control_dock = QtWidgets.QDockWidget('CRC Control', self)
        self.control_dock.setObjectName('crc_control_dock')
        self.control_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable
        )

        contents = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(contents)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Enable / Disable ─────────────────────────────────────────
        toggle_group = QtWidgets.QGroupBox('Output')
        toggle_layout = QtWidgets.QHBoxLayout(toggle_group)

        self.enable_button = QtWidgets.QPushButton('Enable CRC')
        self.enable_button.setCheckable(True)
        self.enable_button.setMinimumHeight(36)
        font = QtGui.QFont()
        font.setBold(True)
        self.enable_button.setFont(font)
        toggle_layout.addWidget(self.enable_button)

        self.state_label = QtWidgets.QLabel('DISABLED')
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        font2 = QtGui.QFont()
        font2.setBold(True)
        font2.setPointSize(11)
        self.state_label.setFont(font2)
        toggle_layout.addWidget(self.state_label)

        layout.addWidget(toggle_group)

        # ── Parameters ───────────────────────────────────────────────
        param_group = QtWidgets.QGroupBox('Parameters')
        form = QtWidgets.QFormLayout(param_group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(6)

        self.threshold_spinbox = QtWidgets.QSpinBox()
        self.threshold_spinbox.setRange(1, 100_000)
        self.threshold_spinbox.setSuffix('  counts')
        self.threshold_spinbox.setToolTip(
            'Photon count threshold — CRC fires a kick when counts in one\n'
            'interval fall BELOW this value (dark state).'
        )
        form.addRow('Threshold:', self.threshold_spinbox)

        self.kick_spinbox = QtWidgets.QSpinBox()
        self.kick_spinbox.setRange(1, 1_000_000)
        self.kick_spinbox.setSuffix('  µs')
        self.kick_spinbox.setToolTip(
            'Duration of the kick pulse (µs).\n'
            'Set to 0 to disable — this button handles that automatically.'
        )
        form.addRow('Kick duration:', self.kick_spinbox)

        self.interval_spinbox = QtWidgets.QSpinBox()
        self.interval_spinbox.setRange(1, 1_000_000)
        self.interval_spinbox.setSuffix('  µs')
        self.interval_spinbox.setToolTip('Detection window between CRC checks (µs).')
        form.addRow('Check interval:', self.interval_spinbox)

        layout.addWidget(param_group)

        # ── Buttons ──────────────────────────────────────────────────
        btn_layout = QtWidgets.QHBoxLayout()

        self.apply_button = QtWidgets.QPushButton('Apply')
        self.apply_button.setToolTip('Send parameters to hardware.')
        btn_layout.addWidget(self.apply_button)

        self.refresh_button = QtWidgets.QPushButton('Refresh')
        self.refresh_button.setToolTip('Read back current state.')
        btn_layout.addWidget(self.refresh_button)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self.control_dock.setWidget(contents)

    # ------------------------------------------------------------------
    def _build_status_bar(self):
        status_bar = QtWidgets.QStatusBar(self)
        status_bar.setStyleSheet('QStatusBar::item { border: 0px }')
        self.setStatusBar(status_bar)

        # Permanent indicator on the right side of the status bar
        self.status_indicator = QtWidgets.QLabel('CRC: DISABLED')
        font = QtGui.QFont()
        font.setBold(True)
        self.status_indicator.setFont(font)
        status_bar.addPermanentWidget(self.status_indicator)

    # ------------------------------------------------------------------
    def update_state_display(self, enabled: bool):
        """Update all state-dependent visual indicators."""
        if enabled:
            self.state_label.setText('ENABLED')
            self.state_label.setStyleSheet('color: #46a046;')   # green
            self.enable_button.setText('Disable CRC')
            self.enable_button.setStyleSheet('color: #d05050; font-weight: bold;')
            self.status_indicator.setText('CRC: ENABLED')
            self.status_indicator.setStyleSheet('color: #46a046; font-weight: bold;')
        else:
            self.state_label.setText('DISABLED')
            self.state_label.setStyleSheet('color: #a04040;')   # red
            self.enable_button.setText('Enable CRC')
            self.enable_button.setStyleSheet('color: #46a046; font-weight: bold;')
            self.status_indicator.setText('CRC: DISABLED')
            self.status_indicator.setStyleSheet('color: #a04040; font-weight: bold;')


class CRCGui(GuiBase):
    """Qudi GUI module for the CRC (Charge Resonance Check) STM32 controller.

    Enable/disable works by sending K0 (disabled) or K<kick> (enabled) to the
    firmware — no special E/D command required.

    Example config::

        crc_gui:
            module.Class: 'crc.crc_gui.CRCGui'
            connect:
                crc_logic: 'crc_logic'
    """

    crc_logic = Connector(interface='CRCLogic')

    # GUI → Logic (queued)
    sigSetEnabled    = QtCore.Signal(bool)
    sigApply         = QtCore.Signal(int, int, int)   # threshold, kick, interval
    sigRefresh       = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._logic = None

    def on_activate(self):
        self._logic = self.crc_logic()
        self._mw = CRCMainWindow()
        self._restore_window_geometry(self._mw)

        # GUI → Logic (queued — hardware stays in logic thread)
        self.sigSetEnabled.connect(self._logic.set_enabled,      QtCore.Qt.QueuedConnection)
        self.sigApply.connect(     self._logic.apply_parameters, QtCore.Qt.QueuedConnection)
        self.sigRefresh.connect(   self._logic.request_status,   QtCore.Qt.QueuedConnection)

        # Logic → GUI
        self._logic.sigStatusUpdated.connect(
            self._on_status_updated, QtCore.Qt.QueuedConnection
        )

        # Widget interactions
        self._mw.enable_button.clicked.connect(self._toggle_clicked)
        self._mw.apply_button.clicked.connect(self._apply_clicked)
        self._mw.refresh_button.clicked.connect(self._refresh_clicked)
        self._mw.action_restore.triggered.connect(self._restore_view)

        # Pull initial state
        self.sigRefresh.emit()
        self.show()

    def on_deactivate(self):
        self._save_window_geometry(self._mw)
        for sig in (self.sigSetEnabled, self.sigApply, self.sigRefresh):
            try:
                sig.disconnect()
            except RuntimeError:
                pass
        try:
            self._logic.sigStatusUpdated.disconnect(self._on_status_updated)
        except RuntimeError:
            pass
        self._mw.close()
        self._mw = None

    def show(self):
        """Make window visible and bring to front."""
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    # ------------------------------------------------------------------
    # Widget handlers
    # ------------------------------------------------------------------

    def _toggle_clicked(self, checked: bool):
        """Enable or disable the CRC output (kick = 0 when disabled)."""
        # Disable button immediately to prevent double-clicks during hardware call
        self._mw.enable_button.setEnabled(False)
        self._mw.statusBar().showMessage(
            'Enabling CRC output...' if checked else 'Disabling CRC (kick → 0, threshold → 0)...',
            4000
        )
        self.sigSetEnabled.emit(checked)

    def _apply_clicked(self):
        threshold = self._mw.threshold_spinbox.value()
        kick      = self._mw.kick_spinbox.value()
        interval  = self._mw.interval_spinbox.value()
        self._mw.statusBar().showMessage('Applying parameters to hardware...', 4000)
        self.sigApply.emit(threshold, kick, interval)

    def _refresh_clicked(self):
        self._mw.statusBar().showMessage('Refreshing...', 2000)
        self.sigRefresh.emit()

    def _restore_view(self):
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self._mw.control_dock)
        self._mw.control_dock.show()

    # ------------------------------------------------------------------
    # Status update from logic
    # ------------------------------------------------------------------

    @QtCore.Slot(object)
    def _on_status_updated(self, status: dict):
        enabled   = bool(status.get('enabled',   False))
        threshold = int(status.get('threshold',  1))
        kick      = int(status.get('kick',       10))
        interval  = int(status.get('interval',   500))

        # Update spinboxes without triggering their signals
        for widget, val in [
            (self._mw.threshold_spinbox, threshold),
            (self._mw.kick_spinbox,      kick),
            (self._mw.interval_spinbox,  interval),
        ]:
            widget.blockSignals(True)
            widget.setValue(val)
            widget.blockSignals(False)

        # Update toggle button state without re-triggering _toggle_clicked
        self._mw.enable_button.blockSignals(True)
        self._mw.enable_button.setChecked(enabled)
        self._mw.enable_button.blockSignals(False)

        # Re-enable button after hardware confirmed
        self._mw.enable_button.setEnabled(True)

        # Update all visual state indicators
        self._mw.update_state_display(enabled)

        self._mw.statusBar().showMessage(
            f'CRC {"ON" if enabled else "OFF"} — '
            f'threshold={"0 (off)" if not enabled else f"{threshold} cts"}, '
            f'kick={"0 (off)" if not enabled else f"{kick} µs"}, '
            f'interval={interval} µs',
            6000
        )
