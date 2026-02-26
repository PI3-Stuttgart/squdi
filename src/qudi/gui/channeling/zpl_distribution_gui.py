# -*- coding: utf-8 -*-
"""
GUI module for ZPL distribution measurement.
"""

from qtpy import QtWidgets, QtCore
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from qudi.core.module import GuiBase
from qudi.core.connector import Connector

class WavelengthCheckDialog(QtWidgets.QDialog):
    def __init__(self, voltages, freqs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wavelength Coverage Check")
        self.resize(600, 400)
        
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        
        # Plot
        # Filter valid
        v_valid = []
        f_valid = []
        for v, f in zip(voltages, freqs):
            if not np.isnan(f):
                v_valid.append(v)
                f_valid.append(f)
                
        if v_valid:
            self.ax.plot(v_valid, f_valid, 'b.-')
            self.ax.set_xlabel("Voltage (V)")
            self.ax.set_ylabel("Frequency (GHz rel. to 484.135 THz)")
            self.ax.set_title("Wavelength Coverage")
            self.ax.grid(True)
            
            start_f = f_valid[0]
            end_f = f_valid[-1]
            layout.addWidget(QtWidgets.QLabel(f"Range: {start_f:.2f} to {end_f:.2f} GHz"))
        else:
            self.ax.text(0.5, 0.5, "No Data", ha='center')
            
        layout.addWidget(self.canvas)
        
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

class ZPLDistributionGui(GuiBase):
    """
    GUI Class for ZPL Distribution.
    """
    
    _logic = Connector(name='logic', interface='ZPLDistributionLogic')

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self._mw = QtWidgets.QWidget()
        self._mw.setWindowTitle('ZPL Distribution')
        self._init_ui()

    def on_activate(self):
        self._logic().sigUpdatePlot.connect(self.update_plot)
        self._logic().sigMeasurementFinished.connect(self.on_finished)
        self._logic().sigScanCompleted.connect(self.on_scan_completed)
        self._logic().sigWavelengthCheckFinished.connect(self.on_coverage_check_finished)
        self._logic().sigBackgroundCaptured.connect(self.on_background_captured)
        self.show()
        
    def on_deactivate(self):
        self._logic().sigUpdatePlot.disconnect(self.update_plot)
        self._logic().sigMeasurementFinished.disconnect(self.on_finished)
        self._logic().sigScanCompleted.disconnect(self.on_scan_completed)
        self._logic().sigWavelengthCheckFinished.disconnect(self.on_coverage_check_finished)
        self._logic().sigBackgroundCaptured.disconnect(self.on_background_captured)
        if self._mw:
            self._mw.close()

    def show(self):
        """Make the window visible."""
        if self._mw:
            self._mw.show()
            self._mw.raise_()

    def _init_ui(self):
        # Main Layout
        layout = QtWidgets.QVBoxLayout()
        self._mw.setLayout(layout)

        # 1. Measurement Controls Top Bar
        control_layout = QtWidgets.QHBoxLayout()
        
        self.start_spin = QtWidgets.QDoubleSpinBox()
        self.start_spin.setPrefix("Start: ")
        self.start_spin.setSuffix(" V")
        self.start_spin.setRange(0, 150)
        self.start_spin.setValue(0)
        
        self.stop_spin = QtWidgets.QDoubleSpinBox()
        self.stop_spin.setPrefix("Stop: ")
        self.stop_spin.setSuffix(" V")
        self.stop_spin.setRange(0, 150)
        self.stop_spin.setValue(100)
        
        self.step_spin = QtWidgets.QDoubleSpinBox()
        self.step_spin.setPrefix("Step: ")
        self.step_spin.setSuffix(" V")
        self.step_spin.setRange(0.001, 100)
        self.step_spin.setValue(5)
        
        self.start_btn = QtWidgets.QPushButton("Start Measurement")
        self.start_btn.clicked.connect(self.start_measurement)
        
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)

        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_measurement)
        self.stop_btn.setEnabled(False)

        control_layout.addWidget(self.start_spin)
        control_layout.addWidget(self.stop_spin)
        control_layout.addWidget(self.step_spin)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.stop_btn)
        
        # Laser Selector
        self.laser_combo = QtWidgets.QComboBox()
        self.laser_combo.addItems(["Main", "QInu"])
        # Set current index based on logic if possible? logic not connected yet fully.
        # We will set it in on_activate or just relies on default.
        control_layout.addWidget(QtWidgets.QLabel("Laser:"))
        control_layout.addWidget(self.laser_combo)
        
        # Focused Mode Controls
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Linear", "Focused"])
        self.mode_combo.currentIndexChanged.connect(self.update_mode_visibility)
        
        self.focused_widget = QtWidgets.QWidget()
        focused_layout = QtWidgets.QHBoxLayout()
        focused_layout.setContentsMargins(0, 0, 0, 0)
        self.focused_widget.setLayout(focused_layout)
        
        self.focus_center_spin = QtWidgets.QDoubleSpinBox()
        self.focus_center_spin.setPrefix("Center: ")
        self.focus_center_spin.setSuffix(" V")
        self.focus_center_spin.setRange(0, 150)
        self.focus_center_spin.setValue(50)
        
        self.focus_width_spin = QtWidgets.QDoubleSpinBox()
        self.focus_width_spin.setPrefix("Width: ")
        self.focus_width_spin.setSuffix(" V")
        self.focus_width_spin.setRange(0.1, 100)
        self.focus_width_spin.setValue(20)
        
        self.fine_step_spin = QtWidgets.QDoubleSpinBox()
        self.fine_step_spin.setPrefix("Fine Step: ")
        self.fine_step_spin.setSuffix(" V")
        self.fine_step_spin.setRange(0.001, 10)
        self.fine_step_spin.setValue(1.0)
        
        self.coarse_step_spin = QtWidgets.QDoubleSpinBox()
        self.coarse_step_spin.setPrefix("Coarse: ")
        self.coarse_step_spin.setSuffix(" V")
        self.coarse_step_spin.setRange(0.001, 20)
        self.coarse_step_spin.setValue(5.0)
        
        focused_layout.addWidget(self.focus_center_spin)
        focused_layout.addWidget(self.focus_width_spin)
        focused_layout.addWidget(self.fine_step_spin)
        focused_layout.addWidget(self.coarse_step_spin)
        
        self.focused_widget.setVisible(False)
        
        control_layout.addWidget(self.mode_combo)
        control_layout.addWidget(self.focused_widget)
        
        # Connect signals for preview
        self.start_spin.valueChanged.connect(self.update_preview)
        self.stop_spin.valueChanged.connect(self.update_preview)
        self.step_spin.valueChanged.connect(self.update_preview)
        self.mode_combo.currentIndexChanged.connect(self.update_preview)
        self.focus_center_spin.valueChanged.connect(self.update_preview)
        self.focus_width_spin.valueChanged.connect(self.update_preview)
        self.fine_step_spin.valueChanged.connect(self.update_preview)
        self.coarse_step_spin.valueChanged.connect(self.update_preview)
        
        # Add label for preview stats
        self.preview_label = QtWidgets.QLabel("Points: 0")
        control_layout.addWidget(self.preview_label)
        
        # Coverage Check
        self.check_coverage_btn = QtWidgets.QPushButton("Check Range")
        self.check_coverage_btn.clicked.connect(self.check_coverage)
        control_layout.addWidget(self.check_coverage_btn)
        
        self.coverage_label = QtWidgets.QLabel("Range: N/A")
        control_layout.addWidget(self.coverage_label)

        layout.addLayout(control_layout)

        # --- Background Removal Row ---
        bg_group = QtWidgets.QGroupBox("Background Removal")
        bg_layout = QtWidgets.QHBoxLayout()
        bg_group.setLayout(bg_layout)

        self.bg_measure_btn = QtWidgets.QPushButton("Measure Background")
        self.bg_measure_btn.setToolTip("Run one spatial scan at the current laser position and store it as background")
        self.bg_measure_btn.clicked.connect(self._on_measure_background_clicked)
        bg_layout.addWidget(self.bg_measure_btn)

        self.bg_clear_btn = QtWidgets.QPushButton("Clear Background")
        self.bg_clear_btn.setToolTip("Discard the stored background image")
        self.bg_clear_btn.clicked.connect(self._on_clear_background_clicked)
        self.bg_clear_btn.setEnabled(False)
        bg_layout.addWidget(self.bg_clear_btn)

        self.bg_enable_chk = QtWidgets.QCheckBox("Subtract Background")
        self.bg_enable_chk.setToolTip("When checked, background is subtracted from each scan before analysis")
        self.bg_enable_chk.setEnabled(False)
        self.bg_enable_chk.toggled.connect(self._on_bg_enable_toggled)
        bg_layout.addWidget(self.bg_enable_chk)

        self.bg_status_label = QtWidgets.QLabel("No background measured")
        bg_layout.addWidget(self.bg_status_label)
        bg_layout.addStretch()

        layout.addWidget(bg_group)
        
        # 2. Main Content Tabs
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)
        
        # --- Tab 1: Distribution Histogram ---
        self.tab_dist = QtWidgets.QWidget()
        dist_layout = QtWidgets.QVBoxLayout()
        self.tab_dist.setLayout(dist_layout)
        
        self.fig_hist = Figure()
        self.canvas_hist = FigureCanvas(self.fig_hist)
        self.ax_hist = self.fig_hist.add_subplot(111)
        self.ax_hist.set_xlabel("Voltage (V)")
        self.ax_hist.set_ylabel("Number of Spots")
        self.ax_hist.set_title("ZPL Distribution (Click bar to see scan)")
        
        self.canvas_hist.mpl_connect('pick_event', self.on_hist_pick)
        dist_layout.addWidget(self.canvas_hist)
        
        # Fit Controls
        fit_layout = QtWidgets.QHBoxLayout()
        self.fit_btn = QtWidgets.QPushButton("Fit Gaussian")
        self.fit_btn.clicked.connect(self.run_fit)
        fit_layout.addWidget(self.fit_btn)
        
        self.fit_results_label = QtWidgets.QLabel("Fit Results: N/A")
        fit_layout.addWidget(self.fit_results_label)
        
        dist_layout.addLayout(fit_layout)
        
        self.tabs.addTab(self.tab_dist, "Distribution")
        
        # --- Tab 2: Scan Analysis ---
        self.tab_analysis = QtWidgets.QWidget()
        analysis_layout = QtWidgets.QHBoxLayout()
        self.tab_analysis.setLayout(analysis_layout)
        
        # Left: Scan Image
        image_container = QtWidgets.QVBoxLayout()
        self.fig_scan = Figure()
        self.canvas_scan = FigureCanvas(self.fig_scan)
        self.ax_scan = self.fig_scan.add_subplot(111)
        self.ax_scan.set_title("Scan Image")
        self.scan_im_obj = None
        self.scan_scatter_obj = None
        image_container.addWidget(self.canvas_scan)
        analysis_layout.addLayout(image_container, stretch=2)
        
        # Right: Spot List & Controls
        side_panel = QtWidgets.QVBoxLayout()
        
        self.info_label = QtWidgets.QLabel("Select a voltage from Distribution tab or dropdown")
        side_panel.addWidget(self.info_label)
        
        # Scan Selector
        side_panel.addWidget(QtWidgets.QLabel("Select Scan:"))
        self.scan_selector = QtWidgets.QComboBox()
        self.scan_selector.currentIndexChanged.connect(self.on_scan_selected_from_combo)
        side_panel.addWidget(self.scan_selector)
        
        # Channel Selector
        side_panel.addWidget(QtWidgets.QLabel("Select Channel:"))
        self.channel_combo = QtWidgets.QComboBox()
        self.channel_combo.currentIndexChanged.connect(self.update_scan_view)
        side_panel.addWidget(self.channel_combo)

        # Visualization Controls
        viz_layout = QtWidgets.QHBoxLayout()
        
        self.vmin_spin = QtWidgets.QDoubleSpinBox()
        self.vmin_spin.setPrefix("Vmin: ")
        self.vmin_spin.setRange(0, 1e9)
        self.vmin_spin.setValue(0)
        self.vmin_spin.valueChanged.connect(self.update_scan_view)
        
        self.vmax_spin = QtWidgets.QDoubleSpinBox()
        self.vmax_spin.setPrefix("Vmax: ")
        self.vmax_spin.setRange(0, 1e9)
        self.vmax_spin.setValue(100000) # Default
        self.vmax_spin.valueChanged.connect(self.update_scan_view)
        
        viz_layout.addWidget(self.vmin_spin)
        viz_layout.addWidget(self.vmax_spin)
        side_panel.addLayout(viz_layout)
        
        self.spots_list_widget = QtWidgets.QListWidget()
        side_panel.addWidget(QtWidgets.QLabel("Detected Spots:"))
        side_panel.addWidget(self.spots_list_widget)
        
        self.remove_spot_btn = QtWidgets.QPushButton("Remove Selected Spot")
        self.remove_spot_btn.clicked.connect(self.remove_selected_spot)
        side_panel.addWidget(self.remove_spot_btn)
        
        self.save_all_btn = QtWidgets.QPushButton("Save All Results")
        self.save_all_btn.clicked.connect(self.save_all_results)
        side_panel.addWidget(self.save_all_btn)
        
        # --- Analysis Controls --- (unchanged)
        side_panel.addSpacing(10)
        side_panel.addWidget(QtWidgets.QLabel("<b>Detection Settings:</b>"))
        
        # Method Selection
        side_panel.addWidget(QtWidgets.QLabel("Method:"))
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(['Simple', 'Gaussian', 'DoG'])
        side_panel.addWidget(self.method_combo)
        
        # Threshold
        side_panel.addWidget(QtWidgets.QLabel("Threshold:"))
        self.threshold_spin = QtWidgets.QDoubleSpinBox()
        self.threshold_spin.setRange(0, 1e9)
        self.threshold_spin.setValue(5000) # Default
        side_panel.addWidget(self.threshold_spin)
        
        # Re-Analyze Button
        self.reanalyze_btn = QtWidgets.QPushButton("Re-Analyze Current")
        self.reanalyze_btn.clicked.connect(self.run_reanalysis)
        side_panel.addWidget(self.reanalyze_btn)
        
        self.reanalyze_all_btn = QtWidgets.QPushButton("Re-Analyze All")
        self.reanalyze_all_btn.clicked.connect(self.run_reanalyze_all)
        side_panel.addWidget(self.reanalyze_all_btn)
        
        
        # Add a note about manual adding
        side_panel.addWidget(QtWidgets.QLabel("Tip:\nLeft Click: Add Spot\nRight Click: Remove Spot"))
        
        analysis_layout.addLayout(side_panel, stretch=1)
        
        self.tabs.addTab(self.tab_analysis, "Scan Analysis")
        
        # Connect canvas click
        self.canvas_scan.mpl_connect('button_press_event', self.on_scan_click)
        
        # 3. Status Bar
        self.status_label = QtWidgets.QLabel("Status: Idle")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QtWidgets.QProgressBar()
        layout.addWidget(self.progress_bar)

    def update_mode_visibility(self, index):
        is_focused = (index == 1) # 1 is Focused
        self.focused_widget.setVisible(is_focused)
        self.step_spin.setVisible(not is_focused)
        self.update_preview()
        
    def update_preview(self):
        """Calculate and display voltage schedule preview."""
        # Only preview if not running? 
        # Actually good to always show what *would* be run.
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        step = self.step_spin.value()
        
        mode = self.mode_combo.currentText()
        center = self.focus_center_spin.value()
        width = self.focus_width_spin.value()
        fine = self.fine_step_spin.value()
        coarse = self.coarse_step_spin.value()
        
        try:
            voltages = self._logic().get_voltage_schedule(start, stop, step, mode, center, width, fine, coarse)
            
            # Update Label
            self.preview_label.setText(f"Points: {len(voltages)}")
            
            # Update Plot
            # If we are not running, we can show lines.
            
            # Remove previous preview lines
            if hasattr(self, 'preview_lines') and self.preview_lines:
                try:
                    self.preview_lines.remove()
                except Exception: 
                    # Artist might have been cleared by ax.clear()
                    pass
                self.preview_lines = None
                
            # Plot new lines as rug plot (small lines at bottom)
            # transform=self.ax_hist.get_xaxis_transform() makes y=0..1 normalized axis coords
            # We want short lines at the bottom, e.g. 0 to 0.05
            
            self.preview_lines = self.ax_hist.vlines(voltages, 0, 0.05, transform=self.ax_hist.get_xaxis_transform(), 
                                                     colors='gray', alpha=0.5, linestyles='solid')
            
            # Auto-scale X if needed (only if no other data)
            # Check if we have bars or scatter points
            has_data = len(self.ax_hist.containers) > 0 or len(self.ax_hist.collections) > 1 # >1 because vlines is a collection
            
            if not has_data:
                 self.ax_hist.set_xlim(start, stop)
                 
            self.canvas_hist.draw()
            
        except Exception as e:
            # Logic might not be ready or error
            # print(f"Preview Error: {e}")
            pass
            
    def start_measurement(self):
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        step = self.step_spin.value()
        method = self.method_combo.currentText()
        threshold = self.threshold_spin.value()
        
        # Focused Params
        mode = self.mode_combo.currentText()
        center = self.focus_center_spin.value()
        width = self.focus_width_spin.value()
        fine = self.fine_step_spin.value()
        coarse = self.coarse_step_spin.value()
        
        # Laser
        laser = self.laser_combo.currentText()
        
        # Reset plots
        self.ax_hist.clear()
        self.ax_hist.set_xlabel("Voltage (V)")
        self.ax_hist.set_ylabel("Number of Spots")
        self.canvas_hist.draw()
        
        self.spots_list_widget.clear()
        self.scan_selector.clear() # Clear selector
        self.ax_scan.clear()
        self.canvas_scan.draw()
        self._current_view_voltage = None
        
        # Pass detection parameters directly to start_measurement
        self._logic().start_measurement(start, stop, step, method, threshold,
                                      mode, center, width, fine, coarse, laser)
        self.start_btn.setEnabled(False)
        self.check_coverage_btn.setEnabled(False)
        self.bg_measure_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setChecked(False)
        self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Status: Running...")
        self.progress_bar.setValue(0)

    def run_reanalysis(self):
        if self._current_view_voltage is not None:
             method = self.method_combo.currentText()
             threshold = self.threshold_spin.value()
             
             self.status_label.setText(f"Status: Re-analyzing {self._current_view_voltage:.2f} V with {method}...")
             QtWidgets.QApplication.processEvents()
             
             channel = self.channel_combo.currentText() if self.channel_combo.count() > 0 else None
             success = self._logic().reanalyze_scan(self._current_view_voltage, method, threshold, channel)
             
             if success:
                 self.status_label.setText(f"Status: Re-analysis complete.")
             else:
                 self.status_label.setText(f"Status: Re-analysis failed.")

    def run_reanalyze_all(self):
        method = self.method_combo.currentText()
        threshold = self.threshold_spin.value()
        
        self.status_label.setText(f"Status: Re-analyzing ALL scans with {method}...")
        QtWidgets.QApplication.processEvents()
        
        # We can optionally select a channel if user wants to force a specific channel for all?
        # Current UI logic for 'Current' uses the dropdown. 
        # For 'All', we should probably respect the same dropdown if it makes sense, 
        # or use 'default' logic if channel varies per scan.
        # But 'channel_combo' content depends on the *currently selected scan*.
        # So using it for *all* scans might be dangerous if they have different channels.
        # However, usually a measurement run has consistent channels.
        # Let's pass None to let logic decide (default or fallback), 
        # or pass the current combo text if valid.
        # Logic `reanalyze_all` signature takes `channel`.
        # Safe bet: pass None (Logic uses original channel or finds match).
        
        count = self._logic().reanalyze_all(method, threshold, channel=None)
        
        self.status_label.setText(f"Status: Re-analysis of {count} scans complete.")
        QtWidgets.QMessageBox.information(self._mw, "Re-analysis Complete", f"Re-analyzed {count} scans.")


    def stop_measurement(self):
        self._logic().stop_measurement()
        self.status_label.setText("Status: Stopping...")

    def toggle_pause(self):
        if self.pause_btn.isChecked():
            self._logic().pause_measurement()
            self.pause_btn.setText("Resume")
            self.status_label.setText("Status: Paused")
        else:
            self._logic().resume_measurement()
            self.pause_btn.setText("Pause")
            self.status_label.setText("Status: Running...")

    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.check_coverage_btn.setEnabled(True)
        self.bg_measure_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Finished")
        self.progress_bar.setValue(100)

    def run_fit(self):
        res = self._logic().fit_gaussian()
        
        if res:
            # Update label
            txt = f"FWHM: {res['fwhm']:.4f} | Amp: {res['amplitude']:.2f} | Int (Fit): {res['integral_fit']:.2f} | Int (Raw): {res['integral_raw']:.0f}"
            self.fit_results_label.setText(txt)
            
            # Plot fit
            # Determine which axis to plot on
            # We need to know if we are plotting vs Frequency or Voltage
            # The logic returns 'is_frequency' flag
            
            # Re-draw histogram to ensure clean state and correct axis
            # But wait, we can just overlay if axis matches.
            # Best is to call update_plot again or just plot on top.
            
            # Let's plot on self.ax_hist which should be the primary axis (Frequency)
            self.ax_hist.plot(res['x_fit'], res['y_fit'], 'r-', label='Gaussian Fit', linewidth=2)
            self.ax_hist.legend()
            self.canvas_hist.draw()
        else:
            self.fit_results_label.setText("Fit Failed")

    def update_plot(self, data):
        self._last_hist_data = data  # Store for picking
        self.ax_hist.clear()

        volts = np.array(data['voltage'])
        counts = np.array(data['counts'])
        freqs = np.array(data.get('frequency', []))

        if len(volts) == 0:
            self.ax_hist.set_xlabel("Voltage (V)")
            self.ax_hist.set_ylabel("Number of Spots")
            self.ax_hist.set_title("ZPL Distribution")
            self.canvas_hist.draw()
            return

        has_freq = (len(freqs) == len(volts)
                    and len(volts) > 0
                    and not np.all(np.isnan(freqs)))

        if has_freq:
            # ---- Primary axis: Frequency (GHz) ----
            x_data = freqs
            self.ax_hist.set_xlabel("Frequency (GHz relative to 484.135 THz)")

            # Compute bar width robustly
            valid_freqs = freqs[np.isfinite(freqs)]
            if len(valid_freqs) > 1:
                diffs = np.diff(np.sort(valid_freqs))
                nonzero = diffs[diffs > 0]
                width = float(np.min(nonzero)) * 0.8 if len(nonzero) > 0 else 1.0
            else:
                width = 1.0  # single-point fallback

            self.ax_hist.bar(x_data, counts, width=width, picker=5, label='Counts')
            self.ax_hist.scatter(x_data, [0] * len(x_data),
                                 color='red', marker='|', s=50, picker=5)

            # Secondary axis: Voltage (top)
            valid_mask = np.isfinite(freqs) & np.isfinite(volts)
            valid_freqs_fit = freqs[valid_mask]
            valid_volts_fit = volts[valid_mask]

            if len(valid_freqs_fit) > 1:
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', np.RankWarning)
                        coef = np.polyfit(valid_freqs_fit, valid_volts_fit, 1)
                    m, c = coef[0], coef[1]
                    def f2v(f, _m=m, _c=c): return _m * f + _c
                    def v2f(v, _m=m, _c=c): return (v - _c) / _m if _m != 0 else v
                    secax = self.ax_hist.secondary_xaxis('top', functions=(f2v, v2f))
                    secax.set_xlabel('Voltage (V)')
                except Exception as e:
                    print(f"Warning: Failed to create secondary voltage axis: {e}")

        else:
            # ---- Fallback: Voltage axis ----
            self.ax_hist.set_xlabel("Voltage (V)")
            step = self.step_spin.value()
            if len(volts) > 1:
                diffs = np.diff(np.sort(volts))
                nonzero = diffs[diffs > 0]
                bar_w = float(np.min(nonzero)) * 0.8 if len(nonzero) > 0 else step * 0.8
            else:
                bar_w = step * 0.8 if step > 0 else 1.0
            self.ax_hist.bar(volts, counts, width=bar_w, picker=5)
            self.ax_hist.scatter(volts, [0] * len(volts),
                                 color='red', marker='|', s=50, picker=5)

        self.ax_hist.set_ylabel("Number of Spots")
        self.ax_hist.set_title("ZPL Distribution")
        self.canvas_hist.draw()
        
        # Refresh current view if it is still active
        if hasattr(self, '_current_view_voltage') and self._current_view_voltage is not None:
            # Re-fetch data for current voltage to reflect updates (like spot add/remove)
             res = self._logic().get_scan_result(self._current_view_voltage)
             if res:
                 self.display_scan(self._current_view_voltage, res['image'], res['spots'])

    def on_scan_completed(self, voltage, image, spots):
        self.status_label.setText(f"Status: Scan at {voltage:.2f} V completed. Found {len(spots)} spots.")
        
        # Add to combo box. Block signals to avoid triggering on_scan_selected_from_combo
        self.scan_selector.blockSignals(True)
        self.scan_selector.addItem(f"{voltage:.4f} V", voltage)
        self.scan_selector.blockSignals(False)
        
        # Auto-update if it's the first one or user hasn't selected another one yet
        if not hasattr(self, '_current_view_voltage') or self._current_view_voltage is None:
             self._current_view_voltage = voltage
             self.display_scan(voltage, image, spots)
             
             # Sync selector
             self.scan_selector.blockSignals(True)
             idx = self.scan_selector.findData(voltage)
             if idx >= 0:
                 self.scan_selector.setCurrentIndex(idx)
             self.scan_selector.blockSignals(False)

    def on_scan_selected_from_combo(self, index):
        if index < 0: return
        voltage = self.scan_selector.itemData(index)
        if voltage is not None:
             res = self._logic().get_scan_result(voltage)
             if res:
                 # Populate channel combo
                 self.channel_combo.blockSignals(True)
                 
                 # Remember current selection
                 current_channel = self.channel_combo.currentText()
                 
                 self.channel_combo.clear()
                 if 'all_channels' in res and res['all_channels']:
                      for ch in res['all_channels'].keys():
                           self.channel_combo.addItem(ch)
                      
                      # Try to preserve current selection
                      idx = self.channel_combo.findText(current_channel)
                      if idx < 0:
                          # Default to analysis channel
                          idx = self.channel_combo.findText(res.get('channel', ''))
                      
                      if idx >= 0:
                           self.channel_combo.setCurrentIndex(idx)
                 else:
                      # Only one channel available
                      self.channel_combo.addItem(res.get('channel', 'Unknown'))
                 self.channel_combo.blockSignals(False)
                 
                 self._current_view_voltage = voltage
                 self.update_scan_view()

    def on_hist_pick(self, event):
        # Handle picking for BarContainer elements (Rectangle)
        if hasattr(event, 'artist') and self.ax_hist.containers:
            container = self.ax_hist.containers[0]
            if event.artist in container:
                ind = container.index(event.artist)
            elif hasattr(event, 'ind') and len(event.ind) > 0:
                 # Fallback for some backends if needed
                 ind = event.ind[0]
            else:
                return

            if hasattr(self, '_last_hist_data') and ind < len(self._last_hist_data['voltage']):
                voltage = self._last_hist_data['voltage'][ind]
                
                # Update combo box selection which will trigger display update
                idx = self.scan_selector.findData(voltage)
                if idx >= 0:
                    self.scan_selector.setCurrentIndex(idx)
                    # This triggers on_scan_selected_from_combo -> display_scan
                else:
                    # Fallback if for some reason check fails (float diff?)
                    # Try finding closest
                    count = self.scan_selector.count()
                    best_idx = -1
                    min_dist = 1e-6
                    for i in range(count):
                        v_item = self.scan_selector.itemData(i)
                        if v_item is not None:
                            dist = abs(v_item - voltage)
                            if dist < min_dist:
                                min_dist = dist
                                best_idx = i
                    
                    if best_idx >= 0:
                        self.scan_selector.setCurrentIndex(best_idx)

                    self.tabs.setCurrentIndex(1) # Switch to Analysis tab

    def display_scan(self, voltage, image, spots):
        self._current_view_voltage = voltage
        self.info_label.setText(f"Analysis for {voltage:.4f} V")
        self.ax_scan.clear()
        
        # Get visualization limits
        vmin = self.vmin_spin.value()
        vmax = self.vmax_spin.value()
        
        # If both 0, maybe auto-scale?
        if vmin == 0 and vmax == 0:
            vmin = None
            vmax = None
        
        channel = self.channel_combo.currentText()
        self.ax_scan.set_title(f"Scan at {voltage:.4f} V ({channel})")
        
        # Plot Image
        self.scan_im_obj = self.ax_scan.imshow(image, origin='lower', cmap='viridis', vmin=vmin, vmax=vmax, interpolation='nearest')
        
        # Plot Spots
        if spots:
            xs = [s['x'] for s in spots]
            ys = [s['y'] for s in spots]
            self.scan_scatter_obj = self.ax_scan.scatter(xs, ys, c='r', marker='x', s=50)
            
        self.canvas_scan.draw()

    def update_scan_view(self):
        """Update the scan display based on channel selection or vmin/vmax."""
        if not hasattr(self, '_current_view_voltage') or self._current_view_voltage is None:
            return
            
        voltage = self._current_view_voltage
        res = self._logic().get_scan_result(voltage)
        if not res: return
        
        # Determine image source
        channel = self.channel_combo.currentText()
        image = res['image'] # Default
        
        if 'all_channels' in res and channel in res['all_channels']:
            image = res['all_channels'][channel]
        elif channel == res.get('count_channel'):
             # Fallback if channel name matches but not in all_channels for some reason
             image = res['image']
             
        # Use existing spots (spots are detected on the *analysis* channel, which might differ from view channel)
        # But usually we view the channel we analyzed.
        # If user switches view channel, should we show spots? Yes, to see correlation.
        
        self.display_scan(voltage, image, res['spots'])

    def on_scan_click(self, event):
        if event.inaxes != self.ax_scan:
            return
        if self._current_view_voltage is None:
            return
            
        ix, iy = event.xdata, event.ydata
        if ix is None or iy is None:
            return
            
        if event.button == 1: # Left Click: Add
            if self._logic().add_spot(self._current_view_voltage, ix, iy):
                self.update_scan_view()
            
        elif event.button == 3: # Right Click: Remove
            # Find nearest spot in list?
            # Or ask Logic to remove nearest. Logic handles data.
            # But we have indices here.
            # Let's find index locally.
            res = self._logic().get_scan_result(self._current_view_voltage)
            if res and res['spots']:
                closest_dist = float('inf')
                closest_idx = -1
                for i, s in enumerate(res['spots']):
                    dist = (s['x'] - ix)**2 + (s['y'] - iy)**2
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_idx = i
                
                if closest_idx != -1 and closest_dist < 25: # Tolerance radius sq (5 pixels)
                    if self._logic().remove_spot(self._current_view_voltage, closest_idx):
                        self.update_scan_view()

    def remove_selected_spot(self):
        row = self.spots_list_widget.currentRow()
        if row >= 0 and self._current_view_voltage is not None:
             self._logic().remove_spot(self._current_view_voltage, row)

    # -------------------------------------------------------------------------
    # Background removal slots
    # -------------------------------------------------------------------------

    def _on_measure_background_clicked(self):
        self.bg_measure_btn.setEnabled(False)
        self.bg_status_label.setText("Measuring background...")
        self._logic().measure_background()

    def _on_clear_background_clicked(self):
        self._logic().clear_background()

    def _on_bg_enable_toggled(self, checked):
        self._logic().background_enabled = checked

    def on_background_captured(self, image):
        """Called when sigBackgroundCaptured is emitted from logic."""
        self.bg_measure_btn.setEnabled(True)
        if image is not None:
            self.bg_status_label.setText("Background acquired ✓")
            self.bg_clear_btn.setEnabled(True)
            self.bg_enable_chk.setEnabled(True)
        else:
            self.bg_status_label.setText("Background measurement FAILED")
            self.bg_clear_btn.setEnabled(False)
            self.bg_enable_chk.setEnabled(False)
            self.bg_enable_chk.setChecked(False)

    def save_all_results(self):
        # Open dialog
        # Use explicit kwargs to avoid qtpy issue
        folder = QtWidgets.QFileDialog.getExistingDirectory(parent=self._mw, caption="Select Directory to Save Analysis")
        if folder:
            self._logic().save_all_results(folder)
            QtWidgets.QMessageBox.information(self._mw, "Saved", f"Results saved to {folder}")

    def check_coverage(self):
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        step = self.step_spin.value()
        mode = self.mode_combo.currentText()
        center = self.focus_center_spin.value()
        width = self.focus_width_spin.value()
        fine = self.fine_step_spin.value()
        coarse = self.coarse_step_spin.value()
        laser = self.laser_combo.currentText()
        
        self.check_coverage_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.status_label.setText(f"Status: Checking coverage ({mode})...")
        
        self._logic().check_wavelength_coverage_args(start, stop, step, mode, center, width, fine, coarse, laser)
        
    def on_coverage_check_finished(self, result):
        self.check_coverage_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.status_label.setText("Status: Idle")
        
        if result:
            voltages, freqs = result
            dialog = WavelengthCheckDialog(voltages, freqs, parent=self._mw)
            dialog.exec_()
            
            # Also update label with range?
            valid_freqs = [f for f in freqs if not np.isnan(f)]
            if valid_freqs:
                 self.coverage_label.setText(f"Range: {valid_freqs[0]:.2f} - {valid_freqs[-1]:.2f} GHz")
            else:
                 self.coverage_label.setText("Range: No Data")
        else:
             self.coverage_label.setText("Range: Failed")
