
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

high_finesse_wavemeter.start_acquisition()



#%%
dl_pro
# %%
# %%
# Parameters
offset_min_v = 10  # GHz to Hz
offset_max_v = 100  # GHz to Hz
step = 10  # GHz to Hz
num_steps = int((offset_max_v - offset_min_v) / step) + 1  # +1 for inclusive range

w0 = 484.130 #THz
# Data structure for results
offsets = np.linspace(offset_min_v, offset_max_v, num_steps)
#%%
scan_names = {}
experiment_name = "scan_10_10_178_80kev"
# Loop through frequencies
for i, v in enumerate(offsets):
    # Set laser frequency
    set_laser_offset(v)
    time.sleep(1)

    # Measure and record wavelength
    wavelength = (high_finesse_wavemeter.get_current_wavelength() - w0) * 1e3   # to GHz
    print(wavelength)

    # Start scan and save data
    scanning_probe_logic.toggle_scan(True, ('x', 'y'))
    while scanning_probe_logic.module_state()=='locked':
            time.sleep(1)
    
    name, dir_ = save_scan(f"{experiment_name}_{i}_{wavelength:.2f}GHz")
    scan_names.update({wavelength: os.path.join(dir_, name)})

    print(f"Scan {i+1}/{num_steps} completed for {wavelength:.2f} GHz")

with open(f"{experiment_name}.txt", 'w') as file:
    json.dump(scan_names, file, indent=4)

# %%
