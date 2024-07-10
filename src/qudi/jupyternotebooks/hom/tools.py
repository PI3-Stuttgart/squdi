# %%
import time
import numpy as np
import json
import schedule
import os
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro,LaserHead,  NetworkConnection, DeviceNotFoundError

#from 0 to 19650 MHz (max val defined by config) laser offset 
def go_to_ple_target(ple_gui, target):
    ple_gui._mw.ple_widget.target_point.setValue(target)
    ple_gui._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
    #laser_scanner_logic.set_target_position({"a": target})
    time.sleep(0.5)

#save confocal map. It will be saved in the folder defined in the app
def save_scan(scanner_gui, scanning_data_logic, name):
    scanner_gui.save_path_widget.saveTagLineEdit.setText(name)
    scanner_gui.scan_2d_dockwidgets[('x', 'y')].scan_widget.save_scan_button.clicked.emit() #saving
    dir_ = scanning_data_logic.module_default_data_dir
    return name, dir_

#laser offset with the topica:
def set_laser_offset(v):
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc._laser1.dl.pc.voltage_set.set(v)

def get_laser_offset():
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        v0 = dlc._laser1.dl.pc.voltage_set.get()
    return v0
#start scanning with toptica
def enable_laser_scanning(enable):
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc._laser1.scan.enabled.set(enable)


def blue_quick_repump(pulsestreamer, dt = 0.01):
    # pulsestreamer._seq.setDigital(1, [(1000, 1)])
    pulsestreamer._seq.setDigital(2, [(1000, 1)])
    time.sleep(dt)
    pulsestreamer._seq.setDigital(2, [(1000, 0)])
    pulsestreamer.pulser_on()

#add the trigger for ple checking to be able to process out it in timetagger dump
def PLE_check_trigger(pulsestreamer, enable=True):
    # pulsestreamer._seq.setDigital(1, [(1000, 1)])
    pulsestreamer._seq.setDigital(5, [(100000000000, 0), (10, int(enable))])
    
    pulsestreamer.pulser_on()

def save_ple(ple_gui, tag, poi_name=None, folder_name = None):
        if folder_name:
            ple_gui._save_folderpath = folder_name
        ple_gui.save_path_widget.saveTagLineEdit.setText(
            f"{poi_name}_{tag}"
            )
        ple_gui._mw.actionSave.triggered.emit()

def do_ple_scan(ple_gui, lines = 1, in_range = None, frequency=None, resolution=None):
    """
    fine_scan_range = (
            self.ple_gui.fit_result[1].best_values['center'] - self.ple_gui.fit_result[1].best_values['sigma'] * 3,
            self.ple_gui.fit_result[1].best_values['center'] + self.ple_gui.fit_result[1].best_values['sigma']  * 3
        )
    """

    #laser_scanner_logic.scan_ranges["a"]
    if in_range is None:
        ple_gui._mw.actionFull_range.triggered.emit()
    else:
        ple_gui.sigScanSettingsChanged.emit(
            {
            'range': {ple_gui.scan_axis: in_range}
            }
        )
    ple_gui._mw.number_of_repeats_SpinBox.setValue(lines)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(0.5)
    ple_gui._mw.actionToggle_scan.setChecked(True)
    ple_gui.toggle_scan()
    while laser_scanner_logic.module_state()=='locked':
            time.sleep(1)
    time.sleep(1)
    ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("Lorentzian")
    time.sleep(1)
    # self.ple_gui._accumulated_data.mean(axis=0)
    print(f"Rsquared {ple_gui.fit_result[1].rsquared}")
    # self.ple_gui.fit_result[1].params["center"].value
    return ple_gui.fit_result[1]


