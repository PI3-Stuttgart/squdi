from functools import partial, wraps
import time
import os
import numpy as np
from PySide2.QtCore import QTimer, QTime, Signal

def return_to_measurement_powers(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        self.set_green_power(cryo = self.current_cryo, value = self.value)
        self.set_green_power(cryo = self.non_active_cryo, value = 0)
        return result
    return wrapper

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
        self.toggle_tagger_counter_plot(False)
        self.toggle_tagger_corr_plot(False)

        self.toggle_tagger_counter_plot(True)
        
        self.stop_dump()
        self.measurement_mode(mode='Off-res')
        self.refocus()

        # Function where the values are varied
        result = func(self, *args, **kwargs)

        # Start the measurement:
        self.toggle_tagger_counter_plot(True)
        self.toggle_tagger_corr_plot(True)
        self.start_dump(self.folder_save, str(self.value))
        self.integration_timer.start(self.integrate_for_mins * 60e3)  # integrate in minutes
        return result
    return wrapper

class CorrMeasurements:

    cts_refocus = []
    min_position = 50
    max_position = 210
    refocused_cts = None

    def __init__(self, 
                 timetaggerlogic, 
                 timetagger, 
                 poi_manager_logic_remote,
                 powercontroller_logic,
                 ibeam_smart_remote,
                 switchlogic,
                 current_cryo,
                 non_active_cryo,
                 folder_save,
                 integrate_for_mins,
                 values
                 ) -> None:
        self.timetaggerlogic = timetaggerlogic
        self.timetagger = timetagger
        self.poi_manager_logic_remote = poi_manager_logic_remote
        self.switchlogic = switchlogic
        self.ibeam_smart_remote = ibeam_smart_remote
        self.powercontroller_logic = powercontroller_logic
        self.integrate_for_mins = integrate_for_mins
        self.current_cryo = current_cryo
        self.non_active_cryo = non_active_cryo
        self.folder_save = folder_save
        self.values = values
        self.power = None

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
    
    #HELP functions
    def check_counts(self):
        ch2_cts = self.timetaggerlogic.trace_data[2][1] #timetaggerlogic.counter.getDataNormalized()[0, :]
        ch3_cts = self.timetaggerlogic.trace_data[3][1]  #timetaggerlogic.counter.getDataNormalized()[1, :]
        tot_cts = ch2_cts.mean() + ch3_cts.mean()
        self.refocused_cts = tot_cts if self.refocused_cts is None else self.refocused_cts

        if tot_cts <= self.refocused_cts * 0.75:
            self.refocus()
        self.timer.start(200 * 1000)

    @return_to_measurement_powers
    def refocus(self):
        ch2_cts = self.timetaggerlogic.trace_data[2][1] #timetaggerlogic.counter.getDataNormalized()[0, :]
        ch3_cts = self.timetaggerlogic.trace_data[3][1]  #timetaggerlogic.counter.getDataNormalized()[1, :]
        tot_cts = ch2_cts.mean() + ch3_cts.mean()
        
        self.save_tagger_plots(self.folder_save, str(self.power))

        self.cts_refocus.append(tot_cts / 1e3)
        self.powercontroller_logic._current_motor = 0
        self.powercontroller_logic.motor_position = 5 # perpendicular pol
        time.sleep(3)

        self.poi_manager_logic_remote._optimizelogic().start_optimize()
        # poi_manager_logic._optimizelogic().start_optimize()
        while self.poi_manager_logic_remote._optimizelogic().module_state()=='locked':
            time.sleep(1) # wait for a long time to 
        time.sleep(20) # wait for a long time to avoid conflicts with the countrate checker

        self.powercontroller_logic._current_motor = 0
        self.powercontroller_logic.motor_position = 22 # parallel pol
        time.sleep(3)
        ch2_cts = self.timetaggerlogic.trace_data[2][1] #timetaggerlogic.counter.getDataNormalized()[0, :]
        ch3_cts = self.timetaggerlogic.trace_data[3][1]  #timetaggerlogic.counter.getDataNormalized()[1, :]
        self.refocused_cts = ch2_cts.mean() + ch3_cts.mean()


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
        power_max = 40000
        power_min = 0
        if cryo == 'bf':
            min_position = 50
            max_position = 210
            # Ensure power is within bounds
            value = max(power_min, min(value, power_max))
            # Map power to the motor position range
            motor_position = min_position + (max_position - min_position) * (value - power_min) / (power_max - power_min)
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

        
    def measurement_mode(self, mode):
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
            self.ibeam_smart_remote.power = 30e3
            self.powercontroller_logic._current_motor = 2
            self.powercontroller_logic.motor_position = 205 # MAX green
        else:
            print("No mode by this name")

    # ws_wavemeter.start_acquisition()



class StarkHOM(CorrMeasurements):
    def __init__(self, timetaggerlogic, 
                 timetagger, 
                 poi_manager_logic_remote, 
                 powercontroller_logic, 
                 ibeam_smart_remote, 
                 switchlogic,
                 ao_electrodes) -> None:
        super().__init__(timetaggerlogic, 
                         timetagger, 
                         poi_manager_logic_remote, 
                         powercontroller_logic, 
                         ibeam_smart_remote, 
                         switchlogic)
        self.ao_electrodes = ao_electrodes


    @g2_value_dependent
    def set_voltage(self, value):
        self.ao_electrodes.setpoint = value