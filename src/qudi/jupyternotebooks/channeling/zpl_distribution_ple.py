
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
# %%
# Parameters
start_freq = 0  # GHz to Hz
end_freq = 18500  # GHz to Hz
step = 500  # GHz to Hz
num_steps = int((end_freq - start_freq) / step) + 1  # +1 for inclusive range
resolution = (150, 150)  # x, y points

w0 = 484.130 #THz
# Data structure for results
frequencies = np.linspace(start_freq, end_freq, num_steps)

scan_names = {}
experiment_name = "scan_10_10_178_80kev"
# Loop through frequencies
for i, freq in enumerate(frequencies):
    # Set laser frequency
    go_to_ple_target(freq)
    time.sleep(3)

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
high_finesse_wavemeter.start_acquisition()
(high_finesse_wavemeter.get_current_wavelength() - 484.130) * 1e3

# %%

# Process data (replace with your specific code)
# Here's an example using NumPy:
fluorescence_intensities = []
for data, _ in scan_data:
    # Assuming data is a 2D array of fluorescence intensities
    fluorescence_intensities.append(data.sum(axis=0))  # Sum along y-axis

# Create histograms (adapt binning as needed)
for i, intensity in enumerate(fluorescence_intensities):
    plt.hist(intensity, bins=50, label=f"{frequencies[i] / 1e9:.2f} GHz")

plt.xlabel("Fluorescence Intensity")
plt.ylabel("Count")
plt.title("Fluorescence Intensity at Different Frequencies")
plt.legend()
plt.show()
