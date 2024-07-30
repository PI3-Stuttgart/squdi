from functools import partial, wraps
import time
import os
import numpy as np
import copy
from PySide2.QtCore import QTimer, QTime, Signal

def return_to_measurement_powers_I_dependent_g2(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        self.set_green_power(cryo = self.current_cryo, value = self.value)
        self.set_green_power(cryo = self.non_active_cryo, value = 0)
        return result
    return wrapper

def return_to_measurement_powers_E_dependent_hom(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        self.set_green_power(cryo = self.current_cryo, value = self.power)
        self.set_green_power(cryo = self.non_active_cryo, value = self.power)
        return result
    return wrapper

def return_to_measurement_powers(measurement_type):
    def decorator_selector(func):
        if measurement_type == 'I_g2':
            return return_to_measurement_powers_I_dependent_g2(func)
        elif measurement_type == 'E_hom':
            return return_to_measurement_powers_E_dependent_hom(func)
    return decorator_selector


def g2_value_dependent(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.values is None:
            return
        else:
            self.timer.start(10000)  # 1 second interval
            self.refocus_timer.start(25 * 60000)  # each 20 mins interval

        if len(self.values) < 1:
            self.integration_timer.stop()
            self.refocus_timer.stop()
            self.timer.stop()
            self.stop_dump()
            return

        self.value = self.values.pop()
        
        self.save_tagger_plots(os.path.join(self.folder_save, str(self.value).replace('.', '_')), str(self.value).replace('.', '_'))

        self.toggle_tagger_counter_plot(False)
        self.toggle_tagger_corr_plot(False)

        self.toggle_tagger_counter_plot(True)

        self.stop_dump()
        self.measurement_mode(mode='Off-res', greens_on = False)
        self.refocus()

        # Function where the values are varied
        result = func(self, *args, **kwargs)

        # Start the measurement:
        self.toggle_tagger_counter_plot(True)
        self.toggle_tagger_corr_plot(True)
        self.start_dump(self.folder_save, str(self.value).replace('.', '_'))
        self.integration_timer.start(self.integrate_for_mins * 60e3)  # integrate in minutes
        return result
    return wrapper
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
                 poi_manager_logic_remote=None,
                 poi_manager_logic=None,
                 powercontroller_logic=None,
                 ibeam_smart_remote=None,
                 ple_gui=None,
                 laser_scanner_logic=None,
                 scanner_gui=None, 
                 scanning_data_logic=None,
                 switchlogic=None,
                 current_cryo=None,
                 non_active_cryo=None,
                 folder_save=None,
                 integrate_for_mins=None,
                 values=None,
                 *args, **kwargs) -> None:
        #WARNING IF NONE!
        
        self.timetaggerlogic = timetaggerlogic
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
        self.integrate_for_mins = integrate_for_mins
        self.current_cryo = current_cryo
        self.non_active_cryo = non_active_cryo
        self.folder_save = folder_save
        self.values = values

        self.powercontroller_logic._current_motor = 0
        self.powercontroller_logic.motor_position = self.perpendicular_position
        self._polarization_is_parallel = False


    def start_periodic_refocus(self, refocus_period_mins = 25, count_check_period_sec = 60):
        self.timer = QTimer()
        self.timer.setInterval(count_check_period_sec * 1000)
        self.timer.timeout.connect(self.check_counts)
        self.timer.start(count_check_period_sec * 1000)

        self.refocus_timer = QTimer()
        self.refocus_timer.setInterval(refocus_period_mins * 60000)
        self.refocus_timer.timeout.connect(self.refocus)
        self.refocus_timer.start(refocus_period_mins * 60000)
    
    def start_integration(self, integrate_for_mins = None, start_delay = 10e3):
        self.integrate_for_mins = integrate_for_mins if integrate_for_mins is not None else self.integrate_for_mins
        self.start_periodic_refocus()

        self.integration_timer = QTimer()
        self.integration_timer.timeout.connect(self.change_power)
        self.integration_timer.setSingleShot(True)
        self.integration_timer.start(start_delay)

    def stop_all_timers(self):
        self.timer.stop()
        self.refocus_timer.stop()
        self.integration_timer.stop()
    
    def get_counts(self, integrate_sec = 0.1, samples = 10, return_ple = False, channels=[2,3]):
        cts = []
        for channel in channels:

            self.timetagger._mw.count_display_comboBox.setCurrentIndex(channel)
            ch_cts = 0
            for i in range(samples):
                ch_cts += float(self.timetagger._mw.count_display_label.text()[:5])
                time.sleep(integrate_sec)
            ch_cts = ch_cts / samples

            cts.append(ch_cts)
        return np.array(cts)

       
    #HELP functions
    def check_counts(self):
        tot_cts = self.get_counts(channels=[2,3]).mean()
        self.refocused_cts = tot_cts if self.refocused_cts is None else self.refocused_cts

        if tot_cts <= self.refocused_cts * 0.75:
            self.refocus()

        self.timer.start(200 * 1000)

    def refocus(self, optimize_both = False):
        
        self.polarization_is_parallel = False

        time.sleep(2)
        self.poi_manager_logic_remote._optimizelogic().start_optimize()
        if optimize_both:
            self.poi_manager_logic._optimizelogic().start_optimize()
            while self.poi_manager_logic._optimizelogic().module_state()=='locked':
                time.sleep(1) # wait for a long time to 
        while self.poi_manager_logic_remote._optimizelogic().module_state()=='locked':
            time.sleep(1) # wait for a long time to 
        time.sleep(5) # wait for a long time to avoid conflicts with the countrate checker

        self.polarization_is_parallel = True
      
        time.sleep(2)
        
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

    def save_tagger_plots(self, folder, tag):
        self.timetagger._save_folderpath = folder
        self.timetagger._mw.currPathLabel.setText(folder)
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
                self.ple_gui.fit_result[1].best_values['center'] - self.ple_gui.fit_result[1].best_values['sigma'] * 3,
                self.ple_gui.fit_result[1].best_values['center'] + self.ple_gui.fit_result[1].best_values['sigma']  * 3
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
        self.pulsestreamer._seq.setDigital(5, [(100000000000, 0), (10, int(enable))])
        
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
            self.ple_gui.save_path_widget.saveTagLineEdit.setText(
                f"{poi_name}_{tag}"
                )
            self.ple_gui._mw.actionSave.triggered.emit()

class CorrMeasurements(MeasurementsBase):

    cts_refocus = []

    refocused_cts = None
    
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.power = None


    # function for doing power dependent measurement 
    @g2_value_dependent
    def change_power(self):
        value = self.value
        if self.current_cryo == 'atto3':
            self.set_green_power('bf', 0)
            self.set_green_power('atto3', value)
        elif self.current_cryo == 'bf':
            self.set_green_power('bf', value)
            self.set_green_power('atto3', 0)


class StarkHOM(MeasurementsBase):
    def __init__(self, ao_electrodes, ple_gui, laser_scanner_logic,scanner_gui, scanning_data_logic, pulsestreamer,
                 *args, **kwargs) -> None:
        super().__init__(
            *args, **kwargs
        )
        self.ao_electrodes = ao_electrodes
        self.scanner_gui = scanner_gui
        self.scanning_data_logic = scanning_data_logic
        self.pulsestreamer = pulsestreamer
        

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

    def start_measurement(self):
        return 

    def set_bf_needs_refocus(self):
        self.bf_needs_refocus = True

    def bluefors_periodic_refocus(self, refocus_period_mins = 360):

        self.bf_refocus_timer = QTimer()
        self.bf_refocus_timer.setInterval(refocus_period_mins * 60000)
        self.bf_refocus_timer.timeout.connect(self.set_bf_needs_refocus)
        self.bf_refocus_timer.start(refocus_period_mins * 60000)

    def zpl_periodic_refocus(self, refocus_period_mins = 360):

        self.zpl_refocus_timer = QTimer()
        self.zpl_refocus_timer.setInterval(refocus_period_mins * 60000)
        self._ple_to_refocus = True
        self.zpl_refocus_timer.timeout.connect(self.check_ple)
        self.zpl_refocus_timer.start(refocus_period_mins * 60000)

    def start_periodic_refocus(self, refocus_period_mins = 30, 
                               count_check_period_sec = 60, 
                               resonance_refocus_mins = 5,
                               bf_refocus_mins = 360):
        self._start_time = time.time()
        
        self.timer = QTimer()
        self.timer.setInterval(count_check_period_sec * 1000)
        self.timer.timeout.connect(self.check_counts)
        self.timer.start(count_check_period_sec * 1000)

        self.refocus_timer = QTimer()
        self.refocus_timer.setInterval(refocus_period_mins * 60000)
        self.refocus_timer.timeout.connect(self.refocus)
        self.refocus_timer.start(refocus_period_mins * 60000)

        self.bluefors_periodic_refocus(refocus_period_mins = bf_refocus_mins)

        self.zpl_periodic_refocus(refocus_period_mins = resonance_refocus_mins)

    @g2_value_dependent
    def set_voltage(self, value):
        self.ao_electrodes.setpoint = value


    def _refocus_hom(self):
        #save to the timed folders
        self._elapsed_time = time.time() - self._start_time
        self.save_tagger_plots(os.path.join(self.folder_save, 
                                            str(self._elapsed_time).replace('.', '_')), 
                                            str(self._elapsed_time).replace('.', '_'))
        
        self.refocus(optimize_both = True)

        self.check_ple(do_ple_refocus=True)

        self.equilize_powers()
        

    # @return_to_measurement_powers(measurement_type='E_hom')
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
                self.powercontroller_logic.motor_position = 45 # green dim
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
                self.ibeam_smart_remote.power = self._reference_power
                self.powercontroller_logic._current_motor = 2
                self.powercontroller_logic.motor_position = 205 # MAX green

        else:
            print("No mode by this name")

    def calibrate_counts(self, cryo, cryo_off, steps = 40):
        #before the measuerement calibrate the coutns
        # self.calibrate_counts('atto3', 'bf')
        # self.calibrate_counts('bf', 'atto3')
        
        self.counts_calibration[cryo] = []
        self.counts_calibration['powers'] = np.linspace(50, 50e3, steps)
        powers_cal = self.counts_calibration['powers']
        
        self.set_green_power(cryo, powers_cal[0])
        self.set_green_power(cryo_off, 0)
        time.sleep(5)

        for _power in powers_cal[1:]:
           
            self.set_green_power(cryo, _power)
            self.set_green_power(cryo_off, 0)
            time.sleep(0.2)
            ch2_cts = float(self.timetaggerlogic.trace_data[2][1].mean()) #timetaggerlogic.counter.getDataNormalized()[0, :]
            time.sleep(0.2)
            ch3_cts = float(self.timetaggerlogic.trace_data[3][1].mean())  #timetaggerlogic.counter.getDataNormalized()[1, :]
            self.counts_calibration[cryo].append(ch2_cts + ch3_cts)
        self.counts_calibration[cryo] = np.array(self.counts_calibration[cryo])

    def equilize_powers(self, power_integration_steps = 5):

        self.polarization_is_parallel = True

        # self.ibeam_smart_remote.power = self._reference_power # exite on max attory
        self.set_green_power('bf', 0)
        self.set_green_power('atto3', self.max_power)

        ch_cts1 = self.get_counts(channels=[1]).mean()

        self.set_green_power('bf', self.max_power)
        self.set_green_power('atto3', 0)

        ch_cts2 = self.get_counts(channels=[1]).mean()
        
        # set the bluefors power to match the counts
        ch_min = min(ch_cts1, ch_cts2)
        if ch_cts1 > ch_cts2:
            equilize_cryo = 'atto3'
            cryo_index = 3
            
            self.set_green_power('bf', 0)
            self.set_green_power('atto3', self.max_power)
        else:
            equilize_cryo = 'bf'
            cryo_index = 2
            
            self.set_green_power('bf', self.max_power)
            self.set_green_power('atto3', 0)

        self.timetagger._mw.count_display_comboBox.setCurrentIndex(cryo_index)
        time.sleep(0.1)
        self.set_green_power(equilize_cryo, self.max_power*0.5)
        time.sleep(2)
        counts_diff = np.array([])
        ch_cts = 0
        for _power in (powers := np.linspace(self.max_power*0.5, self.max_power, 20)):
            self.set_green_power(equilize_cryo, _power)
            ch_cts = 0
            for i in range(power_integration_steps):
                ch_cts += float(self.timetagger._mw.count_display_label.text()[:5])
                time.sleep(0.1)
            ch_cts = ch_cts / power_integration_steps
            counts_diff = np.append(counts_diff, np.abs(ch_cts - cts_min))

        self.set_green_power(equilize_cryo, powers[np.argmin(counts_diff)])

        self.polarization_is_parallel = True

        return ch_cts, ch_cts1, ch_cts2


    def align_resonances(self, offset=0, dv = 0.2, steps = 20):
        #First refocus to the max of APD1
        self.ple_gui.toggle_optimize(True)
        while self.laser_scanner_logic.module_state()=='locked':
                time.sleep(1)
        #TODO: add the line switching to the required channel ('APD1')
        v0 = self.ao_electrodes.setpoint
        counts = np.array([])
        for _setpoint in (setpoints := np.linspace(v0 - dv/2, v0 + dv/2, steps)):
            self.ao_electrodes.setpoint = _setpoint
            time.sleep(0.2)
            if self.timetagger_remote._mw.count_display_label.text()[-4:] != 'kc/s':
                cts = 0
            else:
                cts = float(self.timetagger_remote._mw.count_display_label.text()[:5])
            counts = np.append(counts, cts)
            time.sleep(0.2)
        # ao_electrodes_remote.setpoint = v0
        self.ao_electrodes.setpoint = setpoints[np.argmax(counts)]
        return counts, setpoints
    
    def check_ple(self, do_ple_refocus = False):
        self.PLE_check_trigger(enable=True)
        self.measurement_mode('PLE')
        if self._ple_to_refocus:
            do_ple_refocus = True
        for i in range(3):
            res = self.do_ple_scan(lines=1, 
                            in_range = self.laser_scanner_logic.scan_ranges["a"])
            if res.rsquared > 0.5:
                self.save_ple(tag=f'{self._elapsed_time}', poi_name='', folder_name=self.folder_save) #{self.refocus_timer.elapsed_time}
                break
        
        if do_ple_refocus:
            self.align_resonances()
            for i in range(3):
                res = self.do_ple_scan(lines=1, 
                                in_range = self.laser_scanner_logic.scan_ranges["a"])
                if res.rsquared > 0.5:
                    self.save_ple(tag=f'refocused_{self._elapsed_time}', poi_name='', folder_name=self.folder_save) #self.refocus_timer.elapsed_time
                    break

        self.PLE_check_trigger(enable=False)
        self.measurement_mode('Off-res')

        # self.set_green_power('bf', self._bf_power)
        # self.set_green_power('atto3', self._atto3_power)

        

        #add the trigger for ple checking to be able to process out it in timetagger dump


    