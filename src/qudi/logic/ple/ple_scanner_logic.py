# -*- coding: utf-8 -*-
"""
This file contains a Qudi logic module for controlling scans of the
fourth analog output channel.  It was originally written for
scanning laser frequency, but it can be used to control any parameter
in the experiment that is voltage controlled.  The hardware
range is typically -10 to +10 V.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""
from PySide2 import QtCore
import copy as cp
from qudi.logic.scanning_probe_logic import ScanningProbeLogic
from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.util.widgets.fitting import FitConfigurationDialog, FitWidget


from qudi.util.datastorage import TextDataStorage
from qudi.util.datafitting import FitContainer, FitConfigurationsModel

class PLEScannerLogic(ScanningProbeLogic):

    """This logic module controls scans of DC voltage on the fourth analog
    output channel of the NI Card.  It collects countrate as a function of voltage.
    """
    # declare connectors
    _scanner = Connector(name='scanner', interface='ScanningProbeInterface')
    
    _scan_axis = ConfigOption(name='scan_axis', default='a')
    # status vars
    _scan_ranges = StatusVar(name='scan_ranges', default=None)
    _scan_resolution = StatusVar(name='scan_resolution', default=None)
    _scan_frequency = StatusVar(name='scan_frequency', default=None)

    _number_of_repeats = StatusVar(default=10)

    # config options

    _fit_config = StatusVar(name='fit_config', default=dict())
    _fit_region = StatusVar(name='fit_region', default=[0, 1])

  
    def __init__(self, config, **kwargs):
        super(PLEScannerLogic, self).__init__(config=config, **kwargs)
        """ Create VoltageScanningLogic object with connectors.

          @param dict kwargs: optional parameters
        """
        #Took some from the spectrometer program, beacuse it's graaape
        self.refractive_index_air = 1.00028823
        self.speed_of_light = 2.99792458e8 / self.refractive_index_air
        self._fit_config_model = None
        self._fit_container = None

        self._wavelength = None
        self._fit_results = None
        self._fit_method = ''
        # self.__scan_poll_interval = 0
        # self.__scan_stop_requested = True
        # self._curr_caller_id = self.module_uuid
        # self._thread_lock = RecursiveMutex()
        self.__scan_poll_timer = None
        self.__scan_poll_interval = 0
        self.__scan_stop_requested = True



    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        # self._scanning_device = self.scanning_device()
        self._fit_config_model = FitConfigurationsModel(parent=self)
        self._fit_config_model.load_configs(self._fit_config)
        self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)
        self.fit_region = self._fit_region
        print(f"Scanner settings at startup, type {self._scan_ranges} {self._scan_ranges, self._scan_resolution}")
        
        """ Initialisation performed during activation of the module.
        """
        constr = self.scanner_constraints

        self._scan_saved_to_hist = True


        print(f"Scanner settings at startup, type {self._scan_ranges} {self._scan_ranges, self._scan_resolution}")
        self.log.debug(f"Scanner settings at startup, type {type(self._scan_ranges)} {self._scan_ranges, self._scan_resolution}")
        # scanner settings loaded from StatusVar or defaulted
        new_settings = self.check_sanity_scan_settings(self.scan_settings)
        if new_settings != self.scan_settings:
            self._scan_ranges = new_settings['range']
            self._scan_resolution = new_settings['resolution']
            self._scan_frequency = new_settings['frequency']
        """
        if not isinstance(self._scan_ranges, dict):
            self._scan_ranges = {ax.name: ax.value_range for ax in constr.axes.values()}
        if not isinstance(self._scan_resolution, dict):
            self._scan_resolution = {ax.name: max(ax.min_resolution, min(128, ax.max_resolution))  # TODO Hardcoded 128?
                                     for ax in constr.axes.values()}
        if not isinstance(self._scan_frequency, dict):
            self._scan_frequency = {ax.name: ax.max_frequency for ax in constr.axes.values()}
        """
        print(f"Scanner settings at startup, type {self._scan_ranges} {self._scan_ranges, self._scan_resolution}")

        self.__scan_poll_interval = 0
        self.__scan_stop_requested = True
        self._curr_caller_id = self.module_uuid

        self.__scan_poll_timer = QtCore.QTimer()
        self.__scan_poll_timer.setSingleShot(True)
        self.__scan_poll_timer.timeout.connect(self.__scan_poll_loop, QtCore.Qt.QueuedConnection)
        
        return

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self._fit_config = self._fit_config_model.dump_configs()
        """ 
        Reverse steps of activation
        """
        self.__scan_poll_timer.stop()
        self.__scan_poll_timer.timeout.disconnect()
        if self.module_state() != 'idle':
            self._scanner().stop_scan()
        return  
    

    @QtCore.Slot(tuple)
    @QtCore.Slot(tuple, object)
    def start_scan(self, scan_axes, caller_id=None):
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
                return 0

            scan_axes = tuple(scan_axes)
            self._curr_caller_id = self.module_uuid if caller_id is None else caller_id

            self.module_state.lock()

            settings = {'axes': scan_axes,
                        'range': tuple(self._scan_ranges[ax] for ax in scan_axes),
                        'resolution': tuple(self._scan_resolution[ax] for ax in scan_axes),
                        'frequency': self._scan_frequency[scan_axes[0]]}
            fail, new_settings = self._scanner().configure_scan(settings)
            if fail:
                self.module_state.unlock()
                self.sigScanStateChanged.emit(False, None, self._curr_caller_id)
                return -1

            for ax_index, ax in enumerate(scan_axes):
                # Update scan ranges if needed
                new = tuple(new_settings['range'][ax_index])
                if self._scan_ranges[ax] != new:
                    self._scan_ranges[ax] = new
                    self.sigScanSettingsChanged.emit({'range': {ax: self._scan_ranges[ax]}})

                # Update scan resolution if needed
                new = int(new_settings['resolution'][ax_index])
                if self._scan_resolution[ax] != new:
                    self._scan_resolution[ax] = new
                    self.sigScanSettingsChanged.emit(
                        {'resolution': {ax: self._scan_resolution[ax]}}
                    )

            # Update scan frequency if needed
            new = float(new_settings['frequency'])
            if self._scan_frequency[scan_axes[0]] != new:
                self._scan_frequency[scan_axes[0]] = new
                self.sigScanSettingsChanged.emit({'frequency': {scan_axes[0]: new}})

            # Calculate poll time to check for scan completion. Use line scan time estimate.
            line_points = self._scan_resolution[scan_axes[0]] if len(scan_axes) > 1 else 1
            self.__scan_poll_interval = max(self._min_poll_interval,
                                            line_points / self._scan_frequency[scan_axes[0]])
            self.__scan_poll_timer.setInterval(int(round(self.__scan_poll_interval * 1000)))

            if self._scanner().start_scan() < 0:  # TODO Current interface states that bool is returned from start_scan
                self.module_state.unlock()
                self.sigScanStateChanged.emit(False, None, self._curr_caller_id)
                return -1

            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
            self.__start_timer()
            return 0

    @QtCore.Slot()
    def stop_scan(self):
        with self._thread_lock:
            if self.module_state() == 'idle':
                self.sigScanStateChanged.emit(False, self.scan_data, self._curr_caller_id)
                return 0

            self.__stop_timer()

            err = self._scanner().stop_scan() if self._scanner().module_state() != 'idle' else 0

            self.module_state.unlock()

            if self.scan_settings['save_to_history']:
                # module_uuid signals data-ready to data logic
                self.sigScanStateChanged.emit(False, self.scan_data, self.module_uuid)
            else:
                self.sigScanStateChanged.emit(False, self.scan_data, self._curr_caller_id)

            return err

    @QtCore.Slot()
    def __scan_poll_loop(self):
        with self._thread_lock:
            if self.module_state() == 'idle':
                return

            if self._scanner().module_state() == 'idle':
                self.stop_scan()
                return
            # TODO Added the following line as a quick test; Maybe look at it with more caution if correct
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)

            # Queue next call to this slot
            self.__scan_poll_timer.start()
            return
    
    def __start_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(self.__scan_poll_timer,
                                            'start',
                                            QtCore.Qt.BlockingQueuedConnection)
        else:
            self.__scan_poll_timer.start()

    def __stop_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(self.__scan_poll_timer,
                                            'stop',
                                            QtCore.Qt.BlockingQueuedConnection)
        else:
            self.__scan_poll_timer.stop()
