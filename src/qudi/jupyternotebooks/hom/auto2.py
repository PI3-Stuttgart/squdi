from functools import partial, wraps
import time
import os
from datetime import datetime
import numpy as np
import copy
from PySide2.QtCore import QTimer, QTime, Signal
from scipy.interpolate import splrep, splev
from scipy.optimize import curve_fit

def lorentzian(x, x0, gamma, a, bg):
    return bg + a * (gamma**2 / ((x - x0)**2 + gamma**2))

def find_max_spline(x_data, y_data):
        """
        Finds the maximum value and its corresponding x value using spline interpolation.

        Args:
            x_data: Array of x values (positions).
            y_data: Array of y values (counts).

        Returns:
            Tuple of (max_value, max_x)
        """
        # Create spline representation
        tck = splrep(x_data, y_data, s=0)  # Adjust s as needed
        # Find the range of x values for interpolation
        x_interp = np.linspace(x_data.min(), x_data.max(), num=1000)
        # Interpolate y values
        y_interp = splev(x_interp, tck)
        # Find the index of the maximum interpolated y value
        max_index = np.argmax(y_interp)
        # Return the maximum value and its corresponding x value
        return y_interp[max_index], x_interp[max_index]

def find_lorentzian_center(setpoints, counts):
    # Initial guess for the Lorentzian parameters: [x0, gamma, a]
    initial_guess = [setpoints[np.argmax(counts)], 0.1, np.max(counts), 5]
    # Fit the data to a Lorentzian function
    popt, _ = curve_fit(lorentzian, setpoints, counts, p0=initial_guess)
    # popt contains the optimized parameters [x0, gamma, a]
    x0 = popt[0]
    return x0
 

