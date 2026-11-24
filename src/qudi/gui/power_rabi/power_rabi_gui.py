# -*- coding: utf-8 -*-
"""
GUI for the optical power-Rabi measurement (power_rabi_logic.PowerRabiLogic).

Example config:

    power_rabi_gui:
        module.Class: 'power_rabi.power_rabi_gui.PowerRabiGui'
        connect:
            power_rabi_logic: 'power_rabi_logic'
"""

import numpy as np
import pyqtgraph as pg
from PySide2 import QtCore, QtWidgets

from qudi.core.connector import Connector
from qudi.core.module import GuiBase


def _spin(minimum, maximum, value=0, step=1, suffix='', decimals=None):
    if decimals is None:
        w = QtWidgets.QSpinBox()
        w.setRange(int(minimum), int(maximum))
        w.setSingleStep(int(step))
        w.setValue(int(value))
    else:
        w = QtWidgets.QDoubleSpinBox()
        w.setDecimals(decimals)
        w.setRange(minimum, maximum)
        w.setSingleStep(step)
        w.setValue(value)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


class PowerRabiMainWindow(QtWidgets.QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('qudi: Power Rabi (Bluefors)')
        self.resize(1200, 800)
        self.setDockNestingEnabled(True)
        self.w = {}   # setting key -> widget

        menu = self.menuBar()
        file_menu = menu.addMenu('&File')
        self.action_save = QtWidgets.QAction('&Save data', self)
        self.action_load_cal = QtWidgets.QAction('Load &power calibration...', self)
        self.action_close = QtWidgets.QAction('&Close', self)
        self.action_close.triggered.connect(self.close)
        for a in (self.action_save, self.action_load_cal, self.action_close):
            file_menu.addAction(a)

        # ---------------- toolbar ----------------
        tb = self.addToolBar('Measurement')
        tb.setObjectName('power_rabi_toolbar')
        self.start_button = QtWidgets.QPushButton('Start')
        self.stop_button = QtWidgets.QPushButton('Stop')
        self.preview_button = QtWidgets.QPushButton('Live preview')
        self.preview_button.setCheckable(True)
        self.preview_button.setToolTip('Stream the sequence continuously at the preview voltage and show\n'
                                       'the live histogram, e.g. to align the channel offsets.')
        self.fit_button = QtWidgets.QPushButton('Fit')
        self.save_button = QtWidgets.QPushButton('Save')
        self.name_tag = QtWidgets.QLineEdit()
        self.name_tag.setPlaceholderText('name tag')
        self.name_tag.setMaximumWidth(160)
        for w in (self.start_button, self.stop_button, self.preview_button, self.fit_button,
                  self.save_button, self.name_tag):
            tb.addWidget(w)
        self.progress_label = QtWidgets.QLabel('idle')
        tb.addSeparator()
        tb.addWidget(self.progress_label)

        # ---------------- plots ----------------
        self.tabs = QtWidgets.QTabWidget()
        central = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(central)

        plot_opts = QtWidgets.QHBoxLayout()
        plot_opts.addWidget(QtWidgets.QLabel('x axis:'))
        self.x_axis_combo = QtWidgets.QComboBox()
        self.x_axis_combo.addItems(['sqrt(V)', 'sqrt(P)'])
        plot_opts.addWidget(self.x_axis_combo)
        self.normalize_checkbox = QtWidgets.QCheckBox('normalise 0..1 (g..e)')
        plot_opts.addWidget(self.normalize_checkbox)
        self.fit_label = QtWidgets.QLabel('')
        plot_opts.addWidget(self.fit_label)
        plot_opts.addStretch()
        vbox.addLayout(plot_opts)

        self.rabi_plot = pg.PlotWidget()
        self.rabi_plot.setLabel('bottom', 'sqrt(V)', units='')
        self.rabi_plot.setLabel('left', 'counts per trigger')
        self.rabi_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rabi_curve = self.rabi_plot.plot(pen=pg.mkPen((80, 160, 255), width=1.5),
                                              symbol='o', symbolSize=6,
                                              symbolBrush=(80, 160, 255))
        self.fit_curve = self.rabi_plot.plot(pen=pg.mkPen((255, 140, 0), width=2))
        vbox.addWidget(self.rabi_plot, stretch=3)

        self.hist_plot = pg.PlotWidget()
        self.hist_plot.setLabel('bottom', 'time', units='ns')
        self.hist_plot.setLabel('left', 'events')
        self.hist_plot.showGrid(x=True, y=True, alpha=0.3)
        self.hist_curve = self.hist_plot.plot(pen=pg.mkPen((90, 220, 120), width=1))
        self.roi_region = pg.LinearRegionItem(values=(0, 200), brush=(255, 255, 255, 30))
        self.hist_plot.addItem(self.roi_region)
        vbox.addWidget(self.hist_plot, stretch=2)
        self.tabs.addTab(central, 'Power Rabi')
        self.tabs.addTab(self._build_calibration_tab(), 'Power calibration')
        self.setCentralWidget(self.tabs)

        # ---------------- settings dock ----------------
        self.settings_dock = QtWidgets.QDockWidget('Settings', self)
        self.settings_dock.setObjectName('power_rabi_settings_dock')
        self.settings_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable |
                                       QtWidgets.QDockWidget.DockWidgetFloatable)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(contents)

        # sequence
        seq_box = QtWidgets.QGroupBox('Pulse Streamer sequence')
        grid = QtWidgets.QGridLayout(seq_box)
        grid.addWidget(QtWidgets.QLabel('Period'), 0, 0)
        self.w['period_ns'] = _spin(10, 10_000_000, 1000, 10, ' ns')
        grid.addWidget(self.w['period_ns'], 0, 1, 1, 3)
        for col, txt in enumerate(('', 'Channel', 'Duration', 'Offset')):
            grid.addWidget(QtWidgets.QLabel(txt), 1, col)
        for row, (key, label) in enumerate((('aom', 'AOM (D)'), ('ppg', 'PPG / EOM (D)'),
                                            ('tt', 'TT trigger (D)')), start=2):
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            self.w[f'{key}_channel'] = _spin(0, 7, 0)
            self.w[f'{key}_duration_ns'] = _spin(1, 10_000_000, 10, 1, ' ns')
            self.w[f'{key}_offset_ns'] = _spin(0, 10_000_000, 0, 1, ' ns')
            grid.addWidget(self.w[f'{key}_channel'], row, 1)
            grid.addWidget(self.w[f'{key}_duration_ns'], row, 2)
            grid.addWidget(self.w[f'{key}_offset_ns'], row, 3)
        grid.addWidget(QtWidgets.QLabel('AOM power (A)'), 5, 0)
        self.w['analog_channel'] = _spin(0, 1, 1)
        grid.addWidget(self.w['analog_channel'], 5, 1)
        lay.addWidget(seq_box)

        # sweep
        sweep_box = QtWidgets.QGroupBox('Power sweep')
        form = QtWidgets.QFormLayout(sweep_box)
        self.w['v_start'] = _spin(0, 1, 0, 0.01, ' V', 4)
        self.w['v_stop'] = _spin(0, 1, 1, 0.01, ' V', 4)
        self.w['n_points'] = _spin(2, 10000, 41)
        self.w['sqrt_spacing'] = QtWidgets.QCheckBox('equidistant in sqrt(V)')
        self.w['n_triggers'] = _spin(1, 2_000_000_000, 1_000_000, 100_000)
        self.w['n_sweeps'] = _spin(1, 100000, 1)
        self.w['preview_voltage'] = _spin(0, 1, 0.33, 0.01, ' V', 4)
        form.addRow('Start voltage:', self.w['v_start'])
        form.addRow('Stop voltage:', self.w['v_stop'])
        form.addRow('Points:', self.w['n_points'])
        form.addRow('', self.w['sqrt_spacing'])
        form.addRow('Triggers / point:', self.w['n_triggers'])
        form.addRow('Sweeps:', self.w['n_sweeps'])
        form.addRow('Preview voltage:', self.w['preview_voltage'])
        self.time_estimate_label = QtWidgets.QLabel('')
        form.addRow('Est. duration:', self.time_estimate_label)
        lay.addWidget(sweep_box)

        # histogram
        hist_box = QtWidgets.QGroupBox('Time Tagger histogram')
        form2 = QtWidgets.QFormLayout(hist_box)
        self.w['click_channel'] = _spin(-18, 18, 2)
        self.w['trigger_channel'] = _spin(-18, 18, 5)
        self.w['bin_width_ps'] = _spin(1, 1_000_000, 200, 10, ' ps')
        self.w['n_bins'] = _spin(1, 1_000_000, 1000, 100)
        self.w['roi_start_ns'] = _spin(0, 1e7, 0, 1, ' ns', 2)
        self.w['roi_stop_ns'] = _spin(0, 1e7, 200, 1, ' ns', 2)
        form2.addRow('Click channel (APD/SNSPD):', self.w['click_channel'])
        form2.addRow('Start/trigger channel:', self.w['trigger_channel'])
        form2.addRow('Bin width:', self.w['bin_width_ps'])
        form2.addRow('Number of bins:', self.w['n_bins'])
        self.record_length_label = QtWidgets.QLabel('')
        form2.addRow('Record length:', self.record_length_label)
        form2.addRow('Sum window start:', self.w['roi_start_ns'])
        form2.addRow('Sum window stop:', self.w['roi_stop_ns'])
        lay.addWidget(hist_box)
        lay.addStretch()

        scroll.setWidget(contents)
        self.settings_dock.setWidget(scroll)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.settings_dock)


    def _build_calibration_tab(self):
        tab = QtWidgets.QWidget()
        hbox = QtWidgets.QHBoxLayout(tab)

        box = QtWidgets.QGroupBox('Calibration sweep (power meter in front of the cryostat)')
        form = QtWidgets.QFormLayout(box)
        self.w['cal_v_start'] = _spin(0, 1, 0, 0.01, ' V', 4)
        self.w['cal_v_stop'] = _spin(0, 1, 1, 0.01, ' V', 4)
        self.w['cal_n_points'] = _spin(2, 1000, 41)
        self.cal_mode_combo = QtWidgets.QComboBox()
        self.cal_mode_combo.addItem('Rabi sequence (AOM + EOM pulsed)', 'sequence')
        self.cal_mode_combo.addItem('AOM CW (gate open, PPG off)', 'aom_cw')
        self.cal_mode_combo.setToolTip(
            'Rabi sequence: measures the average power of the actual pulse train -> correct x axis.\n'
            'AOM CW: only for characterising the AOM; ignores the EOM gating.')
        self.w['cal_settle_s'] = _spin(0, 60, 0.5, 0.1, ' s', 2)
        self.w['cal_n_avg'] = _spin(1, 1000, 10)
        self.w['cal_subtract_dark'] = QtWidgets.QCheckBox('subtract dark reading (all outputs off)')
        form.addRow('Start voltage:', self.w['cal_v_start'])
        form.addRow('Stop voltage:', self.w['cal_v_stop'])
        form.addRow('Points:', self.w['cal_n_points'])
        form.addRow('Mode:', self.cal_mode_combo)
        form.addRow('Settle time:', self.w['cal_settle_s'])
        form.addRow('Readings / point:', self.w['cal_n_avg'])
        form.addRow('', self.w['cal_subtract_dark'])

        btns = QtWidgets.QGridLayout()
        self.cal_start_button = QtWidgets.QPushButton('Start calibration')
        self.cal_stop_button = QtWidgets.QPushButton('Stop')
        self.cal_save_button = QtWidgets.QPushButton('Save')
        self.cal_load_button = QtWidgets.QPushButton('Load file...')
        self.cal_clear_button = QtWidgets.QPushButton('Clear')
        self.cal_clear_button.setToolTip('Forget the active calibration (sqrt(P) axis disabled).')
        btns.addWidget(self.cal_start_button, 0, 0)
        btns.addWidget(self.cal_stop_button, 0, 1)
        btns.addWidget(self.cal_save_button, 1, 0)
        btns.addWidget(self.cal_load_button, 1, 1)
        btns.addWidget(self.cal_clear_button, 2, 0)
        form.addRow(btns)
        self.cal_progress_label = QtWidgets.QLabel('')
        form.addRow('Progress:', self.cal_progress_label)
        self.cal_info_label = QtWidgets.QLabel('no calibration active')
        self.cal_info_label.setWordWrap(True)
        form.addRow('Active:', self.cal_info_label)
        box.setMaximumWidth(420)
        hbox.addWidget(box)

        self.cal_plot = pg.PlotWidget()
        self.cal_plot.setLabel('bottom', 'analog voltage', units='V')
        self.cal_plot.setLabel('left', 'average power', units='W')
        self.cal_plot.showGrid(x=True, y=True, alpha=0.3)
        self.cal_plot.addLegend()
        self.cal_active_curve = self.cal_plot.plot(pen=pg.mkPen((255, 140, 0), width=2),
                                                   name='active calibration')
        self.cal_run_curve = self.cal_plot.plot(pen=None, symbol='o', symbolSize=6,
                                                symbolBrush=(80, 160, 255), name='measurement')
        self.cal_errbars = pg.ErrorBarItem(x=np.array([]), y=np.array([]), height=np.array([]),
                                           pen=pg.mkPen((80, 160, 255)))
        self.cal_plot.addItem(self.cal_errbars)
        hbox.addWidget(self.cal_plot, stretch=1)
        return tab


