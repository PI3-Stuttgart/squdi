from pathlib import Path
p=Path('src/qudi/gui/nuclear_ops/nuclear_ops_gui.py');s=p.read_text(encoding='utf-8').replace('\n\n', '\n')
s=s.replace('        self.threshold_editor = QtWidgets.QPlainTextEdit(); tl.addWidget(self.threshold_editor)', '''        self.threshold_title = QtWidgets.QLabel(); tl.addWidget(self.threshold_title)
        self.threshold_table = QtWidgets.QTableWidget(0, 5)
        self.threshold_table.setHorizontalHeaderLabels(["Rule", "Comparison", "Counts", "Exclusion band", "QM channel"])
        self.threshold_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        tl.addWidget(self.threshold_table)''')
s=s.replace('        self._button(setup_layout, "Apply setup now", self.apply_setup)', '''        self.live_setup = QtWidgets.QCheckBox("Apply edits live when leaving a field")
        self.live_setup.setChecked(True); setup_layout.addWidget(self.live_setup)
        for widget in self.setup_widgets.values():
            widget.editingFinished.connect(self.setup_edited)
        self._button(setup_layout, "Apply setup now", self.apply_setup)''')
s=s.replace('    def apply_setup(self):', '    def setup_edited(self):\n        if self.live_setup.isChecked():\n            self.apply_setup()\n\n    def apply_setup(self):')
a=s.index('    @QtCore.Slot(object)\n    def load_profile');s=s[:a]+'''    @QtCore.Slot(object)
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
''';p.write_text(s,encoding='utf-8')
p=Path('src/qudi/logic/nuclear_ops/setup_parameters.py');s=p.read_text().replace('        with self.lock:\n            state =', '        with self.lock:\n            if values == self.state["values"]:\n                return self.snapshot()\n            state =');p.write_text(s)