def green_laser(turn_on = True):
    pulsestreamer._seq = pulsestreamer.pulse_streamer.createSequence()
    # pulse_pattern_cw_450 = [(_hist_record_length, 0), (10, 1)]
    pulsestreamer._seq.setDigital(1, [(1000, int(0))])
    pulsestreamer._seq.setDigital(3, [(1000, int(turn_on))])
    
    # timetagger.sigToggleHist.emit({'hist': (_hist_bin_width, _hist_record_length, int(hist_channel), False)})
    pulsestreamer.pulser_on()
    time.sleep(0.1)

def blue_laser_repump(enable=True, res = True, on_t = 1e5, off_t = 1e9):
    pulsestreamer._seq = pulsestreamer.pulse_streamer.createSequence()
    pulse_pattern_cw_450 = [(int(off_t), 0), (int(on_t), 1)]
    pulsestreamer._seq.setDigital(1, [(1000, int(res))])
    pulsestreamer._seq.setDigital(2, pulse_pattern_cw_450)
    pulsestreamer._seq.setDigital(3, [(1000, int(False))])
    
    
    # timetagger.sigToggleHist.emit({'hist': (_hist_bin_width, _hist_record_length, int(hist_channel), False)})
    pulsestreamer.pulser_on()
    time.sleep(0.1)

#PLE mode:

def measurement_mode(switchlogic,powercontroller_logic, ibeam_smart_remote,mode):
    if mode == "PLE":
        # red on, blue on, green off
        if switchlogic.get_state("Mirror") != 'On':
            switchlogic.set_state(switch = "Mirror", state = "On")
        time.sleep(2)
        if switchlogic.get_state("Mirror") == 'On':
            if switchlogic.get_state("Shutter") != 'Off':
                switchlogic.set_state(switch = "Shutter", state = "Off")
            time.sleep(0.5)
            if switchlogic.get_state("ResonantBF") != 'On':
                switchlogic.set_state(switch = "ResonantBF", state = "On")
            # if switchlogic.get_state("GreenBF") != 'Off':
            #     switchlogic.set_state(switch = "GreenBF", state = "Off")
            # if switchlogic.get_state("GreenAtto3") != 'Off':
            #     switchlogic.set_state(switch = "GreenAtto3", state = "Off")
            # if switchlogic.get_state("BlueBF") != 'On':
            #     switchlogic.set_state(switch = "BlueBF", state = "On")
            # if switchlogic.get_state("BlueAtto3") != 'On':
            #     switchlogic.set_state(switch = "BlueAtto3", state = "On")
            ibeam_smart_remote.power = 50
            powercontroller_logic._current_motor = 2
            powercontroller_logic.motor_position = 240
            time.sleep(1)
        else:
            print("Mirror not in, PLE would burn APDs")
            raise BaseException
        # ibeam_remote.power = 0.01e3
        # blue_laser_repump(enable=True)

    elif mode == "Off-res":
        # green_laser(True)
        if switchlogic.get_state("ResonantBF") != 'Off':
                switchlogic.set_state(switch = "ResonantBF", state = "Off")
        if switchlogic.get_state("Shutter") != 'On':
            switchlogic.set_state(switch = "Shutter", state = "On")
        time.sleep(1)
        if switchlogic.get_state("Mirror") != 'Off':
            switchlogic.set_state(switch = "Mirror", state = "Off")
        # if switchlogic.get_state("GreenBF") != 'On':
        #     switchlogic.set_state(switch = "Green", state = "On")
        # if switchlogic.get_state("GreenAtto3") != 'On':
        #     switchlogic.set_state(switch = "GreenAtto3", state = "On")
        # if switchlogic.get_state("BlueBF") != 'Off':
        #         switchlogic.set_state(switch = "BlueBF", state = "Off")
        # if switchlogic.get_state("BlueAtto3") != 'Off':
        #     switchlogic.set_state(switch = "BlueAtto3", state = "Off")
        ibeam_smart_remote.power = 15e3
        powercontroller_logic._current_motor = 2
        powercontroller_logic.motor_position = 360
    else:
        print("No mode by this name")

# ws_wavemeter.start_acquisition()