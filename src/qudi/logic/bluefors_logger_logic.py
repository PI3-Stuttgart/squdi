# -*- coding: utf-8 -*-
"""
Logic module for periodically logging temperature and pressure data from the Bluefors API.
"""

import os
import time
import datetime
import numpy as np
from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.util.datastorage import TextDataStorage

class BlueforsLoggerLogic(LogicBase):
    """
    Qudi Logic module to periodically read data from the Bluefors API and save it.
    """

    bluefors_api = Connector(interface='BlueforsAPI')
    
    # Configuration options
    log_interval_seconds = ConfigOption(name='log_interval_seconds', default=10)
    targets = ConfigOption(name='targets', default=['mapper.bf.T1', 'mapper.bf.T2', 'mapper.bf.P1', 'mapper.bf.P2'])
    
    # Signals
    sig_logging_changed = QtCore.Signal(bool)
    sig_latest_data = QtCore.Signal(dict)
    
    # Internal state
    _is_logging = False
    _latest_data = {}

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._poll_data)
        self._data_buffer = []
        self._current_file_path = None
        self._current_ds = None

    def on_activate(self):
        self._api = self.bluefors_api()
        self._timer.setInterval(int(self.log_interval_seconds * 1000))
        self.log.info(f"Bluefors Logger activated. Targets: {self.targets}")

    def on_deactivate(self):
        self.stop_logging()
        self.log.info("Bluefors Logger deactivated.")

    @property
    def is_logging(self):
        return self._is_logging

    @property
    def latest_data(self):
        return self._latest_data

    def start_logging(self):
        """
        Start the periodic logging.
        """
        if self._is_logging:
            self.log.warning("Logging is already running.")
            return

        self._data_buffer = []
        self._current_ds = TextDataStorage(root_dir=self.module_default_data_dir,
                                           column_formats='.6e',
                                           include_global_metadata=True)
        # Create a new file initially or setup path
        # TextDataStorage save_data writes the whole array. For a continuous log, 
        # it's often better to just open a file and append. But we can use TextDataStorage 
        # to generate the path and header, then append manually, or buffer and save.
        # Here we'll append to a manually opened file to avoid buffering infinite data.
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_Bluefors_Log.txt"
        
        # Determine full path ensuring daily directory if configured
        root = self.module_default_data_dir
        if self.app.config.get('global', {}).get('daily_data_dirs', False):
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            root = os.path.join(root, date_str)
        
        if not os.path.exists(root):
            os.makedirs(root)
            
        self._current_file_path = os.path.join(root, filename)
        
        # Write header
        headers = ["Timestamp(s)"] + self.targets
        with open(self._current_file_path, 'w') as f:
            f.write("# " + "\t".join(headers) + "\n")
            
        self._timer.start()
        self._is_logging = True
        self.sig_logging_changed.emit(True)
        self.log.info(f"Started logging Bluefors data to {self._current_file_path}")

    def stop_logging(self):
        """
        Stop the periodic logging.
        """
        if not self._is_logging:
            return
            
        self._timer.stop()
        self._is_logging = False
        self.sig_logging_changed.emit(False)
        self.log.info(f"Stopped logging Bluefors data.")

    @QtCore.Slot()
    def _poll_data(self):
        """
        Poll data from the hardware module and append to file.
        """
        if not self._api:
            self.log.error("Hardware module not connected.")
            self.stop_logging()
            return
            
        try:
            results = self._api.get_values(self.targets)
            self._latest_data = results
            self.sig_latest_data.emit(results)
            
            # Format row
            current_time = time.time()
            row = [f"{current_time:.3f}"]
            for target in self.targets:
                val = results.get(target)
                if val is not None:
                    row.append(f"{val:.6e}" if isinstance(val, float) else str(val))
                else:
                    row.append("NaN")
                    
            # Append to file
            if self._current_file_path and os.path.exists(self._current_file_path):
                with open(self._current_file_path, 'a') as f:
                    f.write("\t".join(row) + "\n")
                    
        except Exception as e:
            self.log.error(f"Error polling Bluefors data: {e}")
