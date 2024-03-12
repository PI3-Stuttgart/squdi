import time
import numpy as np
import json
import os
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro,LaserHead,  NetworkConnection, DeviceNotFoundError
def go_to_ple_target(target):
    ple_gui._mw.ple_widget.target_point.setValue(target)
    ple_gui._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
    #laser_scanner_logic.set_target_position({"a": target})
    time.sleep(0.5)

def save_scan(name):
    scanner_gui.save_path_widget.saveTagLineEdit.setText(name)
    scanner_gui.scan_2d_dockwidgets[('x', 'y')].scan_widget.save_scan_button.clicked.emit() #saving
    dir_ = scanning_data_logic.module_default_data_dir
    return name, dir_

#to be rapaired:
def set_laser_offset(v):
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc._laser1.dl.pc.voltage_set.set(v)

def get_laser_offset():
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        v0 = dlc._laser1.dl.pc.voltage_set.get()
    return v0

def enable_laser_scanning(enable):
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc._laser1.scan.enabled.set(enable)
def blue_quick_repump(dt = 0.01):
    # pulsestreamer._seq.setDigital(1, [(1000, 1)])
    pulsestreamer._seq.setDigital(2, [(1000, 1)])
    time.sleep(dt)
    pulsestreamer._seq.setDigital(2, [(1000, 0)])
    pulsestreamer.pulser_on()


def PLE_check_trigger(enable=True):
    # pulsestreamer._seq.setDigital(1, [(1000, 1)])
    pulsestreamer._seq.setDigital(5, [(100000000000, 0), (10, int(enable))])
    
    pulsestreamer.pulser_on()

def save_ple(tag, poi_name=None, folder_name = None):
        if folder_name:
            ple_gui._save_folderpath = folder_name
        ple_gui.save_path_widget.saveTagLineEdit.setText(
            f"{poi_name}_{tag}"
            )
        ple_gui._mw.actionSave.triggered.emit()

def do_ple_scan(lines = 1, in_range = None, frequency=None, resolution=None):
    """
    fine_scan_range = (
            self.ple_gui.fit_result[1].best_values['center'] - self.ple_gui.fit_result[1].best_values['sigma'] * 3,
            self.ple_gui.fit_result[1].best_values['center'] + self.ple_gui.fit_result[1].best_values['sigma']  * 3
        )
    """
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
    print(f"Rsquared {res.rsquared}")
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
def blue_laser_repump(enable=True):
    pulsestreamer._seq = pulsestreamer.pulse_streamer.createSequence()
    pulsestreamer._seq.setDigital(1, [(1000, int(enable))])
    pulse_pattern_cw_450 = [(1000, int(enable))] #[(int(off_time), 0), (on_time, 1)]
    pulsestreamer._seq.setDigital(2, pulse_pattern_cw_450)
    # timetagger.sigToggleHist.emit({'hist': (_hist_bin_width, _hist_record_length, int(hist_channel), False)})
    pulsestreamer.pulser_on()
    time.sleep(0.1)

#PLE mode:

def measurement_mode(mode):
    if mode == "PLE":
        if switchlogic.get_state("Mirror") != 'On':
            switchlogic.set_state(switch = "Mirror", state = "On")
        time.sleep(1)
        if switchlogic.get_state("Shutter") != 'Off':
            switchlogic.set_state(switch = "Shutter", state = "Off")
        time.sleep(0.5)
        blue_laser_repump(enable=True)


    elif mode == "Off-res":
        green_laser(True)
        if switchlogic.get_state("Shutter") != 'On':
            switchlogic.set_state(switch = "Shutter", state = "On")
        time.sleep(1)
        if switchlogic.get_state("Mirror") != 'Off':
            switchlogic.set_state(switch = "Mirror", state = "Off")
    else:
        print("No mode by this name")
