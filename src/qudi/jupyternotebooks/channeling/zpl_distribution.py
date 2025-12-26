
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

ws_wavemeter.start_acquisition()



#%%
dl_pro
# %%
# %%
# Parameters
offset_min_v = 10  # GHz to Hz
offset_max_v = 120  # GHz to Hz
steps = 30
# num_steps = int((offset_max_v - offset_min_v) / step) + 1  # +1 for inclusive range

w0 = 484.130 #THz
# Data structure for results
offsets = np.linspace(offset_min_v, offset_max_v, steps)
#%%
scan_names = {}
experiment_name = "scan_+-15_+-15_250_100kev_sn119"
# Loop through frequencies
for i, v in enumerate(offsets):
    # Set laser frequency
    set_laser_offset(v)
    time.sleep(1)

    # Measure and record wavelength

    wavelength = (ws_wavemeter.get_current_wavelength() - w0) * 1e3   # to GHz
    print(wavelength)
    if wavelength:

    # Start scan and save data
    scanning_probe_logic.toggle_scan(True, ('x', 'y'))
    while scanning_probe_logic.module_state()=='locked':
            time.sleep(1)
    
    name, dir_ = save_scan(f"{experiment_name}_{i}_{wavelength:.2f}GHz")
    scan_names.update({wavelength: os.path.join(dir_, name)})

    print(f"Scan {i+1}/{steps} completed for {wavelength:.2f} GHz")

with open(f"{experiment_name}.txt", 'w') as file:
    json.dump(scan_names, file, indent=4)

# %%
offset_min_v = 10  # GHz to Hz
offset_max_v = 130  # GHz to Hz
steps =30
# num_steps = int((offset_max_v - offset_min_v) / step) + 1  # +1 for inclusive range

w0 = 484.130 #THz
# Data structure for results
offsets = np.linspace(offset_min_v, offset_max_v, steps)
wavelengths = []
for i, v in enumerate(offsets):
    # Set laser frequency
    set_laser_offset(v)
    time.sleep(2)

    # Measure and record wavelength

    wavelength = (ws_wavemeter.get_current_wavelength() - w0) * 1e3   # to GHz
    print(wavelength)
    wavelengths.append(wavelength)

with open(f"{experiment_name}_wavelengths.txt", 'w') as file:
    json.dump(wavelengths, file, indent=4)
# %%


cavity_scanner_logic.set_target_position({"a": 8000})
# %%
import time

INITIAL_FREQUENCY = cavity_scanner_logic.scanner_position['a']  # MHz
DRIFT_RATE = 0.1           # MHz per second (Drifting up)
update_interval = .1      # seconds

start_freq_mhz = INITIAL_FREQUENCY
drift_rate_mhz_per_sec = DRIFT_RATE  # MHz per second


current_freq = start_freq_mhz
# We use a monotonous clock for precision timing
start_time = time.monotonic()
print(f"Starting loop at {start_freq_mhz} MHz with drift {drift_rate_mhz_per_sec} MHz/s")

try:
    while True:
        # 1. Calculate elapsed time since start to avoid accumulating sleep errors
        now = time.monotonic()
        elapsed_time = now - start_time
        
        # 2. Calculate the new frequency based on total elapsed time
        # Formula: Frequency = Start + (Rate * Time)
        current_freq = start_freq_mhz + (drift_rate_mhz_per_sec * elapsed_time)
        
        # 3. Apply the logic
        # Using the specific syntax you requested
        cavity_scanner_logic.set_target_position({"a": current_freq})
        
        # 4. Wait for the next update cycle
        time.sleep(update_interval)

except KeyboardInterrupt:
    print("\nLoop stopped by user.")
    print(f"Final Frequency: {current_freq:.6f} MHz")