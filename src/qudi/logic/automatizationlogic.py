"""
Example config:

    automatization_logic:
        module.Class: 'automatizationlogic.Automatedmeasurements'
        connect:
            spectrometergui: 'spectrometer'
            optimizerlogic: 'scanning_optimize_logic'
            spectrometerlogic: 'spectrometerlogic'
            poimanagerlogic: 'poi_manager_logic'
            switchlogic: 'switchlogic'

"""
from qtpy import QtCore
import inspect
import time
import numpy as np
import os
from qudi.core.module import LogicBase
from qudi.core.connector import Connector

class Automatedmeasurements(LogicBase):
    # TODO: Fix error if device is missing.
    #   If you don't have and don't need a spectrometer, the script still wants to connect to one because we define a connector here.
    #   It would be nice if we could catch this and just print a notice that the device is not connected.
    #   For now I am just commenting out the connectors in question.
    ## declare connectors
    spectrometergui = Connector(name='spectrometergui', interface='SpectrometerGui', optional=True) # TODO: talk to logic and not hardware
    optimizerlogic = Connector(name='optimizerlogic', interface='ScanningOptimizeLogic')
    spectrometerlogic = Connector(name='spectrometerlogic',interface='SpectrometerLogic', optional=True)
    poimanagerlogic = Connector(name='poimanagerlogic',interface='PoiManagerLogic')
    switchlogic = Connector(name='switchlogic',interface='SwitchLogic', optional=True)
    scanningprobelogic = Connector(name='scanningprobelogic',interface='ScanningProbeLogic')
    ple_gui = Connector(name='ple_gui', interface= 'PLEScanGui', optional = True)
    powercontroller_logic = Connector(name='power_controller', interface='PowerControllerLogic', optional=True)
    laser_controller = Connector(name='laser_controller', interface= 'LaserControllerLogic', optional=True)
    wavemeter = Connector(name='wavemeter', interface='HighFinesseWavemeter', optional=True)

    power_steps = []
    etalon_voltages = []
    # internal signals
    sigNextPoi = QtCore.Signal()
    sigNextStep = QtCore.Signal()
    sigStartPle = QtCore.Signal()
    # external signals
    sigSaveSpectrum = QtCore.Signal()
    sigSwitchStatus = QtCore.Signal(str,str) # switch, state


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # dictionary of functions
        self.func_dict = {
            'move' : self.move_to_poi,
            'optimize' : self.optimize_on_poi,
            'spectrum' : self.take_spectrum,
            'blue_on' : self.turn_on_blue_laser,
            'blue_off' : self.turn_off_blue_laser,
            'ple_saturation' : self.ple_saturation
        }

        ## init variables
        self.abort = False
        self.steps = []
        self.debug = False # prints for debugging

        self.power_steps = [10, 43, 56, 60, 70, 80]
        self.etalon_voltages = [-9, -8, -7]

        # init variables that tell teh script if certain measurement was started here
        # (to make sure we don't catch signals when we don't want to)
        self._optimizer_started = False
        self._spectrum_started = False
        self._ple_started = False
        self._stop_after_step_done = False
        self._blue_is_on = None # status of blue laser (True: blue laser shines on sample, False: it does not)

        return


    def on_activate(self):
        """properly activates the module.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')

        # connectors
        self._optimizer_logic = self.optimizerlogic()
        self._poimanager_logic = self.poimanagerlogic()
        self._scanning_probe_logic = self.scanningprobelogic()
        if self.wavemeter():
            self._wavemeter = self.wavemeter()
        if self.powercontroller_logic():
            self._powercontroller_logic = self.powercontroller_logic()
        if self.laser_controller():
            self._laser_controller = self.laser_controller()
        if self.ple_gui():
            self._ple_gui = self.ple_gui()
            self._ple_gui._scanning_logic.sigScanningDone.connect(self._ple_done,  QtCore.Qt.QueuedConnection)
            self.sigStartPle.connect(self.start_ple,  QtCore.Qt.QueuedConnection)
            self._ple_gui_connected = True
        # optional conecctors
        if self.spectrometergui():
            self._spectrometer_gui = self.spectrometergui()
            self._spectrometergui_connected = True
        else:
            self._spectrometergui_connected = False
            print('spectrometergui was not connected.')
        if self.spectrometerlogic():
            self._spectrometer_logic = self.spectrometerlogic()
            self._spectrometerlogic_connected = True
        else:
            self._spectrometerlogic_connected = False
            print('spectrometerlogic was not connected.')
        if self.switchlogic():
            self._switch_logic = self.switchlogic()
            self._switchlogic_connected = True
        else:
            self._switchlogic_connected = False
            print('switchlogic was not connected.')
        
        # connect internal signals
        self.sigNextPoi.connect(self._next_poi, QtCore.Qt.QueuedConnection)
        self.sigNextStep.connect(self._next_step, QtCore.Qt.QueuedConnection )

        # connect external signals
        self._optimizer_logic.sigOptimizeDone.connect(self._optimization_done, QtCore.Qt.QueuedConnection)
        if self._spectrometerlogic_connected:
            self._spectrometer_logic.sigSpectrumDone.connect(self._spectrum_done)
        if self._spectrometergui_connected:
            self.sigSaveSpectrum.connect(self._spectrometer_gui.save_spectrum, QtCore.Qt.QueuedConnection)
        if self._switchlogic_connected:
            self.sigSwitchStatus.connect(self._switch_logic.set_state, QtCore.Qt.QueuedConnection)


    def on_deactivate(self):
        """Properly deactivates the module.
        """
        pass


    def start(self, steps, shift=None):
        """Starts the measurement series on all pois.

        @param list steps: list of the steps (as string) that wil be performed.

        @param array shift: Shift between the position of the defects on the scan and the actual position of the defects.
            actual_position = scan_position + shift
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')

        # initialize pois and steps
        self.init_pois(shift)
        self.init_steps(steps)
        
        self.abort = False
        self.sigNextPoi.emit()
        return

    def stop(self):
        """Stops the measurement series.
        
        Finishes the current measurement and then stops.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self.abort = True
        return


    def init_pois(self,shift=None):
        """initializes the pois.
        
        Get the name and position of the pois. Stores it in list.

        @param array shift: Shift between the position of the defects on the scan and the actual position of the defects.
            actual_position = scan_position + shift
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        # get poin maes from poimanagerlogic and store them as class objects
        self.poi_names = self._poimanager_logic.poi_names
        # copy poi names in array that we can modify (shallow copy)
        self._poi_names = self.poi_names.copy()
        # get positions of the pois (dict)
        poi_positions = self._poimanager_logic.poi_positions
        # shift them if a shift was given
        if shift != None:
            for key in poi_positions.keys():
                # add shift to position
                poi_positions[key] = poi_positions[key] + shift
        # store poi positions as class object
        self.poi_positions = poi_positions
        return


    def init_steps(self, steps):
        """Stores the individual steps (measurements) for the POIs as class objects.

        @param list steps: list of the individual step names (as str).
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        keys = self.func_dict.keys()
        if not set(steps).issubset(set(keys)):
            raise Exception(f'The following steps are not listed in the func_dict: {list(set(steps) - set(keys))}. \nKeeping old steps.')
        self.steps = steps
        return


    def _next_poi(self):
        """Iterates through the pois.
        
        Sets the next poi to be the active one and starts the measurements on this one.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        # Stop program if finished or user wants to stop
        if self.abort or (len(self._poi_names)==0):
            if self.debug:
                print(f'Stopping pois. Abort was set to {self.abort} and {len(self._poi_names)} pois were left.')
            self.abort = True
            self._optimizer_started = False
            self._spectrum_started = False
            self._ple_started = False
            return
        # Choose the first poi in the list, set it as the current one and delete it.
        self._current_poi_name = self._poi_names.pop(0)
        if self.debug:
            print('Current poi %s'%self._current_poi_name)
        # updates the position of the current poi
        self._current_poi_position = self.poi_positions[self._current_poi_name]
        
        # copy the steps into an array that we can modify (shallow copy)
        self._steps = self.steps.copy()
        if self.debug:
            print(f'Steps are {self._steps}.')
        # start the steps
        self.sigNextStep.emit()
        return


    def _next_step(self):
        """Iterates through the steps.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        # Stop the program if user wants to stop.
        if self.abort:
            if self.debug:
                print('Stopping steps.')
            return
        if len(self._steps) == 0:
            # all steps for the current poi are done, go to next poi
            if self.debug:
                print('All steps are done, moving to next poi.')
            self.sigNextPoi.emit()
            return
        # choose next step in list as current one and remove it
        self._current_step = self._steps.pop(0)
        if self.debug:
            print(f'Current step: {self._current_step}.')
        #run the step
        self.func_dict[self._current_step]()
        return

    def move_to_poi(self, poi_name=None):
        """Moves the focus to the poi.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, poi_name {poi_name}')
        if poi_name==None:
            poi_name = self._current_poi_name
        # go to poi
        self._poimanager_logic.go_to_poi(name=poi_name)
        # poimanager does not send signal once point is reached. 
        # We will wait for a bit and send a signal ourselves..


        # We calculate the time by assuming our start- and endposition are within the scanned area.
        if self._poimanager_logic._max_move_velocity == None:
            sleep_time = 5
        else:
            x_range = self._poimanager_logic.roi_scan_image_extent[0]
            y_range = self._poimanager_logic.roi_scan_image_extent[1]
            dx = x_range[1] - x_range[0]
            dy = y_range[1] - y_range[0]
            worst_case_distance = (dx**2 + dy**2)**0.5
            sleep_time = 2 * worst_case_distance/self._poimanager_logic._max_move_velocity + 0.1
        time.sleep(sleep_time)
        self.sigNextStep.emit()
        return


    def optimize_on_poi(self):
        """optimizes on the poi.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        self._optimizer_started = True
        self._position_before_optimize = self._scanning_probe_logic.scanner_position
        self._repeated_optimize = False
        self._optimizer_logic.start_optimize()
        return


    def _optimization_done(self):
        """Catches the signal from the optimizerlocig that the optimization is done.

        Only does something if self._optimizer_started was set to True by the logic.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, _optimizer_started = {self._optimizer_started}')
        if self._optimizer_started == True:
            # make sure we only do sth with the signal if we initialized the measurement
            self._optimizer_started = False
            
            optimal_posi = np.array([self._optimizer_logic.optimal_position['x'], self._optimizer_logic.optimal_position['y'], self._optimizer_logic.optimal_position['z']])
            
            position_before_optimize = np.array([self._position_before_optimize['x'],self._position_before_optimize['y'],self._position_before_optimize['z']])
          
            deviation_from_old_posi = optimal_posi - position_before_optimize
            
            if self._deviation_within_limits(deviation_from_old_posi,[None,None,200e-9]):
                # if defect is closse enough to poi position continue wit this defect
              
                if self.debug:
                    print('Result of fit is within limits.')
                self.sigNextStep.emit()
                return
            else:
                # result of optimization is too far off from starting point
                if self.debug:
                    print('Result of fit is too far off.')
                if not self._repeated_optimize:
                    # if fit failed for the first time, move backt o old posi and optimize once again
                    if self.debug:
                        print('Trying optimize from previous position once again.') # TODO: somwhoe after this we stop
                    self._repeated_optimize = True
                    self._scanning_probe_logic.set_target_position(self._position_before_optimize)
                    time.sleep(0.1)
                    self._optimizer_started = True
                    self._optimizer_logic.start_optimize()
                    return
                else:
                    # if fit failed once before, go to next poi
                    if self.debug:
                        print('Skipping current poi and going to next one.')
                    self.sigNextPoi.emit()
                    return
        else:
         
            return


    def _deviation_within_limits(self,deviations,limits=[None,None,None]):
        """Checks if the deviaton is bigger than a set limit.
        
        If None is given as a limit, the dimension is ignored.

        @return bool: True if within limits, falsse if not.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        for i in range(len(deviations)):
            limit = limits[i]
            deviation = deviations[i]
            if limit != None:
                if abs(deviation) > limit:
                    return False
        return True


    def take_spectrum(self):
        """Tells the spectrumlogic to start taking the spectrum.

        Following settings are used:
        No constant acquisition, background correction, no differential spectrum, automatic flip
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        if not self._spectrometerlogic_connected:
            raise Exception('spectrometerlogic not connected.')
        if not self._spectrometer_logic.acquisition_running:
            self._spectrum_started = True
            # set parameters
            self._spectrometer_logic.background_correction = True
            self._spectrometer_logic.constant_acquisition = False
            self._spectrometer_logic.differential_spectrum = False
            self._spectrometer_logic.do_flip = True
            # acquire the spectrum
            self._spectrometer_logic._sig_get_spectrum.emit(False,False,True) # constant_acquisition, differential_spectrum, reset
            return
        else:
            raise Exception('spectrum acquisition already running.')


    def _spectrum_done(self):
        """Catches the signal from the spectrometerlogic that the spectrum is taken and saves the spectrum.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, _spectrum_started = {self._spectrum_started}')
        if self._spectrum_started:
            name_tag = f'defect-name-{self._current_poi_name}_blue-on-{self._blue_is_on}'
            self.save_spectrum(name_tag)
            self._spectrum_started = False
            self.sigNextStep.emit()
        else:
            return

    
    def save_spectrum(self,name_tag=None):
        """Saves the acquired spectrum.

        You need to have the gui for the spectrometer active and set all the parameters (apart from the nametag).
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, name = {name_tag}')
        if not self._spectrometergui_connected:
            raise Exception('spectrometergui not connected.')
        # This is really ugly but also the fastest way to make it work
        # set parameters in gui
        self._spectrometer_gui.save_widget.saveTagLineEdit.setText(name_tag)
        # hit save
        self.sigSaveSpectrum.emit()
        return

    def start_ple(self):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        if self._ple_gui is None:
            raise Exception('ple module is not connected.')
        self.power, self.eta = self.saturation_parameters[0]
        self._wavemeter._wavelength_buffer = []
        self._laser_controller.etalon_voltage = self.eta
        self._powercontroller_logic.motor_position = self.power
    
        #self._ple_started = True
        self._ple_gui._mw.actionToggle_scan.setChecked(True)
        self._ple_gui.toggle_scan()
        #self._ple_gui._mw.actionToggle_scan.triggered.emit()
        
        return
        

    def _ple_done(self):
        """Catches the signal
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, _ple_started = {self._ple_started}')
        if True:#self._ple_started:
            name_tag = f'defect-name-{self._current_poi_name}_power-{self.power}_eta_{self.eta}'
            self.save_ple(name_tag)
            np.savetxt(os.path.join(self._ple_gui._save_folderpath,f"{name_tag}_wavelength.csv"), self._wavemeter._wavelength_buffer)
            #self._ple_started = False
            self.saturation_parameters = np.delete(self.saturation_parameters, 0, axis=0)
#
            if len(self.saturation_parameters) < 1:
                self.ple_saturation_done()
            else:
                self.start_ple()
                #self.sigStartPle.emit()
        else:
            return

    def ple_saturation_done(self):
        if self._stop_after_step_done:
            return 
        self.sigNextStep.emit()
        #self._ple_started = False

    def ple_saturation(self, poi_name=None, power_steps = None, etalon_voltages = None):
        if poi_name is not None:
            self._current_poi_name = poi_name
            self._stop_after_step_done = True
        if power_steps is not None:
            self.power_steps = power_steps
            self._stop_after_step_done = True
        if etalon_voltages is not None:
            self.etalon_voltages = etalon_voltages
            self._stop_after_step_done = True
        #scan 20 line
        #Set programmatically number of repetitions
        #self._ple_gui._mw.number_of_repeats_SpinBox.setValue(self.)
        #self._ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
        

        self.saturation_parameters = np.transpose([np.tile(self.power_steps, len(self.etalon_voltages)), np.repeat(self.etalon_voltages, len(self.power_steps))])

        self.start_ple()


    def save_ple(self, name_tag=None):
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}, name = {name_tag}')

        self._ple_gui.save_path_widget.saveTagLineEdit.setText(name_tag)
        
        self._ple_gui._mw.action_Save.triggered.emit()
        return

    def turn_on_blue_laser(self):
        """Turns on the blue laser.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        if not self._switchlogic_connected:
            raise Exception('switchlogic not connected.')
        self._blue_is_on = True
        self.sigSwitchStatus.emit('Laser405nm', 'On')
        # the mirror needs time to move.
        # Also if you send the electrical signals to the mirror to soon after the previous one, it gets confused.
        time.sleep(0.5) 
        self.sigNextStep.emit()
        return


    def turn_off_blue_laser(self):
        """Turns off the blue laser.
        """
        if self.debug:
            print(f'{__name__}, {inspect.stack()[0][3]}')
        if not self._switchlogic_connected:
            raise Exception('switchlogic not connected.')
        self._blue_is_on = False
        self.sigSwitchStatus.emit('Laser405nm', 'Off')
        time.sleep(0.5)
        self.sigNextStep.emit()
        return