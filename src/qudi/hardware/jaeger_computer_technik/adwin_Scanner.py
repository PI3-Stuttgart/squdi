from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.anolog_and_digital_io import AnalogAndDigitalIO 
from qudi.interface.finite_sampling_io_interface import FiniteSamplingIOInterface, FiniteSamplingIOConstraints
from qudi.hardware.jaeger_computer_technik.adwin_base import AdwinBase
import os
import numpy as np
from qudi.interface.scanning_probe_interface import ScanningProbeInterface, ScanData
from qudi.interface.scanning_probe_interface import ScanConstraints, ScannerAxis, ScannerChannel
import ADwin
processes_path = os.path.join(os.path.dirname(__file__), 'processes')

"""funciton which has to be implelemnted
    
    {'get_constraints_done', 'reset_done', 'configure_scan_done', 'get_scan_data', 
    'move_absolute_done', 'get_position_done', 'get_target',
    'emergency_stop', 'stop_scan_done', 'move_relative_TODO', 'start_scan_done'}

    Returns:
        _type_: _description_
"""

class Adwin_Scanning_Device(AdwinBase, ScanningProbeInterface):  # ScanningProbeInterface, in principle. Should it also be inhertied  to comply with a scanning device.
    '''
    Legacy of adwin_old confocal part
    '''
    _analog_outputs = ConfigOption(name='channels', missing='warn')
    _digital_outputs = ConfigOption(name='clock', missing='warn')
    ao_min_rate = 1#Hz
    ao_max_rate = 10e3 #conservative #10 MHz?
    ci_max_timebase = 5e7 #50 MHz clock, oder?
    scanner_processes = []
    
    def on_activate(self):
        print('I am here... Activate Adwin Galvo scanner .....')
        self.boot_adwin()
        self._current_position = np.array([0,0,0])# TODO
        #TODO put here some real command, to run the processes.
        self.adwin.Load_Process(os.path.join(processes_path, "sweeping_1D.TB1"))
        #self.adwin.Load_Process(os.path.join(processes_path, "set_channel_out.TB3")) #what is set channel out
        #self.adw.Load_Process(os.path.join(processes_path, "control_digout.TB0"))
        #self.adw.Load_Process(os.path.join(processes_path, "laser_attenuation.TB5"))
        #self.start_adwin_processes(['control_analog_out.TB9'])  
        #self.start_adwin_processes(['control_digout.TB0'])
        self.start_adwin_processes(['sweeping_1D.TB1'])
        
        # TODO
        self._constraints = 'None'
        # FiniteSamplingIOConstraints(
        #     supported_output_modes=(SamplingOutputMode.JUMP_LIST, SamplingOutputMode.EQUIDISTANT_SWEEP),
        #     input_channel_units=self._input_channel_units,
        #     output_channel_units=self._output_channel_units,
        #     frame_size_limits=self._frame_size_limits,
        #     sample_rate_limits=sample_rate_limits,
        #     output_channel_limits=output_voltage_ranges,
        #     input_channel_limits=input_limits
        # )
    def on_deactivate(self):
        """Stops all adwin process needed for the script
        """
        self.stop_all()
        #TODO think about cleaning the tasks if they will be.
        self.reset()
    
    def get_constraints(self):
        return self._constraints
    
    def move_relative(self, distance, velocity = None, blocking = False):
        pass #TODO
    
    def emergency_stop(self):
        self.stop_scan()
    
    def stop_scan(self):
        self.stop_all()
    
    def stop_all(self): ##This is stops only confocal channels.
        for i in range(1, 4): #TODO adjust only for confocal processes to stop. 
            self.adwin.Stop_Process(i)
        return 0#FIXME achtung, try self.check_stautus(process = 3) for more robust work. #FIXME is it?
        
    #this was before set_current_position or so.
    def move_absolute(self, position, velocity = None, blocking = False): #is it move_absolute?
        
        self._current_position = position  
        x = position[0]
        y = position[1]
        z = position[2]      
        #self._current_position[0] = x #m
        #self._current_position[1] = y #m
        #self._current_position[2] = z #
        self.adwin.Set_Par(11, x)
        self.adwin.Set_Par(12, y)
        self.adwin.Set_Par(13, z)
        #self.adw.Set_Par(14, a) #This is the PLE? (at least it was in the old code.)
        self.stop_all()
        self.adwin.Start_Process(10)
    
    def close_scanner(self):
        self.stop_all()
        return 0
    
    def check_stautus(self, process):
        self.pro = self.adwin.Process_Status(process)
        while self.pro == 1:
            self.pro = self.adwin.Process_Status(process)
            time.sleep(0.2)
        
    
    def start_scan(self):
        """former scan line function, its arguments are moved to configure_scan.

        Args:
            line_path (_type_, optional): _description_. Defaults to None.
            pixel_clock (bool, optional): _description_. Defaults to False.

        Returns:
            _type_: _description_
        """
        self._line_length= len(line_path[0])
        self.adwin.SetData_Float(line_path[0], 1, 1, len(line_path[0]))
        self.adwin.SetData_Float(line_path[1], 2, 1, len(line_path[1]))
        self.adwin.SetData_Float(line_path[2], 3, 1, len(line_path[2]))
        self.adwin.SetData_Float(line_path[3], 4, 1, len(line_path[3]))

        if pixel_clock==False:
            self.adwin.Set_Par(22, 0)
            self.adwin.Set_Par(21, len(line_path[0]))
            self.adwin.Set_Par(20, 100)
            self.adwin.Start_Process(1)


        elif pixel_clock==True:
            self.adwin.Set_Par(22, 1)
            self.adwin.Set_Par(21, len(line_path[0])+3)
            self.adwin.Set_Par(20, int(1/self.clock_frequency*100000000)) ##WEIRD!!!!
            self.adwin.Start_Process(1)
            self.check_stautus(1)

        self._current_position = np.array(line_path[:, -1])
        return 0

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

    def get_position(self):

        return self._current_position.tolist()

    def reset(self): ##SHOULDNT IT BE IN ADWIN BASE?
        self.stop_all()
        self.boot_adwin()
        return 1

    def configure_scan(self,  line_path=None, pixel_clock=False, # should be combined in scansettings
                       counter_channels=None,
                       sources=None,
                       clock_channel=None,
                       scanner_ao_channels=None):
        self.scan_settings = line_path
        return 1

    def get_scanner_count_channels(self):
        """ Return list of counter channels """
        ch = self._scanner_counter_channels[:]
        ch.extend(self._scanner_ai_channels)
        return ch

    def set_voltage_range(self, myrange=None):
        return 1
    

    def get_scanner_axes(self):
        """ Scanner axes depends on how many channels tha analog output task has.
        """
        #n_channels = daq.uInt32()
        #daq.DAQmxGetTaskNumChans(self._scanner_ao_task, n_channels)
        possible_channels = ['x', 'y', 'z']

        return possible_channels[0:2]


    def set_voltage_limits(self, RTLT):
        """Changes voltage limits."""
        
        """makes no sense except the Z scanner probably has to be changed.
        """
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


    def _start_analog_output(self): #THIS BELONDS TO OTHER THINDS"!!!! (e.g. ADWIN IO, or MAGNET.)
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)
        """
        try:
            print('todo') #FIXME. make the old output when you start.
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0
    
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


    def get_target(self):
        print('I have no idea')
        
    def get_scan_data(self):
        print('not yet')
        return None
    