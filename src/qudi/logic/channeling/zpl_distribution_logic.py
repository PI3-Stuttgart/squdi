# -*- coding: utf-8 -*-
"""
Logic module for ZPL distribution measurement.
Performs a frequency scan of the laser and at each step performs a spatial scan (2D)
to count the number of fluorescent spots (defects).
"""

import numpy as np
import time
from scipy.ndimage import maximum_filter
from qtpy import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.core.configoption import ConfigOption

class ZPLDistributionLogic(LogicBase):
    """
    Logic class for ZPL Distribution measurement.
    """

    # Connectors
    _laser = Connector(name='laser', interface='SimpleLaserInterface')
    _scan_logic = Connector(name='scan_logic', interface='ScanningProbeLogic')
    _data_logic = Connector(name='data_logic', interface='ScanningDataLogic')
    _wavemeter = Connector(name='wavemeter', interface='WavemeterInterface')
    
    # Status Variables
    _start_voltage = StatusVar(name='start_voltage', default=0.0) 
    _stop_voltage = StatusVar(name='stop_voltage', default=100.0)
    _step_voltage = StatusVar(name='step_voltage', default=5.0)
    _current_voltage = StatusVar(name='current_voltage', default=0.0)
    _progress = StatusVar(name='progress', default=0.0)
    _histogram_data = StatusVar(name='histogram_data', default={'voltage': [], 'counts': [], 'frequency': []}) # Added freq
    _is_running = StatusVar(name='is_running', default=False)
    
    # New: Store detailed results
    _scan_results = StatusVar(name='scan_results', default={}) # Key: voltage, Value: {'image': array, 'spots': list, 'frequency': float}
    
    # Config Options
    _spot_threshold = ConfigOption(name='spot_threshold', default=5000) # Counts/s threshold
    _scan_channels = ConfigOption(name='scan_channels', default=['x', 'y'])
    _count_channel = ConfigOption(name='count_channel', default='APD1')
    _zero_frequency = ConfigOption(name='zero_frequency', default=484.130) # THz
    _detection_method = ConfigOption(name='detection_method', default='Simple') # 'Simple', 'Gaussian', 'DoG'
    
    sigUpdatePlot = QtCore.Signal(object)
    sigMeasurementFinished = QtCore.Signal()
    sigScanCompleted = QtCore.Signal(float, object, list) # voltage, image, spots

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._stop_requested = False
        self._is_paused = False

    def on_activate(self):
        pass

    def on_deactivate(self):
        self.stop_measurement()

    @QtCore.Slot(float, float, float)
    def start_measurement(self, start, stop, step):
        if self._is_running:
            self.log.warning("Measurement already running.")
            return

        self._start_voltage = start
        self._stop_voltage = stop
        self._step_voltage = step
        self._is_running = True
        self._stop_requested = False
        self._is_paused = False
        self._histogram_data = {'voltage': [], 'counts': [], 'frequency': []}
        self._scan_results = {}
        
        try:
            import threading
            self._thread = threading.Thread(target=self._run_measurement_loop)
            self._thread.start()
        except Exception as e:
            self.log.error(f"Error starting measurement thread: {e}")
            self._is_running = False
