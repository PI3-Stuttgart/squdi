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
    
    # Config Options
    _spot_threshold = ConfigOption(name='spot_threshold', default=5000) # Counts/s threshold
    _scan_channels = ConfigOption(name='scan_channels', default=['x', 'y'])
    
    sigUpdatePlot = QtCore.Signal(object)
    sigMeasurementFinished = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._stop_requested = False

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
        self._histogram_data = {'voltage': [], 'counts': []}
        
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

    def _run_measurement_loop(self):
        try:
            voltages = np.arange(self._start_voltage, self._stop_voltage + self._step_voltage, self._step_voltage)
            total_steps = len(voltages)
            
            for i, v in enumerate(voltages):
                if self._stop_requested:
                    break
                
                self._current_voltage = v
                self._progress = (i / total_steps) * 100
                
                # 1. Set Laser Voltage
                self.log.info(f"Setting laser voltage to {v} V")
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
                if scan_data:
                    # Assuming data is dict like {'APD1': array, ...}
                    # We pick the first channel usually
                    if scan_data.data:
                        channel_name = list(scan_data.data.keys())[0]
                        image_data = scan_data.data[channel_name]
                        
                        spot_count = self._count_spots(image_data)
                        self.log.info(f"Found {spot_count} spots at {v} V")
                        
                        self._histogram_data['voltage'].append(v)
                        self._histogram_data['counts'].append(spot_count)
                        
                        # Emit update for plot
                        self.sigUpdatePlot.emit(self._histogram_data)
                else:
                    self.log.warning("No scan data retrieved.")
    
            self._progress = 100.0
            
        except Exception as e:
            self.log.error(f"Error in measurement loop: {e}")
        finally:
            self._is_running = False
            self.sigMeasurementFinished.emit()

    def _count_spots(self, image):
        threshold = self._spot_threshold
        mask = image > threshold
        
        if not np.any(mask):
            return 0
            
        size = 5 # pixels
        local_max = maximum_filter(image, size=size) == image
        
        detected_spots = local_max & mask
        
        return np.sum(detected_spots)
