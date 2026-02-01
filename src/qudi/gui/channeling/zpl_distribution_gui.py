# -*- coding: utf-8 -*-
"""
GUI module for ZPL distribution measurement.
"""

from qtpy import QtWidgets, QtCore
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

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
        
        self.info_label = QtWidgets.QLabel("Select a voltage from Distribution tab")
        side_panel.addWidget(self.info_label)
        
        self.spots_list_widget = QtWidgets.QListWidget()
        side_panel.addWidget(QtWidgets.QLabel("Detected Spots:"))
        side_panel.addWidget(self.spots_list_widget)
        
        self.remove_spot_btn = QtWidgets.QPushButton("Remove Selected Spot")
        self.remove_spot_btn.clicked.connect(self.remove_selected_spot)
        side_panel.addWidget(self.remove_spot_btn)
        
        self.save_all_btn = QtWidgets.QPushButton("Save All Results")
        self.save_all_btn.clicked.connect(self.save_all_results)
        side_panel.addWidget(self.save_all_btn)
        
        # --- Analysis Controls ---
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

    def start_measurement(self):
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        step = self.step_spin.value()
        
        # Update logic config from GUI before starting
        # Ideally logic uses config options, but we can set defaults or just rely on GUI defaults
        # To be cleaner, let's update logic's threshold config if possible or just rely on loop reading it (which it does)
        # But we need to set the Logic's config value from our spinbox
        self._logic()._spot_threshold = self.threshold_spin.value()
        self._logic()._detection_method = self.method_combo.currentText()
        
        # Reset plots
        self.ax_hist.clear()
        self.ax_hist.set_xlabel("Voltage (V)")
        self.ax_hist.set_ylabel("Number of Spots")
        self.canvas_hist.draw()
        
        self.spots_list_widget.clear()
        self.ax_scan.clear()
        self.canvas_scan.draw()
        self._current_view_voltage = None
        
        self._logic().start_measurement(start, stop, step)
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
             
             success = self._logic().reanalyze_scan(self._current_view_voltage, method, threshold)
             
             if success:
                 self.status_label.setText(f"Status: Re-analysis complete.")
             else:
                 self.status_label.setText(f"Status: Re-analysis failed.")
                 
    # ... (stop, pause methods same as before, skipping for brevity in this replace block if possible, but replace needs continuity) ...
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

    def update_plot(self, data):
        self._last_hist_data = data # Store for picking
        self.ax_hist.clear()
        self.ax_hist.set_xlabel("Voltage (V)")
        self.ax_hist.set_ylabel("Number of Spots")
        self.ax_hist.set_title("ZPL Distribution (Click bar to see scan)")
        
        if len(data['voltage']) > 0:
            # picker=5 sets 5 points tolerance
            bars = self.ax_hist.bar(data['voltage'], data['counts'], width=self.step_spin.value()*0.8, picker=5)
            
        self.canvas_hist.draw()
        
        # Refresh current view if it is still active
        if hasattr(self, '_current_view_voltage') and self._current_view_voltage is not None:
            # Re-fetch data for current voltage to reflect updates (like spot add/remove)
             res = self._logic().get_scan_result(self._current_view_voltage)
             if res:
                 self.display_scan(self._current_view_voltage, res['image'], res['spots'])


    def on_scan_completed(self, voltage, image, spots):
        self.status_label.setText(f"Status: Scan at {voltage:.2f} V completed. Found {len(spots)} spots.")
        # Auto-update if it's the first one or user hasn't selected another one
        if not hasattr(self, '_current_view_voltage') or self._current_view_voltage is None:
             self.display_scan(voltage, image, spots)

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

            # Debug logging
            print(f"DEBUG: Pick Event! Ind: {ind}")
            if hasattr(self, '_last_hist_data') and ind < len(self._last_hist_data['voltage']):
                voltage = self._last_hist_data['voltage'][ind]
                print(f"DEBUG: Selected Voltage: {voltage}")
                
                # Fetch detailed result
                res = self._logic().get_scan_result(voltage)
                if not res:
                     # Try finding closest key handles float precision issues
                     min_dist = 1e-6
                     best_v = None
                     if hasattr(self._logic(), '_scan_results') and self._logic()._scan_results:
                         for k in self._logic()._scan_results.keys():
                             dist = abs(k - voltage)
                             if dist < min_dist:
                                 min_dist = dist
                                 best_v = k
                     if best_v is not None:
                         res = self._logic().get_scan_result(best_v)
                         voltage = best_v
                
                if res:
                    self.display_scan(voltage, res['image'], res['spots'])
                    self.tabs.setCurrentIndex(1) # Switch to Analysis tab

    def display_scan(self, voltage, image, spots):
        self._current_view_voltage = voltage
        self.info_label.setText(f"Analysis for {voltage:.4f} V")
        self.ax_scan.clear()
        self.ax_scan.set_title(f"Scan at {voltage:.4f} V")
        
        # Plot Image
        self.scan_im_obj = self.ax_scan.imshow(image, origin='lower', cmap='viridis')
        # Plot Spots
        if spots:
            xs = [s['x'] for s in spots]
            ys = [s['y'] for s in spots]
            self.scan_scatter_obj = self.ax_scan.scatter(xs, ys, c='r', marker='x', s=50) 
        
        self.canvas_scan.draw()
        
        # Update List
        self.spots_list_widget.clear()
        for i, s in enumerate(spots):
            self.spots_list_widget.addItem(f"Spot {i}: ({s['x']}, {s['y']}) Conf: {s['confidence']:.2f}")

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
