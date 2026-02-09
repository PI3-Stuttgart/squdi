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
        self.show()
        
    def on_deactivate(self):
        self._logic().sigUpdatePlot.disconnect(self.update_plot)
        self._logic().sigMeasurementFinished.disconnect(self.on_finished)
        self._logic().sigScanCompleted.disconnect(self.on_scan_completed)
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

        layout.addLayout(control_layout)
        
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
                                      mode, center, width, fine, coarse)
        self.start_btn.setEnabled(False)
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
        self._last_hist_data = data # Store for picking
        self.ax_hist.clear()
        
        volts = np.array(data['voltage'])
        counts = np.array(data['counts'])
        freqs = np.array(data.get('frequency', []))
        
        # Determine Primary Axis
        # User wants "bottom x axis being frequency ... from 484.135 THz"
        # and "top x axis being voltage".
        
        has_freq = len(freqs) == len(volts) and not np.all(np.isnan(freqs)) and len(volts) > 0
        
        if has_freq:
            # Primary Axis: Frequency (GHz)
            x_data = freqs
            self.ax_hist.set_xlabel("Frequency (GHz relative to 484.135 THz)")
            
            # Plot Bars
            # Handle variable width? 
            # If freq is not uniform, bar width is tricky. Use minimal spacing or just points?
            # Creating bars with width requires scalar width or array.
            # Avg step in freq:
            if len(freqs) > 1:
                width = np.mean(np.diff(freqs)) * 0.8
            else:
                width = 0.1 # Default
                
            bars = self.ax_hist.bar(x_data, counts, width=width, picker=5, label='Counts')
            
            # Plot scatter for scan points (0-spots)
            self.ax_hist.scatter(x_data, [0]*len(x_data), color='red', marker='|', s=50, picker=5)

            # Secondary Axis: Voltage (Top)
            # Create a second axis that shares the y-axis
            # We can't just set data, we need to link the axes.
            # If the relationship is linear V -> F, we can use secondary_xaxis with functions.
            # But here we have discrete points.
            # Simplest approach for visual: Use twinY and plot invisible data or set limits?
            # Or assume linear fit between V and F for the axis mapping.
            
            # Let's try secondary_xaxis if available (matplotlib > 3.1) or twiny.
            # Given we have (V, F) pairs.
            # Let's fit V vs F line.
            # Ensure we have valid (non-NaN, non-Inf) data for fitting
            valid_mask = np.isfinite(freqs) & np.isfinite(volts)
            valid_freqs = freqs[valid_mask]
            valid_volts = volts[valid_mask]
            
            if len(valid_freqs) > 1:
                try:
                    # Linear fit: V = m * F + c
                    # slope m = dV/dF
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', np.RankWarning)
                        coef = np.polyfit(valid_freqs, valid_volts, 1)
                    
                    m = coef[0]
                    c = coef[1]
                    
                    def f2v(f): return m * f + c
                    def v2f(v): return (v - c) / m if m != 0 else v
                    
                    secax = self.ax_hist.secondary_xaxis('top', functions=(f2v, v2f))
                    secax.set_xlabel('Voltage (V)')
                except Exception as e:
                    print(f"Warning: Failed to create secondary voltage axis: {e}")
            
        else:
            # Fallback to Voltage if no Frequency
            self.ax_hist.set_xlabel("Voltage (V)")
            bars = self.ax_hist.bar(volts, counts, width=self.step_spin.value()*0.8, picker=5)
            self.ax_hist.scatter(volts, [0]*len(volts), color='red', marker='|', s=50, picker=5)

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
        
        # Auto-update if it's the first one or user hasn't selected another one
        if not hasattr(self, '_current_view_voltage') or self._current_view_voltage is None:
             self.display_scan(voltage, image, spots)
             # Update combo selection without triggering again (conceptually)
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
                 self.channel_combo.clear()
                 if 'all_channels' in res and res['all_channels']:
                      for ch in res['all_channels'].keys():
                           self.channel_combo.addItem(ch)
                      # Set to current analysis channel
                      idx = self.channel_combo.findText(res.get('channel', ''))
                      if idx >= 0:
                           self.channel_combo.setCurrentIndex(idx)
                 else:
                      # Only one channel available
                      self.channel_combo.addItem(res.get('channel', 'Unknown'))
                 self.channel_combo.blockSignals(False)
                 
                 self.display_scan(voltage, res['image'], res['spots'])

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
            self._logic().add_spot(self._current_view_voltage, ix, iy)
            
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
                    self._logic().remove_spot(self._current_view_voltage, closest_idx)

    def remove_selected_spot(self):
        row = self.spots_list_widget.currentRow()
        if row >= 0 and self._current_view_voltage is not None:
             self._logic().remove_spot(self._current_view_voltage, row)
             
    def save_all_results(self):
        # Open dialog
        folder = QtWidgets.QFileDialog.getExistingDirectory(self._mw, "Select Directory to Save Analysis")
        if folder:
            self._logic().save_all_results(folder)
            QtWidgets.QMessageBox.information(self._mw, "Saved", f"Results saved to {folder}")
