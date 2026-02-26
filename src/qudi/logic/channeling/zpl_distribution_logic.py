# -*- coding: utf-8 -*-
"""
Logic module for ZPL distribution measurement.
Performs a frequency scan of the laser and at each step performs a spatial scan (2D)
to count the number of fluorescent spots (defects).
"""

import copy
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
    _laser_qinu = Connector(name='laser_qinu', interface='SimpleLaserInterface')
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
    _zero_frequency = ConfigOption(name='zero_frequency', default=484.135) # THz
    _detection_method = ConfigOption(name='detection_method', default='Simple') # 'Simple', 'Gaussian', 'DoG'
    _active_laser = ConfigOption(name='active_laser', default='Main') # 'Main', 'QInu'
    
    # Focused Mode Config
    _step_mode = ConfigOption(name='step_mode', default='Linear') # 'Linear', 'Focused'
    _focus_center = ConfigOption(name='focus_center', default=50.0)
    _focus_width = ConfigOption(name='focus_width', default=20.0)
    _fine_step = ConfigOption(name='fine_step', default=1.0)
    _coarse_step = ConfigOption(name='coarse_step', default=5.0)
    
    sigUpdatePlot = QtCore.Signal(object)
    sigMeasurementFinished = QtCore.Signal()
    sigScanCompleted = QtCore.Signal(float, object, list) # voltage, image, spots
    sigWavelengthCheckFinished = QtCore.Signal(object) # (start_freq, stop_freq) or None if failed
    sigBackgroundCaptured = QtCore.Signal(object)  # background image ndarray or None

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._stop_requested = False
        self._is_paused = False
        self._is_running = False
        self._background_image = None
        self._background_enabled = False
        self._background_running = False

    def on_activate(self):
        self._is_running = False
        self._background_image = None
        self._background_enabled = False
        self._background_running = False

    def on_deactivate(self):
        self.stop_measurement()

    @QtCore.Slot(float, float, float, str, float)
    def start_measurement(self, start, stop, step, method='Simple', threshold=5000.0, 
                          mode='Linear', center=50.0, width=20.0, fine=1.0, coarse=5.0,
                          laser='Main'):
        if self._is_running:
            self.log.warning("Measurement already running.")
            return

        self._start_voltage = start
        self._stop_voltage = stop
        self._step_voltage = step
        self._current_method = method
        self._current_threshold = threshold
        
        # Store Focused params and Laser
        self._current_mode = mode
        self._current_center = center
        self._current_width = width
        self._current_fine = fine
        self._current_coarse = coarse
        self._active_laser = laser
        
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

    @QtCore.Slot()
    def pause_measurement(self):
        self._is_paused = True

    @QtCore.Slot()
    def resume_measurement(self):
        self._is_paused = False

    @QtCore.Slot()
    def stop_measurement(self):
        self._stop_requested = True
        self._is_paused = False # Resume to allow loop to exit if paused

    def get_voltage_schedule(self, start, stop, step, mode='Linear', center=50.0, width=20.0, fine=1.0, coarse=5.0):
        """Generate the list of voltages to scan based on parameters."""
        if mode == 'Focused':
            # Focused Mode
            fine_start = max(start, center - width/2)
            fine_end = min(stop, center + width/2)
            
            voltages = []
            # Left Coarse
            curr = start
            while curr < fine_start:
                voltages.append(curr)
                curr += coarse
                
            # Fine
            # Align to fine_start
            curr = fine_start
            while curr <= fine_end:
                voltages.append(curr)
                curr += fine
                
            # Right Coarse
            # Start from last point + coarse
            if voltages:
                curr = voltages[-1] + coarse
            else:
                curr = fine_end + coarse 
                
            while curr <= stop:
                voltages.append(curr)
                curr += coarse
                
            voltages = sorted(list(set(voltages))) # Unique and sort
            voltages = [v for v in voltages if start <= v <= stop]
            return voltages
            
        else:
             # Linear
             if step <= 0: step = 1.0
             voltages = np.arange(start, stop + step/100.0, step)
             return list(voltages)

    @QtCore.Slot()
    def check_wavelength_coverage(self):
        """Check the wavelength coverage for the current start/stop settings."""
        if self._is_running:
            self.log.warning("Cannot check coverage while measurement is running.")
            return

        self._is_running = True
        
        # Get current settings from status vars which are updated by GUI via properties or direct set? 
        # Actually in this logic class, start/stop are StatusVars but not automatically synced unless GUI sets them.
        # But wait, start_measurement takes arguments. check_wavelength coverage should probably too, or rely on stored.
        # The GUI spinboxes are not directly connected to these StatusVars.
        # So I should accept arguments.
        # Wait, the slot signature in GUI will likely just call this. 
        # Let's update the signature to accept start/stop/laser.
        pass

    @QtCore.Slot(float, float, float, str, float, float, float, float, str)
    def check_wavelength_coverage_args(self, start, stop, step, mode, center, width, fine, coarse, laser):
        if self._is_running:
            self.log.warning("Cannot check coverage while measurement is running.")
            return

        self._is_running = True
        self._check_start = start
        self._check_stop = stop
        self._check_step = step
        self._check_mode = mode
        self._check_center = center
        self._check_width = width
        self._check_fine = fine
        self._check_coarse = coarse
        self._active_laser = laser
        
        import threading
        self._check_thread = threading.Thread(target=self._run_wavelength_check)
        self._check_thread.start()

    def _run_wavelength_check(self):
        try:
            laser = self.get_active_laser()
            if not laser.is_connected:
                self.log.error("Laser not connected.")
                self.sigWavelengthCheckFinished.emit(None)
                return
            
            # Generate voltages
            voltages = self.get_voltage_schedule(
                self._check_start, 
                self._check_stop, 
                self._check_step,
                self._check_mode,
                self._check_center,
                self._check_width,
                self._check_fine,
                self._check_coarse
            )
            
            if not voltages:
                self.log.warning("No voltages generated for check.")
                self.sigWavelengthCheckFinished.emit(None)
                return

            measured_cw = []
            frequencies_ghz = []
            measured_volts = []
            
            total = len(voltages)
            self.log.info(f"Checking {total} points...")
            
            for i, v in enumerate(voltages):
                if not self._is_running: # Check if stopped/interrupted (though we don't present stop button for check yet)
                     break
                     
                self.log.info(f"Check point {i+1}/{total}: {v:.4f} V")
                laser().set_pc_voltage(v)
                time.sleep(0.5) # Shorter sleep for check? Or stick to 2.0s? User asked to scan. 
                # 2.0s per point for 100 points is 200s (3 mins). Might be slow but safe.
                # Let's use 1.0s as compromise or stick to wait. 
                # The measurement loop uses 2.0s. It's safer to use at least 1.0s.
                
                # Read wavemeter
                f_ghz = np.nan
                
                if self._wavemeter.is_connected:
                    try:
                        wm = self._wavemeter()
                        val = 0.0
                        
                        # Retry loop
                        max_retries = 10
                        for attempt in range(max_retries):
                            # User explicitly asked for get_current_wavelength()
                            if hasattr(wm, 'get_current_wavelength'):
                                raw = wm.get_current_wavelength()
                                # print(f"DEBUG: get_current_wavelength() -> {raw}")
                                val = float(raw)
                                
                            # If 0, maybe default channel is empty, try explicit channels
                            if val == 0 and hasattr(wm, 'get_wavelength'):
                                # print("DEBUG: val is 0, trying channels 1-8...")
                                for ch in range(1, 9): # Channels 1-8
                                    try:
                                        temp = float(wm.get_wavelength(ch))
                                        if temp > 0:
                                            val = temp
                                            # self.log.info(f"  -> Found signal on channel {ch}: {val}")
                                            break
                                    except Exception as e:
                                        # print(f"DEBUG: Error reading channel {ch}: {e}")
                                        pass
                            
                            if val > 0:
                                break
                                
                            # Wait before retry if no signal
                            if attempt < max_retries - 1:
                                time.sleep(0.1)
                                
                        if val > 0:
                            # Heuristic for units
                            # ZPL is ~470 THz (637 nm)
                            # If val > 550, assume nm
                            if val > 550:
                                 # Convert nm to THz
                                 freq_thz = 299792.458 / val
                            else:
                                 freq_thz = val
                                 
                            f_ghz = (freq_thz - self._zero_frequency) * 1000.0
                            self.log.info(f"  -> Val: {val}, Rel Freq: {f_ghz:.4f} GHz")
                        else:
                            self.log.warning(f"  -> Zero reading from wavemeter at {v:.4f}V after {max_retries} attempts")

                    except Exception as e:
                         self.log.error(f"Error reading wavemeter: {e}")
                
                measured_volts.append(v)
                frequencies_ghz.append(f_ghz)
            
            self.sigWavelengthCheckFinished.emit((measured_volts, frequencies_ghz))
            
        except Exception as e:
            self.log.error(f"Error in wavelength check: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            self.sigWavelengthCheckFinished.emit(None)
        finally:
            self._is_running = False
            # Does not emit sigMeasurementFinished because it's not a measurement run? 
            # Correct, but we need to ensure GUI knows we are done if we set buttons.
            # The sigWavelengthCheckFinished should be enough.

    def get_active_laser(self):
        """Return the currently active laser connector based on config."""
        if self._active_laser == 'QInu':
            return self._laser_qinu
        else:
            return self._laser

    def _run_measurement_loop(self):
        try:
             # Generate Voltage Schedule
            if hasattr(self, '_current_mode'):
                voltages = self.get_voltage_schedule(
                    self._start_voltage, 
                    self._stop_voltage, 
                    self._step_voltage,
                    self._current_mode,
                    self._current_center,
                    self._current_width,
                    self._current_fine,
                    self._current_coarse
                )
                if self._current_mode == 'Focused':
                    self.log.info(f"Focused Schedule: {len(voltages)} points around {self._current_center} V")
            else:
                 # Fallback for linear if mode not set (legacy call?)
                 voltages = self.get_voltage_schedule(self._start_voltage, self._stop_voltage, self._step_voltage)
                 
            if len(voltages) == 0:
                 self.log.warning("No voltages to scan.")
                 return

            # Check Laser Connection
            laser = self.get_active_laser()
            if not laser.is_connected:
                self.log.error(f"Selected laser ({self._active_laser}) is not connected.")
                return

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
                self.log.info(f"Setting laser ({self._active_laser}) voltage to {v:.4f} V")
                laser().set_pc_voltage(v)
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
                        
                        # Apply background subtraction if enabled
                        display_image = image_data
                        if self._background_enabled and self._background_image is not None:
                            if self._background_image.shape == image_data.shape:
                                display_image = np.clip(image_data.astype(float) - self._background_image.astype(float), 0, None)
                            else:
                                self.log.warning("Background image shape mismatch; skipping subtraction.")

                        # Use configured method and threshold from start_measurement
                        method = getattr(self, '_current_method', self._detection_method)
                        threshold = getattr(self, '_current_threshold', self._spot_threshold)
                        spots_list = self._detect_spots(display_image, method=method, threshold=threshold)
                        spot_count = len(spots_list)
                        
                        self.log.info(f"Found {spot_count} spots at {v:.4f} V on {channel_name} ({method})")
                        
                        # Store Data
                        self._histogram_data['voltage'].append(v)
                        self._histogram_data['counts'].append(spot_count)
                        self._histogram_data['frequency'].append(frequency_ghz)

                        self._scan_results[v] = {
                            'image': image_data,
                            'display_image': display_image,
                            'spots': spots_list,
                            'timestamp': timestamp,
                            'scan_name': scan_name.replace(':', '-').replace('/', '-').replace('\\', '-'),
                            'channel': channel_name, # The channel used for initial detection
                            'count_channel': self._count_channel, # Detailed info
                            'frequency': frequency_ghz,
                            'all_channels': scan_data.data if hasattr(scan_data, 'data') else {}
                        }

                        # Emit updates — deep-copy to avoid cross-thread mutation
                        self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
                        self.sigScanCompleted.emit(v, display_image, spots_list)
                        
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

    def reanalyze_scan(self, voltage, method, threshold, channel=None):
        """Re-analyze a specific scan with new parameters."""
        if voltage in self._scan_results:
            res = self._scan_results[voltage]

            # Select channel
            image = res['image']
            current_channel = res['channel']

            if channel:
                if 'all_channels' in res and channel in res['all_channels']:
                    image = res['all_channels'][channel]
                    current_channel = channel
                elif channel != current_channel:
                    self.log.warning(f"Channel {channel} not found for {voltage} V")

            # Apply background subtraction if enabled
            display_image = image
            if self._background_enabled and self._background_image is not None:
                if self._background_image.shape == image.shape:
                    display_image = np.clip(
                        image.astype(float) - self._background_image.astype(float), 0, None
                    )
                else:
                    self.log.warning("Background shape mismatch in reanalyze_scan; skipping.")

            spots = self._detect_spots(display_image, method, threshold)
            
            # Update results
            res['spots'] = spots
            res['image'] = image
            res['channel'] = current_channel
            spot_count = len(spots)
            
            # Update histogram source
            try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = spot_count
            except ValueError:
                pass
                
            self.log.info(f"Re-analyzed {voltage:.2f} V with {method} (Thresh: {threshold}): {spot_count} spots")
            
            # Emit updates — deep-copy to avoid cross-thread mutation
            self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
            self.sigScanCompleted.emit(voltage, image, spots) # Re-emit to update GUI view
            return True
        return False

    def reanalyze_all(self, method, threshold, channel=None):
        """Re-analyze ALL scans with new parameters."""
        count = 0
        for voltage in self._scan_results.keys():
             # We use the internal reanalyze_scan logic but defer updates? 
             # Or just do it in loop. Efficiency might be okay for typical number of points (100-200).
             # Let's optimize by not emitting sigScanCompleted for every point, only sigUpdatePlot at end?
             # But reanalyze_scan emits signals.
             # Let's copy logic to avoid spamming signals if needed, or just let it happen.
             # Actually, reanalyze_scan emits sigScanCompleted which might be heavy if GUI redraws image every time.
             # But GUI only redraws if voltage matches current view.
             # sigUpdatePlot redraws histogram. That might be heavy 100 times.
             
             res = self._scan_results[voltage]
             
             # Select channel
             image = res['image']
             current_channel = res['channel']
             
             if channel:
                if 'all_channels' in res and channel in res['all_channels']:
                    image = res['all_channels'][channel]
                    current_channel = channel
             
             spots = self._detect_spots(image, method, threshold)
             
             res['spots'] = spots
             res['image'] = image
             res['channel'] = current_channel
             spot_count = len(spots)
             
             # Update histogram source
             try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = spot_count
             except ValueError:
                pass
             
             count += 1
             
        self.log.info(f"Re-analyzed {count} scans.")
        self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
        
        # If there is a current view, we should update it too.
        # But we don't know what GUI is viewing. 
        # The GUI can request update or we can just emit empty sigScanCompleted? 
        # Better: The user will likely want to see the new distribution.
        return count

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
                
            self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
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
                    
                self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
                return True
        return False

    # -------------------------------------------------------------------------
    # Background measurement
    # -------------------------------------------------------------------------

    @property
    def background_enabled(self):
        return self._background_enabled

    @background_enabled.setter
    def background_enabled(self, value):
        self._background_enabled = bool(value)

    def get_background_image(self):
        """Return the stored background image (ndarray or None)."""
        return self._background_image

    def clear_background(self):
        """Remove the stored background."""
        self._background_image = None
        self._background_enabled = False
        self.sigBackgroundCaptured.emit(None)

    def measure_background(self):
        """Run one spatial scan and store it as the background image.
        Non-blocking: launches a thread and emits sigBackgroundCaptured when done.
        """
        if self._is_running or self._background_running:
            self.log.warning("Cannot measure background while a measurement is running.")
            return
        import threading
        self._background_running = True
        t = threading.Thread(target=self._run_background_scan, daemon=True)
        t.start()

    def _run_background_scan(self):
        try:
            scan_axes = tuple(self._scan_channels)
            self.log.info("Starting background scan...")
            self._scan_logic().toggle_scan(True, scan_axes)
            time.sleep(1.0)
            while self._scan_logic().module_state() != 'idle':
                time.sleep(0.1)

            scan_data = self._data_logic().get_current_scan_data(scan_axes=scan_axes)
            if scan_data and hasattr(scan_data, 'data') and scan_data.data:
                target_channel = self._count_channel
                if target_channel in scan_data.data:
                    bg_image = scan_data.data[target_channel]
                else:
                    keys = list(scan_data.data.keys())
                    if not keys:
                        self.log.error("Background scan: empty data dict.")
                        self.sigBackgroundCaptured.emit(None)
                        return
                    bg_image = scan_data.data[keys[0]]
                    self.log.warning(f"Background: channel '{target_channel}' not found, using '{keys[0]}'.")

                self._background_image = bg_image.copy() if hasattr(bg_image, 'copy') else np.array(bg_image)
                self.log.info("Background image acquired.")
                self.sigBackgroundCaptured.emit(self._background_image)
            else:
                self.log.error("Background scan returned no data.")
                self.sigBackgroundCaptured.emit(None)
        except Exception as e:
            import traceback
            self.log.error(f"Background scan failed: {e}\n{traceback.format_exc()}")
            self.sigBackgroundCaptured.emit(None)
        finally:
            self._background_running = False

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
                
                # Sanitize filename
                v_str = f"{v:.4f}".replace('.', ',') # European style or just safe? 
                # Actually '.' is fine. Colon is not.
                # But just to be safe, maybe user locale issue? 
                # Let's just stick to standard. 
                # If v is float, it should be fine.
                # However, if v is something else or has weird chars?
                # Let's ensure it is float
                try:
                    v_float = float(v)
                    fname = f"scan_{v_float:.4f}V.svg"
                except:
                    # Fallback
                    clean_v = str(v).replace(':', '_').replace('/', '_').replace('\\', '_')
                    fname = f"scan_{clean_v}V.svg"
                
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
                    "scan_channels": self._scan_channels,
                    "count_channel": self._count_channel,
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

    def fit_gaussian(self):
        """
        Fit a Gaussian to the current histogram data.
        Returns:
            dict: { 'amplitude': float, 'mean': float, 'sigma': float, 'offset': float, 'fwhm': float, 'integral_fit': float, 'integral_raw': float, 'x': array, 'y_fit': array }
            or None if fit fails.
        """
        import numpy as np
        from scipy.optimize import curve_fit
        
        # Get data
        volts = np.array(self._histogram_data['voltage'])
        counts = np.array(self._histogram_data['counts'])
        freqs = np.array(self._histogram_data['frequency'])
        
        # Decide X axis: Use Frequency if available and not all NaNs, else Voltage
        if len(freqs) == len(volts) and not np.all(np.isnan(freqs)):
            x = freqs
            # Filter NaNs
            valid = ~np.isnan(x)
            x = x[valid]
            y = counts[valid]
            is_frequency = True
        else:
            x = volts
            y = counts
            is_frequency = False
            
        if len(x) < 4:
            return None
            
        # Define Gaussian function
        def gaussian(x, a, x0, sigma, c):
            return a * np.exp(-(x - x0)**2 / (2 * sigma**2)) + c
            
        # Initial guesses
        a_guess = np.max(y) - np.min(y)
        x0_guess = x[np.argmax(y)]
        sigma_guess = (np.max(x) - np.min(x)) / 6.0
        c_guess = np.min(y)
        
        try:
            popt, pcov = curve_fit(gaussian, x, y, p0=[a_guess, x0_guess, sigma_guess, c_guess])
            a, x0, sigma, c = popt
            
            # Calculate derived stats
            fwhm = 2.35482 * abs(sigma)
            
            # Integral of the Gaussian part (A * sqrt(2*pi) * sigma)
            # This represents the total number of "defects" if A is counts density? 
            # Actually y is "Number of Spots". So sum(y) is total spots.
            # The integral of the fit curve over dx? 
            # If the histogram is counts per bin, then the sum is the integral.
            # The Gaussian integral is area under curve. 
            # If x is Frequency (GHz), area is Counts * GHz. Not directly "Number of spots".
            # The "Integrated Number of Defects" is likely just sum(y) - background?
            # Or area of the Gaussian peak.
            # Let's return the area of the Gaussian component.
            integral_fit = a * np.sqrt(2 * np.pi) * abs(sigma)
            
            # Raw integral (sum of counts)
            integral_raw = np.sum(y)
            
            # Generate fit curve for plotting
            x_fit = np.linspace(np.min(x), np.max(x), 200)
            y_fit = gaussian(x_fit, *popt)
            
            return {
                'amplitude': a,
                'mean': x0,
                'sigma': abs(sigma),
                'offset': c,
                'fwhm': fwhm,
                'integral_fit': integral_fit, 
                'integral_raw': integral_raw,
                'x_fit': x_fit,
                'y_fit': y_fit,
                'is_frequency': is_frequency,
                'params': popt
            }
            
        except Exception as e:
            self.log.warning(f"Gaussian fit failed: {e}")
            return None
