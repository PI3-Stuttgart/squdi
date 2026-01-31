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
    
    # Status Variables
    _start_voltage = StatusVar(name='start_voltage', default=0.0) 
    _stop_voltage = StatusVar(name='stop_voltage', default=100.0)
    _step_voltage = StatusVar(name='step_voltage', default=5.0)
    _current_voltage = StatusVar(name='current_voltage', default=0.0)
    _progress = StatusVar(name='progress', default=0.0)
    _histogram_data = StatusVar(name='histogram_data', default={'voltage': [], 'counts': []})
    _is_running = StatusVar(name='is_running', default=False)
    
    # New: Store detailed results
    _scan_results = StatusVar(name='scan_results', default={}) # Key: voltage, Value: {'image': array, 'spots': list}
    
    # Config Options
    _spot_threshold = ConfigOption(name='spot_threshold', default=5000) # Counts/s threshold
    _scan_channels = ConfigOption(name='scan_channels', default=['x', 'y'])
    _count_channel = ConfigOption(name='count_channel', default='APD1')
    
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
        self._histogram_data = {'voltage': [], 'counts': []}
        self._scan_results = {}
        
        try:
            import threading
            self._thread = threading.Thread(target=self._run_measurement_loop)
            self._thread.start()
        except Exception as e:
            self.log.error(f"Error starting measurement thread: {e}")
            self._is_running = False

    def stop_measurement(self):
        if self._is_running:
            self._stop_requested = True
            
    def pause_measurement(self):
        self._is_paused = True
        self.log.info("Measurement paused.")
        
    def resume_measurement(self):
        self._is_paused = False
        self.log.info("Measurement resumed.")

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
                time.sleep(1.0) # Allow settling
                
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
                        
                        spots_list = self._detect_spots(image_data)
                        spot_count = len(spots_list)
                        
                        self.log.info(f"Found {spot_count} spots at {v:.4f} V on {channel_name}")
                        
                        # Store Data
                        self._histogram_data['voltage'].append(v)
                        self._histogram_data['counts'].append(spot_count)
                        
                        self._scan_results[v] = {
                            'image': image_data,
                            'spots': spots_list,
                            'timestamp': timestamp,
                            'scan_name': scan_name,
                            'channel': channel_name
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

    def _detect_spots(self, image):
        """
        Detect spots and return list of dicts {'x': int, 'y': int, 'val': float, 'confidence': float}
        """
        threshold = self._spot_threshold
        mask = image > threshold
        
        if not np.any(mask):
            return []
            
        size = 5 # pixels
        local_max = maximum_filter(image, size=size) == image
        
        detected_spots_mask = local_max & mask
        
        # Get coordinates
        y_indices, x_indices = np.where(detected_spots_mask)
        
        spots = []
        for y, x in zip(y_indices, x_indices):
            val = float(image[y, x])
            # Simple confidence metric (e.g. signal to threshold ratio)
            confidence = (val - threshold) / threshold 
            spots.append({
                'x': int(x),
                'y': int(y),
                'val': val,
                'confidence': confidence
            })
            
        return spots
    
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
        import matplotlib.pyplot as plt
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        # 1. Save Histogram
        try:
            fig, ax = plt.subplots()
            ax.set_xlabel("Voltage (V)")
            ax.set_ylabel("Number of Spots")
            ax.set_title("ZPL Distribution")
            if len(self._histogram_data['voltage']) > 0:
                ax.bar(self._histogram_data['voltage'], self._histogram_data['counts'], width=self._step_voltage * 0.8)
            fig.savefig(os.path.join(save_dir, "distribution_histogram.svg"))
            plt.close(fig)
        except Exception as e:
            self.log.error(f"Failed to save histogram: {e}")
            
        # 2. Save Individual Scans
        for v, res in self._scan_results.items():
            try:
                fig, ax = plt.subplots()
                ax.set_title(f"Scan at {v:.4f} V")
                ax.imshow(res['image'], origin='lower', cmap='viridis')
                
                spots = res['spots']
                if spots:
                    xs = [s['x'] for s in spots]
                    ys = [s['y'] for s in spots]
                    ax.scatter(xs, ys, c='r', marker='x', s=50)
                
                fname = f"scan_{v:.4f}V.png" # SVG might be too heavy for images, using PNG for maps, or SVG if user insists
                # User asked for SVG? "save all. the obtained histogram as svg and the confocals with marked points"
                # Let's save confocals as SVG too if requested, or PNG. Usually PNG is better for images.
                # Let's do both or just PNG for image + SVG vector overlays? SVG handles images fine.
                fig.savefig(os.path.join(save_dir, fname.replace('.png', '.svg')))
                plt.close(fig)
            except Exception as e:
                self.log.error(f"Failed to save scan at {v}: {e}")
