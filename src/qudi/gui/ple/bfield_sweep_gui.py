# -*- coding: utf-8 -*-
"""
Dockable pyqtgraph GUI for synchronized B-field sweeps with PLE scans.

Example config:

bfield_sweep_gui:
    module.Class: 'ple.bfield_sweep_gui.BFieldSweepGui'
    connect:
        bfield_sweep_logic: 'bfield_sweep_logic'
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide2 import QtCore, QtGui, QtWidgets

import qudi.util.uic as uic
from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.core.statusvariable import StatusVar


class BFieldSweepMainWindow(QtWidgets.QMainWindow):
    """Main window with compact dock widgets for B-field sweep control."""

    def __init__(self):
        super().__init__()
        self.setObjectName("BFieldSweepMainWindow")
        self.setWindowTitle("B-Field Sweep")
        self.resize(1300, 850)
        self.setDockNestingEnabled(True)

        self._build_actions()
        self._build_layout()

    def _build_actions(self):
        self.action_start = QtWidgets.QAction("Start Sweep", self)
        self.action_stop = QtWidgets.QAction("Stop Sweep", self)
        self.action_save = QtWidgets.QAction("Save Summary", self)

        run_menu = self.menuBar().addMenu("Run")
        run_menu.addAction(self.action_start)
        run_menu.addAction(self.action_stop)

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.action_save)

        toolbar = self.addToolBar("Sweep")
        toolbar.setObjectName("BFieldSweepToolbar")
        toolbar.addAction(self.action_start)
        toolbar.addAction(self.action_stop)
        toolbar.addSeparator()
        toolbar.addAction(self.action_save)

    def _build_layout(self):
        # Empty central widget. All content is in docks for flexible tabbing/floating.
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        central.hide()

        self._create_control_dock()
        self._create_status_dock()
        self._create_plot_docks()
        self._create_save_dock()

        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.status_dock)
        self.splitDockWidget(self.control_dock, self.status_dock, QtCore.Qt.Vertical)

        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.fit_plot_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.count_plot_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.coord_plot_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.matrix_plot_dock)
        self.tabifyDockWidget(self.fit_plot_dock, self.count_plot_dock)
        self.tabifyDockWidget(self.count_plot_dock, self.coord_plot_dock)
        self.tabifyDockWidget(self.coord_plot_dock, self.matrix_plot_dock)
        self.matrix_plot_dock.raise_()

        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.save_path_widget)

    def _create_control_dock(self):
        self.control_dock = QtWidgets.QDockWidget("Sweep Control", self)
        self.control_dock.setObjectName("BFieldSweepControlDock")
        widget = QtWidgets.QWidget(self.control_dock)
        form = QtWidgets.QFormLayout(widget)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.plane_combo = QtWidgets.QComboBox(widget)
        self.plane_combo.addItems(["XY", "XZ", "YZ"])

        self.amplitude_spin = QtWidgets.QDoubleSpinBox(widget)
        self.amplitude_spin.setDecimals(4)
        self.amplitude_spin.setRange(0.0, 10.0)
        self.amplitude_spin.setSingleStep(0.01)
        self.amplitude_spin.setSuffix(" T")

        self.steps_spin = QtWidgets.QSpinBox(widget)
        self.steps_spin.setRange(2, 5000)

        self.start_angle_spin = QtWidgets.QDoubleSpinBox(widget)
        self.start_angle_spin.setDecimals(2)
        self.start_angle_spin.setRange(-3600.0, 3600.0)
        self.start_angle_spin.setSuffix(" deg")

        self.stop_angle_spin = QtWidgets.QDoubleSpinBox(widget)
        self.stop_angle_spin.setDecimals(2)
        self.stop_angle_spin.setRange(-3600.0, 3600.0)
        self.stop_angle_spin.setSuffix(" deg")

        self.offset_bx_spin = QtWidgets.QDoubleSpinBox(widget)
        self.offset_by_spin = QtWidgets.QDoubleSpinBox(widget)
        self.offset_bz_spin = QtWidgets.QDoubleSpinBox(widget)
        for spin in (self.offset_bx_spin, self.offset_by_spin, self.offset_bz_spin):
            spin.setDecimals(4)
            spin.setRange(-10.0, 10.0)
            spin.setSingleStep(0.005)
            spin.setSuffix(" T")

        self.scan_axis_combo = QtWidgets.QComboBox(widget)
        self.fit_config_edit = QtWidgets.QLineEdit(widget)
        self.fit_channel_edit = QtWidgets.QLineEdit(widget)
        self.fit_channel_edit.setPlaceholderText("auto")

        self.do_fit_checkbox = QtWidgets.QCheckBox("Enable fit", widget)
        self.fit_averaged_checkbox = QtWidgets.QCheckBox("Fit averaged data", widget)

        self.ple_repeats_spin = QtWidgets.QSpinBox(widget)
        self.ple_repeats_spin.setRange(1, 100000)

        self.save_each_ple_checkbox = QtWidgets.QCheckBox("Save each PLE point", widget)
        self.auto_save_checkbox = QtWidgets.QCheckBox("Auto-save at end", widget)
        self.save_last_ple_checkbox = QtWidgets.QCheckBox("Include last PLE in manual save", widget)
        self.save_last_ple_checkbox.setChecked(True)

        self.start_button = QtWidgets.QPushButton("Start", widget)
        self.stop_button = QtWidgets.QPushButton("Stop", widget)
        self.stop_button.setEnabled(False)

        self.progress_bar = QtWidgets.QProgressBar(widget)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)

        form.addRow("Plane", self.plane_combo)
        form.addRow("Amplitude", self.amplitude_spin)
        form.addRow("Steps", self.steps_spin)
        form.addRow("Start angle", self.start_angle_spin)
        form.addRow("Stop angle", self.stop_angle_spin)
        form.addRow("Bx offset", self.offset_bx_spin)
        form.addRow("By offset", self.offset_by_spin)
        form.addRow("Bz offset", self.offset_bz_spin)
        form.addRow("PLE axis", self.scan_axis_combo)
        form.addRow("Fit config", self.fit_config_edit)
        form.addRow("Fit channel", self.fit_channel_edit)
        form.addRow("PLE repeats", self.ple_repeats_spin)
        form.addRow(self.do_fit_checkbox)
        form.addRow(self.fit_averaged_checkbox)
        form.addRow(self.save_each_ple_checkbox)
        form.addRow(self.auto_save_checkbox)
        form.addRow(self.save_last_ple_checkbox)
        form.addRow("Progress", self.progress_bar)
        form.addRow(buttons)

        self.control_dock.setWidget(widget)

    def _create_status_dock(self):
        self.status_dock = QtWidgets.QDockWidget("Live Status", self)
        self.status_dock.setObjectName("BFieldSweepStatusDock")
        widget = QtWidgets.QWidget(self.status_dock)
        form = QtWidgets.QFormLayout(widget)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.stage_label = QtWidgets.QLabel("idle", widget)
        self.step_label = QtWidgets.QLabel("0 / 0", widget)
        self.angle_label = QtWidgets.QLabel("nan deg", widget)
        self.fit_center_label = QtWidgets.QLabel("nan", widget)
        self.peak_counts_label = QtWidgets.QLabel("nan", widget)
        self.target_cart_label = QtWidgets.QLabel("(nan, nan, nan) T", widget)
        self.target_sph_label = QtWidgets.QLabel("(nan, nan, nan)", widget)
        self.actual_cart_label = QtWidgets.QLabel("(nan, nan, nan) T", widget)
        self.actual_sph_label = QtWidgets.QLabel("(nan, nan, nan)", widget)
        self.ramp_state_label = QtWidgets.QLabel("-", widget)

        form.addRow("Stage", self.stage_label)
        form.addRow("Point", self.step_label)
        form.addRow("Polar angle", self.angle_label)
        form.addRow("Fit center", self.fit_center_label)
        form.addRow("Peak counts", self.peak_counts_label)
        form.addRow("Target Bx,By,Bz", self.target_cart_label)
        form.addRow("Target r,theta,phi", self.target_sph_label)
        form.addRow("Actual Bx,By,Bz", self.actual_cart_label)
        form.addRow("Actual r,theta,phi", self.actual_sph_label)
        form.addRow("Ramp state", self.ramp_state_label)

        self.status_dock.setWidget(widget)

    def _create_plot_docks(self):
        self.fit_plot_dock = QtWidgets.QDockWidget("Fit Center vs Angle", self)
        self.fit_plot_dock.setObjectName("BFieldSweepFitPlotDock")
        self.fit_plot = pg.PlotWidget()
        self.fit_plot.showGrid(x=True, y=True, alpha=0.3)
        self.fit_plot.setLabel("bottom", "Polar angle", units="deg")
        self.fit_plot.setLabel("left", "Fit center")
        self.fit_curve = self.fit_plot.plot(
            pen=pg.mkPen("#42b883", width=2), symbol="o", symbolSize=6
        )
        self.fit_plot_dock.setWidget(self.fit_plot)

        self.count_plot_dock = QtWidgets.QDockWidget("Peak Counts vs Angle", self)
        self.count_plot_dock.setObjectName("BFieldSweepCountPlotDock")
        self.count_plot = pg.PlotWidget()
        self.count_plot.showGrid(x=True, y=True, alpha=0.3)
        self.count_plot.setLabel("bottom", "Polar angle", units="deg")
        self.count_plot.setLabel("left", "Peak counts")
        self.count_curve = self.count_plot.plot(
            pen=pg.mkPen("#4a8fe7", width=2), symbol="o", symbolSize=6
        )
        self.count_plot_dock.setWidget(self.count_plot)

        self.coord_plot_dock = QtWidgets.QDockWidget("B Coordinates vs Point", self)
        self.coord_plot_dock.setObjectName("BFieldSweepCoordPlotDock")
        self.coord_plot = pg.PlotWidget()
        self.coord_plot.showGrid(x=True, y=True, alpha=0.3)
        self.coord_plot.setLabel("bottom", "Point index")
        self.coord_plot.setLabel("left", "B-field", units="T")
        self.coord_plot.addLegend()
        self.bx_target_curve = self.coord_plot.plot(
            pen=pg.mkPen("#e24a33", width=2), name="Bx target"
        )
        self.by_target_curve = self.coord_plot.plot(
            pen=pg.mkPen("#348abd", width=2), name="By target"
        )
        self.bz_target_curve = self.coord_plot.plot(
            pen=pg.mkPen("#988ed5", width=2), name="Bz target"
        )
        self.bx_actual_curve = self.coord_plot.plot(
            pen=pg.mkPen("#e24a33", width=1, style=QtCore.Qt.DashLine),
            name="Bx actual",
        )
        self.by_actual_curve = self.coord_plot.plot(
            pen=pg.mkPen("#348abd", width=1, style=QtCore.Qt.DashLine),
            name="By actual",
        )
        self.bz_actual_curve = self.coord_plot.plot(
            pen=pg.mkPen("#988ed5", width=1, style=QtCore.Qt.DashLine),
            name="Bz actual",
        )
        self.coord_plot_dock.setWidget(self.coord_plot)

        self.matrix_plot_dock = QtWidgets.QDockWidget("PLE Matrix vs B Angle", self)
        self.matrix_plot_dock.setObjectName("BFieldSweepMatrixPlotDock")
        self.matrix_plot = pg.PlotWidget()
        self.matrix_plot.setLabel("bottom", "Frequency")
        self.matrix_plot.setLabel("left", "B-field angle", units="deg")
        self.matrix_plot.showGrid(x=True, y=True, alpha=0.2)
        self.matrix_image = pg.ImageItem(axisOrder="row-major")
        self.matrix_plot.addItem(self.matrix_image)
        self.matrix_plot_dock.setWidget(self.matrix_plot)

    def _create_save_dock(self):
        ui_file = os.path.join(os.path.dirname(__file__), "save_path_widget.ui")
        self.save_path_widget = QtWidgets.QDockWidget()
        self.save_path_widget.setObjectName("BFieldSweepSaveDock")
        uic.loadUi(ui_file, self.save_path_widget)


class BFieldSweepGui(GuiBase):
    """GUI module for BFieldSweepLogic."""

    _logic = Connector(name="bfield_sweep_logic", interface="BFieldSweepLogic")

    _save_folderpath = StatusVar("save_folderpath", default=None)
    _window_state = StatusVar("window_state", default=None)

    sigStartSweep = QtCore.Signal(object)
    sigStopSweep = QtCore.Signal()
    sigSaveSweep = QtCore.Signal(str, object, bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw: Optional[BFieldSweepMainWindow] = None

    def on_activate(self):
        pg.setConfigOptions(antialias=True)

        self._mw = BFieldSweepMainWindow()
        self._restore_window_geometry(self._mw)

        logic = self._logic()
        defaults = logic.get_default_settings()
        self._apply_defaults(defaults)
        self._refresh_scan_axes(defaults.get("scan_axis", ""))

        # Save dock path behavior mirrors other Qudi GUI modules (PLE/ODMR/etc.).
        self._mw.save_path_widget.currPathLabel.setText(
            "Default" if self._save_folderpath is None else self._save_folderpath
        )
        self._mw.save_path_widget.DailyPathCheckBox.clicked.connect(
            lambda: self._mw.save_path_widget.newPathCheckBox.setEnabled(
                not self._mw.save_path_widget.DailyPathCheckBox.isChecked()
            )
        )
        if self._save_folderpath is None:
            self._mw.save_path_widget.DailyPathCheckBox.setChecked(True)
            self._mw.save_path_widget.DailyPathCheckBox.clicked.emit()

        # GUI interactions
        self._mw.start_button.clicked.connect(self._start_clicked)
        self._mw.stop_button.clicked.connect(self._stop_clicked)
        self._mw.action_start.triggered.connect(self._start_clicked)
        self._mw.action_stop.triggered.connect(self._stop_clicked)
        self._mw.action_save.triggered.connect(self._save_clicked)

        # GUI -> logic
        self.sigStartSweep.connect(logic.start_sweep, QtCore.Qt.QueuedConnection)
        self.sigStopSweep.connect(logic.stop_sweep, QtCore.Qt.QueuedConnection)
        self.sigSaveSweep.connect(logic.save_results, QtCore.Qt.QueuedConnection)

        # Logic -> GUI
        logic.sigSweepStateChanged.connect(
            self._on_sweep_state_changed, QtCore.Qt.QueuedConnection
        )
        logic.sigProgressChanged.connect(self._on_progress, QtCore.Qt.QueuedConnection)
        logic.sigResultsChanged.connect(self._on_results, QtCore.Qt.QueuedConnection)
        logic.sigCurrentFieldChanged.connect(
            self._on_current_field, QtCore.Qt.QueuedConnection
        )
        logic.sigSaveFinished.connect(self._on_save_finished, QtCore.Qt.QueuedConnection)
        logic.sigMessage.connect(self._set_status_text, QtCore.Qt.QueuedConnection)

        self._on_sweep_state_changed(False)
        self.show()

    def on_deactivate(self):
        if self._mw is None:
            return

        logic = self._logic()
        try:
            self.sigStartSweep.disconnect()
            self.sigStopSweep.disconnect()
            self.sigSaveSweep.disconnect()
        except RuntimeError:
            pass

        for signal, slot in (
            (logic.sigSweepStateChanged, self._on_sweep_state_changed),
            (logic.sigProgressChanged, self._on_progress),
            (logic.sigResultsChanged, self._on_results),
            (logic.sigCurrentFieldChanged, self._on_current_field),
            (logic.sigSaveFinished, self._on_save_finished),
            (logic.sigMessage, self._set_status_text),
        ):
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass

        for signal in (
            self._mw.start_button.clicked,
            self._mw.stop_button.clicked,
            self._mw.action_start.triggered,
            self._mw.action_stop.triggered,
            self._mw.action_save.triggered,
        ):
            try:
                signal.disconnect()
            except RuntimeError:
                pass

        self._save_window_geometry(self._mw)
        self._mw.close()
        self._mw = None

    def show(self):
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _apply_defaults(self, defaults: Dict[str, Any]):
        self._mw.plane_combo.setCurrentText(str(defaults.get("plane", "XY")).upper())
        self._mw.amplitude_spin.setValue(float(defaults.get("amplitude_t", 0.2)))
        self._mw.steps_spin.setValue(int(defaults.get("steps", 121)))
        self._mw.start_angle_spin.setValue(float(defaults.get("start_angle_deg", 0.0)))
        self._mw.stop_angle_spin.setValue(float(defaults.get("stop_angle_deg", 360.0)))
        self._mw.offset_bx_spin.setValue(float(defaults.get("bx_offset_t", 0.0)))
        self._mw.offset_by_spin.setValue(float(defaults.get("by_offset_t", 0.0)))
        self._mw.offset_bz_spin.setValue(float(defaults.get("bz_offset_t", 0.0)))
        self._mw.fit_config_edit.setText(str(defaults.get("fit_config", "TwoLorentz")))
        self._mw.fit_channel_edit.setText(str(defaults.get("fit_channel", "")).strip())
        self._mw.ple_repeats_spin.setValue(int(defaults.get("ple_repeats", 1)))
        self._mw.do_fit_checkbox.setChecked(bool(defaults.get("do_fit", True)))
        self._mw.fit_averaged_checkbox.setChecked(bool(defaults.get("fit_averaged", False)))
        self._mw.save_each_ple_checkbox.setChecked(
            bool(defaults.get("save_each_ple_scan", False))
        )
        self._mw.auto_save_checkbox.setChecked(bool(defaults.get("auto_save", False)))
        self._mw.save_last_ple_checkbox.setChecked(
            bool(defaults.get("save_last_ple", True))
        )
        self._mw.save_path_widget.saveTagLineEdit.setText(str(defaults.get("tag", "")))

    def _refresh_scan_axes(self, preferred_axis: str = ""):
        axes = self._logic().get_available_scan_axes()
        self._mw.scan_axis_combo.blockSignals(True)
        self._mw.scan_axis_combo.clear()
        self._mw.scan_axis_combo.addItems(axes if len(axes) else [""])
        if preferred_axis and preferred_axis in axes:
            self._mw.scan_axis_combo.setCurrentText(preferred_axis)
        self._mw.scan_axis_combo.blockSignals(False)

    def _start_clicked(self):
        settings = self._collect_settings()
        self.sigStartSweep.emit(settings)

    def _stop_clicked(self):
        self.sigStopSweep.emit()

    def _save_clicked(self):
        root_dir = self._resolve_save_root(prompt_for_new=True)
        tag = self._mw.save_path_widget.saveTagLineEdit.text().strip()
        include_last_ple = self._mw.save_last_ple_checkbox.isChecked()
        self.sigSaveSweep.emit(tag, root_dir, include_last_ple)

    def _collect_settings(self):
        root_dir = self._resolve_save_root(prompt_for_new=False)
        return {
            "plane": self._mw.plane_combo.currentText(),
            "amplitude_t": float(self._mw.amplitude_spin.value()),
            "steps": int(self._mw.steps_spin.value()),
            "start_angle_deg": float(self._mw.start_angle_spin.value()),
            "stop_angle_deg": float(self._mw.stop_angle_spin.value()),
            "bx_offset_t": float(self._mw.offset_bx_spin.value()),
            "by_offset_t": float(self._mw.offset_by_spin.value()),
            "bz_offset_t": float(self._mw.offset_bz_spin.value()),
            "scan_axis": self._mw.scan_axis_combo.currentText().strip(),
            "fit_config": self._mw.fit_config_edit.text().strip(),
            "fit_channel": self._mw.fit_channel_edit.text().strip(),
            "do_fit": self._mw.do_fit_checkbox.isChecked(),
            "fit_averaged": self._mw.fit_averaged_checkbox.isChecked(),
            "ple_repeats": int(self._mw.ple_repeats_spin.value()),
            "save_each_ple_scan": self._mw.save_each_ple_checkbox.isChecked(),
            "auto_save": self._mw.auto_save_checkbox.isChecked(),
            "save_last_ple": self._mw.save_last_ple_checkbox.isChecked(),
            "tag": self._mw.save_path_widget.saveTagLineEdit.text().strip(),
            "root_dir": root_dir,
        }

    def _resolve_save_root(self, prompt_for_new: bool):
        save_widget = self._mw.save_path_widget

        if save_widget.DailyPathCheckBox.isChecked():
            self._save_folderpath = None
            save_widget.currPathLabel.setText("Default")
            return None

        if (
            prompt_for_new
            and save_widget.newPathCheckBox.isChecked()
            and save_widget.newPathCheckBox.isEnabled()
        ):
            new_path = QtWidgets.QFileDialog.getExistingDirectory(
                self._mw, "Select Folder"
            )
            if new_path:
                self._save_folderpath = new_path
                save_widget.currPathLabel.setText(self._save_folderpath)
                save_widget.newPathCheckBox.setChecked(False)
                return self._save_folderpath
            return self._save_folderpath

        return self._save_folderpath

    @QtCore.Slot(bool)
    def _on_sweep_state_changed(self, running: bool):
        self._mw.start_button.setEnabled(not running)
        self._mw.stop_button.setEnabled(running)
        self._mw.action_start.setEnabled(not running)
        self._mw.action_stop.setEnabled(running)
        if not running:
            self._mw.progress_bar.setFormat("%p%")

    @QtCore.Slot(object)
    def _on_progress(self, payload):
        if not isinstance(payload, dict):
            return
        stage = str(payload.get("stage", ""))
        index = int(payload.get("index", 0))
        total = int(payload.get("total", 0))
        angle = float(payload.get("angle_deg", np.nan))

        self._mw.stage_label.setText(stage)
        self._mw.step_label.setText(f"{index + 1 if total else 0} / {total}")
        self._mw.angle_label.setText(self._fmt(angle, 3, " deg"))

        if total > 0:
            self._mw.progress_bar.setRange(0, total)
            self._mw.progress_bar.setValue(min(max(index + 1, 0), total))
        else:
            self._mw.progress_bar.setRange(0, 1)
            self._mw.progress_bar.setValue(0)

        target = np.asarray(payload.get("target_field_t", [np.nan, np.nan, np.nan]), dtype=float)
        target_sph = np.asarray(
            payload.get("target_spherical", [np.nan, np.nan, np.nan]), dtype=float
        )
        self._mw.target_cart_label.setText(
            "({:.4f}, {:.4f}, {:.4f}) T".format(target[0], target[1], target[2])
        )
        self._mw.target_sph_label.setText(
            "({:.4f} T, {:.2f} deg, {:.2f} deg)".format(
                target_sph[0], target_sph[1], target_sph[2]
            )
        )

        ramp_state = payload.get("ramping_state", [])
        self._mw.ramp_state_label.setText(str(ramp_state))

    @QtCore.Slot(object)
    def _on_results(self, payload):
        if not isinstance(payload, dict):
            return
        results = payload.get("results", [])
        if len(results) == 0:
            self._mw.fit_curve.setData([], [])
            self._mw.count_curve.setData([], [])
            self._mw.bx_target_curve.setData([], [])
            self._mw.by_target_curve.setData([], [])
            self._mw.bz_target_curve.setData([], [])
            self._mw.bx_actual_curve.setData([], [])
            self._mw.by_actual_curve.setData([], [])
            self._mw.bz_actual_curve.setData([], [])
            self._mw.matrix_image.setImage(
                np.array([[np.nan]], dtype=float), autoLevels=True
            )
            self._mw.matrix_image.setTransform(QtGui.QTransform())
            self._mw.fit_center_label.setText("nan")
            self._mw.peak_counts_label.setText("nan")
            return

        idx = np.asarray([r["index"] for r in results], dtype=float)
        angle = np.asarray([r["angle_deg"] for r in results], dtype=float)
        fit_center = np.asarray([r["fit_center"] for r in results], dtype=float)
        peak_counts = np.asarray([r["peak_counts"] for r in results], dtype=float)
        target = np.asarray([r["target_field_t"] for r in results], dtype=float)
        actual = np.asarray([r["actual_field_t"] for r in results], dtype=float)

        self._mw.fit_curve.setData(angle, fit_center)
        self._mw.count_curve.setData(angle, peak_counts)
        self._mw.bx_target_curve.setData(idx, target[:, 0])
        self._mw.by_target_curve.setData(idx, target[:, 1])
        self._mw.bz_target_curve.setData(idx, target[:, 2])
        self._mw.bx_actual_curve.setData(idx, actual[:, 0])
        self._mw.by_actual_curve.setData(idx, actual[:, 1])
        self._mw.bz_actual_curve.setData(idx, actual[:, 2])

        last = results[-1]
        self._mw.fit_center_label.setText(
            self._fmt(last.get("fit_center", np.nan), 6, "")
        )
        self._mw.peak_counts_label.setText(
            self._fmt(last.get("peak_counts", np.nan), 3, "")
        )
        self._update_matrix_plot(results)

    @QtCore.Slot(object)
    def _on_current_field(self, payload):
        if not isinstance(payload, dict):
            return
        field = np.asarray(payload.get("field", [np.nan, np.nan, np.nan]), dtype=float)
        sph = np.asarray(payload.get("spherical", [np.nan, np.nan, np.nan]), dtype=float)

        self._mw.actual_cart_label.setText(
            "({:.4f}, {:.4f}, {:.4f}) T".format(field[0], field[1], field[2])
        )
        self._mw.actual_sph_label.setText(
            "({:.4f} T, {:.2f} deg, {:.2f} deg)".format(sph[0], sph[1], sph[2])
        )

        if "ramping_state" in payload:
            self._mw.ramp_state_label.setText(str(payload["ramping_state"]))

    @QtCore.Slot(object)
    def _on_save_finished(self, payload):
        if isinstance(payload, dict) and "summary_file" in payload:
            self._set_status_text(f"Saved: {payload['summary_file']}")
        else:
            self._set_status_text("Save finished.")

    @QtCore.Slot(str)
    def _set_status_text(self, text: str):
        self._mw.statusBar().showMessage(str(text), 7000)

    def _update_matrix_plot(self, results):
        traces = []
        angles = []
        x_axis_ref = None
        x_unit = ""

        for res in results:
            y_data = np.asarray(res.get("scan_signal", []), dtype=float).ravel()
            x_data = np.asarray(res.get("scan_axis_values", []), dtype=float).ravel()
            angle = float(res.get("angle_deg", np.nan))

            if y_data.size == 0 or not np.isfinite(angle):
                continue
            if x_data.size != y_data.size:
                if x_data.size > 1:
                    x_data = np.linspace(x_data[0], x_data[-1], y_data.size, dtype=float)
                else:
                    x_data = np.arange(y_data.size, dtype=float)
            if x_data.size > 1 and x_data[1] < x_data[0]:
                x_data = x_data[::-1]
                y_data = y_data[::-1]

            if x_axis_ref is None:
                x_axis_ref = x_data
                x_unit = str(res.get("scan_axis_unit", "")).strip()
                traces.append(y_data)
                angles.append(angle)
                continue

            if y_data.size != x_axis_ref.size:
                try:
                    sort_idx = np.argsort(x_data)
                    y_data = np.interp(
                        x_axis_ref,
                        x_data[sort_idx],
                        y_data[sort_idx],
                        left=np.nan,
                        right=np.nan,
                    )
                except Exception:
                    common = int(min(x_axis_ref.size, y_data.size))
                    x_axis_ref = x_axis_ref[:common]
                    traces = [trace[:common] for trace in traces]
                    y_data = y_data[:common]

            traces.append(y_data)
            angles.append(angle)

        if len(traces) == 0:
            self._mw.matrix_image.setImage(np.array([[np.nan]], dtype=float), autoLevels=True)
            self._mw.matrix_image.setTransform(QtGui.QTransform())
            return

        matrix = np.asarray(traces, dtype=float)
        self._mw.matrix_image.setImage(matrix, autoLevels=True)

        x_axis_ref = np.asarray(x_axis_ref, dtype=float)
        angles = np.asarray(angles, dtype=float)

        if x_axis_ref.size > 1:
            dx = float((x_axis_ref[-1] - x_axis_ref[0]) / (x_axis_ref.size - 1))
        else:
            dx = 1.0
        if angles.size > 1:
            dy = float((angles[-1] - angles[0]) / (angles.size - 1))
        else:
            dy = 1.0

        transform = QtGui.QTransform()
        transform.translate(float(x_axis_ref[0]), float(angles[0]))
        transform.scale(dx if dx != 0 else 1.0, dy if dy != 0 else 1.0)
        self._mw.matrix_image.setTransform(transform)

        self._mw.matrix_plot.setLabel("bottom", "Frequency", units=(x_unit or None))
        self._mw.matrix_plot.setLabel("left", "B-field angle", units="deg")
        self._mw.matrix_plot.enableAutoRange()

    @staticmethod
    def _fmt(value, digits, suffix):
        try:
            if np.isnan(float(value)):
                return "nan"
            return f"{float(value):.{int(digits)}f}{suffix}"
        except Exception:
            return "nan"