# ... (stop, pause same) ...

    def _run_measurement_loop(self):
        try:
            voltages = np.arange(self._start_voltage, self._stop_voltage + self._step_voltage, self._step_voltage)
            total_steps = len(voltages)
            
            for i, v in enumerate(voltages):
                # Handle Pause
                while self._is_paused:
                    if self._stop_requested:
                        break
                    time.sleep(0.5)
                
                if self._stop_requested:
                    break
                
                self._current_voltage = v
                self._progress = (i / total_steps) * 100
                
                # 1. Set Laser Voltage
                self.log.info(f"Setting laser voltage to {v:.4f} V")
                self._laser().set_pc_voltage(v)
                time.sleep(2.0) # Allow settling (increased to 2s based on notebook)
                
                # 1b. Measure Wavemeter (if connected)
                frequency_ghz = np.nan
                if self._wavemeter.is_connected:
                    try:
                        # Attempt to read
                        # Note: Interface might vary, assuming get_frequency or get_current_wavelength
                        # Notebook used: ws_wavemeter.get_current_wavelength()
                        # standard interface usually has get_wavelength() or similar.
                        # Using 'WavemeterInterface' from qudi usually has 'get_wavelength' returning meters or similar, or THz?
                        # Let's try to call what was in the notebook if it matches a known connector
                        # Notebook: ws_wavemeter.get_current_wavelength()
                        # Let's assume the connector provides this or similar.
                        # Safest is to try-except attribute access if standard interface is unknown
                        wm = self._wavemeter()
                        val = np.nan
                        if hasattr(wm, 'get_current_wavelength'):
                             val = wm.get_current_wavelength()
                        elif hasattr(wm, 'get_wavelength'):
                             val = wm.get_wavelength()
                        
                        # Notebook logic: (val - w0) * 1e3
                        # implying val is in THz if w0 is THz and result is GHz?
                        # Or val is nm and w0 is nm? 
                        # w0 = 484.130. 484 nm is blue. 484 THz is red (619nm). ZPL is 637nm (470THz).
                        # Likely Frequency in THz.
                        if not np.isnan(val):
                            frequency_ghz = (val - self._zero_frequency) * 1000.0
                            self.log.info(f"Measured Frequency: {frequency_ghz:.4f} GHz (Raw: {val})")
                    except Exception as e:
                        self.log.warning(f"Could not read wavemeter: {e}")
                
                # 2. Run Spatial Scan
                self.log.info("Starting spatial scan...")
                scan_axes = tuple(self._scan_channels)
                self._scan_logic().toggle_scan(True, scan_axes)
                
                # Wait for scan to finish
                time.sleep(1.0) # Wait for start
                while self._scan_logic().module_state() != 'idle':
                    if self._stop_requested:
                        self._scan_logic().stop_scan()
                        return
                    time.sleep(0.1)
                    
                # 3. Save Scan
                timestamp = time.strftime("%H%M%S")
                scan_name = f"ZPL_Dist_Scan_{v:.4f}V_{timestamp}"
                self._data_logic().save_scan_by_axis(scan_axes=scan_axes, tag=scan_name)
                
                # 4. Analyze Data
                scan_data = self._data_logic().get_current_scan_data(scan_axes=scan_axes)
                
                if scan_data and hasattr(scan_data, 'data') and scan_data.data:
                    # Robustly get the channel
                    try:
                        target_channel = self._count_channel
                        if target_channel in scan_data.data:
                            image_data = scan_data.data[target_channel]
                            channel_name = target_channel
                        else:
                             # Fallback to first available
                             keys = list(scan_data.data.keys())
                             if not keys:
                                 self.log.warning(f"Scan data dictionary is empty at {v} V")
                                 continue
                             channel_name = keys[0]
                             self.log.warning(f"Channel '{target_channel}' not found. Using '{channel_name}' instead.")
                             image_data = scan_data.data[channel_name]
                        
                        # Use configured method and threshold
                        method = self._detection_method
                        threshold = self._spot_threshold
                        spots_list = self._detect_spots(image_data, method=method, threshold=threshold)
                        spot_count = len(spots_list)
                        
                        self.log.info(f"Found {spot_count} spots at {v:.4f} V on {channel_name} ({method})")
                        
                        # Store Data
                        self._histogram_data['voltage'].append(v)
                        self._histogram_data['counts'].append(spot_count)
                        self._histogram_data['frequency'].append(frequency_ghz)
                        
                        self._scan_results[v] = {
                            'image': image_data,
                            'spots': spots_list,
                            'timestamp': timestamp,
                            'scan_name': scan_name,
                            'channel': channel_name,
                            'frequency': frequency_ghz
                        }
                        
                        # Emit updates
                        self.sigUpdatePlot.emit(self._histogram_data)
                        self.sigScanCompleted.emit(v, image_data, spots_list)
                        
                    except Exception as e:
                         import traceback
                         self.log.error(f"Error processing scan data: {e}\n{traceback.format_exc()}")
                else:
                    self.log.warning("No valid scan data retrieved.")
    
            self._progress = 100.0
            
        except Exception as e:
            import traceback
            self.log.error(f"Error in measurement loop: {e}\n{traceback.format_exc()}")
        finally:
            self._is_running = False
            self.sigMeasurementFinished.emit()

    def _detect_spots(self, image, method='Simple', threshold=None):
        """
        Detect spots using specified method.
        
        Args:
            image (normalized ndarray): The scan image.
            method (str): 'Simple', 'Gaussian', or 'DoG'.
            threshold (float): Threshold value. If None, uses self._spot_threshold().
        
        Returns:
            list of dicts: Detected spots.
        """
        if threshold is None:
            threshold = self._spot_threshold
            
        import scipy.ndimage as ndimage
        
        spots = []
        
        if method == 'Simple':
            # Original simple thresholding
            mask = image > threshold
            if not np.any(mask):
                return []
            size = 5
            local_max = ndimage.maximum_filter(image, size=size) == image
            detected_spots_mask = local_max & mask
            y_indices, x_indices = np.where(detected_spots_mask)
            
            for y, x in zip(y_indices, x_indices):
                val = float(image[y, x])
                confidence = (val - threshold) / threshold if threshold > 0 else 0
                spots.append({
                    'x': int(x), 'y': int(y), 'val': val, 'confidence': confidence
                })
                
        elif method == 'Gaussian':
            # Gaussian smoothing before thresholding
            sigma = 1.0
            smoothed = ndimage.gaussian_filter(image, sigma=sigma)
            mask = smoothed > threshold
            if not np.any(mask):
                return []
            local_max = ndimage.maximum_filter(smoothed, size=5) == smoothed
            detected_spots_mask = local_max & mask
            y_indices, x_indices = np.where(detected_spots_mask)
            
            for y, x in zip(y_indices, x_indices):
                val = float(image[y, x]) # Use original intensity
                confidence = (float(smoothed[y, x]) - threshold) / threshold if threshold > 0 else 0
                spots.append({
                    'x': int(x), 'y': int(y), 'val': val, 'confidence': confidence
                })
                
        elif method == 'DoG':
            # Difference of Gaussians
            sigma1 = 1.0
            sigma2 = 2.0
            g1 = ndimage.gaussian_filter(image, sigma=sigma1)
            g2 = ndimage.gaussian_filter(image, sigma=sigma2)
            dog = g1 - g2
            
            # For DoG, threshold is usually lower than raw counts, likely differential
            # But user might supply raw count threshold. 
            # Let's interpret threshold as minimum intensity in the DoG image? 
            # Or keep threshold as strict intensity cut on *original* image + peak in DoG.
            # Strategy: Peak in DoG AND Value > Threshold
            
            # 1. Find peaks in DoG
            dog_max = ndimage.maximum_filter(dog, size=5) == dog
            # 2. Check intensity in original image
            intensity_mask = image > threshold
            
            detected_spots_mask = dog_max & intensity_mask & (dog > 0)
            
            y_indices, x_indices = np.where(detected_spots_mask)
             
            for y, x in zip(y_indices, x_indices):
                val = float(image[y, x])
                # Confidence could be DoG magnitude * intensity
                confidence = float(dog[y, x])
                spots.append({
                    'x': int(x), 'y': int(y), 'val': val, 'confidence': confidence
                })
                
        return spots

    def reanalyze_scan(self, voltage, method, threshold):
        """Re-analyze a specific scan with new parameters."""
        if voltage in self._scan_results:
            res = self._scan_results[voltage]
            image = res['image']
            
            spots = self._detect_spots(image, method, threshold)
            
            # Update results
            res['spots'] = spots
            spot_count = len(spots)
            
            # Update histogram source
            try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = spot_count
            except ValueError:
                pass
                
            self.log.info(f"Re-analyzed {voltage:.2f} V with {method} (Thresh: {threshold}): {spot_count} spots")
            
            # Emit updates
            self.sigUpdatePlot.emit(self._histogram_data)
            self.sigScanCompleted.emit(voltage, image, spots) # Re-emit to update GUI view
            return True
        return False

    def get_scan_result(self, voltage):
        return self._scan_results.get(voltage)

    def add_spot(self, voltage, x, y):
        """Manually add a spot."""
        if voltage in self._scan_results:
            result = self._scan_results[voltage]
            
            # Check if spot already exists close by?
            # For now just add
            image = result['image']
            val = float(image[int(y), int(x)]) if (0 <= int(y) < image.shape[0] and 0 <= int(x) < image.shape[1]) else 0.0
            
            new_spot = {
                'x': int(x),
                'y': int(y),
                'val': val,
                'confidence': 1.0 # Manual
            }
            result['spots'].append(new_spot)
            
            # Recalculate count
            count = len(result['spots'])
            
            # Update histogram data source
            try:
                # Find index of voltage
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = count
            except ValueError:
                pass
                
            self.sigUpdatePlot.emit(self._histogram_data)
            return True
        return False

    def remove_spot(self, voltage, spot_index):
        """Remove a spot by index."""
        if voltage in self._scan_results:
            result = self._scan_results[voltage]
            if 0 <= spot_index < len(result['spots']):
                result['spots'].pop(spot_index)
                
                # Recalculate count
                count = len(result['spots'])
                
                # Update histogram data source
                try:
                    idx = self._histogram_data['voltage'].index(voltage)
                    self._histogram_data['counts'][idx] = count
                except ValueError:
                    pass
                    
                self.sigUpdatePlot.emit(self._histogram_data)
                return True
        return False
        
    def save_all_results(self, save_dir):
        """Save results to folder."""
        import os
        import csv
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        # 1. Save Histogram (SVG + CSV)
        try:
            # SVG
            fig = Figure()
            FigureCanvasAgg(fig) # Attach backend
            ax = fig.add_subplot(111)
            
            ax.set_xlabel("Voltage (V)")
            ax.set_ylabel("Number of Spots")
            ax.set_title("ZPL Distribution")
            if len(self._histogram_data['voltage']) > 0:
                ax.bar(self._histogram_data['voltage'], self._histogram_data['counts'], width=self._step_voltage * 0.8)
            
            fig.savefig(os.path.join(save_dir, "distribution_histogram.svg"))
            # No need to close explicitly with Figure object, it's just an object
            
            # CSV
            with open(os.path.join(save_dir, "distribution_histogram.csv"), 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Voltage", "Frequency (GHz)", "Counts"])
                
                # Robust zip
                volts = self._histogram_data['voltage']
                counts = self._histogram_data['counts']
                freqs = self._histogram_data.get('frequency', [float('nan')]*len(volts))
                
                # Ensure freqs has same length
                if len(freqs) < len(volts):
                    freqs.extend([float('nan')] * (len(volts) - len(freqs)))
                
                for v, f_val, c in zip(volts, freqs, counts):
                    writer.writerow([v, f_val, c])
                    
        except Exception as e:
            import traceback
            self.log.error(f"Failed to save histogram: {e}\n{traceback.format_exc()}")
            
        # 2. Save Individual Scans (SVG + Global CSV)
        all_spots = []
        
        for v, res in self._scan_results.items():
            freq = res.get('frequency', float('nan'))
            
            # Collect spots for CSV
            for s in res['spots']:
                all_spots.append({
                    'Voltage': v,
                    'Frequency': freq,
                    'X': s['x'],
                    'Y': s['y'],
                    'Value': s['val'],
                    'Confidence': s['confidence']
                })
        
            # Save Figure
            try:
                fig = Figure()
                FigureCanvasAgg(fig)
                ax = fig.add_subplot(111)
                
                ax.set_title(f"Scan at {v:.4f} V ({freq:.2f} GHz)")
                ax.imshow(res['image'], origin='lower', cmap='viridis')
                
                spots = res['spots']
                if spots:
                    xs = [s['x'] for s in spots]
                    ys = [s['y'] for s in spots]
                    ax.scatter(xs, ys, c='r', marker='x', s=50)
                
                fname = f"scan_{v:.4f}V.svg"
                fig.savefig(os.path.join(save_dir, fname))
            except Exception as e:
                self.log.error(f"Failed to save scan at {v}: {e}")
                
        # Save All Spots CSV
        try:
            with open(os.path.join(save_dir, "all_spots.csv"), 'w', newline='') as f:
                fieldnames = ['Voltage', 'Frequency', 'X', 'Y', 'Value', 'Confidence']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_spots)
        except Exception as e:
            self.log.error(f"Failed to save spots CSV: {e}")
            
        # 4. Save JSON Database Export
        try:
            import json
            
            class NumpyEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, np.integer):
                        return int(obj)
                    elif isinstance(obj, np.floating):
                        return float(obj)
                    elif isinstance(obj, np.ndarray):
                        return obj.tolist()
                    return super(NumpyEncoder, self).default(obj)

            export_data = {
                "metadata": {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "scan_channels": self._scan_channels(),
                    "count_channel": self._count_channel(),
                    "detection_method": self._detection_method,
                    "spot_threshold": self._spot_threshold
                },
                "histogram": {
                    "voltage": self._histogram_data['voltage'],
                    "counts": self._histogram_data['counts'],
                    "frequency": self._histogram_data.get('frequency', [])
                },
                "scans": []
            }
            
            for v, res in self._scan_results.items():
                scan_entry = {
                    "voltage": v,
                    "frequency": res.get('frequency', None),
                    "timestamp": res.get('timestamp', ""),
                    "channel": res.get('channel', ""),
                    "spots": res['spots'], # List of dicts, already JSON/Encoder friendly
                    "image": res['image']  # Numpy array, handled by Encoder
                }
                export_data["scans"].append(scan_entry)
                
            with open(os.path.join(save_dir, "results.json"), 'w') as f:
                json.dump(export_data, f, cls=NumpyEncoder, indent=2)
                
        except Exception as e:
            import traceback
            self.log.error(f"Failed to save JSON export: {e}\n{traceback.format_exc()}")
