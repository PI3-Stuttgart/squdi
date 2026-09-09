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
    sigSetup = QtCore.Signal(object)
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
        self._scripts = {p.stem: p for p in self.runner().userscript_paths}
        self.recipe.addItems(sorted(self._scripts))
        form.addWidget(QtWidgets.QLabel("Userscript")); form.addWidget(self.recipe)
        self._button(form, "Load script", self.load_template)
        self._button(form, "Import specification…", self.import_spec)
        self._button(form, "Export specification…", self.export_spec)
        el.addLayout(form)
        el.addWidget(QtWidgets.QLabel("Python userscript: edit pulses above and SWEEPS/PARAMETERS below. Shared defaults are in Setup."))
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
        self.threshold_title = QtWidgets.QLabel(); tl.addWidget(self.threshold_title)
        self.threshold_table = QtWidgets.QTableWidget(0, 5)
        self.threshold_table.setHorizontalHeaderLabels(["Rule", "Comparison", "Counts", "Exclusion band", "QM channel"])
        self.threshold_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        tl.addWidget(self.threshold_table)
        self._button(tl, "Save as next threshold version", self.save_profile)
        tabs.addTab(threshold_tab, "Readout thresholds")
        from qudi.logic.nuclear_ops.setup_parameters import PARAMETERS
        setup_tab = QtWidgets.QWidget()
        setup_layout = QtWidgets.QVBoxLayout(setup_tab)
        self.setup_label = QtWidgets.QLabel("Edits apply at the next program boundary. Script PARAMETERS and scan axes take precedence.")
        setup_layout.addWidget(self.setup_label)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        settings = QtWidgets.QWidget(); settings_layout = QtWidgets.QVBoxLayout(settings)
        self.setup_widgets = {}
        groups = {}
        for key, (group, label, default, unit, minimum, maximum) in PARAMETERS.items():
            if group not in groups:
                box = QtWidgets.QGroupBox(group); form = QtWidgets.QFormLayout(box)
                groups[group] = form; settings_layout.addWidget(box)
            widget = QtWidgets.QSpinBox() if isinstance(default, int) else QtWidgets.QDoubleSpinBox()
            widget.setRange(minimum, maximum)
            if isinstance(widget, QtWidgets.QDoubleSpinBox):
                widget.setDecimals(6); widget.setSingleStep(.001)
            if unit == "ns":
                widget.setSingleStep(4)
            widget.setSuffix(" " + unit if unit else "")
            groups[group].addRow(label, widget); self.setup_widgets[key] = widget
        scroll.setWidget(settings); setup_layout.addWidget(scroll)
        self.live_setup = QtWidgets.QCheckBox("Apply edits live when leaving a field")
        self.live_setup.setChecked(True); setup_layout.addWidget(self.live_setup)
        for widget in self.setup_widgets.values():
            widget.editingFinished.connect(self.setup_edited)
        self._button(setup_layout, "Apply setup now", self.apply_setup)
        tabs.addTab(setup_tab, "Setup")
        self.load_setup(self.runner().setup_snapshot)
        counter_tab = QtWidgets.QWidget(); cl = QtWidgets.QVBoxLayout(counter_tab)
        cl.addWidget(QtWidgets.QLabel("Swabian gated counter — raw photon times in ps; CRC remains on QM. Channel routing is in Setup."))
        self.counter_status = QtWidgets.QLabel("Idle"); cl.addWidget(self.counter_status)
        self.counter_progress = QtWidgets.QProgressBar(); cl.addWidget(self.counter_progress)
        self.counter_trace = pg.PlotWidget(title="Recent gate counts", background="#16222d")
        self.counter_trace.setLabel("left", "Photons"); self.counter_trace.setLabel("bottom", "Gate index")
        cl.addWidget(self.counter_trace)
        self.counter_histogram = pg.PlotWidget(title="Gate count distribution", background="#16222d")
        self.counter_histogram.setLabel("bottom", "Photons / gate"); cl.addWidget(self.counter_histogram)
        counter_buttons = QtWidgets.QHBoxLayout()
        self._button(counter_buttons, "Start queued measurement", self.sigStart.emit)
        self._button(counter_buttons, "Stop counting / cancel run", self.sigCancel.emit)
        cl.addLayout(counter_buttons)
        tabs.addTab(counter_tab, "Gated counter")
        self.tabs = tabs
        self.status = QtWidgets.QLabel("Ready"); layout.addWidget(self.status)
        queue, runner, calibration = self.queue(), self.runner(), self.calibration()
        for signal, slot in ((self.sigSetup, runner.update_setup), (runner.sigSetupChanged, self.load_setup),
                             (runner.sigSetupError, self.setup_error), (runner.sigCounterUpdated, self.update_counter),
                             (self.sigEnqueue, queue.enqueue), (self.sigStart, queue.start_next),
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
        path = self._scripts[self.recipe.currentText()]
        self._script_path = str(path)
        self.editor.setPlainText(path.read_text(encoding="utf-8"))

    def enqueue(self):
        try:
            spec = self.runner().script_specification(self.editor.toPlainText(), self._script_path)
            self.runner().validate_experiment(spec)
            self.sigEnqueue.emit(spec.to_dict())
            self.status.setText("Queued a frozen copy of the Python userscript")
        except Exception as exc:
            self.status.setText(str(exc))

    def import_spec(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self._mw, "Open userscript", "", "Python (*.py)")
        if path:
            try:
                self._script_path = path
                self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                self.status.setText(str(exc))

    def export_spec(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self._mw, "Save userscript", self._script_path, "Python (*.py)")
        if path:
            try:
                compile(self.editor.toPlainText(), path, "exec")
                Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
                self._script_path = path
                self.status.setText("Saved " + path)
            except Exception as exc:
                self.status.setText(str(exc))

    def setup_edited(self):
        if self.live_setup.isChecked():
            self.apply_setup()

    def apply_setup(self):
        self.sigSetup.emit({key: widget.value() for key, widget in self.setup_widgets.items()})

    @QtCore.Slot(object)
    def load_setup(self, snapshot):
        for key, widget in self.setup_widgets.items():
            widget.setValue(snapshot["values"][key])
        self.setup_label.setText("Setup revision {} saved. Applies at the next program boundary; script overrides take precedence.".format(snapshot["revision"]))

    @QtCore.Slot(str)
    def setup_error(self, message):
        self.setup_label.setText("Not applied: " + message)

    @QtCore.Slot(object)
    def update_counter(self, snapshot):
        self.counter_status.setText("Swabian: " + snapshot["status"])
        if "completed" in snapshot:
            self.counter_progress.setValue(round(100*snapshot["completed"]/max(1, snapshot["expected"])))
            self.counter_status.setText("Swabian: {} — {} / {} gates".format(snapshot["status"], snapshot["completed"], snapshot["expected"]))
        counts = np.asarray(snapshot.get("counts", []))
        if counts.size:
            self.counter_trace.clear(); self.counter_histogram.clear()
            self.counter_trace.plot(counts, pen="#67d7dd")
            hist, edges = np.histogram(counts, bins=min(100, max(1, int(np.ptp(counts))+1)))
            self.counter_histogram.plot((edges[:-1]+edges[1:])/2, hist, pen="#ffcd76", fillLevel=0, brush=(255,205,118,60))

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
        self._profile = self.calibration().snapshot().profile.to_dict()
        self.threshold_title.setText("{} / version {}. Threshold updates apply to the next run.".format(self._profile["name"], self._profile["version"]))
        self.threshold_table.setRowCount(len(self._profile["rules"]))
        for row, (name, rule) in enumerate(self._profile["rules"].items()):
            item = QtWidgets.QTableWidgetItem(name); item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.threshold_table.setItem(row, 0, item)
            comparison = QtWidgets.QComboBox(); comparison.addItems([">", ">=", "<", "<="])
            comparison.setCurrentText(rule["comparison"]); self.threshold_table.setCellWidget(row, 1, comparison)
            for column, key in [(2, "counts"), (3, "exclusion_width")]:
                value = QtWidgets.QDoubleSpinBox(); value.setRange(0 if column == 3 else -1e9, 1e9)
                value.setDecimals(3); value.setValue(rule[key]); self.threshold_table.setCellWidget(row, column, value)
            channel = QtWidgets.QLineEdit(rule["channel"]); self.threshold_table.setCellWidget(row, 4, channel)

    def save_profile(self):
        try:
            value = dict(self._profile)
            value["rules"] = {}
            for row in range(self.threshold_table.rowCount()):
                value["rules"][self.threshold_table.item(row, 0).text()] = {
                    "comparison": self.threshold_table.cellWidget(row, 1).currentText(),
                    "counts": self.threshold_table.cellWidget(row, 2).value(),
                    "exclusion_width": self.threshold_table.cellWidget(row, 3).value(),
                    "channel": self.threshold_table.cellWidget(row, 4).text()}
            value["version"] = self.calibration().snapshot(value["name"]).profile.version + 1
            value.pop("updated_at", None)
            self.sigProfile.emit(ReadoutThresholdProfile.from_dict(value))
            self.status.setText("Saving threshold version {}".format(value["version"]))
        except Exception as exc:
            self.status.setText(str(exc))
