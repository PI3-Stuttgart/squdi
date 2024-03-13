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

#TODO when scan stopped plot the last complete scan. 
#TODO refresh matrix when settings change
#TODO resolution
#!ValueError: all the input array dimensions for the concatenation axis must match exactly, but along dimension 1, the array at index 0 has size 50 and the array at index 1 has size 100

from PySide2 import QtCore
import copy as cp
from qudi.logic.scanning.probe_logic import ScanningProbeLogic

from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar

from qudi.util.widgets.fitting import FitConfigurationDialog, FitWidget

from qudi.util.delay import delay
from time import sleep

from qudi.util.datastorage import TextDataStorage
from qudi.util.datafitting import FitContainer, FitConfigurationsModel
import numpy as np
class PLEScannerLogic(ScanningProbeLogic):


    """This logic module controls scans of DC voltage on the fourth analog
    output channel of the NI Card.  It collects countrate as a function of voltage.
    """

    # declare connectors
    _scanner = Connector(name='scanner', interface='ScanningProbeInterface')
    _wavemeter = Connector(name='wavemeter', interface='HighFinesseWavemeter', optional = True) #FIX it to make more generatal and talk to the Wavemeter interfafce
    _calibration_factor = 1 #calibrate the wavelength 
    _wavelength_range = [0, 0]
 
    #! We should refactor it to the hardware scanner interface
    _scan_axis = ConfigOption(name='scan_axis', default='a')
    _channel = StatusVar(name='channel', default=None)


    # status vars
    _scan_ranges = StatusVar(name='scan_ranges', default=None)
    _scan_resolution = StatusVar(name='scan_resolution', default=None)
    _scan_frequency = StatusVar(name='scan_frequency', default=None)

    _number_of_repeats = StatusVar(default=10)
    _repeated = 0
    display_repeated = 0
    # config options
    _fit_config = StatusVar(name='fit_config', default=None)
    _fit_region = StatusVar(name='fit_region', default=[0, 1])
    _scan_poll_interval = 100
    _default_fit_configs = (
        {'name'             : 'Lorentzian',
        'model'            : 'Lorentzian',
        'estimator'        : 'Peak',
        'custom_parameters': None},
        
        {'name'             : 'DoubleLorentzian',
        'model'            : 'DoubleLorentzian',
        'estimator'        : 'Peaks',
        'custom_parameters': None},

        {'name'             : 'Gaussian',
        'model'            : 'Gaussian',
        'estimator'        : 'Peak',
        'custom_parameters': None}
        
    )

    accumulated = None
    sigRepeatScan = QtCore.Signal(bool, tuple)
    sigFitUpdated = QtCore.Signal(object, str)
    sigToggleScan = QtCore.Signal(bool, tuple, object)
    sigSetScannerTarget = QtCore.Signal(dict)
    sigUpdateAccumulated = QtCore.Signal(object, object)
    sigScanningDone = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super(PLEScannerLogic, self).__init__(config=config, **kwargs)

        """ Create VoltageScanningLogic object with connectors.

          @param dict kwargs: optional parameters
        """
        self._thread_lock = RecursiveMutex()

        #Took some from the spectrometer program, beacuse it's graaape
        self.refractive_index_air = 1.00028823
        self.speed_of_light = 2.99792458e8 / self.refractive_index_air
        self._fit_container = None
        self._fit_config_model = None
        self._fit_results = None

        self._wavelength = None
        self._fit_method = ''
        self.__scan_poll_timer = None
        self.__scan_poll_interval = 100
        self.__scan_stop_requested = True
        self._curr_caller_id = self.module_uuid

        self.data_accumulated = None
        self._scan_id = 0
        self._fit_results = dict()
        self._fit_results['fluorescence'] = [None] * 1

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        # self._scanning_device = self.scanning_device()
        if self._wavemeter():
            self._wavemeter().start_acquisition()
        self._fit_config_model = FitConfigurationsModel(parent=self)
        self._fit_config_model.load_configs(self._fit_config)
        self._fit_container = FitContainer(parent=self, config_model=self._fit_config_model)
        self.fit_region = self._fit_region
        self.sigSetScannerTarget.connect(self.set_target_position)
        constr = self.scanner_constraints
        self._channel = list(constr.channels.keys())[0] if self._channel is None else self._channel
        self._scan_saved_to_hist = True
        self.log.debug(f"Scanner settings at startup, type {type(self._scan_ranges)} {self._scan_ranges, self._scan_resolution}")
        # scanner settings loaded from StatusVar or defaulted
        new_settings = self.check_sanity_scan_settings(self.scan_settings)
        if new_settings != self.scan_settings:
            self._scan_ranges = new_settings['range']
            self._scan_resolution = new_settings['resolution']
            self._scan_frequency = new_settings['frequency']
        
        if not self._min_poll_interval:
            # defaults to maximum scan frequency of scanner
            self._min_poll_interval = 1/np.max([constr.axes[ax].frequency_range for ax in constr.axes])



        """
        if not isinstance(self._scan_ranges, dict):
            self._scan_ranges = {ax.name: ax.value_range for ax in constr.axes.values()}
        if not isinstance(self._scan_resolution, dict):
            self._scan_resolution = {ax.name: max(ax.min_resolution, min(128, ax.max_resolution))  # TODO Hardcoded 128?
                                     for ax in constr.axes.values()}
        if not isinstance(self._scan_frequency, dict):
            self._scan_frequency = {ax.name: ax.max_frequency for ax in constr.axes.values()}
        """
        self.sigRepeatScan.connect(self.toggle_scan, QtCore.Qt.QueuedConnection)
        self.__scan_poll_interval = 100
        self.__scan_stop_requested = True
        self._curr_caller_id = self.module_uuid

        if not self._min_poll_interval:
            # defaults to maximum scan frequency of scanner
            self._min_poll_interval = 1/np.max([self.scanner_constraints.axes[ax].frequency_range for ax in self.scanner_constraints.axes])

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

    def calibrate_scan(self):
        self.scan_ranges_wavemeter = [0, 0]
        if self._wavemeter():
            for i in range(5):
                start, stop = self.run_calibration()
                self.scan_ranges_wavemeter[1] = (self.scan_ranges_wavemeter[1] + stop)/2

            #self._scan_ranges.update({"a": [i*1e3 for i in self.scan_ranges_wavemeter]}) #in GHzs
        self._calibration_factor = 1e12 * self.scan_ranges_wavemeter[-1] / self._scan_ranges[self._scan_axis][-1] 

    def run_calibration(self):
        self.set_target_position({self._scan_axis: self.scan_ranges[self._scan_axis][0]}, move_blocking=True)
        new_pos = self._scanner().get_target()
        sleep(2) #in mu sec
        self.wavelength_start = self._wavemeter().get_current_wavelength()
       
        self.set_target_position({self._scan_axis: self.scan_ranges[self._scan_axis][-1]}, move_blocking=True)
        new_pos = self._scanner().get_target()
        sleep(2) #in mu sec
        self.wavelength_stop = self._wavemeter().get_current_wavelength()
       
        
        return 0, self.wavelength_stop - self.wavelength_start

    @QtCore.Slot(str, str)
    def do_fit(self, fit_config, channel, averaged=False):
        """
        Execute the currently configured fit on the measurement data. Optionally on passed data
        """
       
        if fit_config != 'No Fit' and fit_config not in self._fit_config_model.configuration_names:
            self.log.error(f'Unknown fit configuration "{fit_config}" encountered.')
            return

        if self.scan_data is None:
            return
        
        y_data = self.scan_data.accumulated[self._channel].mean(axis=0) if averaged else self.scan_data.data[self._channel] 
        x_range = self.scan_ranges[self._scan_axis]
        x_data = np.linspace(*x_range, self.scan_resolution[self._scan_axis])
        try:
            fit_config, fit_result = self._fit_container.fit_data(fit_config, x_data, y_data)
        except:
            self.log.exception('Data fitting failed:')
            return
        
        if fit_result is not None:
            self._fit_results[self._channel] = (fit_config, fit_result)
        else:
            self._fit_results[self._channel] = None
        
        self.sigFitUpdated.emit(self._fit_results[self._channel], self._channel)

    @_fit_config.representer
    def __repr_fit_configs(self, value):
        configs = self.fit_config_model.dump_configs()
        if len(configs) < 1:
            configs = None
        return configs

    @_fit_config.constructor
    def __constr_fit_configs(self, value):
        if not value:
            return self._default_fit_configs
        return value

    @property
    def fit_results(self):
        return self._fit_results.copy()
    @property
    def fit_config_model(self):
        return self._fit_config_model

    @property
    def fit_container(self):
        return self._fit_container

    @property
    def fit_results(self):
        return self._fit_results.copy()
    
    def stack_data(self):
        if (self.scan_data is not None) and (self.scan_data.scan_dimension == 1):
           
            if self.accumulated is None:
                
                self.accumulated = {channel: data_i[np.newaxis, :] for channel, data_i in self.scan_data.data.items()}
                
            else:
                if len(list(self.scan_data.data.values())[0]) > 0:
                    self.accumulated = {channel : np.vstack((self.accumulated[channel], data_i))[-self._number_of_repeats:] for channel, data_i in self.scan_data.data.items()}
                else:
                    return
            self._scanner()._scan_data.accumulated = self.accumulated
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
            # self.sigUpdateAccumulated.emit(self.accumulated, self.scan_data)

    @QtCore.Slot(dict)
    def set_scan_settings(self, settings):
        with self._thread_lock:
            if 'range' in settings:
                self.set_scan_range(settings['range'])
            if 'resolution' in settings:
                self.set_scan_resolution(settings['resolution'])
            if 'frequency' in settings:
                self.set_scan_frequency(settings['frequency'])
            if 'save_to_history' in settings:
                self._scan_saved_to_hist = settings['save_to_history']
            # self.reset_accumulated()

    def update_number_of_repeats(self, number_of_repeats):
        self._number_of_repeats = number_of_repeats

    
    def set_target_position(self, pos_dict, caller_id=None, move_blocking=False):
        with self._thread_lock:
            if self.module_state() != 'idle':
                # self.log.error('Unable to change scanner target position while a scan is running.')
                new_pos = self._scanner().get_target()
                self.sigScannerTargetChanged.emit(new_pos, self.module_uuid)
                return new_pos

            ax_constr = self.scanner_constraints.axes
            new_pos = pos_dict.copy()
            for ax, pos in pos_dict.items():
                if ax not in ax_constr:
                    self.log.error('Unknown scanner axis: "{0}"'.format(ax))
                    new_pos = self._scanner().get_target()
                    self.sigScannerTargetChanged.emit(new_pos, self.module_uuid)
                    return new_pos

                new_pos[ax] = ax_constr[ax].clip_value(pos)
                if pos != new_pos[ax]:
                    self.log.warning('Scanner position target value out of bounds for axis "{0}". '
                                     'Clipping value to {1:.3e}.'.format(ax, new_pos[ax]))

            new_pos = self._scanner().move_absolute(new_pos, blocking=move_blocking)
            if any(pos != new_pos[ax] for ax, pos in pos_dict.items()):
                caller_id = None
            #self.log.debug(f"Logic set target with id {caller_id} to new: {new_pos}")
            self.sigScannerTargetChanged.emit(
                new_pos,
                self.module_uuid if caller_id is None else caller_id
            )
            return new_pos

    def toggle_scan(self, start, scan_axes, caller_id=None):
        self._toggled_scan_axes = scan_axes
        with self._thread_lock:
            if start:
                # if self._repeated == 0:
                #     self.display_repeated = 0
                return self.start_scan(self._toggled_scan_axes, caller_id)
            return self.stop_scan()

    def start_scan(self, scan_axes, caller_id=None):
        self._curr_caller_id = self.module_uuid if caller_id is None else caller_id
        self.display_repeated = self._repeated
        
        with self._thread_lock:

            if self.module_state() != 'idle':
                self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)
                return 0

            scan_axes = tuple(scan_axes)
            

            self.module_state.lock()

            settings = {'axes': scan_axes,
                        'range': tuple(self._scan_ranges[ax] for ax in scan_axes),
                        'resolution': tuple(self._scan_resolution[ax] for ax in scan_axes),
                        'frequency': self._scan_frequency[scan_axes[0]],
                        'lines_to_scan': self._number_of_repeats}
            fail, new_settings = self._scanner().configure_scan(settings)
            if fail:
                self.module_state.unlock()
                self.stop_scan() 
                self.sigScanStateChanged.emit(False, None, self._curr_caller_id)
                return -1

       
            self._update_scan_settings(scan_axes, new_settings)
            

            # Calculate poll time to check for scan completion. Use line scan time estimate.
            line_points = self._scan_resolution[scan_axes[0]] if len(scan_axes) > 1 else 1
            # self.__scan_poll_interval = max(self._min_poll_interval,
            #                                 line_points / self._scan_frequency[scan_axes[0]])
            self.__scan_poll_timer.setInterval(int(round(self._scan_poll_interval)))# * 1000)))
            
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
            self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)

            if self.module_state() == 'idle':
                self.sigScanStateChanged.emit(False, self.scan_data, self._curr_caller_id)
                return 0
            
            self.__stop_timer()

            err = self._scanner().stop_scan() if self._scanner().module_state() != 'idle' else 0

            self.module_state.unlock()
        
            # if self.scan_settings['save_to_history']:
            #     # module_uuid signals data-ready to data logic
            #     self.sigScanStateChanged.emit(False, self.scan_data, self.module_uuid)
            # else:
            self.sigScanStateChanged.emit(False, self.scan_data, self._curr_caller_id)

            return err

    def reset_accumulated(self):
        self.accumulated = None
        #if self.scan_data is not None:
        #    self.scan_data._accumulated = None
    
    def _update_scan_settings(self, scan_axes, settings):
        for ax_index, ax in enumerate(scan_axes):
            # Update scan ranges if needed
            new = tuple(settings['range'][ax_index])
            if self._scan_ranges[ax] != new:
                self._scan_ranges[ax] = new
                self.sigScanSettingsChanged.emit({'range': {ax: self._scan_ranges[ax]}})

            # Update scan resolution if needed
            new = int(settings['resolution'][ax_index])
            if self._scan_resolution[ax] != new:
                self._scan_resolution[ax] = new
                self.sigScanSettingsChanged.emit(
                    {'resolution': {ax: self._scan_resolution[ax]}}
                )

        # Update scan frequency if needed
        new = float(settings['frequency'])
        if self._scan_frequency[scan_axes[0]] != new:
            self._scan_frequency[scan_axes[0]] = new
            self.sigScanSettingsChanged.emit({'frequency': {scan_axes[0]: new}})

    @QtCore.Slot()
    def __scan_poll_loop(self):
        with self._thread_lock:
            try:
                if self.module_state() == 'idle':
                    return
                # if self._scanner().
                # lines_to_scan = self._number_of_repeats
                if self._scanner().module_state() == 'idle':
                    
                    self.stop_scan()
                    
                    if (self._curr_caller_id == self._scan_id) or (self._curr_caller_id == self.module_uuid):
                        self._repeated += 1
                        self.display_repeated += 1
                        
                        self.stack_data()
                        
                        if (self._number_of_repeats > self._repeated 
                            or self._number_of_repeats == 0):
                            self.sigRepeatScan.emit(True, self._toggled_scan_axes) 
                        elif not hasattr(self._scanner(), "_triggered_ao") and self._repeated == 1:
                            self.sigScanningDone.emit()
                            self.sigRepeatScan.emit(False, self._toggled_scan_axes)
                            self._repeated = 0 
                        else:
                            # if self._scanner()._scanned_lines > self._scanner().lines_to_scan or self._number_of_repeats == 0:
                            self.sigScanningDone.emit()
                            self.sigRepeatScan.emit(False, self._toggled_scan_axes)
                            self._repeated = 0 
                    return
                # TODO Added the following line as a quick test; Maybe look at it with more caution if correct
                # self._scanner().sigNextDataChunk.emit()
                self.sigScanStateChanged.emit(True, self.scan_data, self._curr_caller_id)

                # Queue next call to this slot
                self.__scan_poll_timer.start()
            except TimeoutError:
                self.log.exception('Timed out while waiting for scan data:')
            except:
                self.log.exception('An exception was raised while polling the scan:')
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