class MeasurementsBase:

    cts_refocus = []
    min_position = 50
    max_position = 210
    max_power = 40e3 #max out the power 
    perpendicular_position = 19
    parallel_position = 30
    refocused_cts = None
    _polarization_is_parallel = None


    def __init__(self, 
                 timetaggerlogic=None, 
                 timetagger=None, 
                 timetagger_remote=None,
                 timetaggerlogic_remote = None,
                 poi_manager_logic_remote=None,
                 poi_manager_logic=None,
                 powercontroller_logic=None,
                 pulsestreamer = None,
                 ibeam_smart_remote=None,
                 ple_gui=None,
                 laser_scanner_logic=None,
                 scanner_gui=None, 
                 scanning_data_logic=None,
                 switchlogic=None,
                 folder_save=None,
                
                 *args, **kwargs) -> None:
        #WARNING IF NONE!
        
        self.timetaggerlogic = timetaggerlogic
        self.timetaggerlogic_remote = timetaggerlogic_remote
        self.timetagger = timetagger
        self.timetagger_remote = timetagger_remote
        self.poi_manager_logic_remote = poi_manager_logic_remote
        self.poi_manager_logic = poi_manager_logic
        self.switchlogic = switchlogic
        self.ibeam_smart_remote = ibeam_smart_remote
        self.ple_gui = ple_gui
        self.laser_scanner_logic = laser_scanner_logic
        self.scanner_gui = scanner_gui
        self.scanning_data_logic = scanning_data_logic
        self.powercontroller_logic = powercontroller_logic
        self.pulsestreamer = pulsestreamer
        self.folder_save = folder_save
        self.folder_save_papa = folder_save
        self.start_time = datetime.now()
        self.folder_interval = 20 #folder_interval_minutes  # Set the folder saving interval in minutes


        self.powercontroller_logic._current_motor = 0
        self.powercontroller_logic.motor_position = self.perpendicular_position
        self._polarization_is_parallel = False

    def get_counts(self, channels=[2,3]):
        cts = []
        for channel in channels:
            if channel in self.timetaggerlogic.trace_data_avg.keys():
                cc = self.timetaggerlogic.trace_data_avg[channel][1][-5:].mean()
                cts.append(float(cc))
        
        return np.array(cts)

    def get_remote_counts(self, channels=[1]):
        cts = []
        for channel in channels:
            cc = self.timetaggerlogic_remote.trace_data_avg[channel][1][-5:].mean()
            cts.append(float(cc))
        return np.array(cts)

    def refocus(self, optimize_both = False):
        
        self.polarization_is_parallel = False

        time.sleep(1)
        self.poi_manager_logic_remote._optimizelogic().start_optimize()
        if optimize_both:
            self.poi_manager_logic._optimizelogic().start_optimize()
            while self.poi_manager_logic._optimizelogic().module_state()=='locked':
                time.sleep(1) # wait for a long time to 
        while self.poi_manager_logic_remote._optimizelogic().module_state()=='locked':
            time.sleep(1) # wait for a long time to 
        time.sleep(1) # wait for a long time to avoid conflicts with the countrate checker
        self.polarization_is_parallel = True
        time.sleep(1)
        tot_cts = self.get_counts(channels=[2,3]).mean()
        self.refocused_cts = tot_cts

    @property
    def polarization_is_parallel(self):
        return self._polarization_is_parallel
    
    @polarization_is_parallel.setter
    def polarization_is_parallel(self, is_parallel):
        if is_parallel:
            self.powercontroller_logic._current_motor = 0
            self.powercontroller_logic.motor_position = self.parallel_position # parallel pol
            self._polarization_is_parallel = True
        else:
            self.powercontroller_logic._current_motor = 0
            self.powercontroller_logic.motor_position = self.perpendicular_position # parallel pol
            self._polarization_is_parallel = False

    def toggle_tagger_counter_plot(self, state):
        # start/ stop the counter measurement
        self.timetagger._mw.toggleCounterPushButton.setChecked(state)
        self.timetagger._mw.toggleCounterPushButton.toggled.emit(state)
        
    def toggle_tagger_corr_plot(self, state):
        # start/ stop the counter measurement
        self.timetagger._mw.toggleCorrPushButton.setChecked(state)
        self.timetagger._mw.toggleCorrPushButton.toggled.emit(state)

    def save_tagger_plots(self, tag,  folder_path=None):
        if folder_path is None:
            folder_path = self.timed_folder

        self.timetagger._save_folderpath = folder_path
        self.timetagger._mw.currPathLabel.setText(folder_path)
        self.timetagger._mw.saveTagLineEdit.setText(tag)     
        self.timetagger._mw.counter_checkBox.setChecked(True)
        self.timetagger._save_data_clicked()
        self.timetagger._mw.corr_checkBox.setChecked(True)
        self.timetagger._save_data_clicked()

    def set_green_power(self, cryo, value):
        power_max = self.max_power
        power_min = 0
        if cryo == 'bf':
            # Ensure power is within bounds
            value = max(power_min, min(value, power_max))
            # Map power to the motor position range
            motor_position = self.min_position + (self.max_position - self.min_position) * (value - power_min) / (power_max - power_min)
            self.powercontroller_logic._current_motor = 2
            self.powercontroller_logic.motor_position = motor_position
            
        elif cryo == 'atto3':
            self.ibeam_smart_remote.power = value

    def start_dump(self, folder, tag):
        pth = os.path.join(folder, str(tag))
        os.makedirs(pth, exist_ok = True)
        self.timetagger._mw.saveDumpTagLineEdit.setText(tag)
        self.timetagger._save_dump_folderpath = pth
        self.timetagger._mw.currDumpPathLabel.setText(self.timetagger._save_dump_folderpath)
        
        self.timetagger._mw.dump_checkBox.setChecked(True)
        self.timetagger._dump_toggled()

    def stop_dump(self):
        self.timetagger._mw.dump_checkBox.setChecked(False)
        self.timetagger._dump_toggled()

    def measurement_mode(self, mode, greens_on=True):
        if mode == "PLE":
            if self.switchlogic.get_state("Mirror") != 'On':
                self.switchlogic.set_state(switch = "Mirror", state = "On")
            time.sleep(1)
            if self.switchlogic.get_state("Mirror") == 'On':
                if self.switchlogic.get_state("Shutter") != 'Off':
                    self.switchlogic.set_state(switch = "Shutter", state = "Off")
                time.sleep(0.5)
                if self.switchlogic.get_state("ResonantBF") != 'On':
                    self.switchlogic.set_state(switch = "ResonantBF", state = "On")
                self.ibeam_smart_remote.power = 50
                self.powercontroller_logic._current_motor = 2
                self.powercontroller_logic.motor_position = self.min_position # green dim
                time.sleep(0.5)
            else:
                print("Mirror not in, PLE would burn APDs")
                raise BaseException
        elif mode == "Off-res":
            if self.switchlogic.get_state("ResonantBF") != 'Off':
                    self.switchlogic.set_state(switch = "ResonantBF", state = "Off")
            if self.switchlogic.get_state("Shutter") != 'On':
                self.switchlogic.set_state(switch = "Shutter", state = "On")
            time.sleep(1)
            if self.switchlogic.get_state("Mirror") != 'Off':
                self.switchlogic.set_state(switch = "Mirror", state = "Off")
            if greens_on:
                self.ibeam_smart_remote.power = self.max_power
                self.powercontroller_logic._current_motor = 2
                self.powercontroller_logic.motor_position = self.max_position # MAX green
        else:
            print("No mode by this name")

    def do_ple_scan(self, lines = 1, in_range = None, frequency=None, resolution=None, channel = None):
        """
        fine_scan_range = (
                self.ple_gui.fit_result[1].best_values['center']
                - self.ple_gui.fit_result[1].best_values['sigma'] * 3,
                self.ple_gui.fit_result[1].best_values['center']
                + self.ple_gui.fit_result[1].best_values['sigma']  * 3
            )
        """
        if channel is not None:
            self.ple_gui._mw.channel_comboBox.setCurrentText(channel) ## MAY BE MISTAKEN
            # ple_gui._mw.channel_comboBox.setCurrentText('APD4')
        #laser_scanner_logic.scan_ranges["a"]
        if in_range is None:
            self.ple_gui._mw.actionFull_range.triggered.emit()
        else:
            self.ple_gui.sigScanSettingsChanged.emit(
                {
                'range': {self.ple_gui.scan_axis: in_range}
                }
            )
        self.ple_gui._mw.number_of_repeats_SpinBox.setValue(lines)
        self.ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
        time.sleep(0.5)
        self.ple_gui._mw.actionToggle_scan.setChecked(True)
        self.ple_gui.toggle_scan()
        while self.laser_scanner_logic.module_state()=='locked':
                time.sleep(1)
        time.sleep(1)
        self.ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("Lorentzian")
        time.sleep(1)
        # self.ple_gui._accumulated_data.mean(axis=0)
        # print(f"Rsquared {self.ple_gui.fit_result[1].rsquared}")
        # self.ple_gui.fit_result[1].params["center"].value
        return self.ple_gui.fit_result[1]
    
    def PLE_check_trigger(self, enable=True):
        # pulsestreamer._seq.setDigital(1, [(1000, 1)])
        self.pulsestreamer._seq.setDigital(5, [(10000000, 0), (10, int(enable))])
        
        self.pulsestreamer.pulser_on()
    
        #from 0 to 19650 MHz (max val defined by config) laser offset 
    def go_to_ple_target(self, target):
        self.ple_gui._mw.ple_widget.target_point.setValue(target)
        self.ple_gui._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
        #laser_scanner_logic.set_target_position({"a": target})
        time.sleep(0.5)

    #save confocal map. It will be saved in the folder defined in the app
    def save_scan(self, name):
        self.scanner_gui.save_path_widget.saveTagLineEdit.setText(name)
        self.scanner_gui.scan_2d_dockwidgets[('x', 'y')].scan_widget.save_scan_button.clicked.emit() #saving
        dir_ = self.scanning_data_logic.module_default_data_dir
        return name, dir_

    def save_ple(self, tag, poi_name=None, folder_name = None):
            if folder_name:
                self.ple_gui._save_folderpath = folder_name
                self.ple_gui.save_path_widget.currPathLabel.setText(self.ple_gui._save_folderpath)
            self.ple_gui.save_path_widget.saveTagLineEdit.setText(
                f"{poi_name}_{tag}"
                )
            self.ple_gui._mw.actionSave.triggered.emit()

