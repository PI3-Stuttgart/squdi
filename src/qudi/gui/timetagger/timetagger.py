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
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
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
    sigSetTimeDiffRefRanges = QtCore.Signal(float, float)
    sigToggleDump = QtCore.Signal(bool, str, str)
    sigToggleGatedCounter = QtCore.Signal(object)
    sigToggleSSR = QtCore.Signal(object)

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
    _time_diff_ref_start_ns = StatusVar('time_diff_ref_start_ns', default=120)
    _time_diff_ref_stop_ns = StatusVar('time_diff_ref_stop_ns', default=220)
    _time_diff_use_ref = StatusVar('time_diff_use_ref', default=False)


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
        self._gated_counter_dock = None  # created programmatically if veto channel configured
        self._ssr_dock = None  # created programmatically if time difference channels are configured

    def on_deactivate(self):
        """ Reverse steps of activation """
        self._save_window_geometry(self._mw)
        self.__disconnect_fit_control_signals()
        if self._gated_counter_dock is not None:
            self.sigToggleGatedCounter.disconnect()
            self._timetaggerlogic.sigGatedCounterDataChanged.disconnect(self.update_gated_counter_data)
        if self._ssr_dock is not None:
            self.sigToggleSSR.disconnect()
            self._timetaggerlogic.sigSsrDataChanged.disconnect(self.update_ssr_data)
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
        self._time_diff_pw.setLabel('left', 'Counts (Signal/Ref. Mean)', units='arb.')
        
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
        self.time_diff_ref_start_line = pg.InfiniteLine(pos=self._time_diff_ref_start_ns / 1e9, angle=90, movable=True, pen=pg.mkPen('b', style=QtCore.Qt.DashLine))
        self.time_diff_ref_stop_line = pg.InfiniteLine(pos=self._time_diff_ref_stop_ns / 1e9, angle=90, movable=True, pen=pg.mkPen('b', style=QtCore.Qt.DashLine))

        self._time_diff_raw_pw.addItem(self.time_diff_start_line)
        self._time_diff_raw_pw.addItem(self.time_diff_stop_line)
        self._time_diff_raw_pw.addItem(self.time_diff_ref_start_line)
        self._time_diff_raw_pw.addItem(self.time_diff_ref_stop_line)


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
        self._mw.toggleTimeDiffPushButton.toggled.connect(self.update_time_diff)
        self._mw.timeDiffUseRefCheckBox.toggled.connect(self.update_time_diff)
        
        # Connect widget signals directly to the property setters
        self._mw.timeDiffBinWidthDoubleSpinBox.valueChanged.connect(lambda value: setattr(self, 'time_diff_bin_width', value))
        self._mw.timeDiffRecordLengthDoubleSpinBox.valueChanged.connect(lambda value: setattr(self, 'time_diff_record_length', value))
        self._mw.timeDiffNumHistSpinBox.valueChanged.connect(lambda value: setattr(self, 'time_diff_num_histograms', value))
        self._mw.timeDiffUseRefCheckBox.toggled.connect(lambda checked: setattr(self, 'time_diff_use_ref', checked))
        
        # Initialize widget values from StatusVar using the new properties/setters
        self.time_diff_bin_width = self._time_diff_bin_width
        self.time_diff_record_length = self._time_diff_record_length
        self.time_diff_num_histograms = self._time_diff_num_histograms
        self.time_diff_use_ref = self._time_diff_use_ref

        # The rest of the original connections remain
        self._mw.timeDiffStartDoubleSpinBox.setValue(self._time_diff_start_ns)
        self._mw.timeDiffStopDoubleSpinBox.setValue(self._time_diff_stop_ns)
        self._mw.timeDiffRefStartDoubleSpinBox.setValue(self._time_diff_ref_start_ns)
        self._mw.timeDiffRefStopDoubleSpinBox.setValue(self._time_diff_ref_stop_ns)

        self.sigToggleTimeDiff.connect(self._timetaggerlogic.configure_time_diff, QtCore.Qt.QueuedConnection)
        self.sigSetTimeDiffRanges.connect(self._timetaggerlogic.set_time_diff_ranges, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigTimeDiffDataChanged.connect(self.update_time_diff_data, QtCore.Qt.QueuedConnection)
        
        self.time_diff_start_line.sigPositionChanged.connect(self.time_diff_range_line_moved)
        self.time_diff_stop_line.sigPositionChanged.connect(self.time_diff_range_line_moved)
        self.time_diff_ref_start_line.sigPositionChanged.connect(self.time_diff_ref_range_line_moved)
        self.time_diff_ref_stop_line.sigPositionChanged.connect(self.time_diff_ref_range_line_moved)
        
        self._mw.timeDiffStartDoubleSpinBox.valueChanged.connect(self.time_diff_range_spinbox_changed)
        self._mw.timeDiffStopDoubleSpinBox.valueChanged.connect(self.time_diff_range_spinbox_changed)
        self._mw.timeDiffRefStartDoubleSpinBox.valueChanged.connect(self.time_diff_ref_range_spinbox_changed)
        self._mw.timeDiffRefStopDoubleSpinBox.valueChanged.connect(self.time_diff_ref_range_spinbox_changed)

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

        # --- Optional: Gated Counter (CRC-filtered) dock widget ---
        if self._timetaggerlogic.gated_counter_available:
            self._setup_gated_counter_dock()
        else:
            self._gated_counter_dock = None
        if self._timetaggerlogic.ssr_available:
            self._setup_ssr_dock()
        else:
            self._ssr_dock = None
    
    


    def show(self):
        """Make window visible and put it above all other windows."""
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()
        return

    def _setup_gated_counter_dock(self):
        """Programmatically create the optional Gated Counter dock widget."""
        color = [pg.mkColor(c) for c in ['#115f9a', '#991f17', '#76c68f', '#ffb400']]
        hw_constr = self._timetaggerlogic._constraints
        counter_channels = hw_constr['counter']['channels']

        # --- Dock Widget ---
        self._gated_counter_dock = QtWidgets.QDockWidget('Gated Counter (CRC)', self._mw)
        self._gated_counter_dock.setObjectName('gated_counter_crc_dockWidget')
        self._gated_counter_dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        contents = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(contents)

        # Plot
        self._gated_pw = pg.PlotWidget()
        self._gated_pw.setLabel('bottom', 'Time', units='s')
        self._gated_pw.setLabel('left', 'Counts (CRC gated)', units='c/s')
        self._gated_pw.setMouseEnabled(x=False, y=False)
        self._gated_pw.setMenuEnabled(False)
        self._gated_pw.hideButtons()
        layout.addWidget(self._gated_pw, 0, 0, 3, 1)

        # Settings group
        settings_grp = QtWidgets.QGroupBox('Settings')
        settings_grp.setMaximumWidth(195)
        settings_layout = QtWidgets.QFormLayout(settings_grp)

        self._gated_freq_spinbox = QtWidgets.QDoubleSpinBox()
        self._gated_freq_spinbox.setSuffix(' Hz')
        self._gated_freq_spinbox.setDecimals(0)
        self._gated_freq_spinbox.setMinimum(1)
        self._gated_freq_spinbox.setMaximum(100000)
        self._gated_freq_spinbox.setValue(self._counter_freq)
        settings_layout.addRow('Count Freq.', self._gated_freq_spinbox)

        self._gated_length_spinbox = QtWidgets.QDoubleSpinBox()
        self._gated_length_spinbox.setSuffix(' s')
        self._gated_length_spinbox.setDecimals(0)
        self._gated_length_spinbox.setMinimum(1)
        self._gated_length_spinbox.setMaximum(1000000)
        self._gated_length_spinbox.setValue(self._counter_length)
        settings_layout.addRow('Length', self._gated_length_spinbox)

        self._gated_channel_checkboxes = {}
        ch_label = QtWidgets.QLabel('Channels:')
        settings_layout.addRow(ch_label)
        for ch in counter_channels:
            cb = QtWidgets.QCheckBox(f'Ch {ch}')
            cb.setChecked(True)
            cb.toggled.connect(self.update_gated_counter)
            self._gated_channel_checkboxes[ch] = cb
            settings_layout.addRow(cb)

        self._gated_toggle_btn = QtWidgets.QPushButton('Toggle')
        self._gated_toggle_btn.setCheckable(True)
        self._gated_toggle_btn.toggled.connect(self.update_gated_counter)
        settings_layout.addRow(self._gated_toggle_btn)

        # Extra gate closure spinbox (keeps gate closed after kick ends)
        self._gated_extra_gate_spinbox = ScienDSpinBox()
        self._gated_extra_gate_spinbox.setSuffix('s')
        self._gated_extra_gate_spinbox.setDecimals(9)
        self._gated_extra_gate_spinbox.setMinimum(-1)
        self._gated_extra_gate_spinbox.setMaximum(1)
        self._gated_extra_gate_spinbox.setValue(0.00001)  # default: 400 mus
        self._gated_extra_gate_spinbox.setToolTip(
            'Extra time the gate stays closed after the kick ends\n'
            '(covers laser turn-off transient). Re-toggle to apply.'
        )
        settings_layout.addRow('Extra Gate', self._gated_extra_gate_spinbox)

        layout.addWidget(settings_grp, 0, 1)

        # Display frame
        disp_frame = QtWidgets.QFrame()
        disp_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        disp_frame.setMaximumWidth(195)
        disp_layout = QtWidgets.QVBoxLayout(disp_frame)
        self._gated_count_label = QtWidgets.QLabel('0 c/s')
        font = QtGui.QFont('Segoe UI Semilight', 20)
        self._gated_count_label.setFont(font)
        self._gated_count_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        disp_layout.addWidget(self._gated_count_label)
        layout.addWidget(disp_frame, 1, 1)

        layout.addItem(QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum,
                                              QtWidgets.QSizePolicy.Expanding), 2, 1)

        self._gated_counter_dock.setWidget(contents)
        self._mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, self._gated_counter_dock)
        self._mw.tabifyDockWidget(self._mw.corr_dockWidget, self._gated_counter_dock)

        # Plot curve
        self._gated_curve = pg.PlotCurveItem(pen=pg.mkPen(color[2]), clipToView=True)
        self._gated_curve_avg = pg.PlotCurveItem(pen=pg.mkPen(color[3]), clipToView=True)
        self._gated_pw.addItem(self._gated_curve)
        self._gated_pw.addItem(self._gated_curve_avg)

        # Connect signals
        self.sigToggleGatedCounter.connect(self._timetaggerlogic.configure_gated_counter, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigGatedCounterDataChanged.connect(self.update_gated_counter_data, QtCore.Qt.QueuedConnection)
        
    def update_gated_counter(self):
        """Emit signal to start/stop gated counter with current settings."""
        freq = self._gated_freq_spinbox.value()
        length = self._gated_length_spinbox.value()
        channels = {ch: cb.isChecked() for ch, cb in self._gated_channel_checkboxes.items()}
        toggle = self._gated_toggle_btn.isChecked()
        extra_gate_ms = self._gated_extra_gate_spinbox.value()
        self.sigToggleGatedCounter.emit({'gated_counter': (freq, length, channels, toggle, extra_gate_ms)})

    def update_gated_counter_data(self, data):
        """Update the gated counter plot and count display."""
        x, y = data['trace']
        self._gated_curve.setData(x=x, y=y)
        if data['trace_avg'][0].size > 0:
            xa, ya = data['trace_avg']
            self._gated_curve_avg.setData(x=xa, y=ya)
        self._gated_count_label.setText('{:.2r}c/s'.format(ScaledFloat(data['sum'])))

    def _setup_ssr_dock(self):
        """Programmatically create the optional SSR dock widget."""
        color = [pg.mkColor(c) for c in ['#115f9a', '#991f17', '#76c68f', '#ffb400']]
        hw_constr = self._timetaggerlogic._constraints
        timediff_channels = hw_constr['time_differences']['channels']

        self._ssr_dock = QtWidgets.QDockWidget('SSR (CRC + Readout)', self._mw)
        self._ssr_dock.setObjectName('ssr_dockWidget')
        self._ssr_dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        contents = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(contents)

        self._ssr_raw_pw = pg.PlotWidget()
        self._ssr_raw_pw.setLabel('bottom', 'Time', units='s')
        self._ssr_raw_pw.setLabel('left', 'Summed Counts', units='counts')
        self._ssr_raw_pw.setMouseEnabled(x=False, y=False)
        self._ssr_raw_pw.setMenuEnabled(False)
        self._ssr_raw_pw.hideButtons()
        layout.addWidget(self._ssr_raw_pw, 0, 0)

        self._ssr_hist_pw = pg.PlotWidget()
        self._ssr_hist_pw.setLabel('bottom', 'Readout Counts', units='counts')
        self._ssr_hist_pw.setLabel('left', 'Shots', units='#')
        self._ssr_hist_pw.setMouseEnabled(x=False, y=False)
        self._ssr_hist_pw.setMenuEnabled(False)
        self._ssr_hist_pw.hideButtons()
        layout.addWidget(self._ssr_hist_pw, 1, 0)

        self._ssr_raw_curve = pg.PlotCurveItem(pen=pg.mkPen(color[2]), clipToView=True)
        self._ssr_hist_curve = pg.PlotCurveItem(pen=pg.mkPen(color[3]), symbol='o',
                                                symbolBrush=color[3], symbolSize=4, clipToView=True)
        self._ssr_threshold_line = pg.InfiniteLine(angle=90, movable=False,
                                                   pen=pg.mkPen(color[1], style=QtCore.Qt.DashLine))
        self._ssr_raw_pw.addItem(self._ssr_raw_curve)
        self._ssr_hist_pw.addItem(self._ssr_hist_curve)
        self._ssr_hist_pw.addItem(self._ssr_threshold_line)

        settings_grp = QtWidgets.QGroupBox('Settings')
        settings_grp.setMaximumWidth(235)
        settings_layout = QtWidgets.QFormLayout(settings_grp)

        self._ssr_click_channel_combo = QtWidgets.QComboBox()
        for ch in timediff_channels:
            self._ssr_click_channel_combo.addItem(str(ch))
        settings_layout.addRow('Click Ch.', self._ssr_click_channel_combo)

        self._ssr_bin_width_spinbox = QtWidgets.QDoubleSpinBox()
        self._ssr_bin_width_spinbox.setDecimals(0)
        self._ssr_bin_width_spinbox.setMinimum(1)
        self._ssr_bin_width_spinbox.setMaximum(1e9)
        self._ssr_bin_width_spinbox.setSuffix(' ps')
        self._ssr_bin_width_spinbox.setValue(self._time_diff_bin_width)
        settings_layout.addRow('Bin Width', self._ssr_bin_width_spinbox)

        self._ssr_record_length_spinbox = QtWidgets.QDoubleSpinBox()
        self._ssr_record_length_spinbox.setDecimals(3)
        self._ssr_record_length_spinbox.setMinimum(1e-3)
        self._ssr_record_length_spinbox.setMaximum(1e9)
        self._ssr_record_length_spinbox.setSuffix(' us')
        self._ssr_record_length_spinbox.setValue(self._time_diff_record_length)
        settings_layout.addRow('Record Length', self._ssr_record_length_spinbox)

        self._ssr_num_hist_spinbox = QtWidgets.QSpinBox()
        self._ssr_num_hist_spinbox.setMinimum(1)
        self._ssr_num_hist_spinbox.setMaximum(1000000)
        self._ssr_num_hist_spinbox.setValue(self._time_diff_num_histograms)
        settings_layout.addRow('# Hist', self._ssr_num_hist_spinbox)

        self._ssr_crc_start_spinbox = ScienDSpinBox()
        self._ssr_crc_start_spinbox.setMinimum(0)
        self._ssr_crc_start_spinbox.setMaximum(1e9)
        self._ssr_crc_start_spinbox.setSuffix(' ns')
        self._ssr_crc_start_spinbox.setValue(self._time_diff_start_ns)
        settings_layout.addRow('CRC Start', self._ssr_crc_start_spinbox)

        self._ssr_crc_stop_spinbox = ScienDSpinBox()
        self._ssr_crc_stop_spinbox.setMinimum(0)
        self._ssr_crc_stop_spinbox.setMaximum(1e9)
        self._ssr_crc_stop_spinbox.setSuffix(' ns')
        self._ssr_crc_stop_spinbox.setValue(self._time_diff_stop_ns)
        settings_layout.addRow('CRC Stop', self._ssr_crc_stop_spinbox)

        self._ssr_readout_start_spinbox = ScienDSpinBox()
        self._ssr_readout_start_spinbox.setMinimum(0)
        self._ssr_readout_start_spinbox.setMaximum(1e9)
        self._ssr_readout_start_spinbox.setSuffix(' ns')
        self._ssr_readout_start_spinbox.setValue(self._time_diff_ref_start_ns)
        settings_layout.addRow('SSR Start', self._ssr_readout_start_spinbox)

        self._ssr_readout_stop_spinbox = ScienDSpinBox()
        self._ssr_readout_stop_spinbox.setMinimum(0)
        self._ssr_readout_stop_spinbox.setMaximum(1e9)
        self._ssr_readout_stop_spinbox.setSuffix(' ns')
        self._ssr_readout_stop_spinbox.setValue(self._time_diff_ref_stop_ns)
        settings_layout.addRow('SSR Stop', self._ssr_readout_stop_spinbox)

        self._ssr_crc_threshold_spinbox = ScienDSpinBox()
        self._ssr_crc_threshold_spinbox.setMinimum(0)
        self._ssr_crc_threshold_spinbox.setMaximum(1e9)
        self._ssr_crc_threshold_spinbox.setValue(1.0)
        settings_layout.addRow('CRC Thres.', self._ssr_crc_threshold_spinbox)

        self._ssr_readout_threshold_spinbox = ScienDSpinBox()
        self._ssr_readout_threshold_spinbox.setMinimum(0)
        self._ssr_readout_threshold_spinbox.setMaximum(1e9)
        self._ssr_readout_threshold_spinbox.setValue(2.0)
        settings_layout.addRow('SSR Thres.', self._ssr_readout_threshold_spinbox)

        self._ssr_toggle_btn = QtWidgets.QPushButton('Toggle SSR')
        self._ssr_toggle_btn.setCheckable(True)
        settings_layout.addRow(self._ssr_toggle_btn)
        layout.addWidget(settings_grp, 0, 1)

        stats_frame = QtWidgets.QFrame()
        stats_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        stats_frame.setMaximumWidth(235)
        stats_layout = QtWidgets.QVBoxLayout(stats_frame)
        self._ssr_status_label = QtWidgets.QLabel('Valid 0/0\nPass 0.0%\nBright 0.0%\nDark 0.0%')
        self._ssr_status_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        stats_layout.addWidget(self._ssr_status_label)
        layout.addWidget(stats_frame, 1, 1)

        self._ssr_dock.setWidget(contents)
        self._mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, self._ssr_dock)
        self._mw.tabifyDockWidget(self._mw.time_diff_dockWidget, self._ssr_dock)

        self.sigToggleSSR.connect(self._timetaggerlogic.configure_ssr, QtCore.Qt.QueuedConnection)
        self._timetaggerlogic.sigSsrDataChanged.connect(self.update_ssr_data, QtCore.Qt.QueuedConnection)

        self._ssr_click_channel_combo.currentTextChanged.connect(self.update_ssr)
        self._ssr_toggle_btn.toggled.connect(self.update_ssr)
        self._ssr_bin_width_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_record_length_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_num_hist_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_crc_start_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_crc_stop_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_readout_start_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_readout_stop_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_crc_threshold_spinbox.editingFinished.connect(self.update_ssr)
        self._ssr_readout_threshold_spinbox.editingFinished.connect(self.update_ssr)
        self.update_ssr()

    def update_ssr(self):
        """Emit signal to start/stop SSR monitor with current settings."""
        click_ch = self._ssr_click_channel_combo.currentText()
        if not click_ch:
            return
        signal_data = {
            'ssr': (
                self._ssr_bin_width_spinbox.value(),
                self._ssr_record_length_spinbox.value(),
                int(click_ch),
                self._ssr_num_hist_spinbox.value(),
                self._ssr_toggle_btn.isChecked(),
                self._ssr_crc_start_spinbox.value(),
                self._ssr_crc_stop_spinbox.value(),
                self._ssr_readout_start_spinbox.value(),
                self._ssr_readout_stop_spinbox.value(),
                self._ssr_crc_threshold_spinbox.value(),
                self._ssr_readout_threshold_spinbox.value()
            )
        }
        self.sigToggleSSR.emit(signal_data)

    def update_ssr_data(self, data):
        """Update SSR raw trace, histogram and summary labels."""
        raw_x, raw_y = data['raw_trace']
        hist_x, hist_y = data['ssr_hist']
        self._ssr_raw_curve.setData(x=raw_x, y=raw_y)
        self._ssr_hist_curve.setData(x=hist_x, y=hist_y)
        self._ssr_threshold_line.setValue(data['readout_threshold'])
        self._ssr_status_label.setText(
            f"Valid {data['valid_shots']}/{data['total_shots']}\n"
            f"Pass {100.0 * data['crc_pass_rate']:.1f}%\n"
            f"Bright {100.0 * data['bright_rate']:.1f}%\n"
            f"Dark {100.0 * data['dark_rate']:.1f}%"
        )

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
        
        click_ch_text = self._mw.timeDiffChannelComboBox.currentText()
        if not click_ch_text: return
            
        toggle = self._mw.toggleTimeDiffPushButton.isChecked()
        signal_data = {'time_diff': (self._time_diff_bin_width, self._time_diff_record_length, int(click_ch_text), self._time_diff_num_histograms, toggle, self._time_diff_use_ref)}
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

    def time_diff_ref_range_line_moved(self):
        start_val_s = self.time_diff_ref_start_line.value()
        stop_val_s = self.time_diff_ref_stop_line.value()
        
        self._time_diff_ref_start_ns = start_val_s * 1e9
        self._time_diff_ref_stop_ns = stop_val_s * 1e9

        self._mw.timeDiffRefStartDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffRefStopDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffRefStartDoubleSpinBox.setValue(self._time_diff_ref_start_ns)
        self._mw.timeDiffRefStopDoubleSpinBox.setValue(self._time_diff_ref_stop_ns)
        self._mw.timeDiffRefStartDoubleSpinBox.blockSignals(False)
        self._mw.timeDiffRefStopDoubleSpinBox.blockSignals(False)

        self.sigSetTimeDiffRefRanges.emit(self._time_diff_ref_start_ns, self._time_diff_ref_stop_ns)
        
    def time_diff_ref_range_spinbox_changed(self):
        self._time_diff_ref_start_ns = self._mw.timeDiffRefStartDoubleSpinBox.value()
        self._time_diff_ref_stop_ns = self._mw.timeDiffRefStopDoubleSpinBox.value()
        
        self.time_diff_ref_start_line.blockSignals(True)
        self.time_diff_ref_stop_line.blockSignals(True)
        self.time_diff_ref_start_line.setValue(self._time_diff_ref_start_ns / 1e9)
        self.time_diff_ref_stop_line.setValue(self._time_diff_ref_stop_ns / 1e9)
        self.time_diff_ref_start_line.blockSignals(False)
        self.time_diff_ref_stop_line.blockSignals(False)

        self.sigSetTimeDiffRefRanges.emit(self._time_diff_ref_start_ns, self._time_diff_ref_stop_ns)

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
        save_type = None
        if self._mw.counter_checkBox.isChecked():
            save_type = 'counter'
        elif self._mw.corr_checkBox.isChecked():
            save_type = 'corr'
        elif self._mw.hist_checkBox.isChecked():
            save_type = 'hist'
        elif self._mw.time_diff_checkBox.isChecked():
            save_type = 'time_diff'
        elif self._mw.time_diff_raw_checkBox.isChecked():
            save_type = 'time_diff_raw'

        if save_type is None:
            self.log.warning("No data type selected for saving.")
            return

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

    @property
    def time_diff_bin_width(self):
        return self._time_diff_bin_width

    @time_diff_bin_width.setter
    def time_diff_bin_width(self, value):
        self._time_diff_bin_width = value
        self._mw.timeDiffBinWidthDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffBinWidthDoubleSpinBox.setValue(value)
        self._mw.timeDiffBinWidthDoubleSpinBox.blockSignals(False)

    @property
    def time_diff_record_length(self):
        return self._time_diff_record_length

    @time_diff_record_length.setter
    def time_diff_record_length(self, value):
        self._time_diff_record_length = value
        self._mw.timeDiffRecordLengthDoubleSpinBox.blockSignals(True)
        self._mw.timeDiffRecordLengthDoubleSpinBox.setValue(value)
        self._mw.timeDiffRecordLengthDoubleSpinBox.blockSignals(False)

    @property
    def time_diff_num_histograms(self):
        return self._time_diff_num_histograms

    @time_diff_num_histograms.setter
    def time_diff_num_histograms(self, value):
        self._time_diff_num_histograms = value
        self._mw.timeDiffNumHistSpinBox.blockSignals(True)
        self._mw.timeDiffNumHistSpinBox.setValue(value)
        self._mw.timeDiffNumHistSpinBox.blockSignals(False)

    @property
    def time_diff_use_ref(self):
        return self._time_diff_use_ref

    @time_diff_use_ref.setter
    def time_diff_use_ref(self, checked):
        self._time_diff_use_ref = checked
        self._mw.timeDiffUseRefCheckBox.blockSignals(True)
        self._mw.timeDiffUseRefCheckBox.setChecked(checked)
        self._mw.timeDiffUseRefCheckBox.blockSignals(False)
