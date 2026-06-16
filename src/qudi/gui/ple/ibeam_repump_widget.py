# -*- coding: utf-8 -*-
"""
GUI widget for the iBeam Smart repump dock widget inside the PLE GUI.

Provides:
  - CW Enable toggle checkbox
  - Power spinbox (µW)
  - Line Repump checkbox
  - Line Repump duration spinbox (s)
"""

from PySide2 import QtCore, QtWidgets
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox


class IBeamRepumpWidget(QtWidgets.QWidget):
    """Compact widget for controlling the iBeam Smart repump laser."""

    # ── signals ─────────────────────────────────────────────────────────────
    sigCwToggled = QtCore.Signal(bool)
    sigPowerChanged = QtCore.Signal(float)
    sigLineRepumpToggled = QtCore.Signal(bool)
    sigConditionalRepumpToggled = QtCore.Signal(bool)
    sigLineRepumpDurationChanged = QtCore.Signal(float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._build_ui()
        self._connect_internal()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ── CW row ──────────────────────────────────────────────────────────
        cw_row = QtWidgets.QHBoxLayout()

        self.cw_checkBox = QtWidgets.QCheckBox("CW Enable")
        self.cw_checkBox.setToolTip("Toggle iBeam Smart CW output on / off")
        cw_row.addWidget(self.cw_checkBox)

        cw_row.addWidget(QtWidgets.QLabel("Power:"))

        self.power_spinbox = ScienDSpinBox()
        self.power_spinbox.setRange(0.01, 100000.0)
        self.power_spinbox.setDecimals(2)
        self.power_spinbox.setSuffix('µW')
        self.power_spinbox.setValue(1000.0)
        self.power_spinbox.setMinimumWidth(90)
        self.power_spinbox.setToolTip("iBeam output power in µW")
        cw_row.addWidget(self.power_spinbox)
        cw_row.addStretch()

        main_layout.addLayout(cw_row)

        # ── Line Repump row ──────────────────────────────────────────────────
        lr_row = QtWidgets.QHBoxLayout()

        self.line_repump_checkBox = QtWidgets.QCheckBox("Line Repump")
        self.line_repump_checkBox.setToolTip(
            "When checked, the iBeam fires for the set duration after each scan line"
        )
        lr_row.addWidget(self.line_repump_checkBox)

        lr_row.addWidget(QtWidgets.QLabel("Duration:"))

        self.duration_spinbox = ScienDSpinBox()
        self.duration_spinbox.setRange(0.0, 60.0)
        self.duration_spinbox.setDecimals(3)
        self.duration_spinbox.setSuffix('s')
        self.duration_spinbox.setValue(0.5)
        self.duration_spinbox.setMinimumWidth(80)
        self.duration_spinbox.setToolTip("Duration of each line-repump pulse in seconds")
        lr_row.addWidget(self.duration_spinbox)
        lr_row.addStretch()

        main_layout.addLayout(lr_row)
        
        # ── Conditional Repump row ───────────────────────────────────────────
        cond_row = QtWidgets.QHBoxLayout()
        self.conditional_repump_checkBox = QtWidgets.QCheckBox("Conditional (on Fit Fail)")
        self.conditional_repump_checkBox.setToolTip(
            "If checked, repump only triggers when the GUI's selected Fit fails (e.g., defect ionized)."
        )
        cond_row.addWidget(self.conditional_repump_checkBox)
        cond_row.addStretch()
        main_layout.addLayout(cond_row)
        
        main_layout.addStretch()

    def _connect_internal(self):
        """Wire widget signals to external signals."""
        self.cw_checkBox.toggled.connect(self.sigCwToggled)
        self.power_spinbox.editingFinished.connect(
            lambda: self.sigPowerChanged.emit(self.power_spinbox.value())
        )
        self.line_repump_checkBox.toggled.connect(self.sigLineRepumpToggled)
        self.conditional_repump_checkBox.toggled.connect(self.sigConditionalRepumpToggled)
        self.duration_spinbox.editingFinished.connect(
            lambda: self.sigLineRepumpDurationChanged.emit(self.duration_spinbox.value())
        )

    # ── public slot ──────────────────────────────────────────────────────────

    @QtCore.Slot(bool, float)
    def update_state(self, cw_enabled: bool, power_uW: float):
        """Refresh widget values from logic without triggering outgoing signals."""
        self.cw_checkBox.blockSignals(True)
        self.power_spinbox.blockSignals(True)
        self.cw_checkBox.setChecked(cw_enabled)
        self.power_spinbox.setValue(power_uW)
        self.cw_checkBox.blockSignals(False)
        self.power_spinbox.blockSignals(False)
