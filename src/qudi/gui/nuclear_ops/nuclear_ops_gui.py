"""NuclearOps experiment editor, persistent queue and live numerical plots."""
import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide2 import QtCore, QtWidgets

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.logic.nuclear_ops.models import ExperimentSpec
from qudi.logic.nuclear_ops.thresholds import ReadoutThresholdProfile
from qudi.logic.nuclear_ops.hdf5_store import NuclearDataset


class NuclearOpsGui(GuiBase):
    queue = Connector(interface="ExperimentQueueLogic")
    runner = Connector(interface="NuclearOperationsLogic")
    calibration = Connector(interface="ReadoutCalibrationLogic")
    sigEnqueue = QtCore.Signal(object)
    sigStart = QtCore.Signal()
    sigPause = QtCore.Signal()
    sigResume = QtCore.Signal()
    sigCancel = QtCore.Signal()
    sigRemove = QtCore.Signal(str)
    sigQueuePaused = QtCore.Signal(bool)
    sigProfile = QtCore.Signal(object)

    def on_activate(self):
        self._connections = []
        self._items = []
        self._dataset = None
        self._analysis = None
        self._mw = QtWidgets.QMainWindow()
        self._mw.setWindowTitle("tinOps — Nuclear Operations")
        self._mw.resize(1200, 820)
        central = QtWidgets.QWidget()
        self._mw.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        dummy = self.runner().is_dummy
        self.banner = QtWidgets.QLabel("DUMMY MODE • Synthetic data • No devices connected" if dummy else "LIVE HARDWARE MODE")
        self.banner.setStyleSheet("padding:12px;background:#254f68;color:white;font-size:17px;font-weight:bold")
        layout.addWidget(self.banner)
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)
        experiments = QtWidgets.QWidget()
        el = QtWidgets.QVBoxLayout(experiments)
        form = QtWidgets.QHBoxLayout()
        self.recipe = QtWidgets.QComboBox()
        self.recipe.addItems(self.runner().recipe_names)
        form.addWidget(QtWidgets.QLabel("Recipe")); form.addWidget(self.recipe)
        self._button(form, "Load recipe template", self.load_template)
        self._button(form, "Import specification…", self.import_spec)
        self._button(form, "Export specification…", self.export_spec)
        el.addLayout(form)
        el.addWidget(QtWidgets.QLabel("Edit the scan values, integration count and parameters below, then add the experiment to the queue."))
        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setStyleSheet("font-family:Consolas;font-size:12px")
        el.addWidget(self.editor)
        buttons = QtWidgets.QHBoxLayout()
        self._button(buttons, "Add to queue", self.enqueue)
        self._button(buttons, "Start queue", self.sigStart.emit)
        self._button(buttons, "Pause run", self.sigPause.emit)
        self._button(buttons, "Resume run", self.sigResume.emit)
        self._button(buttons, "Cancel run", self.sigCancel.emit)
        self.hold = QtWidgets.QCheckBox("Hold queue")
        self.hold.toggled.connect(self.sigQueuePaused.emit)
        buttons.addWidget(self.hold)
        el.addLayout(buttons)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Experiment", "Status", "Run file", "Error"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        el.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        self._button(row, "Remove selected pending", self.remove_pending)
        self._button(row, "Plot selected result", self.open_selected)
        self._button(row, "Reanalyze selected result", self.reanalyze_selected)
        el.addLayout(row)
        self.progress = QtWidgets.QProgressBar(); el.addWidget(self.progress)
        tabs.addTab(experiments, "Experiments & queue")
        result_tab = QtWidgets.QWidget(); rl = QtWidgets.QVBoxLayout(result_tab)
        selectors = QtWidgets.QHBoxLayout()
        self.xaxis = QtWidgets.QComboBox(); self.yaxis = QtWidgets.QComboBox()
        selectors.addWidget(QtWidgets.QLabel("X")); selectors.addWidget(self.xaxis)
        selectors.addWidget(QtWidgets.QLabel("Y")); selectors.addWidget(self.yaxis)
        self._button(selectors, "Open saved HDF5…", self.open_file)
        rl.addLayout(selectors)
        self.plot = pg.PlotWidget(background="#16222d")
        self.plot.showGrid(x=True, y=True, alpha=.2)
        rl.addWidget(self.plot)
        self.fit_info = QtWidgets.QPlainTextEdit(); self.fit_info.setReadOnly(True)
        self.fit_info.setMaximumHeight(160); rl.addWidget(self.fit_info)
        tabs.addTab(result_tab, "Live results & fits")
        self.xaxis.currentTextChanged.connect(self.draw)
        self.yaxis.currentTextChanged.connect(self.draw)
        threshold_tab = QtWidgets.QWidget(); tl = QtWidgets.QVBoxLayout(threshold_tab)
        tl.addWidget(QtWidgets.QLabel("Threshold changes create a new profile version. Existing runs retain their stored snapshot."))
        self.threshold_editor = QtWidgets.QPlainTextEdit(); tl.addWidget(self.threshold_editor)
        self._button(tl, "Save as next threshold version", self.save_profile)
        tabs.addTab(threshold_tab, "Readout thresholds")
        self.tabs = tabs
        self.status = QtWidgets.QLabel("Ready"); layout.addWidget(self.status)
        queue, runner, calibration = self.queue(), self.runner(), self.calibration()
        for signal, slot in ((self.sigEnqueue, queue.enqueue), (self.sigStart, queue.start_next),
                             (self.sigPause, queue.pause_current), (self.sigResume, queue.resume_current),
                             (self.sigCancel, queue.cancel_current), (self.sigRemove, queue.remove_pending),
                             (self.sigQueuePaused, queue.set_queue_paused), (self.sigProfile, calibration.set_profile),
                             (queue.sigQueueChanged, self.update_queue), (queue.sigProgressUpdated, self.update_progress),
                             (runner.sigDataUpdated, self.update_data), (calibration.sigProfilesChanged, self.load_profile)):
            signal.connect(slot, QtCore.Qt.QueuedConnection)
            self._connections.append((signal, slot))
        self.load_template(); self.load_profile(); self.update_queue(queue.queue_snapshot)
        self.show()

    @property
    def window(self):
        return self._mw

    def on_deactivate(self):
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._mw.close()
        self._mw.deleteLater()

    def show(self):
        self._mw.show(); self._mw.raise_(); self._mw.activateWindow()

    @staticmethod
    def _button(layout, title, callback):
        button = QtWidgets.QPushButton(title)
        button.clicked.connect(callback); layout.addWidget(button)
        return button

    def load_template(self):
        name = self.recipe.currentText()
        from qudi.logic.nuclear_ops.templates import experiment_template
        self.editor.setPlainText(json.dumps(experiment_template(name), indent=2))

    def enqueue(self):
        try:
            spec = ExperimentSpec.from_dict(json.loads(self.editor.toPlainText()))
            self.runner().validate_experiment(spec)
            self.sigEnqueue.emit(spec.to_dict())
            self.status.setText("Experiment added to queue")
        except Exception as exc:
            self.status.setText(str(exc))

    def import_spec(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self._mw, "Import specification", "", "JSON (*.json)")
        if path:
            try:
                spec = ExperimentSpec.from_dict(json.loads(Path(path).read_text()))
                self.editor.setPlainText(json.dumps(spec.to_dict(), indent=2))
            except Exception as exc:
                self.status.setText(str(exc))

    def export_spec(self):
        try:
            spec = ExperimentSpec.from_dict(json.loads(self.editor.toPlainText()))
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self._mw, "Export specification", "experiment.json", "JSON (*.json)")
            if path:
                Path(path).write_text(json.dumps(spec.to_dict(), indent=2))
        except Exception as exc:
            self.status.setText(str(exc))

    @QtCore.Slot(object)
    def update_queue(self, snapshot):
        selected = self.table.currentRow()
        self._items = snapshot.get("items", [])
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            for col, value in enumerate((item["experiment"]["name"], item["status"], item["run_file"], item["error"])):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(str(value)))
        if 0 <= selected < len(self._items):
            self.table.selectRow(selected)
        self.hold.blockSignals(True); self.hold.setChecked(snapshot.get("paused", False)); self.hold.blockSignals(False)

    def selected(self):
        row = self.table.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def remove_pending(self):
        item = self.selected()
        if item and item["status"] == "pending":
            self.sigRemove.emit(item["item_id"])

    @QtCore.Slot(str, float)
    def update_progress(self, item_id, fraction):
        self.progress.setValue(round(fraction * 100))

    @QtCore.Slot(object)
    def update_data(self, dataset):
        self._dataset = dataset
        self._analysis = None
        oldx, oldy = self.xaxis.currentText(), self.yaxis.currentText()
        self.xaxis.blockSignals(True); self.yaxis.blockSignals(True)
        xs = [name for name, v in dataset.coords.items() if v.dims == ("record",) and v.dtype.kind in "if"]
        ys = [name for name, v in dataset.data_vars.items() if v.dims == ("record",) and v.dtype.kind in "if"]
        self.xaxis.clear(); self.xaxis.addItems(xs)
        self.yaxis.clear(); self.yaxis.addItems(ys)
        self.xaxis.setCurrentText(oldx if oldx in xs else next((x for x in xs if x not in ("record", "block", "sweeps")), xs[0] if xs else ""))
        self.yaxis.setCurrentText(oldy if oldy in ys else "result_counts")
        self.xaxis.blockSignals(False); self.yaxis.blockSignals(False)
        self.draw()

    def draw(self, *_):
        self.plot.clear()
        if self._dataset is None:
            return
        x, y = self.xaxis.currentText(), self.yaxis.currentText()
        if x not in self._dataset or y not in self._dataset:
            return
        self.plot.plot(self._dataset[x].values, self._dataset[y].values, pen=None, symbol="o", symbolSize=5, symbolBrush="#67d7dd")
        self.plot.setLabel("bottom", x, units=self._dataset[x].attrs.get("unit", ""))
        self.plot.setLabel("left", y)
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        fit_name = "fit_" + y
        if self._analysis is not None and fit_name in self._analysis:
            fitted = self._analysis[fit_name].values
            if fitted.size == self._dataset.sizes["record"]:
                blocks = self._dataset.block.values if "block" in self._dataset else np.zeros(fitted.size)
                for block in np.unique(blocks):
                    selected = np.flatnonzero(blocks == block)
                    order = selected[np.argsort(self._dataset[x].values[selected])]
                    self.plot.plot(self._dataset[x].values[order], fitted[order], pen=pg.mkPen("#ffcd76", width=2))

    def open_selected(self):
        item = self.selected()
        if item and item["run_file"] and item["status"] in ("completed", "failed", "cancelled"):
            self.load_result(item["run_file"])

    def open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self._mw, "Open result", "", "HDF5 (*.h5)")
        if path:
            self.load_result(path)

    def load_result(self, path):
        try:
            run = NuclearDataset.open(path)
            self.update_data(run.dataset)
            self._analysis = run.analysis
            summary = []
            if "fit_parameters" in self._analysis:
                for group in self._analysis.fit_group.values:
                    summary.append("Fit group {}: {}".format(group, self._analysis.fit_message.sel(fit_group=group).item()))
                    for parameter in self._analysis.fit_parameter.values:
                        value = self._analysis.fit_parameters.sel(fit_group=group, fit_parameter=parameter).item()
                        error = self._analysis.fit_standard_errors.sel(fit_group=group, fit_parameter=parameter).item()
                        summary.append("  {} = {:.6g} +/- {:.3g}".format(parameter, value, error))
                summary.append("Time parameters use the scan unit; frequency uses its inverse. Phase is in radians at minimum x.")
            else:
                summary.append(str(self._analysis))
            self.fit_info.setPlainText("\n".join(summary))
            self.draw()
            self.status.setText(path)
            self.tabs.setCurrentIndex(1)
        except Exception as exc:
            self.status.setText(str(exc))

    def reanalyze_selected(self):
        item = self.selected()
        if item and item["status"] == "completed":
            try:
                self.runner().reanalyze(item["run_file"])
                self.load_result(item["run_file"])
            except Exception as exc:
                self.status.setText(str(exc))

    @QtCore.Slot(object)
    def load_profile(self, *_):
        self.threshold_editor.setPlainText(json.dumps(self.calibration().snapshot().profile.to_dict(), indent=2))

    def save_profile(self):
        try:
            value = json.loads(self.threshold_editor.toPlainText())
            current = self.calibration().snapshot(value["name"]).profile
            value["version"] = current.version + 1
            value.pop("updated_at", None)
            self.sigProfile.emit(ReadoutThresholdProfile.from_dict(value))
            self.status.setText("Saving threshold version {}".format(value["version"]))
        except Exception as exc:
            self.status.setText(str(exc))
