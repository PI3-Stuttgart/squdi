from pathlib import Path
p=Path('src/qudi/gui/nuclear_ops/nuclear_ops_gui.py');s=p.read_text()
s=s.replace('    sigProfile =', '    sigSetup = QtCore.Signal(object)\n    sigProfile =')
s=s.replace('        self.recipe.addItems(self.runner().recipe_names)', '        self._scripts = {p.stem: p for p in self.runner().userscript_paths}\n        self.recipe.addItems(sorted(self._scripts))')
s=s.replace('"Recipe"', '"Userscript"').replace('"Load recipe template"', '"Load script"').replace('"Import specification…"','"Open Python script…"').replace('"Export specification…"','"Save Python script…"')
s=s.replace('Edit the scan values, integration count and parameters below, then add the experiment to the queue.', 'Python userscript: edit pulses above and SWEEPS/PARAMETERS below. Shared defaults are in Setup.')
s=s.replace('        self.tabs = tabs', '''        from qudi.logic.nuclear_ops.setup_parameters import PARAMETERS
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
        self.tabs = tabs''')
s=s.replace('        for signal, slot in ((self.sigEnqueue, queue.enqueue),', '        for signal, slot in ((self.sigSetup, runner.update_setup), (runner.sigSetupChanged, self.load_setup),\n                             (runner.sigSetupError, self.setup_error), (runner.sigCounterUpdated, self.update_counter),\n                             (self.sigEnqueue, queue.enqueue),')
a=s.index('    def load_template(self):');b=s.index('    @QtCore.Slot(object)\n    def update_queue',a)
s=s[:a]+'''    def load_template(self):
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

'''+s[b:]
p.write_text(s)
