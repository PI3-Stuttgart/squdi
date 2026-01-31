
# %%
import time
import numpy as np
import json
import os
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro,LaserHead,  NetworkConnection, DeviceNotFoundError
scanning_probe_logic_ = scanning_probe_logic #galvo_scanning_probe_logic
ple_gui_ = ple_gui #_qinu
scanner_gui_ = galvo_scanner_gui
dl_pro_ = dl_pro #_qinu
def go_to_ple_target(target):
    ple_gui_._mw.ple_widget.target_point.setValue(target)
    ple_gui_._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
    #laser_scanner_logic.set_target_position({"a": target})
    time.sleep(0.5)

def save_scan(name):
    scanner_gui_.save_path_widget.saveTagLineEdit.setText(name)
    scanner_gui_.scan_2d_dockwidgets[('x', 'y')].scan_widget.save_scan_button.clicked.emit() #saving
    dir_ = scanning_probe_logic_.module_default_data_dir
    return name, dir_

#to be rapaired:
def set_laser_offset(v):
    with DLCpro(NetworkConnection(dl_pro_.tcp_address)) as dlc:
        dlc._laser1.dl.pc.voltage_set.set(v)

ws_wavemeter.start_acquisition()



#%%
dl_pro_
# %%
# %%
# Parameters
offset_min_v = 20  # GHz to Hz
offset_max_v = 120  # GHz to Hz
steps = 30
# num_steps = int((offset_max_v - offset_min_v) / step) + 1  # +1 for inclusive range

w0 = 484.130 #THz
# Data structure for results
offsets = np.linspace(offset_min_v, offset_max_v, steps)
#%%
scan_names = {}
experiment_name = "scan_40_40_250_100kev-number5_deepest_trench_etched-total"
# Loop through frequencies
for i, v in enumerate(offsets):
    # Set laser frequency
    set_laser_offset(v)
    time.sleep(2)

    # Measure and record wavelength
    wavelength = (ws_wavemeter.get_current_wavelength() - w0) * 1e3   # to GHz
    print(wavelength)
    time.sleep(1)
    # Start scan and save data
    scanning_probe_logic_.toggle_scan(True, ('x', 'y'))
    while scanning_probe_logic_.module_state()=='locked':
            time.sleep(1)
    
    name, dir_ = save_scan(f"{experiment_name}_{i}_{wavelength:.2f}GHz")
    scan_names.update({wavelength: os.path.join(dir_, name)})

    print(f"Scan {i+1}/{steps} completed for {wavelength:.2f} GHz")

with open(f"{experiment_name}.txt", 'w') as file:
    json.dump(scan_names, file, indent=4)

# %%
for i, v in enumerate(offsets):
    # Set laser frequency
    set_laser_offset(v)
    time.sleep(2)

    # Measure and record wavelength
    wavelength = (ws_wavemeter.get_current_wavelength() - w0) * 1e3   # to GHz
    print(wavelength)


    print(f"Scan {i+1}/{steps} completed for {wavelength:.2f} GHz")
# %%