class PowerRabiGui(GuiBase):
    """ qudi GUI for the optical power-Rabi measurement. """

    power_rabi_logic = Connector(interface='PowerRabiLogic')

    sigStart = QtCore.Signal()
    sigStartPreview = QtCore.Signal()
    sigStopPreview = QtCore.Signal()
    sigSettings = QtCore.Signal(object)
    sigRoi = QtCore.Signal(float, float)
    sigFit = QtCore.Signal()
    sigSave = QtCore.Signal(str)
    sigStartCalibration = QtCore.Signal()
    sigSaveCalibration = QtCore.Signal(str)
    sigClearCalibration = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._logic = None
        self._last_data = None
        self._last_fit = None

    def on_activate(self):
        self._logic = self.power_rabi_logic()
        self._mw = PowerRabiMainWindow()
        self._restore_window_geometry(self._mw)

        q = QtCore.Qt.QueuedConnection
        self.sigStart.connect(self._logic.start_measurement, q)
        self.sigStartPreview.connect(self._logic.start_preview, q)
        self.sigStopPreview.connect(self._logic.stop_preview, q)
        self.sigSettings.connect(self._logic.set_settings, q)
        self.sigRoi.connect(self._logic.recalculate_roi, q)
        self.sigFit.connect(self._logic.do_fit, q)
        self.sigSave.connect(self._logic.save_data, q)
        self.sigStartCalibration.connect(self._logic.start_calibration, q)
        self.sigSaveCalibration.connect(self._logic.save_calibration, q)
        self.sigClearCalibration.connect(self._logic.clear_calibration, q)

        self._logic.sigDataUpdated.connect(self._update_data, q)
        self._logic.sigHistogramUpdated.connect(self._update_histogram, q)
        self._logic.sigStateChanged.connect(self._update_state, q)
        self._logic.sigProgress.connect(self._update_progress, q)
        self._logic.sigSettingsUpdated.connect(self._update_settings, q)
        self._logic.sigFitUpdated.connect(self._update_fit, q)
        self._logic.sigCalibrationUpdated.connect(self._update_calibration, q)
        self._logic.sigCalProgress.connect(self._update_cal_progress, q)

        mw = self._mw
        mw.start_button.clicked.connect(self._start_clicked)
        mw.stop_button.clicked.connect(self._stop_clicked)
        mw.preview_button.toggled.connect(self._preview_toggled)
        mw.fit_button.clicked.connect(self.sigFit.emit)
        mw.save_button.clicked.connect(self._save_clicked)
        mw.action_save.triggered.connect(self._save_clicked)
        mw.action_load_cal.triggered.connect(self._load_calibration)
        mw.x_axis_combo.currentIndexChanged.connect(self._replot)
        mw.normalize_checkbox.toggled.connect(self._replot)
        mw.roi_region.sigRegionChangeFinished.connect(self._roi_dragged)
        mw.cal_start_button.clicked.connect(self._cal_start_clicked)
        mw.cal_stop_button.clicked.connect(self._stop_clicked)
        mw.cal_save_button.clicked.connect(
            lambda: self.sigSaveCalibration.emit(mw.name_tag.text().strip()))
        mw.cal_load_button.clicked.connect(self._load_calibration)
        mw.cal_clear_button.clicked.connect(self.sigClearCalibration.emit)
        mw.cal_mode_combo.currentIndexChanged.connect(self._settings_edited)

        for key, widget in mw.w.items():
            if key in ('roi_start_ns', 'roi_stop_ns'):
                widget.valueChanged.connect(self._roi_spin_changed)
            elif isinstance(widget, QtWidgets.QCheckBox):
                widget.toggled.connect(self._settings_edited)
            else:
                widget.valueChanged.connect(self._settings_edited)

        self._update_settings(self._logic.settings)
        self._update_state(self._logic.state)
        self._logic.request_calibration_update()
        self.show()

    def on_deactivate(self):
        self._save_window_geometry(self._mw)
        for sig in (self.sigStart, self.sigStartPreview, self.sigStopPreview, self.sigSettings,
                    self.sigRoi, self.sigFit, self.sigSave, self.sigStartCalibration,
                    self.sigSaveCalibration, self.sigClearCalibration):
            try:
                sig.disconnect()
            except RuntimeError:
                pass
        for sig, slot in ((self._logic.sigDataUpdated, self._update_data),
                          (self._logic.sigHistogramUpdated, self._update_histogram),
                          (self._logic.sigStateChanged, self._update_state),
                          (self._logic.sigProgress, self._update_progress),
                          (self._logic.sigSettingsUpdated, self._update_settings),
                          (self._logic.sigFitUpdated, self._update_fit),
                          (self._logic.sigCalibrationUpdated, self._update_calibration),
                          (self._logic.sigCalProgress, self._update_cal_progress)):
            try:
                sig.disconnect(slot)
            except RuntimeError:
                pass
        self._mw.close()
        self._mw = None

    def show(self):
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    # ------------------------------------------------------------------ user actions
    def _collect_settings(self):
        out = {}
        for key, widget in self._mw.w.items():
            out[key] = widget.isChecked() if isinstance(widget, QtWidgets.QCheckBox) else widget.value()
        out['cal_mode'] = self._mw.cal_mode_combo.currentData()
        return out

    def _settings_edited(self, *_):
        self._update_estimates()
        self.sigSettings.emit(self._collect_settings())

    def _start_clicked(self):
        self.sigSettings.emit(self._collect_settings())
        self.sigStart.emit()

    def _stop_clicked(self):
        self._logic.stop_measurement()          # direct call: only sets a flag
        if self._mw.preview_button.isChecked():
            self._mw.preview_button.setChecked(False)

    def _preview_toggled(self, checked):
        if checked:
            self.sigSettings.emit(self._collect_settings())
            self.sigStartPreview.emit()
        else:
            self.sigStopPreview.emit()

    def _save_clicked(self):
        self.sigSave.emit(self._mw.name_tag.text().strip())

    def _load_calibration(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._mw, 'Load voltage -> power calibration (2 columns: V, P[W])', '',
            'Data files (*.dat *.txt *.csv);;All files (*)')
        if path:
            self._logic.load_power_calibration(path)

    def _cal_start_clicked(self):
        answer = QtWidgets.QMessageBox.question(
            self._mw, 'Power calibration',
            'Is the power meter in the beam in front of the cryostat?\n\n'
            'The sequence will be streamed continuously at each voltage.',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self.sigSettings.emit(self._collect_settings())
        self.sigStartCalibration.emit()

    @QtCore.Slot(int, int)
    def _update_cal_progress(self, point, n_points):
        self._mw.cal_progress_label.setText(f'{point}/{n_points}')

    @QtCore.Slot(object)
    def _update_calibration(self, cal):
        mw = self._mw
        if cal['active_voltage'] is not None:
            mw.cal_active_curve.setData(cal['active_voltage'], cal['active_power'])
            info = cal.get('active_info') or {}
            text = f'{info.get("mode", "?")}, {info.get("timestamp", "")}'
            if info.get('source_file'):
                text += f'\n{info["source_file"]}'
            text += f'\nmax {np.nanmax(cal["active_power"]) * 1e6:.3f} µW'
            mw.cal_info_label.setText(text)
        else:
            mw.cal_active_curve.setData([], [])
            mw.cal_info_label.setText('no calibration active')
        run = cal.get('run')
        if run is not None:
            ok = np.isfinite(run['power'])
            x, y, e = run['voltage'][ok], run['power'][ok], run['power_std'][ok]
            mw.cal_run_curve.setData(x, y)
            mw.cal_errbars.setData(x=x, y=y, height=2 * np.nan_to_num(e))
            if run.get('finished'):
                mw.cal_progress_label.setText(
                    f'done (dark {run["dark"] * 1e9:.2f} nW subtracted)' if run['dark'] else 'done')
        else:
            mw.cal_run_curve.setData([], [])
            mw.cal_errbars.setData(x=np.array([]), y=np.array([]), height=np.array([]))

    def _roi_dragged(self):
        lo, hi = self._mw.roi_region.getRegion()
        for key, val in (('roi_start_ns', max(lo, 0)), ('roi_stop_ns', max(hi, 0))):
            self._mw.w[key].blockSignals(True)
            self._mw.w[key].setValue(val)
            self._mw.w[key].blockSignals(False)
        self.sigRoi.emit(max(lo, 0), max(hi, 0))

    def _roi_spin_changed(self, *_):
        lo = self._mw.w['roi_start_ns'].value()
        hi = self._mw.w['roi_stop_ns'].value()
        self._mw.roi_region.blockSignals(True)
        self._mw.roi_region.setRegion((lo, hi))
        self._mw.roi_region.blockSignals(False)
        self.sigRoi.emit(lo, hi)

    # ------------------------------------------------------------------ updates from logic
    @QtCore.Slot(object)
    def _update_settings(self, settings):
        for key, widget in self._mw.w.items():
            if key not in settings:
                continue
            widget.blockSignals(True)
            if isinstance(widget, QtWidgets.QCheckBox):
                widget.setChecked(bool(settings[key]))
            else:
                widget.setValue(settings[key])
            widget.blockSignals(False)
        if 'cal_mode' in settings:
            idx = self._mw.cal_mode_combo.findData(settings['cal_mode'])
            self._mw.cal_mode_combo.blockSignals(True)
            self._mw.cal_mode_combo.setCurrentIndex(max(idx, 0))
            self._mw.cal_mode_combo.blockSignals(False)
        self._mw.roi_region.blockSignals(True)
        self._mw.roi_region.setRegion((settings['roi_start_ns'], settings['roi_stop_ns']))
        self._mw.roi_region.blockSignals(False)
        self._update_estimates()

    def _update_estimates(self):
        s = self._collect_settings()
        t = s['n_points'] * s['n_sweeps'] * (s['n_triggers'] * s['period_ns'] * 1e-9 + 0.05)
        self._mw.time_estimate_label.setText(f'~{t:.0f} s' if t < 120 else f'~{t / 60:.1f} min')
        self._mw.record_length_label.setText(f'{s["n_bins"] * s["bin_width_ps"] / 1e3:.1f} ns')

    @QtCore.Slot(str)
    def _update_state(self, state):
        mw = self._mw
        calibrating = state == 'calibrating'
        running = state == 'running' or calibrating
        preview = state == 'preview'
        mw.start_button.setEnabled(state == 'idle')
        mw.stop_button.setEnabled(running or preview)
        mw.preview_button.setEnabled(not running)
        mw.cal_start_button.setEnabled(state == 'idle')
        mw.cal_stop_button.setEnabled(calibrating)
        mw.cal_load_button.setEnabled(not running)
        mw.cal_clear_button.setEnabled(not running)
        mw.cal_mode_combo.setEnabled(not running)
        mw.preview_button.blockSignals(True)
        mw.preview_button.setChecked(preview)
        mw.preview_button.blockSignals(False)
        mw.fit_button.setEnabled(not running)
        mw.save_button.setEnabled(not running)
        for key, widget in mw.w.items():
            if key not in ('roi_start_ns', 'roi_stop_ns'):
                widget.setEnabled(not running)
        if state != 'running':
            mw.progress_label.setText(state)

    @QtCore.Slot(int, int, int, int)
    def _update_progress(self, point, n_points, sweep, n_sweeps):
        self._mw.progress_label.setText(f'point {point}/{n_points}   sweep {sweep}/{n_sweeps}')

    @QtCore.Slot(object, object)
    def _update_histogram(self, t_ns, counts):
        self._mw.hist_curve.setData(t_ns, counts)

    @QtCore.Slot(object)
    def _update_data(self, data):
        self._last_data = data
        sqrtp_ok = data.get('sqrt_power') is not None
        item = self._mw.x_axis_combo.model().item(1)
        item.setEnabled(sqrtp_ok)
        if not sqrtp_ok and self._mw.x_axis_combo.currentIndex() == 1:
            self._mw.x_axis_combo.setCurrentIndex(0)
        self._replot()

    @QtCore.Slot(object)
    def _update_fit(self, fit):
        self._last_fit = fit
        if fit is None:
            self._mw.fit_label.setText('')
        else:
            self._mw.fit_label.setText(
                f'π at sqrt(V) = {fit["sqrtV_pi"]:.4f}  (V = {fit["V_pi"]:.4f} V)')
        self._replot()

    def _replot(self, *_):
        data = self._last_data
        mw = self._mw
        if data is None or len(data['voltage']) == 0:
            mw.rabi_curve.setData([], [])
            mw.fit_curve.setData([], [])
            return
        use_p = mw.x_axis_combo.currentIndex() == 1 and data.get('sqrt_power') is not None
        x = data['sqrt_power'] if use_p else data['sqrt_voltage']
        y = np.array(data['counts_per_trigger'], dtype=float)
        valid = np.isfinite(y)
        lo = hi = None
        if mw.normalize_checkbox.isChecked() and valid.sum() > 1:
            lo, hi = np.nanmin(y), np.nanmax(y)
            if hi > lo:
                y = (y - lo) / (hi - lo)
        mw.rabi_curve.setData(x[valid], y[valid])
        mw.rabi_plot.setLabel('bottom', 'sqrt(P_avg) (sqrt(W))' if use_p else 'sqrt(V)')
        mw.rabi_plot.setLabel('left', 'normalised population' if mw.normalize_checkbox.isChecked()
                              else 'counts per trigger')

        fit = self._last_fit
        if fit is not None and not use_p:
            yf = fit['y_fit']
            if lo is not None and hi > lo:
                yf = (yf - lo) / (hi - lo)
            mw.fit_curve.setData(fit['x_fit'], yf)
        else:
            mw.fit_curve.setData([], [])