class StarkHOM(MeasurementsBase):
    def __init__(self, ao_electrodes,
                 *args, **kwargs) -> None:
        super().__init__(
            *args, **kwargs
        )
        self.ao_electrodes = ao_electrodes
        ao_electrodes._constraints._channel_limits = {'ao3': [-1.38, 1.38]}
        
        self.to_refocus_ple = False
        self._refocus_both = False
        self._setpoint_offset = 0
        self._reference_power = 40e3
        self.bf_needs_refocus = False
        self._measurement_done = False
        self.counts_calibration = dict()
        self.zpl_calibration = dict()
        self._bf_power = 40e3
        self._atto3_power = 40e3
        self._ple_to_refocus = False
        self._elapsed_time = 0
        self.equilize_cryo = 'bf'
        self.check_fresh = 1

        self.folder_save = folder_save
        self.polarization_is_parallel = False
        self.query_time = 3  # minutes
        self.next_time = 2 * 60 * 60 * 1000  # N hours in milliseconds
        self.measurements = ['hom', 'hom_detuned', 'g2_bf', 'g2_atto3'][::-1]
        self.setpoint_story = []
        self.iteration = 0

        # Initialize timers
        self.timer = QTimer()
        self.next_measurement_timer = QTimer()
        self.elapsed_timer = QElapsedTimer()

        self.scanning_probe_logic_remote = self.poi_manager_logic_remote._optimizelogic()._scan_logic()
        self.scanning_probe_logic = self.poi_manager_logic._optimizelogic()._scan_logic()


        self.measurement_setpoints = [0] #, -0.3, -0.6]

    def start_measurement(self, folder):
        self.start_time = datetime.now()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_tagger_plots(tag=f'iter_{self.iteration}', folder_path=folder)

        self.toggle_tagger_counter_plot(False)
        self.toggle_tagger_corr_plot(False)


        self.toggle_tagger_counter_plot(True)

        self.stop_dump()

        self.toggle_tagger_counter_plot(True)
        self.toggle_tagger_corr_plot(True)

        self.polarization_is_parallel = True

        self.start_dump(folder, 
                    f'dump'.replace('.', '_'))


    def refocus_and_realign(self):
        
        print("Measurement", self.current_measurement)
        print("Iteraion", self.iteration)
        current_save_folder = os.path.join(self.folder_save, 
                                                current_measurement)
        if self.iteration == 0:
            self.start_measurement(current_save_folder)

        self.save_tagger_plots(f'iter_{self.iteration}', 
                                folder_path=current_save_folder)
        if self.iteration % 2 == 0:
                self.measurement_mode('Off-res')
                self.refocus(optimize_both=True) 
                time.sleep(1)
        
        if self.current_measurement == 'hom':

            if selfiteration % 4 == 0:
                target_laser = self.laser_scanner_logic.scanner_target

                self.measurement_mode('PLE')

                self.do_ple_scan(lines=5, 
                                    in_range = self.laser_scanner_logic.scan_ranges["a"])

                self.laser_scanner_logic.set_target_position(
                            {key: float(value) for key, value in target_laser.items()}
                        )
                
                self.save_ple(tag=f'iter_{self.iteration}', 
                                                folder_name=current_save_folder)

                self.ple_gui.toggle_optimize(True)
                time.sleep(0.5)
                while self.laser_scanner_logic.module_state() == 'locked':
                    time.sleep(1)
            
            if self.iteration % 1 == 0:
                self.measurement_mode('PLE')
                time.sleep(0.5)
                self.set_green_power('atto3', 5e3)
                self.align_resonances(dv=0.2, steps=40)
                time.sleep(1)
                self.setpoint_story.append(self.ao_electrodes.setpoint)

        self.measurement_mode('Off-res')
        time.sleep(0.2)

        if self.current_measurement == 'hom_detuned':
            self.ao_electrodes.setpoint = -0.05

        if self.current_measurement == 'g2_atto3':
            self.set_green_power('atto3', self.max_power)
            self.set_green_power('bf', 0)
        
        if self.current_measurement == 'g2_bf':
            self.set_green_power('bf', self.max_power)
            self.set_green_power('atto3', 0)
            
        self.polarization_is_parallel = True
        self.iteration = self.iteration + 1
        print("Measurement", self.current_measurement)
        print("New Iteraion", self.iteration)
        
    def next_measurement(self):
        
        self.timer.stop()
        self.next_measurement_timer.stop()
        
        self.current_measurement = self.measurements.pop()
        self.iteration = 0
        timer.start(self.query_time * 60 * 1000)
        

        if len(self.measurements) < 1:
            self.timer.stop()
            self.next_measurement_timer.stop()
            return 
        
        self.next_measurement_timer.start(self.next_time)

    def start_experiment(self):
        self.polarization_is_parallel = False
        self.measurement_mode('Off-res')

        self.timer.setInterval(self.query_time * 60 * 1000)
        self.timer.timeout.connect(self.refocus_and_realign)

        self.measurements = ['hom', 'hom_detuned', 'g2_bf', 'g2_atto3'][::-1]
        
        self.next_measurement_timer.setInterval(self.next_time)
        self.next_measurement_timer.setSingleShot(True)  # Ensure the timer only fires once
        self.next_measurement_timer.timeout.connect(self.next_measurement)

        

        self.elapsed_timer.start()
        self.timer.start(self.query_time * 60 * 1000)
        self.current_measurement = self.measurements.pop()
        self.next_measurement_timer.start(self.next_time)

        self.start_measurement(os.path.join(self..folder_save, self.current_measurement))
        iteration = 1
    
    def time_left(self):
        # Time left for the current timer (in milliseconds)
        elapsed = self.elapsed_timer.elapsed()
        return max(0, self.timer.interval() - elapsed)

    def next_measurement_time_left(self):
        # Time left for the next measurement timer (in milliseconds)
        elapsed = self.elapsed_timer.elapsed()
        return max(0, self.next_measurement_timer.interval() - elapsed)
    
    def change_setpoint(self):
        self.stop_dump()

        if len(self.measurement_setpoints) > 0:

            self._setpoint_offset = self.measurement_setpoints.pop()
           
            self.folder_save = os.path.join(self.folder_save_papa, f"setpoint_{int(self._setpoint_offset * 100)}_V")

            os.makedirs(self.folder_save, exist_ok=True)

            self.start_measurement()
        

    def calibrate_counts(self, cryo, cryo_off, steps = 40):
        #before the measuerement calibrate the coutns
        # self.calibrate_counts('atto3', 'bf')
        # self.calibrate_counts('bf', 'atto3')
        
        self.counts_calibration[cryo] = []
        self.counts_calibration['powers'] = np.linspace(50, self.max_power, steps)
        powers_cal = self.counts_calibration['powers']
        
        self.polarization_is_parallel = True

        self.set_green_power(cryo, powers_cal[0])
        self.set_green_power(cryo_off, 0)
        time.sleep(1)

        for _power in powers_cal[1:]:
           
            self.set_green_power(cryo, _power)
            
            time.sleep(0.2)
            ch_cts = self.get_counts(channels=[2,3]).sum()
            self.counts_calibration[cryo].append(ch_cts)
        self.counts_calibration[cryo] = np.array(self.counts_calibration[cryo])


    def equalize_powers(self):

        self.polarization_is_parallel = True

        # self.ibeam_smart_remote.power = self._reference_power # exite on max attory
        self.set_green_power('bf', 0)
        self.set_green_power('atto3', self.max_power)
        time.sleep(0.2)
        ch_cts1 = self.get_counts(channels=[2,3]).sum()

        self.set_green_power('bf', self.max_power)
        self.set_green_power('atto3', 0)
        time.sleep(0.2)
        ch_cts2 = self.get_counts(channels=[2,3]).sum()
        
        # set the bluefors power to match the counts
        cts_min = min(ch_cts1, ch_cts2)
        if np.abs(ch_cts1 - ch_cts2) < self.check_fresh:
            self.set_green_power('bf', self.max_power)
            self.set_green_power('atto3', self.max_power)
            return
        if ch_cts1 > ch_cts2:
            equilize_cryo = 'atto3'
            nonq = 'bf'
            cryo_index = 3
            
            self.set_green_power('bf', 0)
            self.set_green_power('atto3', self.max_power)
        else:
            equilize_cryo = 'bf'
            nonq = 'atto3'
            cryo_index = 2
            
            self.set_green_power('bf', self.max_power)
            self.set_green_power('atto3', 0)

        
        self.set_green_power(equilize_cryo, self.max_power*0.5)
        time.sleep(0.5)
        counts_diff = np.array([])
      
        for _power in (powers := np.linspace(self.max_power*0.5, self.max_power, 18)):
            self.set_green_power(equilize_cryo, _power)
            ch_cts = self.get_counts(channels=[2,3]).sum()
            counts_diff = np.append(counts_diff, np.abs(ch_cts - cts_min))

        self.set_green_power(equilize_cryo, powers[np.argmin(counts_diff)])
        
        self.set_green_power(nonq, self.max_power)
        self.polarization_is_parallel = True

        return ch_cts, ch_cts1, ch_cts2




    def align_resonances(self, dv=0.3, steps=30, offset=0):
        self.ple_gui.toggle_optimize(True)
        time.sleep(0.5)
        while self.laser_scanner_logic.module_state() == 'locked':
            time.sleep(1)
        
        # TODO: add the line switching to the required channel ('APD1')
        v0 = self.ao_electrodes.setpoint
        setpoints = np.linspace(v0 - dv, v0 + dv, steps)

        # Make sure setpoints are within valid range
        setpoints = setpoints[np.abs(setpoints) < 1.379]
        
        counts = np.array([])
        
        for _setpoint in setpoints:
            self.ao_electrodes.setpoint = _setpoint
            time.sleep(0.1)
            cts = self.get_remote_counts(channels=[1])
            counts = np.append(counts, cts)
            

        # Fit the Lorentzian to the measured points
        max_value, optimal_setpoint = find_max_spline(setpoints, counts)
        # optimal_setpoint = find_lorentzian_center(setpoints, counts)
        
        # Set the setpoint to the center of the Lorentzian plus any offset
        self.ao_electrodes.setpoint = optimal_setpoint + offset
        
        return counts, setpoints

    
    def check_ple(self, do_ple_refocus = False):
        self.PLE_check_trigger(enable=True)
        self.measurement_mode('PLE')
        if self._ple_to_refocus:
            do_ple_refocus = True
        for i in range(1):
            res = self.do_ple_scan(lines=1, 
                            in_range = self.laser_scanner_logic.scan_ranges["a"])
            if res.rsquared > 0.5:
                self.save_ple(tag=f'{self._elapsed_time}', poi_name='', folder_name=self.timed_folder) #{self.refocus_timer.elapsed_time}
                break
        
        if do_ple_refocus:
            self.go_to_ple_target(target=res.best_values['center'])
            
            self.set_green_power('bf', 10e3)
            self.set_green_power('atto3', 1e3)

            self.align_resonances(offset=self._setpoint_offset)
            for i in range(1):
                res = self.do_ple_scan(lines=1, 
                                in_range = self.laser_scanner_logic.scan_ranges["a"])
                if res.rsquared > 0.5:

                    

                    self.save_ple(tag=f'refocused_{self._elapsed_time}', poi_name='', folder_name=self.timed_folder) #self.refocus_timer.elapsed_time
                    break

        self.PLE_check_trigger(enable=False)
        self.measurement_mode('Off-res')

    @property
    def timed_folder(self):
        elapsed_time = datetime.now() - self.start_time
        folder_index = int(elapsed_time.total_seconds() // (self.folder_interval * 60))  # Folder interval in seconds
        folder_path = os.path.join(self.folder_save, f"interval_{self.folder_interval * folder_index}_min")

        os.makedirs(folder_path, exist_ok=True)
        return folder_path
    

    def max_out_position(self, channels=[2], channel_2=[3], step_size = 0.1e-6):
        # Initialize target and current counts
        self.step_size = step_size
        self.target_position = self.scanning_probe_logic.scanner_target
        self.target_counts = self.get_counts(channels).sum()
        self.current_counts = self.get_counts(channels).sum()
          # Small step size for adjustments
        if channel_2:
            self.target_position_remote = self.scanning_probe_logic_remote.scanner_target
            self.target_counts_remote = self.get_counts(channels=channel_2).sum()
            self.current_counts_remote = self.get_counts(channels=channel_2).sum()

        self.direction_x = {'x': step_size, 'y': 0, 'z': 0}  # Initial direction for X adjustment
        self.direction_y = {'x': 0, 'y': step_size, 'z': 0}  # Initial direction for Y adjustment
        self.direction_z = {'x': 0, 'y': 0, 'z': step_size}  # Initial direction for Z adjustment
        self.iteration = 0  # Tracks the current step within the 3-iteration cycle
        self.initial_position = self.target_position.copy()
        self.initial_position_remote = self.target_position_remote.copy()
        constraint_range = 0.6e-6  # 1 micrometer box around the initial position
        self.constraints = {
            'x': (self.initial_position['x'] - constraint_range, self.initial_position['x'] + constraint_range),
            'y': (self.initial_position['y'] - constraint_range, self.initial_position['y'] + constraint_range),
            'z': (self.initial_position['z'] - constraint_range, self.initial_position['z'] + constraint_range)
        }
        self.constraints_remote = {
            'x': (self.initial_position_remote['x'] - constraint_range, self.initial_position_remote['x'] + constraint_range),
            'y': (self.initial_position_remote['y'] - constraint_range, self.initial_position_remote['y'] + constraint_range),
            'z': (self.initial_position_remote['z'] - constraint_range, self.initial_position_remote['z'] + constraint_range)
        }

        for axis in self.target_position:
            # Perform 10-step sweep
            sweep_data = []
            sweep_data_remote = []
            for i in (x_data := np.arange(-0.5, 0.5, 0.1)):
                
                new_position = self.target_position.copy()
                new_position[axis] += float(i * self.step_size)
                new_position[axis] = max(self.constraints[axis][0], 
                                         min(new_position[axis], 
                                             self.constraints[axis][1]))
                self.scanning_probe_logic.set_target_position(
                    {key: float(value) for key, value in new_position.items()}
                )
                time.sleep(0.1)  # Adjust sleep time as needed
                sweep_data.append(self.get_counts(channels=channels).sum())
                if channel_2:
                    new_position = self.target_position_remote.copy()
                    new_position[axis] += float(i * self.step_size)
                    new_position[axis] = max(self.constraints_remote[axis][0], 
                                         min(new_position[axis], 
                                             self.constraints_remote[axis][1]))
                    
                    self.scanning_probe_logic_remote.set_target_position(
                        {key: float(value) for key, value in new_position.items()}
                    )
                    time.sleep(0.1)  #
                    sweep_data_remote.append(self.get_counts(channels=channel_2).sum())
                
                
                
            # Fit a Gaussian model to the sweep data

            
            max_value, max_x = find_max_spline(x_data, sweep_data)
            self.target_position[axis] += max_x * self.step_size
            self.gently_move(axis, max_x)
            if channel_2:
                max_value2, max_x2 = find_max_spline(x_data, sweep_data_remote)
                self.target_position_remote[axis] += max_x2 * self.step_size
                self.gently_move(axis, max_x2, is_remote=True)
            time.sleep(1)

    def gently_move(self, axis, max_x, is_remote=False):
        # Determine the number of steps based on a desired step size or maximum distance
        max_step_size = 0.1 * self.step_size  # Adjust as needed
        num_steps = int(np.ceil(abs(max_x * self.step_size) / max_step_size))
        step_size = max_x * self.step_size / num_steps

        # Gradually move to the new optimum
        for _ in range(num_steps):
            
            
            if is_remote:
                self.target_position_remote[axis] += step_size
                self.scanning_probe_logic_remote.set_target_position(
                    {key: float(value) for key, value in self.target_position_remote.items()}
                )
            else:
                self.target_position[axis] += step_size
                self.scanning_probe_logic.set_target_position(
                    {key: float(value) for key, value in self.target_position.items()}
                )
            # Add a delay here if necessary to allow the system to stabilize
            time.sleep(0.1)  # Adjust delay as needed

    def check_and_adjust_counts(self):
        self.polarization_is_parallel = False

        self.max_out_position(channels=[2], channel_2=[3])
        

        self.polarization_is_parallel = True


