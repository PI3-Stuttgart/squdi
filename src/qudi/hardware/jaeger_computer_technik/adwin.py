# -*- coding: utf-8 -*-

"""
This file contains the Qudi Hardware module NICard class.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""
import time
import numpy as np
import re
from qtpy import QtCore
from core.module import Base
from core.configoption import ConfigOption
from interface.slow_counter_interface import SlowCounterConstraints
from interface.slow_counter_interface import CountingMode
from interface.confocal_scanner_interface import ConfocalScannerInterface
import ADwin
import os
import ctypes

processes_path = os.path.join(os.path.dirname(__file__), 'processes')

class adwin(Base, ConfocalScannerInterface):

    ########################## I dont know :-) ##################################
    # signals to interfuse
    # this signl gets passed from layer to layer until it reaches the gui.
    sigLimitsChanged = QtCore.Signal()

    # config options
    _photon_sources = ConfigOption('photon_sources', list(), missing='warn')

    # confocal settings.
    _clock_channel = ConfigOption('clock_channel', missing='error')

    _default_clock_frequency = ConfigOption('default_clock_frequency', 100, missing='info')
    _counter_channels = ConfigOption('counter_channels', missing='error')
    _counter_ai_channels = ConfigOption('counter_ai_channels', list(), missing='info')
    _counter_voltage_range = ConfigOption('counter_voltage_range', [-10, 10], missing='info')

    # confocal scanner
    _default_scanner_clock_frequency = ConfigOption('default_scanner_clock_frequency', 100, missing='info')
    _scanner_clock_channel = ConfigOption('scanner_clock_channel', missing='warn')
    _pixel_clock_channel = ConfigOption('pixel_clock_channel', None) # trigger for TT to run.
    _scanner_ao_channels = ConfigOption('scanner_ao_channels', missing='error')
    _scanner_ai_channels = ConfigOption('scanner_ai_channels', list(), missing='info')
    _scanner_counter_channels = ConfigOption('scanner_counter_channels', list(), missing='warn')
    _scanner_voltage_ranges = ConfigOption('scanner_voltage_ranges', missing='error')
    _scanner_position_ranges = ConfigOption('scanner_position_ranges', missing='error')

    # odmr
    #_odmr_trigger_channel = ConfigOption('odmr_trigger_channel', missing='error')
    #_odmr_trigger_line = ConfigOption('odmr_trigger_line', 'Dev1/port0/line0', missing='warn')
    #_odmr_switch_line = ConfigOption('odmr_switch_line', 'Dev1/port0/line1', missing='warn')

    _gate_in_channel = ConfigOption('gate_in_channel', missing='error')
    # number of readout samples, mainly used for gated counter
    _default_samples_number = ConfigOption('default_samples_number', 50, missing='info')
    # used as a default for expected maximum counts
    _max_counts = ConfigOption('max_counts', default=3e7)
    # timeout for the Read or/and write process in s
    _RWTimeout = ConfigOption('read_write_timeout', default=10)
    _counting_edge_rising = ConfigOption('counting_edge_rising', default=True)

    ######################### new code #####################################################

    def on_activate(self):
        """ Starts up the NI Card at activation.
        """
        # the tasks used on that hardware device:

        self.boot_adwin()
        self.load_processes()
        self._counter_daq_tasks = list()
        self._counter_analog_daq_task = None
        self._clock_daq_task = None
        self._scanner_clock_daq_task = None
        self._scanner_ao_task = None
        self._scanner_counter_daq_tasks = list()
        self._line_length = None
        self._odmr_length = None
        self._gated_counter_daq_task = None
        self._scanner_analog_daq_task = None
        self._odmr_pulser_daq_task = None
        self._oversampling = 0
        self._lock_in_active = False

        self._photon_sources = self._photon_sources if self._photon_sources is not None else list()
        self._scanner_counter_channels = self._scanner_counter_channels if self._scanner_counter_channels is not None else list()
        self._scanner_ai_channels = self._scanner_ai_channels if self._scanner_ai_channels is not None else list()

        # handle all the parameters given by the config
        self._current_position = np.zeros(len(self._scanner_ao_channels))

        if len(self._scanner_ao_channels) < len(self._scanner_voltage_ranges):
            self.log.error(
                'Specify at least as many scanner_voltage_ranges as scanner_ao_channels!')

        if len(self._scanner_ao_channels) < len(self._scanner_position_ranges):
            self.log.error(
                'Specify at least as many scanner_position_ranges as scanner_ao_channels!')

        if len(self._scanner_counter_channels) + len(self._scanner_ai_channels) < 1:
            self.log.error(
                'Specify at least one counter or analog input channel for the scanner!')

        # Analog output is always needed and it does not interfere with the
        # rest, so start it always and leave it running
        if self._start_analog_output() < 0:
            self.log.error('Failed to start analog output.')
            raise Exception('Failed to start NI Card module due to analog output failure.')

    def load_processes(self):
        self.adw.Load_Process(os.path.join(processes_path, "sweeping_1D.TB1"))
        self.adw.Load_Process(os.path.join(processes_path, "control_green.TB2"))
        self.adw.Load_Process(os.path.join(processes_path, "set_channel_out.TB3"))


    def boot_adwin(self):
            self.adw = ADwin.ADwin(0x1, 1)
            self.BTL = self.adw.ADwindir + "adwin" + "11" + ".btl"
            self.adw.Boot(self.BTL)

    def stop_all(self):
        for i in range(1, 4):
            self.adw.Stop_Process(i)

    def check_stautus(self, process):
        self.pro = self.adw.Process_Status(process)
        while self.pro == 1:
            self.pro = self.adw.Process_Status(process)
            time.sleep(0.2)


    def turn_on_laser(self, green, blue):
        self.conlist = []
        if green == True:
            self.conlist.append(1.0)
        elif green == False:
            self.conlist.append(0.0)
        else:
            raise Exception('No Laser with this color')
        if blue == True:
            self.conlist.append(1.0)
        elif blue == False:
            self.conlist.append(0.0)
        else:
            raise Exception('No Laser with this color')
        self.adw.SetData_Float(self.conlist, 5, 1, 2)
        self.stop_all()
        self.adw.Start_Process(2)


    def close_scanner(self):
        self.stop_all()
        return 0

    def scanner_set_position(self, x, y, z, a):
        self._current_position[0] = x #m
        self._current_position[1] = y #m
        self._current_position[2] = z #
        self.adw.Set_Par(11, x)
        self.adw.Set_Par(12, y)
        self.adw.Set_Par(13, z)
        self.adw.Set_Par(14, a)
        self.stop_all()
        self.adw.Start_Process(3)

    def scan_line(self, line_path=None, pixel_clock=False):
        self._line_length= len(line_path[0])
        self.adw.SetData_Float(line_path[0], 1, 1, len(line_path[0]))
        self.adw.SetData_Float(line_path[1], 2, 1, len(line_path[1]))
        self.adw.SetData_Float(line_path[2], 3, 1, len(line_path[2]))
        self.adw.SetData_Float(line_path[3], 4, 1, len(line_path[3]))

        if pixel_clock==False:
            self.adw.Set_Par(22, 0)
            self.adw.Set_Par(21, len(line_path[0])+1)
            self.adw.Set_Par(20, 100)
            self.adw.Start_Process(1)


        elif pixel_clock==True:
            self.adw.Set_Par(22, 1)
            self.adw.Set_Par(21, len(line_path[0]) + 3)
            self.adw.Set_Par(20, int(1/self.clock_frequency*100000000))
            self.adw.Start_Process(1)
            self.check_stautus(1)

        self._current_position = np.array(line_path[:, -1])
        return 0


        '''
        self._line_length = 100
        
        self._scan_data = np.empty(
            (len(self.get_scanner_count_channels()), 2 * self._line_length),
            dtype=np.uint32)

        
        self._real_data = np.empty(
            (len(self._scanner_counter_channels), self._line_length),
            dtype=np.uint32)

        # add up adjoint pixels to also get the counts from the low time of
        # the clock:
        self._real_data = self._scan_data[:, ::2]
        self._real_data += self._scan_data[:, 1::2]

        all_data = np.full(
                (len(self.get_scanner_count_channels()), self._line_length), 2, dtype=np.float64)
        all_data[0:len(self._real_data)] = np.array(
                self._real_data, np.float64)

        if self._scanner_ai_channels:
            all_data[len(self._scanner_counter_channels):] = self._analog_data[:, :-1]

            # update the scanner position instance variable
        self._current_position = np.array(line_path[:, -1])

        return all_data.transpose()
        '''


    def close_scanner_clock(self, power=0):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return self.close_clock(scanner=True)


    def close_clock(self, scanner=False):
        """ Closes the clock and cleans up afterwards.

        @param bool scanner: specifies if the counter- or scanner- function
                             should be used to close the device.
                                True = scanner
                                False = counter

        @return int: error code (0:OK, -1:error)
        """

        return 0

    def get_position_range(self, myrange=None):

        """ Returns the physical range of the scanner.

        @return float [4][2]: array of 4 ranges with an array containing lower
                              and upper limit. The unit of the scan range is
                              meters.
        """
        return self._scanner_position_ranges

    #def get_scanner_count_channels(self):

    def set_position_range(self, myrange=None):
        if myrange is None:
            myrange = [[0., 1e-6], [0., 1e-6], [0., 1e-6], [0., 1e-6]]

        if not isinstance(myrange, (frozenset, list, set, tuple, np.ndarray, )):
            self.log.error('Given range is no array type.')
            return -1

        if len(myrange) != 4:
            self.log.error(
                'Given range should have dimension 4, but has {0:d} instead.'
                ''.format(len(myrange)))
            return -1

        for pos in myrange:
            if len(pos) != 2:
                self.log.error(
                    'Given range limit {1:d} should have dimension 2, but has {0:d} instead.'
                    ''.format(len(pos), pos))
                return -1
            if pos[0]>pos[1]:
                self.log.error(
                    'Given range limit {0:d} has the wrong order.'.format(pos))
                return -1

        self._scanner_position_ranges = myrange
        return 0

    def get_scanner_position(self):

        return self._current_position.tolist()

    def reset_hardware(self):
        self.stop_all()
        self.boot_adwin()
        return 1

    def set_up_scanner(self,
                       counter_channels=None,
                       sources=None,
                       clock_channel=None,
                       scanner_ao_channels=None):
        return 1

    def get_scanner_count_channels(self):
        """ Return list of counter channels """
        ch = self._scanner_counter_channels[:]
        ch.extend(self._scanner_ai_channels)
        return ch


    def set_voltage_range(self, myrange=None):
        return 1

    def on_deactivate(self):
        """ Shut down the ADWIN card.
        """
        self.close_scanner()
        #TODO think about cleaning the tasks if they will be.
        self.reset_hardware()

    def get_scanner_axes(self):
        """ Scanner axes depends on how many channels tha analog output task has.
        """
        if self._scanner_ao_task is None:
            self.log.error('Cannot get channel number, analog output task does not exist.')
            return []

        #n_channels = daq.uInt32()
        #daq.DAQmxGetTaskNumChans(self._scanner_ao_task, n_channels)
        possible_channels = ['x', 'y', 'z', 'a']

        return possible_channels[0:2]


    def set_voltage_limits(self, RTLT):
        """Changes voltage limits."""
        n_ch = len(self.get_scanner_axes())
        if RTLT == 'LT':
            # changes limits
            self.set_voltage_range(myrange=[[0, 10], [0, 10], [0, 10], [0, 10]][0:n_ch])
            # resets the analog output. This reloads the new limits
            self._start_analog_output()
            # update scanner position range to LT
            self.set_position_range(self._scanner_position_ranges_lt)
        elif RTLT == 'RT':
            self.set_voltage_range(myrange=[[0, 4], [0, 4], [0, 4], [0, 10]][0:n_ch])
            self._start_analog_output()
            # update scanner position range to RT
            self.set_position_range(self._scanner_position_ranges_rt)
        else:
            print('Limit needs to be either LT or RT')
            return
        # signal to gui (via rest of the layers).
        # this provokes an update of the axes.
        self.sigLimitsChanged.emit()


    def _start_analog_output(self):
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)
        """
        try:
            print('todo') #FIXME. make the old output when you start.
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0

    '''
    
    #### Done see on_activate
    
    def on_activate(self):
        """ Starts up the NI Card at activation.
        """
        # the tasks used on that hardware device:
        self._counter_daq_tasks = list()
        self._counter_analog_daq_task = None
        self._clock_daq_task = None
        self._scanner_clock_daq_task = None
        self._scanner_ao_task = None
        self._scanner_counter_daq_tasks = list()
        self._line_length = None
        self._odmr_length = None
        self._gated_counter_daq_task = None
        self._scanner_analog_daq_task = None
        self._odmr_pulser_daq_task = None
        self._oversampling = 0
        self._lock_in_active = False

        self._photon_sources = self._photon_sources if self._photon_sources is not None else list()
        self._scanner_counter_channels = self._scanner_counter_channels if self._scanner_counter_channels is not None else list()
        self._scanner_ai_channels = self._scanner_ai_channels if self._scanner_ai_channels is not None else list()

        # handle all the parameters given by the config
        self._current_position = np.zeros(len(self._scanner_ao_channels))

        if len(self._scanner_ao_channels) < len(self._scanner_voltage_ranges):
            self.log.error(
                'Specify at least as many scanner_voltage_ranges as scanner_ao_channels!')

        if len(self._scanner_ao_channels) < len(self._scanner_position_ranges):
            self.log.error(
                'Specify at least as many scanner_position_ranges as scanner_ao_channels!')

        if len(self._scanner_counter_channels) + len(self._scanner_ai_channels) < 1:
            self.log.error(
                'Specify at least one counter or analog input channel for the scanner!')

        # Analog output is always needed and it does not interfere with the
        # rest, so start it always and leave it running
        if self._start_analog_output() < 0:
            self.log.error('Failed to start analog output.')
            raise Exception('Failed to start NI Card module due to analog output failure.')

    '''

    '''
    
    ###### Done see turn_off_confocal
    
    def on_deactivate(self):
        """ Shut down the ADWIN card.
        """
        self._stop_analog_output()
        #TODO think about cleaning the tasks if they will be.
        self.reset_hardware()
    '''
    # =================== SlowCounterInterface Commands ========================

    '''

    ###### No Idea yet

    def get_constraints(self):
        """ Get hardware limits of NI device.

        @return SlowCounterConstraints: constraints class for slow counter

        FIXME: ask hardware for limits when module is loaded
        """
        constraints = SlowCounterConstraints()
        constraints.max_detectors = 4
        constraints.min_count_frequency = 1e-3
        constraints.max_count_frequency = 10e9
        constraints.counting_mode = [CountingMode.CONTINUOUS]
        return constraints

    '''


    
    #### Already in linesweep 
    
    def set_up_clock(self, clock_frequency=None, clock_channel=None, scanner=False, idle=False):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of
                                      the clock in Hz
        @param string clock_channel: if defined, this is the physical channel
                                     of the clock within the NI card.
        @param bool scanner: if set to True method will set up a clock function
                             for the scanner, otherwise a clock function for a
                             counter will be set.
        @param bool idle: set whether idle situation of the counter (where
                          counter is doing nothing) is defined as
                                True  = 'Voltage High/Rising Edge'
                                False = 'Voltage Low/Falling Edge'

        @return int: error code (0:OK, -1:error)
        """
        self.clock_frequency = clock_frequency
        return 0


    '''
    
    #### counting is done by TimeTagger
    
    def set_up_counter(self,
                       counter_channels=None,
                       sources=None,
                       clock_channel=None,
                       counter_buffer=None):
        """ Configures the actual counter with a given clock.

        @param list(str) counter_channels: optional, physical channel of the counter
        @param list(str) sources: optional, physical channel where the photons
                                  are to count from
        @param str clock_channel: optional, specifies the clock channel for the
                                  counter
        @param int counter_buffer: optional, a buffer of specified integer
                                   length, where in each bin the count numbers
                                   are saved.

        @return int: error code (0:OK, -1:error)
        """

        return 0
    '''


    '''
    
    ##### counter is done by TimeTagger
    
    def get_counter_channels(self):
        """ Returns the list of counter channel names.

        @return tuple(str): channel names

        Most methods calling this might just care about the number of channels, though.
        """
        ch = self._counter_channels[:]
        ch.extend(self._counter_ai_channels)
        return ch

    def get_counter(self, samples=None):
        """ Returns the current counts per second of the counter.

        @param int samples: if defined, number of samples to read in one go.
                            How many samples are read per readout cycle. The
                            readout frequency was defined in the counter setup.
                            That sets also the length of the readout array.

        @return float [samples]: array with entries as photon counts per second
        """

        return 0

    def close_counter(self, scanner=False):
        """ Closes the counter or scanner and cleans up afterwards.

        @param bool scanner: specifies if the counter- or scanner- function
                             will be excecuted to close the device.
                                True = scanner
                                False = counter

        @return int: error code (0:OK, -1:error)
        """
        error = 0

        return error
    
    '''

    '''
    ### clock deactivates automaticly after linesweep
    
    def close_clock(self, scanner=False):
        """ Closes the clock and cleans up afterwards.

        @param bool scanner: specifies if the counter- or scanner- function
                             should be used to close the device.
                                True = scanner
                                False = counter

        @return int: error code (0:OK, -1:error)
        """

        return 0

    
    '''
    # ================ End SlowCounterInterface Commands =======================

    # ================ ConfocalScannerInterface Commands =======================
    '''
    
    ##### Done see turn_off_confocal
    
    def reset_hardware(self):
        """ Resets the adwin ch 1-4 , dont touch the magnet controls!

        @return int: error code (0:OK, -1:error)
        """
        retval = 0
        return retval

    '''


    '''
    
    ##### Counting is done by TimeTagger
    
    def get_scanner_count_channels(self):
        """ Return list of counter channels """
        return 1
    '''

    '''
    
    #### Position range is set in linesweep max position is set at -5 and 5
    
    def get_position_range(self):
        """ Returns the physical range of the scanner.

        @return float [4][2]: array of 4 ranges with an array containing lower
                              and upper limit. The unit of the scan range is
                              meters.
        """
        return self._scanner_position_ranges

    def set_position_range(self, myrange=None):
        """ Sets the physical range of the scanner.

        @param float [4][2] myrange: array of 4 ranges with an array containing
                                     lower and upper limit. The unit of the
                                     scan range is meters.

        @return int: error code (0:OK, -1:error)
        """
        if myrange is None:
            myrange = [[0, 1e-6], [0, 1e-6], [0, 1e-6], [0, 1e-6]]

        if not isinstance(myrange, (frozenset, list, set, tuple, np.ndarray, )):
            self.log.error('Given range is no array type.')
            return -1

        if len(myrange) != 4:
            self.log.error(
                'Given range should have dimension 4, but has {0:d} instead.'
                ''.format(len(myrange)))
            return -1

        for pos in myrange:
            if len(pos) != 2:
                self.log.error(
                    'Given range limit {1:d} should have dimension 2, but has {0:d} instead.'
                    ''.format(len(pos), pos))
                return -1
            if pos[0]>pos[1]:
                self.log.error(
                    'Given range limit {0:d} has the wrong order.'.format(pos))
                return -1

        self._scanner_position_ranges = myrange
        return 0

    '''


    '''
    
    #### voltage range == position range for now
    
    def set_voltage_range(self, myrange=None):
        """ Sets the voltage range of the NI Card.

        @param float [n][2] myrange: array containing lower and upper limit

        @return int: error code (0:OK, -1:error)
        """
        n_ch = len(self.get_scanner_axes())
        if myrange is None:
            myrange = [[-10., 10.], [-10., 10.], [-10., 10.], [-10., 10.]][0:n_ch]

        if not isinstance(myrange, (frozenset, list, set, tuple, np.ndarray)):
            self.log.error('Given range is no array type.')
            return -1

        if len(myrange) != n_ch:
            self.log.error(
                'Given range should have dimension 2, but has {0:d} instead.'
                ''.format(len(myrange)))
            return -1

        for r in myrange:
            if r[0] > r[1]:
                self.log.error('Given range limit {0:d} has the wrong order.'.format(r))
                return -1

        self._scanner_voltage_ranges = myrange
        return 0
    
    '''
    '''
    
    #### restart and start/ stop output is done by turn_off_confocal()
    
    def _start_analog_output(self):
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)
        """
        try:
            set_position_adwin(x,y,z) #FIXME.
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0

    def _stop_analog_output(self):
        """ Stops the analog output.

        @return int: error code (0:OK, -1:error)
        """
        retval = 0
        #TODO repeating from reset hardware.
        return retval

    '''

    
    def set_up_scanner_clock(self, clock_frequency=None, clock_channel=None):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of
                                      the clock
        @param string clock_channel: if defined, this is the physical channel
                                     of the clock

        @return int: error code (0:OK, -1:error)
        """
        # The clock for the scanner is created on the same principle as it is
        # for the counter. Just to keep consistency, this function is a wrapper
        # around the set_up_clock.
        return self.set_up_clock(
            clock_frequency=clock_frequency,
            clock_channel=clock_channel,
            scanner=True)


    '''
    
    ###### Is done by linesweep
    
    def set_up_scanner(self,
                       counter_channels=None,
                       sources=None,
                       clock_channel=None,
                       scanner_ao_channels=None):
        """ Configures the actual scanner with a given clock.

        The scanner works pretty much like the counter. Here you connect a
        created clock with a counting task. That can be seen as a gated
        counting, where the counts where sampled by the underlying clock.

        @param list(str) counter_channels: this is the physical channel of the counter
        @param list(str) sources:  this is the physical channel where the photons are to count from
        @param string clock_channel: optional, if defined, this specifies the clock for the counter
        @param list(str) scanner_ao_channels: optional, if defined, this specifies
                                           the analog output channels

        @return int: error code (0:OK, -1:error)
        """
        retval = 0


        return retval
    '''
    '''
    
    ###### Done by set_scanner_position
    
    def scanner_set_position(self, x=None, y=None, z=None, a=None):
        """ Move stage to x, y, z, a (where a is the fourth channel).

        @param float x: position in x-direction (in axis unit)
        @param float y: position in y-direction (in axis unit)
        @param float z: position in z-direction (in axis unit)
        @param float a: position in a-direction (in axis unit)

        @return int: error code (0:OK, -1:error)
        """
        #TOTO repeated from start analog output?

        if self.module_state() == 'locked':
            #self.log.error('Another scan_line is already running, close this one first.')
            #return -1
            print("error overridden in hardware.national_instuments_x_series.py") #This makes it possible to change the cross on the confocal while still scanning the PLE channel

        if x is not None:
            if not(self._scanner_position_ranges[0][0] <= x <= self._scanner_position_ranges[0][1]):
                self.log.error('You want to set x out of range: {0:f}.'.format(x))
                return -1
            self._current_position[0] = np.float(x)

        if y is not None:
            if not(self._scanner_position_ranges[1][0] <= y <= self._scanner_position_ranges[1][1]):
                self.log.error('You want to set y out of range: {0:f}.'.format(y))
                return -1
            self._current_position[1] = np.float(y)

        if z is not None:
            if not(self._scanner_position_ranges[2][0] <= z <= self._scanner_position_ranges[2][1]):
                self.log.error('You want to set z out of range: {0:f}.'.format(z))
                return -1
            self._current_position[2] = np.float(z)

        if a is not None:
            if not(self._scanner_position_ranges[3][0] <= a <= self._scanner_position_ranges[3][1]):
                self.log.error('You want to set a out of range: {0:f}.'.format(a))
                return -1
            self._current_position[3] = np.float(a)

        # the position has to be a vstack
        my_position = np.vstack(self._current_position)

        # then directly write the position to the hardware
        try:
            set_scanner_position(my_position)
        except:
            return -1
        return 0

    def _write_scanner_ao(self, voltages, length=1, start=False):
        """Writes a set of voltages to the analog outputs.

        @param float[][n] voltages: array of n-part tuples defining the voltage
                                    points
        @param int length: number of tuples to write
        @param bool start: write imediately (True)
                           or wait for start of task (False)

        n depends on how many channels are configured for analog output
        """
        # Number of samples which were actually written, will be stored here.
        # The error code of this variable can be asked with .value to check
        # whether all channels have been written successfully.

        return 0
    '''



    '''
    ###########################
    To Do
    ###########################
    

    def _scanner_position_to_volt(self, positions=None):
        """ Converts a set of position pixels to acutal voltages.

        @param float[][n] positions: array of n-part tuples defining the pixels

        @return float[][n]: array of n-part tuples of corresponing voltages

        The positions is typically a matrix like
            [[x_values], [y_values], [z_values], [a_values]]
            but x, xy, xyz and xyza are allowed formats.
        """

        if not isinstance(positions, (frozenset, list, set, tuple, np.ndarray, )):
            self.log.error('Given position list is no array type.')
            return np.array([np.NaN])

        vlist = []
        for i, position in enumerate(positions):
            vlist.append(
                (self._scanner_voltage_ranges[i][1] - self._scanner_voltage_ranges[i][0])
                / (self._scanner_position_ranges[i][1] - self._scanner_position_ranges[i][0])
                * (position - self._scanner_position_ranges[i][0])
                + self._scanner_voltage_ranges[i][0]
            )
        volts = np.vstack(vlist)

        for i, v in enumerate(volts):
            if v.min() < self._scanner_voltage_ranges[i][0] or v.max() > self._scanner_voltage_ranges[i][1]:
                self.log.error(
                    'Voltages ({0}, {1}) exceed the limit, the positions have to '
                    'be adjusted to stay in the given range.'.format(v.min(), v.max()))
                return np.array([np.NaN])
        return volts

    def get_scanner_position(self):
        """ Get the current position of the scanner hardware.

        @return float[]: current position in (x, y, z, a).
        """
        return self._current_position.tolist()

    '''

    '''
    #### done by scan_line

    def _set_up_line(self, length=100):
        """ Sets up the analog output for scanning a line.
        """
        return 0

    def scan_line(self, line_path=None, pixel_clock=False):
        """ Scans a line and return the counts on that line.

        @param float[c][m] line_path: array of c-tuples defining the voltage points
            (m = samples per line)
        @param bool pixel_clock: whether we need to output a pixel clock for this line

        @return float[m][n]: m (samples per line) n-channel photon counts per second

        The input array looks for a xy scan of 5x5 points at the position z=-2
        like the following:
            [ [1, 2, 3, 4, 5], [1, 1, 1, 1, 1], [-2, -2, -2, -2] ]
        n is the number of scanner axes, which can vary. Typical values are 2 for galvo scanners,
        3 for xyz scanners and 4 for xyz scanners with a special function on the a axis.
        """
        status = confocal_sweep_1D(*params)
        return status
    '''


    '''
    
    ############ done by  turn_off_confocal
    
    def close_scanner(self):
        """ Closes the scanner and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return 0

    def close_scanner_clock(self):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return self.close_clock(scanner=True)

    '''

    # ================ End ConfocalScannerInterface Commands ===================


    '''
    
    ####### limits are set to -5 to 5V

    def set_voltage_limits(self, RTLT):
        """Changes voltage limits."""
        n_ch = len(self.get_scanner_axes())
        if RTLT == 'LT':
            # changes limits
            self.set_voltage_range(myrange=[[0, 10], [0, 10], [0, 10], [0, 10]][0:n_ch])
            # resets the analog output. This reloads the new limits
            self._start_analog_output()
            # update scanner position range to LT
            self.set_position_range(self._scanner_position_ranges_lt)
        elif RTLT == 'RT':
            self.set_voltage_range(myrange=[[0, 4], [0, 4], [0, 4], [0, 10]][0:n_ch])
            self._start_analog_output()
            # update scanner position range to RT
            self.set_position_range(self._scanner_position_ranges_rt)
        else:
            print('Limit needs to be either LT or RT')
            return
        # signal to gui (via rest of the layers).
        # this provokes an update of the axes.
        self.sigLimitsChanged.emit()
    # ======================== Digital channel control ==========================

    def digital_channel_switch(self, channel_name, mode=True):
        """
        Switches on or off the voltage output (5V) of one of the digital channels, that
        can as an example be used to switch on or off the AOM driver or apply a single
        trigger for ODMR.
        @param str channel_name: Name of the channel which should be controlled
                                    for example ('/Dev1/PFI9')
        @param bool mode: specifies if the voltage output of the chosen channel should be turned on or off

        @return int: error code (0:OK, -1:error)
        """
        if channel_name is None:
            self.log.error('No channel for digital output specified')
            return -1
        else:
            switch_laser_on(channel_name)
            return 0
    '''

