# %%
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

ws_wavemeter.start_acquisition()

#%%

for i in range(2):
    # Start scan and save data
    scanning_probe_logic.toggle_scan(True, ('x', 'y'))
    while scanning_probe_logic.module_state()=='locked':
            time.sleep(1)
    
    name, dir_ = save_scan(f"pillar_scan_{i}")
    
# %%
#Calibrate PLE scanner:
go_to_ple_target(laser_scanner_logic.scan_ranges['a'][0])
time.sleep(1)
ws_wavemeter




#%%
list(poi_manager_logic._roi._pois.keys())
# %%
switchlogic.states
# %%
green_laser(False)

#%%
measurement_mode('PLE')
#%%
enable_laser_scanning(True)
v0 = get_laser_offset()
set_laser_offset(v0)
# %%
set_laser_offset(v0 + 10)
#%%
enable_laser_scanning(False)
#%%
poi_manager_logic.go_to_poi("tin14")
for i in range(2):
    scanning_optimize_logic.start_optimize()
    while scanning_optimize_logic.module_state()=='locked':
        time.sleep(1)
# green_laser(True)
        
#%%
measurement_mode('Off-res')
#%%

for i in range(2):
    scanning_optimize_logic.start_optimize()
    while scanning_optimize_logic.module_state()=='locked':
        time.sleep(1)
# %%

# %%
res = do_ple_scan(lines=5)


#%%
green_laser(True)
#%%
blue_quick_repump(dt = 1)
# %%
#Recording g2
from TimeTagger import FileWriter, FileReader
# %%
folder = r'Z:\Vlad\SnV\HOM\dumps'


#%%
import schedule

def blast_green():
    # Code to be executed every 50 seconds goes here
    green_laser(True)
    time.sleep(5)
    measurement_mode('PLE')
    time.sleep(3)

def check_ple():
    end_time = time.time()
    elapsed_time = end_time - start_time
    PLE_check_trigger(enable=True)
    measurement_mode('PLE')
    
    for i in range(3):
        res = do_ple_scan(lines=1)
        if res.rsquared > 0.5:
            save_ple(tag=f'{elapsed_time}', poi_name='')
            break

    PLE_check_trigger(enable=False)
    measurement_mode('Off-res')
#%%
# Schedule the function
schedule.every(60).seconds.do(check_ple)
start_time = time.time()
fw = tagger.write_into_file(os.path.join(folder, 'g2_1_6March.ttbin'), channels=[1,2,3, 5, 8, 6])

# Keep the script running to continuously check for scheduled tasks
while True:
    schedule.run_pending()
    time.sleep(1)  # Check for tasks more frequently (adjust if needed)
# %%
schedule.every(40).seconds.do(blast_green)
while True:
    schedule.run_pending()
    time.sleep(1)  # Check for tasks more frequently (adjust if needed)
#%%
green_laser(True)
time.sleep(1)
blue_laser_repump(True, on_t=1e6)
# %%
