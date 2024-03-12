# -*- coding: utf-8 -*-
"""
This file contains a qudi logic module template

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

from ast import Raise
from email.policy import default
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.configoption import ConfigOption
from qudi.logic.pulsed.pulse_objects import PulseBlockElement, PulseBlock, PulseBlockEnsemble
from qudi.logic.pulsed.sampling_functions import SamplingFunctions
from PySide2 import QtCore
import numpy as np
from qudi.core.statusvariable import StatusVar
from qudi.util.delay import delay
import time

class RepumpInterfuseLogic(LogicBase):
    sigGuiParamsUpdated = QtCore.Signal(object,  QtCore.Qt.QueuedConnection)
    sigTimingPlotUpdated = QtCore.Signal(object,  QtCore.Qt.QueuedConnection)
    _pulsed = Connector(name='pulsed', interface='PulsedMasterLogic')
    _switchlogic = Connector(name='switchlogic', interface="SwitchLogic", optional=True) 
    _switch_name = ConfigOption(name='switcher_name', default=None)
    _resonant_laser = ConfigOption(name='resonant_laser', default=None)
    _repump_laser = ConfigOption(name='repump_laser', default=None)

    ensembles = []
    trigger_channel = 'd_ch6'

    default_params = {
        "resonant":
            {   
                "length" : 30e-9,
                "period" : 150e-9
            },
        "repump":
            {   
                "length" : 30e-9,
                "delay"  : 150e-9,
                "repeat"  : 0
            }
        }
    parameters = StatusVar(name="parameters", default=default_params)
    test = StatusVar(name="test", default=0)
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.repump_scan_length = 200 #msec
    
    def on_activate(self):
        self.pulsed = self._pulsed()
        self.switch = self._switchlogic()
        self.do_prescan_repump = False
        #self.create_pulse_block(channels = list(self._resonant_lasers.values()))
        self.a_ch = {
        'a_ch1': SamplingFunctions.Idle(),
        'a_ch2': SamplingFunctions.Idle()
        }
        self.d_ch = {
        'd_ch1': False, 
        'd_ch2': False, 
        'd_ch3': False, 
        'd_ch4': False,
        'd_ch5': False,
        'd_ch6': False,
        'd_ch7': False,
        'd_ch8': False,
        }
        
    def on_deactivate(self):
        pass

    def start_pulsed(self, enabled, ensemble_name):
        self.pulsed.sigSampleBlockEnsemble.emit(ensemble_name)
        self.pulsed.sigLoadBlockEnsemble.emit(ensemble_name) 
        self.pulsed.sigPulserRunningUpdated.emit(enabled)    
    
    @QtCore.Slot(dict)
    def pulser_updated(self, params):
        self.parameters['resonant'].update(params['resonant'])
        self.parameters['repump'].update(params['repump'])

        self.check_period()

        self.pulsed.sigPulserRunningUpdated.emit(False) 
        self.construct_pulsed()

        self.construct_timing_diagram()

    def check_period(self):
        new_period = self.parameters['resonant']['length'] + self.parameters['repump']['delay'] + self.parameters['repump']['length']
        
        if new_period > self.parameters['resonant']['period']:
            self.parameters['resonant']['period'] = new_period
        self.sigGuiParamsUpdated.emit(self.parameters)

    def construct_pulsed(self):
        self.construct_resonant_and_repump_ensemble()
        self.pulsed.sigSampleBlockEnsemble.emit('resonant_repump_ensemble')
        self.pulsed.sigLoadBlockEnsemble.emit('resonant_repump_ensemble') 
        self.pulsed.sigPulserRunningUpdated.emit(True) 
        return

    def _construct_resonant_repump_off_block(self):
        element_list = []

        d_ch = self.d_ch.copy()
        d_ch.update({self._resonant_laser: True}) 
        resonant_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['resonant']['length'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch, 
            laser_on=False
        )
        element_list.append(resonant_pulse_block)

        # now the delay until the repump
        d_ch = self.d_ch.copy()
        delay_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['repump']['delay'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch, 
            laser_on=False
        )
        element_list.append(delay_pulse_block)

        #now repump length
        d_ch = self.d_ch.copy() 
        repump_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['repump']['length'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch,
            laser_on=False
        )
        element_list.append(repump_pulse_block)
        #now the nothing till the priod ends
        d_ch = self.d_ch.copy()
        time_off = self.parameters['resonant']['period'] - self.parameters['resonant']['length'] - self.parameters['repump']['delay'] - self.parameters["repump"]['length']
        if time_off < 0 :
            raise ValueError('Period is too short') 
        off_pulse_block = PulseBlockElement(
            init_length_s = time_off, 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch,  
            laser_on=False
        )
        element_list.append(off_pulse_block)

        pulse_block = PulseBlock(name='resonant_repump_off', element_list=element_list)
        self.pulsed.sigSavePulseBlock.emit(pulse_block)
        return pulse_block

    def _construct_resonant_repump_on_block(self):
        element_list = []

        d_ch = self.d_ch.copy()
        d_ch.update({self._resonant_laser: True}) 
        resonant_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['resonant']['length'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch, 
            laser_on=False
        )
        element_list.append(resonant_pulse_block)

        # now the delay until the repump
        d_ch = self.d_ch.copy()
        delay_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['repump']['delay'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch, 
            laser_on=False
        )
        element_list.append(delay_pulse_block)

        #now repump length
        d_ch = self.d_ch.copy() 
        d_ch.update({self._repump_laser: True}) 
        repump_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['repump']['length'], 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch,
            laser_on=False
        )
        element_list.append(repump_pulse_block)
        #now the nothing till the priod ends
        d_ch = self.d_ch.copy()
        time_off = self.parameters['resonant']['period'] - self.parameters['resonant']['length'] - self.parameters['repump']['delay'] - self.parameters["repump"]['length']
        if time_off < 0 :
            raise ValueError('Period is too short') 
        off_pulse_block = PulseBlockElement(
            init_length_s = time_off, 
            increment_s=0, 
            pulse_function=self.a_ch, 
            digital_high=d_ch,  
            laser_on=False
        )
        element_list.append(off_pulse_block)

        pulse_block = PulseBlock(name='resonant_repump_on', element_list=element_list)
        self.pulsed.sigSavePulseBlock.emit(pulse_block)
        return pulse_block
    
    def cw_repump_on(self, enable):
        element_list = []

        d_ch = self.d_ch.copy() 
        d_ch.update({self._repump_laser: True}) 
        repump_pulse_block = PulseBlockElement(
            init_length_s=self.parameters['repump']['length'], 
            increment_s=0, 
            # pulse_function=self.a_ch, 
            digital_high=d_ch,
            laser_on=False
        )
        element_list.append(repump_pulse_block)
        pulse_block = PulseBlock(name='repump_on', element_list=element_list)
        self.pulsed.sigSavePulseBlock.emit(pulse_block)
        block_list = [(pulse_block.name, 0)]
        block_ensemble = PulseBlockEnsemble(name='repump_on', block_list=block_list, rotating_frame=False)
        self.pulsed.sigSaveBlockEnsemble.emit(block_ensemble)

        self.pulsed.sigSampleBlockEnsemble.emit('repump_on')
        self.pulsed.sigLoadBlockEnsemble.emit('repump_on') 

        self.start_pulsed(enable, 'repump_on')
    

    def construct_resonant_and_repump_ensemble(self):
        repeat_every = self.parameters['repump']['repeat']

        repump_on = self._construct_resonant_repump_on_block()
        repump_off = self._construct_resonant_repump_off_block()
        if repeat_every == 0:
            block_list = [(repump_on.name, 0)]
        else:
            block_list = [(repump_off.name, repeat_every-1), (repump_on.name, 0)]

        block_ensemble = PulseBlockEnsemble(name='resonant_repump_ensemble', block_list=block_list, rotating_frame=False)
        self.pulsed.sigSaveBlockEnsemble.emit(block_ensemble)
    
    def construct_timing_diagram(self):
        sample = self.pulsed.sequencegeneratorlogic().analyze_block_ensemble('resonant_repump_ensemble')
        length_s = self.parameters['resonant']['period']
        self.timing_diagram = {}
        xrange = np.linspace(0, length_s, sample['number_of_samples']+1)
        for i in self.pulsed.digital_channels:
            rising = sample['digital_rising_bins'][i]
            falling = sample['digital_falling_bins'][i]
            y = np.zeros_like(xrange)
            if len(rising)==len(falling):
                for j in range(len(rising)):
                    y[rising[j]:falling[j]] = 0.3
            self.timing_diagram[i] = (xrange, y)
        self.timing_diagram['resonant'] = self._resonant_laser
        self.timing_diagram['repump'] = self._repump_laser
        
        self.sigTimingPlotUpdated.emit(self.timing_diagram)

    def repump_before_scan(self):
        if self.do_prescan_repump:
            if self.switch is None:
                return 
           
            self.switch.set_state(self._switch_name, 'On')
            time.sleep(self.repump_scan_length/1000)
            #delay(msec = self.repump_scan_length)
            self.switch.set_state(self._switch_name, 'Off')
            
        