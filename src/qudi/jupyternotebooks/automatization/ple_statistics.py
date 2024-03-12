import time
import numpy as np
import os
class PleAuto:
    def __init__(self, ple_gui, 
                 ple_optimize_logic,
                 laser_scanner_logic, 
                 poi_manager_logic, 
                 scanning_optimize_logic, 
                 spectrometer, 
                 spectrometerlogic,
                 cobolt,
                 ibeam_smart
                 ) -> None:
        self.ple_gui = ple_gui
        self.ple_optimize_logic = ple_optimize_logic
        self.poi_manager_logic = poi_manager_logic
        self.laser_scanner_logic = laser_scanner_logic
        self.scanning_optimize_logic = scanning_optimize_logic
        self.spectrometer = spectrometer
        self.spectrometerlogic = spectrometerlogic
        self.cobolt = cobolt
        self.ibeam_smart = ibeam_smart
        return
    def go_to_poi(self, poi_cur, ref_poi="ref", opt_times = 1):
        self.poi_manager_logic.go_to_poi(ref_poi)
        time.sleep(2)
        self.poi_manager_logic.go_to_poi(poi_cur)
        time.sleep(0.5)
        self.poi_manager_logic.go_to_poi(poi_cur)
        time.sleep(0.5)
        for i in range(opt_times):
            self.scanning_optimize_logic.start_optimize()
            while self.scanning_optimize_logic.module_state()=='locked':
                time.sleep(1)
        time.sleep(1)

    def optimize_ple(self, opt_times = 1):
        for i in range(opt_times):
            self.ple_gui.sigToggleOptimize.emit(True)
            while self.ple_optimize_logic.module_state()=='locked':
                time.sleep(1)

    def optimize_all(self, opt_times = 1):
        #assume the resonant is on
        self.optimize_ple()
        time.sleep(1)
        for i in range(opt_times):
            self.scanning_optimize_logic.start_optimize()
            while self.scanning_optimize_logic.module_state()=='locked':
                time.sleep(1)
        time.sleep(1)
    def set_resonant_power(self, power):
        self.ple_gui._mw.Controller_widget.power_SpinBox.setValue(int(power))
        time.sleep(0.5)
        self.ple_gui._mw.Controller_widget.power_SpinBox.editingFinished.emit()
        time.sleep(3)


    def do_ple_scan(self, lines = 1, in_range = None, frequency=None, resolution=None):
        """
        fine_scan_range = (
                self.ple_gui.fit_result[1].best_values['center'] - self.ple_gui.fit_result[1].best_values['sigma'] * 3,
                self.ple_gui.fit_result[1].best_values['center'] + self.ple_gui.fit_result[1].best_values['sigma']  * 3
            )
        """
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
        # self.ple_gui.fit_result[1].params["center"].value
        return self.ple_gui.fit_result[1].params

    def take_spectrum(self):
        self.spectrometer.acquire_spectrum()
        while self.spectrometerlogic._acquisition_running:
                time.sleep(1)
        time.sleep(1)


    def go_to_ple_target(self, target):
        #target = self.ple_gui.fit_result[1].params["center"].value
        # self.ple_gui._mw.ple_widget.target_point.setValue(0)
        # time.sleep(2)
        self.ple_gui._mw.ple_widget.target_point.setValue(target)
        self.ple_gui._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
        time.sleep(0.5)

    def one_pulse_repump(self, color='violet', power=0.1):
        if color == "violet":
            self.cobolt.set_laser_modulated_power(power = power)
            self.cobolt.enable_modulated()
            time.sleep(0.2)
            self.cobolt.disable_modulated()
        elif color == "green":
            self.ibeam_smart.setPower(power)
            self.ibeam_smart.enable()
            time.sleep(0.2)
            self.ibeam_smart.disable()
        elif color == "blue":
            pass

    def save_ple(self, tag, poi_name=None, folder_name = None):
        if folder_name:
            self.ple_gui._save_folderpath = folder_name
        self.ple_gui.save_path_widget.saveTagLineEdit.setText(
            f"{poi_name}_{tag}"
            )
        self.ple_gui._mw.actionSave.triggered.emit()
    
    
    def save_spectrum(self, name_tag, folder_path=None):
        if folder_path:
            self.spectrometer._save_folderpath = folder_path
        self.spectrometer.save_widget.saveTagLineEdit.setText(name_tag)
        # hit save
        self.spectrometer._mw.action_save_spectrum.triggered.emit()
        return self.spectrometerlogic.last_saved_path
