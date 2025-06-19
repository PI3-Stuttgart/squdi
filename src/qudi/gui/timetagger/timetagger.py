from sys import displayhook
import numpy as np
import os
import pyqtgraph as pg
from PySide2 import QtCore, QtWidgets, QtGui
import time
import datetime

from qudi.core.connector import Connector
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.core.module import GuiBase
from qudi.util.widgets.plotting import colorbar
from qudi.util.colordefs import ColorScaleInferno
from qudi.util.colordefs import QudiPalette as palette
from qudi.core.statusvariable import StatusVar
from qudi.util.units import ScaledFloat
from qudi.util.mutex import Mutex
from qudi.util.widgets.fitting import FitWidget, FitConfigurationDialog
from qtpy import uic

class TTWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'timetagger.ui')

        # Load it
        super(TTWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()



class TTGui(GuiBase):
    """
    Main GUI for the Timetagger module implementing Counting, Autocorrelation, and histogram functions.

    """
    
    # declare connectors
    timetaggerlogic = Connector(name='timetaggerlogic', interface='TimeTaggerLogic')

    # --- Signals to Logic ---
    sigToggleCounter = QtCore.Signal(object)
    sigToggleCorr = QtCore.Signal(object)
    sigToggleHist = QtCore.Signal(object)
    sigToggleTimeDiff = QtCore.Signal(object)
    sigSetTimeDiffRanges = QtCore.Signal(float, float)
    sigToggleDump = QtCore.Signal(bool, str, str)

    # --- Status Variables ---
    _counter_freq = StatusVar('counter_freq', default=50)
    _counter_length = StatusVar('counter_length', default=10)

    _corr_bin_width = StatusVar('corr_bin_width', default=50)
    _corr_record_length = StatusVar('corr_record_length', default=10)

    _hist_bin_width = StatusVar('hist_bin_width', default=50)
    _hist_record_length = StatusVar('hist_record_length', default=10)
    
    _time_diff_bin_width = StatusVar('time_diff_bin_width', default=100)
    _time_diff_record_length = StatusVar('time_diff_record_length', default=100)
    _time_diff_num_histograms = StatusVar('time_diff_num_histograms', default=100)
    _time_diff_start_ns = StatusVar('time_diff_start_ns', default=0)
    _time_diff_stop_ns = StatusVar('time_diff_stop_ns', default=100)

    _save_folderpath = StatusVar('save_folder_path', default='Default')
    save_folderpath = StatusVar('save_folderpath', default='')
    _save_dump_folderpath = StatusVar('save_dump_folderpath', default='')


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._timetaggerlogic = None
        self.fit_widget = None
        self._fit_config_dialog = None
        self._mw = None
        self._pw = None

    def on_deactivate(self):
        """ Reverse steps of activation """
        self._save_window_geometry(self._mw)
        self.__disconnect_fit_control_signals()
        self._fsd.close()
        self._fsd = None
        self._mw.close()

    def on_activate(self):
        self._timetaggerlogic = self.timetaggerlogic()
        self._mw = TTWindow()
        self._restore_window_geometry(self._mw)
        self._use_antialias = True

        self.threadlock_counter = Mutex()
        self.threadlock_corr = Mutex()

        # Fit settings dialog
        self._fsd = FitConfigurationDialog(
            parent=self._mw,
            fit_config_model=self._timetaggerlogic.fit_config_model
        )
        self._mw.actionFit_settings.triggered.connect(self._fsd.show)

        # Setup main window and dock widgets
        self._mw.centralwidget.hide()
        self._mw.setDockNestingEnabled(True)
        self._mw.tabifyDockWidget(self._mw.corr_dockWidget, self._mw.dockWidget_4)
        self._mw.tabifyDockWidget(self._mw.dockWidget_4, self._mw.time_diff_raw_dockWidget)
        self._mw.tabifyDockWidget(self._mw.time_diff_raw_dockWidget, self._mw.time_diff_dockWidget)


        # --- Configure PlotWidgets ---
        self._pw = self._mw.counterGraphicsView
        self._pw.setLabel('bottom', 'Time', units='s')
        self._pw.setLabel('left', 'Counts', units='c/s')
        self._pw.setMouseEnabled(x=False, y=False)
        self._pw.setMouseTracking(False)
        self._pw.setMenuEnabled(False)
        self._pw.hideButtons()

        self._corr_pw = self._mw.corrGraphicsView
        self._corr_pw.setLabel('bottom', 'Time', units='s')
        self._corr_pw.setLabel('left', 'g2', units='arb.')

        self._hist_pw = self._mw.histGraphicsView
        self._hist_pw.setLabel('bottom', 'Time', units='s')
        self._hist_pw.setLabel('left', 'Events', units='arb.')

        self._time_diff_raw_pw = self._mw.timeDiffRawGraphicsView
        self._time_diff_raw_pw.setLabel('bottom', 'Time', units='s')
        self._time_diff_raw_pw.setLabel('left', 'Events', units='arb.')

        self._time_diff_pw = self._mw.timeDiffGraphicsView
        self._time_diff_pw.setLabel('bottom', 'Histogram Number', units='#')
        self._time_diff_pw.setLabel('left', 'Counts', units='arb.')
        
        # Define colors for plots
        color = [pg.mkColor(c) for c in ['#115f9a', '#991f17', '#76c68f', '#ffb400', '#e27c7c', '#9080ff']]

        # --- Get hardware constraints and setup UI controls ---
        hw_constr = self._timetaggerlogic._constraints
        counter_channels = hw_constr['counter']['channels']
        hist_channels = hw_constr['hist']['channels']
        timediff_channels = hw_constr['time_differences']['channels']

        self.counter_channel_checkBoxes = {}
        self._mw.count_display_comboBox.addItem('Channel Sum')
        for ch in counter_channels:
            self._mw.count_display_comboBox.addItem(f'Channel {ch}')
            label = QtWidgets.QLabel(str(ch), self._mw)
            checkbox = QtWidgets.QCheckBox(self._mw)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self.update_counter)
            self.counter_channel_checkBoxes[ch] = checkbox
            idx = len(self.counter_channel_checkBoxes) -1
            self._mw.counterChannelGridLayout.addWidget(checkbox, idx, 1)
            self._mw.counterChannelGridLayout.addWidget(label, idx, 2)
            
        for ch in hist_channels:
            self._mw.histChannelComboBox.addItem(f'{ch}')
            
        for ch in timediff_channels:
            self._mw.timeDiffChannelComboBox.addItem(f'{ch}')

        # --- Setup Plot Curves ---
        self.curves = dict()
        self.averaged_curves = dict()
        for i, ch in enumerate(counter_channels):
            pen1 = pg.mkPen(color[i % len(color)], cosmetic=True)
            pen2 = pg.mkPen(color[(i+1) % len(color)], cosmetic=True)
            self.averaged_curves[ch] = pg.PlotCurveItem(pen=pen2, clipToView=True, downsampleMethod='subsample', autoDownsample=True)
            self.curves[ch] = pg.PlotCurveItem(pen=pen1, clipToView=True, downsampleMethod='subsample', autoDownsample=True)
            
        self.curves['sum'] = pg.PlotCurveItem(pen=pg.mkPen(color[0]), clipToView=True, downsampleMethod='subsample', autoDownsample=True)
        self.curves['corr'] = pg.PlotCurveItem(pen=pg.mkPen(color[2]), clipToView=True, downsampleMethod='subsample', autoDownsample=True)
        self.curves['hist'] = pg.PlotCurveItem(pen=pg.mkPen(color[2]), clipToView=True, downsampleMethod='subsample', autoDownsample=True)
        self.curves['time_diff_raw'] = pg.PlotCurveItem(pen=pg.mkPen(color[3]), clipToView=True, downsampleMethod='subsample', autoDownsample=True)
        self.curves['time_diff'] = pg.PlotCurveItem(pen=pg.mkPen(color[4]), symbol='o', symbolBrush=color[4], clipToView=True)

        self._corr_pw.addItem(self.curves['corr'])
        self.fit_curve = self._corr_pw.plot(pen=pg.mkPen(palette.c2, width=2))
        self._hist_pw.addItem(self.curves['hist'])
        self._time_diff_raw_pw.addItem(self.curves['time_diff_raw'])
        self._time_diff_pw.addItem(self.curves['time_diff'])
        
        # --- Time Difference Range Selectors ---
        self.time_diff_start_line = pg.InfiniteLine(pos=self._time_diff_start_ns / 1e9, angle=90, movable=True, pen='g')
        self.time_diff_stop_line = pg.InfiniteLine(pos=self._time_diff_stop_ns / 1e9, angle=90, movable=True, pen='r')
        self._time_diff_raw_pw.addItem(self.time_diff_start_line)
        self._time_diff_raw_pw.addItem(self.time_diff_stop_line)

        # --- Connecting signals and slots ---
        # Counter
        self._mw.toggleCounterPushButton.toggled.connect(self.update_counter)
        self._mw.counterCountFreqDoubleSpinBox.setValue(self._counter_freq)
        self._mw.counterCountLengthDoubleSpinBox.setValue(self._counter_length)
        self._mw.count_display_comboBox.currentTextChanged.connect(self.update_counter)
        self.sigToggleCounter.connect(self._timetaggerlogic.configure_counter, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigCounterDataChanged.connect(self.update_counter_data, QtCore.Qt.QueuedConnection)
        
        # Correlation
        self._mw.toggleCorrPushButton.toggled.connect(self.update_corr)
        self._mw.corrBinWidthDoubleSpinBox.setValue(self._corr_bin_width)
        self._mw.corrRecordLengthDoubleSpinBox.setValue(self._corr_record_length)
        self.sigToggleCorr.connect(self._timetaggerlogic.configure_corr, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigCorrDataChanged.connect(self.update_corr_data, QtCore.Qt.QueuedConnection)
        
        # Correlation Fitting
        self.fit_widget = FitWidget(parent=self._mw, fit_container=self._timetaggerlogic.fit_container)
        self._mw.fitLayout.addWidget(self.fit_widget)
        self.__connect_fit_control_signals()
        self._timetaggerlogic.sig_fit_updated.connect(self.update_fit)

        # Histogram
        self._mw.toggleHistPushButton.toggled.connect(self.update_hist)
        self._mw.histBinWidthDoubleSpinBox.setValue(self._hist_bin_width)
        self._mw.histRecordLengthDoubleSpinBox.setValue(self._hist_record_length)
        self.sigToggleHist.connect(self._timetaggerlogic.configure_hist, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigHistDataChanged.connect(self.update_hist_data, QtCore.Qt.QueuedConnection)

        # Time Difference
        self._mw.toggleTimeDiffPushButton.toggled.connect(self.update_time_diff)
        self._mw.timeDiffBinWidthDoubleSpinBox.setValue(self._time_diff_bin_width)
        self._mw.timeDiffRecordLengthDoubleSpinBox.setValue(self._time_diff_record_length)
        self._mw.timeDiffNumHistSpinBox.setValue(self._time_diff_num_histograms)
        self._mw.timeDiffStartDoubleSpinBox.setValue(self._time_diff_start_ns)
        self._mw.timeDiffStopDoubleSpinBox.setValue(self._time_diff_stop_ns)
        self.sigToggleTimeDiff.connect(self._timetaggerlogic.configure_time_diff, QtCore.Qt.QueuedConnection)
        self.sigSetTimeDiffRanges.connect(self._timetaggerlogic.set_time_diff_ranges, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigTimeDiffDataChanged.connect(self.update_time_diff_data, QtCore.Qt.QueuedConnection)
        self.time_diff_start_line.sigPositionChanged.connect(self.time_diff_range_line_moved)
        self.time_diff_stop_line.sigPositionChanged.connect(self.time_diff_range_line_moved)
        self._mw.timeDiffStartDoubleSpinBox.valueChanged.connect(self.time_diff_range_spinbox_changed)
        self._mw.timeDiffStopDoubleSpinBox.valueChanged.connect(self.time_diff_range_spinbox_changed)

        # Data Dumping
        self.sigToggleDump.connect(self._timetaggerlogic.dump_data, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigDumpSizeChanged.connect(self.update_dump_size, QtCore.Qt.QueuedConnection)
        self._mw.dump_checkBox.toggled.connect(self._dump_toggled)
        self._mw.currDumpPathLabel.setText(self._save_dump_folderpath)
        self._mw.dumpNewPathPushButton.clicked.connect(self._new_dump_path_clicked)

        # Data Saving
        self._mw.saveAllPushButton.clicked.connect(self._save_data_clicked)
        self._mw.currPathLabel.setText(self._save_folderpath)
        self._mw.DailyPathPushButton.clicked.connect(self._daily_path_clicked)
        self._mw.newPathPushButton.clicked.connect(self._new_path_clicked)
        self._mw.counter_checkBox.setChecked(True)
    
    def show(self):
        """Make window visible and put it above all other windows."""
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()
        return
        
    def update_counter(self):
        self._counter_freq = self._mw.counterCountFreqDoubleSpinBox.value()
        self._counter_length = self._mw.counterCountLengthDoubleSpinBox.value()
        channels = {ch: cb.isChecked() for ch, cb in self.counter_channel_checkBoxes.items()}
        
        items = self._pw.items()
        for ch, is_checked in channels.items():
            if is_checked and self.curves[ch] not in items:
                self._pw.addItem(self.curves[ch])
                self._pw.addItem(self.averaged_curves[ch])
            elif not is_checked and self.curves[ch] in items:
                self._pw.removeItem(self.curves[ch])
                self._pw.removeItem(self.averaged_curves[ch])
            
        toggle = self._mw.toggleCounterPushButton.isChecked()
        disp = self._mw.count_display_comboBox.currentText()
        signal_data = {'counter': (self._counter_freq, self._counter_length, channels, toggle, disp)}
        self.sigToggleCounter.emit(signal_data)
    
    def update_counter_data(self, data):
        for ch in data['trace_data']:
            x_arr, y_arr = data['trace_data'][ch]
            self.curves[ch].setData(y=y_arr, x=x_arr)
        for ch in data['trace_data_avg']:
            x_arr, y_arr = data['trace_data_avg'][ch]
            self.averaged_curves[ch].setData(y=y_arr, x=x_arr)
        counts = data['sum']
        self._mw.count_display_label.setText('{:.2r}c/s'.format(ScaledFloat(counts)))
        
    def update_dump_size(self, memory_used):
        self._mw.memory_label.setText('{:.2r}b'.format(ScaledFloat(memory_used)))

    def update_corr(self):
        self._corr_bin_width = self._mw.corrBinWidthDoubleSpinBox.value()
        self._corr_record_length = self._mw.corrRecordLengthDoubleSpinBox.value()

        toggle = self._mw.toggleCorrPushButton.isChecked()
        signal_data = {'corr': (self._corr_bin_width, self._corr_record_length, toggle)}
        self.sigToggleCorr.emit(signal_data)
    
    def update_corr_data(self, data):
        x_arr, y_arr = data['corr_data']
        self.curves['corr'].setData(y=y_arr, x=x_arr)
    
    def update_hist(self):
        self._hist_bin_width = self._mw.histBinWidthDoubleSpinBox.value()
        self._hist_record_length = self._mw.histRecordLengthDoubleSpinBox.value()

        toggle = self._mw.toggleHistPushButton.isChecked()
        signal_data = {'hist': (self._hist_bin_width, self._hist_record_length, int(self._mw.histChannelComboBox.currentText()), toggle)}
        self.sigToggleHist.emit(signal_data)
    
    def update_hist_data(self, data):
        x_arr, y_arr = data['hist_data']
        self.curves['hist'].setData(y=y_arr, x=x_arr)

    def update_time_diff(self):
        self._time_diff_bin_width = self._mw.timeDiffBinWidthDoubleSpinBox.value()
        self._time_diff_record_length = self._mw.timeDiffRecordLengthDoubleSpinBox.value()
        self._time_diff_num_histograms = self._mw.timeDiffNumHistSpinBox.value()
        click_ch_text = self._mw.timeDiffChannelComboBox.currentText()
        if not click_ch_text: return
            
        toggle = self._mw.toggleTimeDiffPushButton.isChecked()
        signal_data = {'time_diff': (self._time_diff_bin_width, self._time_diff_record_length, int(click_ch_text), self._time_diff_num_histograms, toggle)}
        self.sigToggleTimeDiff.emit(signal_data)

    def update_time_diff_data(self, data):
        if 'time_diff_data_raw' in data:
            x_raw, y_raw = data['time_diff_data_raw']
            self.curves['time_diff_raw'].setData(x=x_raw, y=y_raw)
        if 'time_diff_data' in data:
            x_proc, y_proc = data['time_diff_data']
            self.curves['time_diff'].setData(x=x_proc, y=y_proc)

    def time_diff_range_line_moved(self):
        start_val_s = self.time_diff_start_line.value()
        stop_val_s = self.time_diff_stop_line.value()
        
        self._time_diff_start_ns = start_val_s * 1e9
        self._time_diff_stop_ns = stop_val_s * 1e9

        self._mw.timeDiffStartDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffStopDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffStartDoubleSpinBox.setValue(self._time_diff_start_ns)
        self._mw.timeDiffStopDoubleSpinBox.setValue(self._time_diff_stop_ns)
        self._mw.timeDiffStartDoubleSpinBox.blockSignals(False)
        self._mw.timeDiffStopDoubleSpinBox.blockSignals(False)

        self.sigSetTimeDiffRanges.emit(self._time_diff_start_ns, self._time_diff_stop_ns)

    def time_diff_range_spinbox_changed(self):
        self._time_diff_start_ns = self._mw.timeDiffStartDoubleSpinBox.value()
        self._time_diff_stop_ns = self._mw.timeDiffStopDoubleSpinBox.value()
        
        self.time_diff_start_line.blockSignals(True)
        self.time_diff_stop_line.blockSignals(True)
        self.time_diff_start_line.setValue(self._time_diff_start_ns / 1e9)
        self.time_diff_stop_line.setValue(self._time_diff_stop_ns / 1e9)
        self.time_diff_start_line.blockSignals(False)
        self.time_diff_stop_line.blockSignals(False)

        self.sigSetTimeDiffRanges.emit(self._time_diff_start_ns, self._time_diff_stop_ns)

    def _new_path_clicked(self):
        new_path = QtWidgets.QFileDialog.getExistingDirectory(self._mw, 'Select Folder')
        if new_path:
            self._save_folderpath = new_path
            self._mw.currPathLabel.setText(self._save_folderpath)
    
    def _daily_path_clicked(self):
        self._save_folderpath = 'Default'
        self._mw.currPathLabel.setText(self._save_folderpath)

    def _new_dump_path_clicked(self):
        new_path = QtWidgets.QFileDialog.getExistingDirectory(self._mw, 'Select Folder')
        if new_path:
            self._save_dump_folderpath = new_path
            self._mw.currDumpPathLabel.setText(self._save_dump_folderpath)

    def _dump_toggled(self):
        if not self._mw.dump_checkBox.isChecked():
            self.sigToggleDump.emit(False, '', '')
        else:
            if self._mw.dumpNewPathPushButton.isChecked() and self._mw.dumpNewPathPushButton.isEnabled():
                self._mw.currDumpPathLabel.setText(self._save_dump_folderpath)
                self._mw.dumpNewPathPushButton.setChecked(False)
                self.sigToggleDump.emit(True, self._mw.saveDumpTagLineEdit.text(), self._save_dump_folderpath)
            elif self._save_dump_folderpath.strip():
                self._mw.currDumpPathLabel.setText(self._save_dump_folderpath)
                self._mw.dumpNewPathPushButton.setChecked(False)
                self.sigToggleDump.emit(True, self._mw.saveDumpTagLineEdit.text(), self._save_dump_folderpath)
            else:
                self.log.warning("Set the dump path.")

    def _save_data_clicked(self):
        save_type = next((st for st, cb in {
            'counter': self._mw.counter_checkBox, 
            'corr': self._mw.corr_checkBox, 
            'hist': self._mw.hist_checkBox
        }.items() if cb.isChecked()), None)

        if self._mw.newPathPushButton.isChecked() and self._mw.newPathPushButton.isEnabled():
            self._mw.currPathLabel.setText(self._save_folderpath)
            self._mw.newPathPushButton.setChecked(False)
        if self._mw.DailyPathPushButton.isChecked():
            self._save_folderpath = 'Default'
            self._mw.currPathLabel.setText(self._save_folderpath)
        
        self._timetaggerlogic._save_recorded_data(to_file=True, 
                                                  name_tag=self._mw.saveTagLineEdit.text(), 
                                                  save_figure=True, 
                                                  save_type=save_type, 
                                                  save_path = self._save_folderpath)

    def update_fit(self, fit_method, fit_results):
        """ Update the drawn fit curve. """
        if fit_method != 'No Fit' and fit_results is not None:
            self.fit_curve.setData(x=fit_results.high_res_best_fit[0], y=fit_results.high_res_best_fit[1])
        else:
            self.fit_curve.setData(x=[], y=[])

    def __connect_fit_control_signals(self):
        self.fit_widget.link_fit_container(self._timetaggerlogic.fit_container)
        self.fit_widget.sigDoFit.connect(self._timetaggerlogic.do_fit)

    def __disconnect_fit_control_signals(self):
        self.fit_widget.sigDoFit.disconnect()
