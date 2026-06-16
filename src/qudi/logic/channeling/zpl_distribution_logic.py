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
    sigSavingFinished = QtCore.Signal(bool, str)  # success, message

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._stop_requested = False
        self._is_paused = False
        self._is_running = False
        self._background_image = None
        self._background_enabled = False
        self._background_running = False
        self._saving_running = False

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
        self._histogram_data = {'voltage': [], 'counts': [], 'frequency': [],
                                'error': [], 'mean_confidence': []}
        self._scan_results = {}
        
        try:
            import threading
            self._thread = threading.Thread(target=self._run_measurement_loop)
            self._thread.start()
        except Exception as e:
            self.log.error(f"Error starting measurement thread: {e}")
            self._is_running = False

    @QtCore.Slot(float, float, float, str, float)
    def append_measurement(self, start, stop, step, method='Simple', threshold=5000.0, 
                           mode='Linear', center=50.0, width=20.0, fine=1.0, coarse=5.0,
                           laser='Main'):
        """
        Starts a measurement on a specific range and appends results to existing ones 
        instead of clearing.
        """
        if self._is_running:
            self.log.warning("Measurement already running.")
            return

        # Use provided parameters for this segment
        self._current_method = method
        self._current_threshold = threshold
        self._active_laser = laser
        
        self._start_voltage = start
        self._stop_voltage = stop
        self._step_voltage = step
        self._current_mode = mode
        self._current_center = center
        self._current_width = width
        self._current_fine = fine
        self._current_coarse = coarse

        # Generate the specific schedule for this append run
        voltages = self.get_voltage_schedule(start, stop, step, mode, center, width, fine, coarse)

        self._is_running = True
        self._stop_requested = False
        self._is_paused = False
        
        # NOTE: We do NOT clear self._histogram_data or self._scan_results here!
        
        try:
            import threading
            self._thread = threading.Thread(target=self._run_measurement_loop, kwargs={'voltages': voltages})
            self._thread.start()
        except Exception as e:
            self.log.error(f"Error starting append measurement thread: {e}")
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

    _MAX_SCHEDULE_POINTS = 10000  # Safety cap to prevent MemoryError on bad inputs

    def get_voltage_schedule(self, start, stop, step, mode='Linear', center=50.0, width=20.0, fine=1.0, coarse=5.0):
        """Generate the list of voltages to scan based on parameters."""
        if mode == 'Focused':
            # Guard: fine and coarse must be positive
            if fine <= 0:
                fine = 1.0
            if coarse <= 0:
                coarse = 5.0

            fine_start = max(start, center - width/2)
            fine_end = min(stop, center + width/2)

            # Quick upper-bound estimate to catch runaway cases early
            fine_range = max(0.0, fine_end - fine_start)
            coarse_range = max(0.0, stop - start) - fine_range
            est_points = int(fine_range / fine) + int(coarse_range / coarse) + 10
            if est_points > self._MAX_SCHEDULE_POINTS:
                raise ValueError(
                    f"Focused schedule would generate ~{est_points} points (max {self._MAX_SCHEDULE_POINTS}). "
                    "Increase step sizes or reduce scan range."
                )

            voltages = []
            # Left Coarse
            curr = start
            while curr < fine_start:
                voltages.append(curr)
                curr += coarse
                if len(voltages) > self._MAX_SCHEDULE_POINTS:
                    raise ValueError("Schedule exceeded maximum point limit.")

            # Fine region
            curr = fine_start
            while curr <= fine_end:
                voltages.append(curr)
                curr += fine
                if len(voltages) > self._MAX_SCHEDULE_POINTS:
                    raise ValueError("Schedule exceeded maximum point limit.")

            # Right Coarse
            curr = (voltages[-1] + coarse) if voltages else (fine_end + coarse)
            while curr <= stop:
                voltages.append(curr)
                curr += coarse
                if len(voltages) > self._MAX_SCHEDULE_POINTS:
                    raise ValueError("Schedule exceeded maximum point limit.")

            voltages = sorted(list(set(voltages)))
            voltages = [v for v in voltages if start <= v <= stop]
            return voltages

        else:
            # Linear
            if step <= 0:
                step = 1.0
            est_points = int((stop - start) / step) + 2
            if est_points > self._MAX_SCHEDULE_POINTS:
                raise ValueError(
                    f"Linear schedule would generate ~{est_points} points (max {self._MAX_SCHEDULE_POINTS}). "
                    "Increase step size or reduce scan range."
                )
            voltages = np.arange(start, stop + step / 100.0, step)
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

    def _run_measurement_loop(self, voltages=None):
        try:
             # Generate Voltage Schedule if not provided
            if voltages is None:
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
                 self._is_running = False
                 self.sigMeasurementFinished.emit()
                 return

            # Check Laser Connection
            laser = self.get_active_laser()
            if not laser.is_connected:
                self.log.error(f"Selected laser ({self._active_laser}) is not connected.")
                self._is_running = False
                self.sigMeasurementFinished.emit()
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
                        wm = self._wavemeter()
                        val = np.nan
                        
                        max_retries = 10
                        for attempt in range(max_retries):
                            try:
                                if hasattr(wm, 'get_current_wavelength'):
                                    val = float(wm.get_current_wavelength())
                                elif hasattr(wm, 'get_wavelength'):
                                    val = float(wm.get_wavelength())
                                    
                                if val > 0:
                                    break
                            except Exception:
                                pass
                                
                            if attempt < max_retries - 1:
                                time.sleep(0.1)
                        
                        if val > 0:
                            # Heuristic for units: ZPL is ~470 THz (637 nm)
                            if val > 550:
                                 freq_thz = 299792.458 / val
                            else:
                                 freq_thz = val
                            
                            frequency_ghz = (freq_thz - self._zero_frequency) * 1000.0
                            self.log.info(f"Measured Frequency: {frequency_ghz:.4f} GHz (Raw: {val})")
                        else:
                            self.log.warning(f"No valid wavemeter reading at {v:.4f} V (Raw: {val})")
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
                        
                        conf_stats = self._compute_confidence_stats(spots_list)
                        self.log.info(f"Found {spot_count} spots at {v:.4f} V on {channel_name} ({method}) "
                                      f"[err={conf_stats['error']}, mean_conf={conf_stats['mean_confidence']:.2f}]")
                        
                        # Store Data
                        # Check if voltage is already in histogram to replace (for partial re-scans)
                        found_idx = -1
                        for idx, hv in enumerate(self._histogram_data['voltage']):
                            if abs(hv - v) < 1e-4: # Tolerance for float comparison
                                found_idx = idx
                                break
                        
                        if found_idx >= 0:
                            self._histogram_data['counts'][found_idx] = spot_count
                            self._histogram_data['frequency'][found_idx] = frequency_ghz
                            self._histogram_data['error'][found_idx] = conf_stats['error']
                            self._histogram_data['mean_confidence'][found_idx] = conf_stats['mean_confidence']
                        else:
                            self._histogram_data['voltage'].append(v)
                            self._histogram_data['counts'].append(spot_count)
                            self._histogram_data['frequency'].append(frequency_ghz)
                            self._histogram_data['error'].append(conf_stats['error'])
                            self._histogram_data['mean_confidence'].append(conf_stats['mean_confidence'])

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

    @staticmethod
    def _compute_confidence_stats(spots_list):
        """Compute error bar and mean confidence from a list of detected spots.

        Error bar = number of *marginal* detections (confidence < 1.0).
        This represents how sensitive the count is to small threshold
        changes — i.e. spots that could easily appear or disappear.

        Returns dict with 'error', 'mean_confidence', 'n_marginal', 'n_solid'.
        """
        if not spots_list:
            return {'error': 0, 'mean_confidence': 0.0,
                    'n_marginal': 0, 'n_solid': 0}
        confidences = [s.get('confidence', 0.0) for s in spots_list]
        n_total = len(confidences)
        n_marginal = sum(1 for c in confidences if c < 1.0)
        n_solid = n_total - n_marginal
        mean_conf = float(np.mean(confidences))
        return {
            'error': n_marginal,
            'mean_confidence': round(mean_conf, 4),
            'n_marginal': n_marginal,
            'n_solid': n_solid,
        }

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
            
            # 1. Find peaks in DoG
            dog_max = ndimage.maximum_filter(dog, size=5) == dog
            # 2. Check intensity in original image
            intensity_mask = image > threshold
            
            detected_spots_mask = dog_max & intensity_mask & (dog > 0)
            
            y_indices, x_indices = np.where(detected_spots_mask)
             
            for y, x in zip(y_indices, x_indices):
                val = float(image[y, x])
                confidence = float(dog[y, x])
                spots.append({
                    'x': int(x), 'y': int(y), 'val': val, 'confidence': confidence
                })

        elif method == 'Adaptive':
            # ------------------------------------------------------------------
            # Multiscale Laplacian-of-Gaussian with adaptive threshold
            # ------------------------------------------------------------------
            # The "threshold" parameter acts as a *sensitivity multiplier*:
            #   adaptive_cutoff = median + (threshold / 1000) * MAD
            # Lower threshold → more sensitive (more detections).
            # Typical useful range: 1000–10000 (i.e. multiplier 1–10).
            # ------------------------------------------------------------------
            img = image.astype(np.float64)

            # --- Adaptive threshold from image statistics ---
            median_val = np.median(img)
            mad = np.median(np.abs(img - median_val))   # median absolute deviation
            if mad == 0:
                mad = np.std(img)  # fallback for very uniform images
            sensitivity = max(threshold / 1000.0, 0.5)  # convert user threshold to multiplier
            adaptive_cutoff = median_val + sensitivity * mad

            # --- Multiscale LoG ---
            sigmas = [0.7, 1.0, 1.5, 2.5, 4.0]
            # Normalized LoG response at each scale (sigma^2 normalization)
            log_responses = []
            for s in sigmas:
                log_img = -ndimage.gaussian_laplace(img, sigma=s) * (s ** 2)
                log_responses.append(log_img)

            # Stack into 3D volume (sigma, y, x) and take scale-space maximum
            log_stack = np.stack(log_responses, axis=0)           # (N_sigma, H, W)
            best_scale_idx = np.argmax(log_stack, axis=0)          # (H, W)
            best_response = np.max(log_stack, axis=0)              # (H, W)

            # --- Peak detection: local maximum in 2D on the best-response map ---
            neighborhood_size = 5
            local_max = ndimage.maximum_filter(best_response, size=neighborhood_size) == best_response

            # --- Threshold conditions ---
            # 1) LoG response must be positive  (blob, not valley)
            # 2) Raw intensity above adaptive cutoff
            # 3) LoG response above a small positive floor (suppress flat regions)
            log_floor = mad * 0.1 if mad > 0 else 1.0
            peak_mask = local_max & (best_response > log_floor) & (img > adaptive_cutoff)

            y_indices, x_indices = np.where(peak_mask)
            responses = best_response[y_indices, x_indices]
            scale_indices = best_scale_idx[y_indices, x_indices]

            if len(y_indices) == 0:
                return []

            # --- Non-maximum suppression with minimum separation ---
            # Sort by LoG response (strongest first) and suppress neighbours
            min_sep_px = 3  # minimum pixel separation between distinct defects
            min_sep_sq = min_sep_px ** 2
            order = np.argsort(-responses)
            keep = np.ones(len(order), dtype=bool)
            kept_coords = []

            for rank in range(len(order)):
                if not keep[rank]:
                    continue
                idx = order[rank]
                yy, xx = int(y_indices[idx]), int(x_indices[idx])
                # Suppress weaker peaks nearby
                for later in range(rank + 1, len(order)):
                    if not keep[later]:
                        continue
                    jdx = order[later]
                    dy = int(y_indices[jdx]) - yy
                    dx = int(x_indices[jdx]) - xx
                    if dy * dy + dx * dx < min_sep_sq:
                        keep[later] = False
                kept_coords.append((yy, xx, idx))

            for yy, xx, idx in kept_coords:
                val = float(img[yy, xx])
                # Confidence = LoG response normalised by MAD (unit-free, comparable across scans)
                confidence = float(responses[order[np.where(order == idx)[0][0]]]) / mad if mad > 0 else float(responses[idx])
                best_sigma = sigmas[int(scale_indices[idx])]
                spots.append({
                    'x': xx, 'y': yy, 'val': val,
                    'confidence': round(confidence, 3),
                    'sigma': round(best_sigma, 2),
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

            # Track the active method/threshold for saving
            self._current_method = method
            self._current_threshold = threshold

            spots = self._detect_spots(display_image, method, threshold)
            
            # Update results
            res['spots'] = spots
            res['image'] = image
            res['channel'] = current_channel
            spot_count = len(spots)
            
            # Update histogram source with confidence stats
            conf_stats = self._compute_confidence_stats(spots)
            try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = spot_count
                self._histogram_data['error'][idx] = conf_stats['error']
                self._histogram_data['mean_confidence'][idx] = conf_stats['mean_confidence']
            except (ValueError, IndexError):
                pass
                
            self.log.info(f"Re-analyzed {voltage:.2f} V with {method} (Thresh: {threshold}): {spot_count} spots")
            
            # Emit updates — deep-copy to avoid cross-thread mutation
            self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))
            self.sigScanCompleted.emit(voltage, image, spots) # Re-emit to update GUI view
            return True
        return False

    def reanalyze_all(self, method, threshold, channel=None):
        """Re-analyze ALL scans with new parameters."""
        # Track the active method/threshold for saving
        self._current_method = method
        self._current_threshold = threshold

        count = 0
        last_voltage = None
        last_image = None
        last_spots = None

        for voltage in self._scan_results.keys():
             res = self._scan_results[voltage]
             
             # Select channel
             image = res['image']
             current_channel = res['channel']
             
             if channel:
                if 'all_channels' in res and channel in res['all_channels']:
                    image = res['all_channels'][channel]
                    current_channel = channel

             # Apply background subtraction if enabled
             display_image = image
             if self._background_enabled and self._background_image is not None:
                 if self._background_image.shape == image.shape:
                     display_image = np.clip(
                         image.astype(float) - self._background_image.astype(float), 0, None
                     )

             spots = self._detect_spots(display_image, method, threshold)
             
             res['spots'] = spots
             res['image'] = image
             res['channel'] = current_channel
             spot_count = len(spots)
             
             # Update histogram source with confidence stats
             conf_stats = self._compute_confidence_stats(spots)
             try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = spot_count
                self._histogram_data['error'][idx] = conf_stats['error']
                self._histogram_data['mean_confidence'][idx] = conf_stats['mean_confidence']
             except (ValueError, IndexError):
                pass
             
             last_voltage = voltage
             last_image = image
             last_spots = spots
             count += 1
             
        self.log.info(f"Re-analyzed {count} scans with {method} (threshold={threshold}).")
        self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))

        # Emit for the last scan so the GUI refreshes if it's viewing one of them
        if last_voltage is not None:
            self.sigScanCompleted.emit(last_voltage, last_image, last_spots)

        return count

    def compute_threshold_errors(self, method, threshold, thresh_lower, thresh_upper, channel=None):
        """Run detection at lower/upper threshold bounds and compute asymmetric error bars.

        For each voltage step:
          - count_main  = spots at `threshold`       (already stored)
          - count_lower = spots at `thresh_lower`    (usually more spots)
          - count_upper = spots at `thresh_upper`    (usually fewer spots)
          - error_plus  = count_lower - count_main   (how many MORE we'd get)
          - error_minus = count_main  - count_upper  (how many we'd LOSE)

        Stores error_lower / error_upper in _histogram_data and re-emits sigUpdatePlot.
        """
        error_lower = []   # error bar going DOWN (count_main - count_upper)
        error_upper = []   # error bar going UP   (count_lower - count_main)

        for voltage in self._scan_results.keys():
            res = self._scan_results[voltage]

            # Select channel
            image = res['image']
            if channel:
                if 'all_channels' in res and channel in res['all_channels']:
                    image = res['all_channels'][channel]

            # Apply background subtraction if enabled
            display_image = image
            if self._background_enabled and self._background_image is not None:
                if self._background_image.shape == image.shape:
                    display_image = np.clip(
                        image.astype(float) - self._background_image.astype(float), 0, None
                    )

            count_main = len(res['spots'])  # already computed at `threshold`
            spots_lo = self._detect_spots(display_image, method, thresh_lower)
            spots_hi = self._detect_spots(display_image, method, thresh_upper)
            count_lo = len(spots_lo)
            count_hi = len(spots_hi)

            err_plus = max(count_lo - count_main, 0)
            err_minus = max(count_main - count_hi, 0)

            error_upper.append(err_plus)
            error_lower.append(err_minus)

        # Store in histogram data
        self._histogram_data['error_lower'] = error_lower
        self._histogram_data['error_upper'] = error_upper
        # Also update the simple 'error' key with the max of both for CSV compatibility
        self._histogram_data['error'] = [max(lo, up) for lo, up in zip(error_lower, error_upper)]

        self.log.info(f"Threshold error analysis complete: {len(error_lower)} scans, "
                      f"bounds=[{thresh_lower}, {thresh_upper}]")
        self.sigUpdatePlot.emit(copy.deepcopy(self._histogram_data))

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
            conf_stats = self._compute_confidence_stats(result['spots'])
            
            # Update histogram data source
            try:
                idx = self._histogram_data['voltage'].index(voltage)
                self._histogram_data['counts'][idx] = count
                self._histogram_data['error'][idx] = conf_stats['error']
                self._histogram_data['mean_confidence'][idx] = conf_stats['mean_confidence']
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
                conf_stats = self._compute_confidence_stats(result['spots'])
                try:
                    idx = self._histogram_data['voltage'].index(voltage)
                    self._histogram_data['counts'][idx] = count
                    self._histogram_data['error'][idx] = conf_stats['error']
                    self._histogram_data['mean_confidence'][idx] = conf_stats['mean_confidence']
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

    def get_default_data_dir(self):
        """Return the qudi module_default_data_dir (respects config daily_data_dirs)."""
        try:
            return str(self.module_default_data_dir)
        except Exception:
            import os
            return os.path.expanduser('~')

    def save_all_results(self, save_dir):
        """Non-blocking: launch background thread to write all results."""
        if self._saving_running:
            self.log.warning("Save already in progress.")
            return
        self._saving_running = True
        import threading
        t = threading.Thread(target=self._save_all_results_worker, args=(save_dir,), daemon=True)
        t.start()

    def _save_all_results_worker(self, save_dir):
        """Background worker: saves histogram CSV/SVG, per-scan DAT, spots CSV,
        raw NPZ, and summary JSON in a separate thread.
        Emits sigSavingFinished(success, message) when done.
        """
        import os
        import csv
        import json
        import traceback
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        errors = []

        try:
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            # ── Thread safety: snapshot all shared data up front ────────────
            # Matplotlib is NOT thread-safe.  The measurement thread may
            # mutate _scan_results / _histogram_data while we render SVGs,
            # causing an access violation.  Deep-copy everything once.
            histogram_data = copy.deepcopy(self._histogram_data)
            scan_results   = copy.deepcopy(self._scan_results)

            # ── Attempt to get scan resolution + range from scan_logic ──────
            scan_resolution = {}
            scan_range_um = {}
            try:
                sl = self._scan_logic()
                if hasattr(sl, 'scan_settings'):
                    ss = sl.scan_settings
                    if ss and 'resolution' in ss:
                        scan_resolution = ss['resolution']
                    if ss and 'range' in ss:
                        # Convert to µm (internal unit is likely m)
                        for ax, rng in ss['range'].items():
                            try:
                                scan_range_um[ax] = round(float(rng) * 1e6, 3)
                            except (TypeError, ValueError):
                                scan_range_um[ax] = rng
                elif hasattr(sl, '_scan_settings'):
                    ss = sl._scan_settings
                    if ss and 'resolution' in ss:
                        scan_resolution = ss['resolution']
                    if ss and 'range' in ss:
                        for ax, rng in ss['range'].items():
                            try:
                                scan_range_um[ax] = round(float(rng) * 1e6, 3)
                            except (TypeError, ValueError):
                                scan_range_um[ax] = rng
            except Exception as e:
                self.log.warning(f"Could not retrieve scan settings: {e}")

            # ── 1. Histogram SVG ───────────────────────────────────────────────
            try:
                fig = Figure()
                FigureCanvasAgg(fig)
                ax = fig.add_subplot(111)
                ax.set_xlabel("Frequency (GHz) / Voltage (V)")
                ax.set_ylabel("Number of Spots")
                ax.set_title("ZPL Distribution")
                volts_sv = histogram_data['voltage']
                counts_sv = histogram_data['counts']
                freqs_sv = histogram_data.get('frequency', [])
                errors_sv = histogram_data.get('error', [0] * len(volts_sv))
                if len(volts_sv) > 0:
                    use_freq = (len(freqs_sv) == len(volts_sv)
                                and not all(np.isnan(f) for f in freqs_sv if not np.isnan(f) == np.isnan(f)))
                    x_sv = freqs_sv if (use_freq and len(freqs_sv) == len(volts_sv)) else volts_sv
                    if len(x_sv) > 1:
                        diffs_sv = np.diff(np.sort([v for v in x_sv if not np.isnan(v)]))
                        nonzero_sv = diffs_sv[diffs_sv > 0]
                        bar_w_sv = float(np.min(nonzero_sv)) * 0.8 if len(nonzero_sv) > 0 else 1.0
                    else:
                        bar_w_sv = getattr(self, '_step_voltage', 1.0) * 0.8
                    ax.bar(x_sv, counts_sv, width=bar_w_sv, alpha=0.85, color='steelblue')
                    # Add error bars
                    if len(errors_sv) == len(x_sv):
                        ax.errorbar(x_sv, counts_sv, yerr=errors_sv, fmt='none',
                                    ecolor='black', capsize=3, capthick=1)
                fig.savefig(os.path.join(save_dir, "distribution_histogram.svg"))
            except Exception as e:
                err = f"Histogram SVG: {e}"
                errors.append(err)
                self.log.error(f"{err}\n{traceback.format_exc()}")

            # ── 2. Histogram CSV ───────────────────────────────────────────────
            try:
                volts = histogram_data['voltage']
                counts = histogram_data['counts']
                freqs = histogram_data.get('frequency', [float('nan')] * len(volts))
                if len(freqs) < len(volts):
                    freqs = list(freqs) + [float('nan')] * (len(volts) - len(freqs))
                # Build resolution string
                res_str = ', '.join(f"{ax}: {r}" for ax, r in scan_resolution.items()) if scan_resolution else 'N/A'
                range_str = ', '.join(f"{ax}: {r} µm" for ax, r in scan_range_um.items()) if scan_range_um else 'N/A'
                with open(os.path.join(save_dir, "distribution_histogram.csv"), 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([f"# Scan Resolution: {res_str}"])
                    writer.writerow([f"# Scan Range: {range_str}"])
                    writer.writerow([f"# Zero Frequency (THz): {self._zero_frequency}"])
                    writer.writerow([f"# Detection Method: {self._current_method}"])
                    writer.writerow([f"# Threshold: {self._current_threshold}"])
                    writer.writerow(["Voltage (V)", "Frequency (GHz)", "Spot Count",
                                     "Error (marginal)", "Mean Confidence"])
                    err_list = histogram_data.get('error', [0] * len(volts))
                    conf_list = histogram_data.get('mean_confidence', [0.0] * len(volts))
                    for i, (v, f_val, c) in enumerate(zip(volts, freqs, counts)):
                        e = err_list[i] if i < len(err_list) else 0
                        mc = conf_list[i] if i < len(conf_list) else 0.0
                        writer.writerow([v, f_val, c, e, f"{mc:.4f}"])
            except Exception as e:
                err = f"Histogram CSV: {e}"
                errors.append(err)
                self.log.error(f"{err}\n{traceback.format_exc()}")

            # ── 3. Per-scan: DAT + raw NPZ ─────────────────────────────────────
            all_spots = []
            for v, res in scan_results.items():
                freq = res.get('frequency', float('nan'))

                # Collect spots for global CSV
                for s in res['spots']:
                    all_spots.append({
                        'Voltage': v, 'Frequency_GHz': freq,
                        'X': s['x'], 'Y': s['y'],
                        'Value': s['val'], 'Confidence': s['confidence']
                    })

                try:
                    v_float = float(v)
                    v_safe = f"{v_float:.4f}"
                except Exception:
                    v_safe = str(v).replace(':', '_').replace('/', '_').replace('\\', '_')

                # DAT file with raw scan data
                try:
                    wavelength_nm = float('nan')
                    if not np.isnan(freq):
                        freq_thz = (freq / 1000.0) + self._zero_frequency
                        if freq_thz > 0:
                            wavelength_nm = 299792.458 / freq_thz

                    dat_path = os.path.join(save_dir, f"scan_{v_safe}V.dat")
                    with open(dat_path, 'w') as f:
                        f.write(f"# Laser Voltage (V): {v}\n")
                        if not np.isnan(wavelength_nm):
                            f.write(f"# Measured Wavelength (nm): {wavelength_nm:.5f}\n")
                        else:
                            f.write("# Measured Wavelength (nm): NaN\n")
                        if not np.isnan(freq):
                            f.write(f"# Measured Frequency relative to {self._zero_frequency} THz (GHz): {freq:.4f}\n")
                        else:
                            f.write(f"# Measured Frequency relative to {self._zero_frequency} THz (GHz): NaN\n")
                        f.write("# Scan Raw Data (2D array)\n")
                        np.savetxt(f, res['image'], fmt='%g', delimiter='\t')
                except Exception as e:
                    err = f"DAT scan {v_safe}V: {e}"
                    errors.append(err)
                    self.log.error(err)

                # Raw NPZ  — all channels + metadata
                try:
                    npz_path = os.path.join(save_dir, f"scan_{v_safe}V_raw.npz")
                    # Build arrays dict: one entry per channel
                    arrays = {}
                    if 'all_channels' in res and res['all_channels']:
                        for ch_name, arr in res['all_channels'].items():
                            safe_ch = ch_name.replace(' ', '_').replace('/', '_')
                            arrays[safe_ch] = np.asarray(arr)
                    else:
                        # Fallback: just the primary image
                        arrays['image'] = np.asarray(res['image'])

                    # Metadata as JSON-encoded string (npz only stores arrays natively)
                    meta = {
                        'voltage_V': float(v) if not isinstance(v, float) else v,
                        'frequency_GHz': float(freq) if not np.isnan(freq) else None,
                        'timestamp': res.get('timestamp', ''),
                        'channel': res.get('channel', ''),
                        'count_channel': res.get('count_channel', ''),
                        'detection_method': self._current_method,
                        'threshold': float(self._current_threshold),
                        'scan_resolution': scan_resolution,
                        'zero_frequency_THz': self._zero_frequency,
                        'spots': res['spots'],  # list of dicts
                    }
                    arrays['_metadata_json'] = np.array(json.dumps(meta))
                    np.savez_compressed(npz_path, **arrays)
                except Exception as e:
                    err = f"NPZ scan {v_safe}V: {e}"
                    errors.append(err)
                    self.log.error(f"{err}\n{traceback.format_exc()}")

            # ── 4. All-spots CSV ───────────────────────────────────────────────
            try:
                with open(os.path.join(save_dir, "all_spots.csv"), 'w', newline='') as f:
                    fieldnames = ['Voltage', 'Frequency_GHz', 'X', 'Y', 'Value', 'Confidence']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(all_spots)
            except Exception as e:
                err = f"All-spots CSV: {e}"
                errors.append(err)
                self.log.error(err)

            # ── 5. Summary JSON ────────────────────────────────────────────────
            try:
                class NumpyEncoder(json.JSONEncoder):
                    def default(self, obj):
                        if isinstance(obj, np.integer): return int(obj)
                        if isinstance(obj, np.floating): return float(obj)
                        if isinstance(obj, np.ndarray): return obj.tolist()
                        return super().default(obj)

                export_data = {
                    "metadata": {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "scan_channels": list(self._scan_channels),
                        "count_channel": self._count_channel,
                        "detection_method": self._current_method,
                        "spot_threshold": float(self._current_threshold),
                        "scan_resolution": scan_resolution,
                        "scan_range_um": scan_range_um,
                        "zero_frequency_THz": self._zero_frequency,
                    },
                    "histogram": {
                        "voltage": histogram_data['voltage'],
                        "counts": histogram_data['counts'],
                        "frequency_GHz": histogram_data.get('frequency', [])
                    },
                    "scans": [
                        {
                            "voltage": v,
                            "frequency_GHz": res.get('frequency', None),
                            "timestamp": res.get('timestamp', ''),
                            "channel": res.get('channel', ''),
                            "n_spots": len(res['spots']),
                            "spots": res['spots'],
                            # image omitted from JSON to keep file small; use NPZ instead
                        }
                        for v, res in scan_results.items()
                    ]
                }
                with open(os.path.join(save_dir, "results.json"), 'w') as f:
                    json.dump(export_data, f, cls=NumpyEncoder, indent=2)
            except Exception as e:
                err = f"Summary JSON: {e}"
                errors.append(err)
                self.log.error(f"{err}\n{traceback.format_exc()}")

            if errors:
                msg = f"Saved to {save_dir} with {len(errors)} error(s): {'; '.join(errors)}"
                self.sigSavingFinished.emit(False, msg)
            else:
                self.sigSavingFinished.emit(True, f"All results saved to:\n{save_dir}")

        except Exception as e:
            self.log.error(f"Save worker crashed: {e}\n{traceback.format_exc()}")
            self.sigSavingFinished.emit(False, f"Save failed: {e}")
        finally:
            self._saving_running = False

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
