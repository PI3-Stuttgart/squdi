#%%
# ## 1. Imports
import numpy as np
import matplotlib.pyplot as plt
import time
import os
from collections import namedtuple
import time
import os
import time
import numpy as np
from tqdm import tqdm
from tqdm.auto import tqdm # Import tqdm for progress bars
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro, NetworkConnection
def do_ple_scan(lines = 1, in_range = None, frequency=None, resolution=None, channel = None):
    """
    fine_scan_range = (
            ple_gui.fit_result[1].best_values['center']
            - ple_gui.fit_result[1].best_values['sigma'] * 3,
            ple_gui.fit_result[1].best_values['center']
            + ple_gui.fit_result[1].best_values['sigma']  * 3
        )
    """
    if channel is not None:
        ple_gui._mw.channel_comboBox.setCurrentText(channel) ## MAY BE MISTAKEN
        # ple_gui._mw.channel_comboBox.setCurrentText('APD4')
    #laser_scanner_logic.scan_ranges["a"]
    if in_range is None:
        ple_gui._mw.actionFull_range.triggered.emit()
    else:
        ple_gui.sigScanSettingsChanged.emit(
            {'range': {ple_gui.scan_axis: in_range}}
        )
    ple_gui._mw.number_of_repeats_SpinBox.setValue(lines)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(0.5)
    ple_gui._mw.actionToggle_scan.setChecked(True)
    ple_gui.toggle_scan()
    while laser_scanner_logic.module_state()=='locked':
            time.sleep(0.5)
    time.sleep(0.2)
    ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("TwoLorentz")
    time.sleep(0.2)
    #ple_gui._accumulated_data.mean(axis=0)
    #print(f"Rsquared {ple_gui.fit_result[1].rsquared}")
    #ple_gui.fit_result[1].params["center"].value
    return ple_gui.fit_result[1]

def save_ple(tag, poi_name=None, folder_name = None):
        if folder_name:
            ple_gui._save_folderpath = folder_name
            ple_gui.save_path_widget.currPathLabel.setText(ple_gui._save_folderpath)
        ple_gui.save_path_widget.saveTagLineEdit.setText(
            f"{tag}"
            )
        ple_gui._mw.actionSave.triggered.emit()
def go_to_ple_target(target):
    ple_gui._mw.ple_widget.target_point.setValue(target)
    ple_gui._mw.ple_widget.target_point.sigPositionChangeFinished.emit(target)
    #laser_scanner_logic.set_target_position({"a": target})
    time.sleep(0.5) 


#%%
ple_gui._fit_averaged = False



BASE_FOLDER = r'Z:\Vlad\heavyIV\202-2\dezembre\CPT2\B-sweeps_xy'  # Base folder to save all measurements
B_AMPLITUDE = 0.2  # Tesla
NUM_STEPS = 150     # Number of points
Bx_offset = 0

# Parameters for the small-angle arc sweep
# This defines a 30-degree sweep (+/- 15 degrees) around the Y-axis in the YZ plane.
ARC_SPAN_DEGREES = 45.0 

print("Generating B-field target points for all sweep types...")

# --- Define angles for the full circle sweeps ---
full_circle_angles = np.linspace(0, 2 * np.pi, NUM_STEPS)

# --- Define angles for the YZ arc sweep ---
# The Y-axis in the YZ plane is at 90 degrees (pi/2 radians).
center_angle_rad = 0 #np.pi / 2
span_rad = np.deg2rad(ARC_SPAN_DEGREES)
start_angle = center_angle_rad - (span_rad / 2)
end_angle = center_angle_rad + (span_rad / 2)
arc_angles = np.linspace(start_angle, end_angle, NUM_STEPS)


sweep_definitions = {
    'XY': {
        'points': list(zip(
            B_AMPLITUDE * np.cos(full_circle_angles),      # Bx
            B_AMPLITUDE * np.sin(full_circle_angles),      # By
            np.zeros(NUM_STEPS)                            # Bz
        )),
        'folder': os.path.join(BASE_FOLDER, 'B_sweep_XY_perp')
    },
    'XZ': {
        'points': list(zip(
            B_AMPLITUDE * np.sin(full_circle_angles),      # Bx
            np.zeros(NUM_STEPS),                           # By
            B_AMPLITUDE * np.cos(full_circle_angles)       # Bz
        )),
        'folder': os.path.join(BASE_FOLDER, 'B_sweep_XZ_perp')
    },
    'YZ': {
        'points': list(zip(
            np.zeros(NUM_STEPS) + Bx_offset,               # Bx
            B_AMPLITUDE * np.sin(full_circle_angles),      # By
            B_AMPLITUDE * np.cos(full_circle_angles)       # Bz
        )),
        'folder': os.path.join(BASE_FOLDER, 'B_sweep_YZ_perp')
    },
    # Definition for the small-angle YZ sweep ---
    'YZ_arc': {
        'points': list(zip(
            np.zeros(NUM_STEPS),               # Bx
            B_AMPLITUDE * np.sin(arc_angles),              # By (will be strong)
            B_AMPLITUDE * np.cos(arc_angles)               # Bz (will be small)
        )),
        'folder': os.path.join(BASE_FOLDER, f'B_sweep_YZ_arc_{ARC_SPAN_DEGREES}deg')
    },
    'XZ_arc': {
    'points': list(zip(
        
        np.zeros(NUM_STEPS),               # Bx
        B_AMPLITUDE * np.cos(arc_angles),              # By (will be strong)
        B_AMPLITUDE * np.sin(arc_angles)               # Bz (will be small)
    )),
    'folder': os.path.join(BASE_FOLDER, f'B_sweep_XZ_arc_{ARC_SPAN_DEGREES}deg')
},
    'XY_arc': {
    'points': list(zip(
        B_AMPLITUDE * np.sin(arc_angles),               # Bx
        B_AMPLITUDE * np.cos(arc_angles),              # By (will be strong)
        np.zeros(NUM_STEPS)              # Bz (will be small)
    )),
    'folder': os.path.join(BASE_FOLDER, f'B_sweep_XY_arc_{ARC_SPAN_DEGREES}deg')
},
}
#%%
fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection='3d')

# Plot the points for each plane
for plane_name, config in sweep_definitions.items():
    # Unzip the list of (x, y, z) tuples into three separate lists

    points = config['points']
    if not points: continue # Skip if no points
    x_coords, y_coords, z_coords = zip(*points)
    
    # Create the scatter plot for the current plane
    ax.scatter(x_coords, y_coords, z_coords,  marker='o', label=plane_name)

# --- Add labels and titles for clarity ---
ax.set_xlabel('$B_x$ (T)', fontsize=12)
ax.set_ylabel('$B_y$ (T)', fontsize=12)
ax.set_zlabel('$B_z$ (T)', fontsize=12)
ax.set_title('3D Visualization of All Planned B-Field Sweeps', fontsize=16)

# --- Set axis limits and aspect ratio ---
ax.set_xlim([-B_AMPLITUDE, B_AMPLITUDE])
ax.set_zlim([-B_AMPLITUDE, B_AMPLITUDE])
ax.set_ylim([-B_AMPLITUDE, B_AMPLITUDE])
ax.set_aspect('equal')  # Crucial for correct spherical appearance

# --- Add legend and grid ---
ax.legend()
ax.grid(True)
#%%
def repump_with_green(duration=1):
    switch_combiner_interfuse.set_state(switch="GreenBF", state="On")
    switch_combiner_interfuse.set_state(switch="ResonantBF", state="Off")
    time.sleep(duration)
    switch_combiner_interfuse.set_state(switch="GreenBF", state="Off")
    switch_combiner_interfuse.set_state(switch="ResonantBF", state="On")

def check_counts():
    arr = timetaggerlogic.trace_data[1][1][-10:]
    arr.sort()
    crc_cts = arr[::-1][:10].mean()
    return crc_cts

def check_charge_state(min_counts=1000):
    attempts = 0
    time.sleep(0.5)
    crc_cts = check_counts()
    while crc_cts < min_counts and attempts < 10:
        repump_with_green(0.25)
        time.sleep(1)
        crc_cts = check_counts()
        attempts += 1
    if crc_cts < min_counts:
        print('Charge state could not be restored.')

        #raise RuntimeError(f"Charge state could not be restored after {attempts} attempts (counts={crc_cts}).")
    time.sleep(0.5)


    

#%%
all_results = {}
sweep_definitions_ = {i:j for i, j in sweep_definitions.items() if i in ['XZ_arc'] } #

ple_gui._fit_averaged = False

with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
    dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    dlc.laser1.wide_scan.continuous_mode.set(False)
while laser_scanner_logic.module_state()=='locked':
    ple_gui._mw.actionToggle_scan.setChecked(False)
    time.sleep(0.25)
    ple_gui.toggle_scan()
    time.sleep(1)
time.sleep(1)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.actionToggle_scan.setChecked(True)
time.sleep(0.5)
ple_gui.toggle_scan()
time.sleep(0.5)

for plane, config in sweep_definitions_.items():
    plane_name=plane
    field_targets=np.array(config['points'])
    output_folder=config['folder']

    base_output_folder = output_folder
    folder_index = 1
    while os.path.exists(output_folder):
        output_folder = f"{base_output_folder}_{folder_index}"
        folder_index += 1
    os.makedirs(output_folder)
    print(f"Created folder: {output_folder}")
    print(f"\n--- Starting {plane_name} Measurement ---")
    print(f"Output folder: {output_folder}")    
        
    centers = []
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    ple_gui._fit_averaged = False
    ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0] + 1)
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    if ple_gui._mw.number_of_repeats_SpinBox.value() == field_targets.shape[0] + 1:
        
        ple_gui._mw.actionToggle_scan.setChecked(True)
        time.sleep(0.25)
        ple_gui.toggle_scan()
    else:
        ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0] + 1)
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

    time.sleep(4)
    ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("TwoLorentz")
    time.sleep(0.5)
    fit = ple_gui.fit_result[1]
    if 'center_1' in fit.params.keys():
        current_center = fit.params["center_1"].value
        
        centers.append(current_center)
        rngs = tt_laser_scanner._current_scan_ranges[0]
    else:
        current_center = (rngs[1] - rngs[0])/2
    for i, field_target in enumerate(field_targets):
        vector_magnet.ramp(field_target=field_target)
        while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
            time.sleep(1)
        #print("✅ Field reached:", field_target)
        with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
            rngs = tt_laser_scanner._current_scan_ranges[0]
            pos_s = np.linspace(rngs[0], rngs[1], 100)
            v_start, v_end = dlc.laser1.wide_scan.scan_begin.get(), dlc.laser1.wide_scan.scan_end.get()
            vs = np.linspace(v_start, v_end, 100)
            voltage_center = lambda cur_center: vs[np.argmin(np.abs(pos_s - float(cur_center)))]
            time.sleep(1)
            dlc.laser1.wide_scan.continuous_mode.set(False)
            dlc.laser1.wide_scan.trigger.output_enabled.set(True)

            laser_state = dlc._laser1.wide_scan.state.get()
            if laser_state == 0:
                dlc._laser1.wide_scan.start()
            time.sleep(0.5)
            laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(0.5)
            while laser_state != 0:
                time.sleep(1)
                laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(1)
            dlc.laser1.wide_scan.trigger.output_enabled.set(False)
            
            ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("TwoLorentz")
            time.sleep(0.25)
            fit = ple_gui.fit_result[1]
            if 'center_1' in fit.params.keys():
                current_center = fit.params["center_1"].value
            if fit.rsquared < 0.2:
                ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("Lorentzian")
                time.sleep(1)
                fit = ple_gui.fit_result[1]
                if 'center' in fit.params.keys():
                    current_center = fit.params["center"].value
                    

                if fit.rsquared < 0.2:
                    # print("⚠️ Fit quality too low")
                    time.sleep(1)
                    
                    dlc.laser1.wide_scan.value_set.set(voltage_center(current_center))
                    #check_charge_state(min_counts=1000)
                    
                    dlc.laser1.wide_scan.value_set.set(voltage_center(rngs[0]))
                    time.sleep(1)
            if i % 3 == 0:
                #print("⚠️ Optimizing")
                time.sleep(1)
                dlc.laser1.wide_scan.value_set.set(voltage_center(current_center))
                dlc.laser1.amp.cc.current_set.set(2600)
                time.sleep(0.5)
                #check_charge_state(min_counts=500)
                
                dlc.laser1.scan.enabled.set(True)
                
                poi_manager_logic._optimizelogic().start_optimize()

                while poi_manager_logic._optimizelogic().module_state()=='locked':
                    time.sleep(1) # wait for a long time to 

                
                #check_charge_state(min_counts=1000)
                
                dlc.laser1.wide_scan.value_set.set(voltage_center(rngs[0]))
                dlc.laser1.scan.enabled.set(False)
                dlc.laser1.amp.cc.current_set.set(2100)
                dlc.laser1.wide_scan.trigger.output_enabled.set(True)
                time.sleep(0.5)

    tag = f"plane-{plane_name}"
    save_ple(tag=tag, poi_name=None, folder_name=output_folder)
    # Save the array of target fields in the output folder
    np.savetxt(os.path.join(output_folder, "field_targets.csv"), field_targets, delimiter=",", header="Bx,By,Bz", comments="")
    if laser_scanner_logic.module_state()=='locked':
        ple_gui._mw.actionToggle_scan.setChecked(False)
        time.sleep(0.25)
        ple_gui.toggle_scan()
        time.sleep(1)

# %%
all_results = {}
sweep_definitions_ = {i:j for i, j in sweep_definitions.items() if i in ['XZ_arc'] } #
ple_gui._fit_averaged = False



for plane, config in sweep_definitions_.items():
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc.laser1.wide_scan.trigger.output_enabled.set(True)
        dlc.laser1.wide_scan.continuous_mode.set(False)
    while laser_scanner_logic.module_state()=='locked':
        ple_gui._mw.actionToggle_scan.setChecked(False)
        time.sleep(0.25)
        ple_gui.toggle_scan()
        time.sleep(1)
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(0.5)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(0.5)
    ple_gui._mw.actionToggle_scan.setChecked(True)
    time.sleep(0.5)
    ple_gui.toggle_scan()
    time.sleep(0.5)

    plane_name=plane
    field_targets=np.array(config['points'])
    output_folder=config['folder']

    base_output_folder = output_folder
    folder_index = 1
    while os.path.exists(output_folder):
        output_folder = f"{base_output_folder}_{folder_index}"
        folder_index += 1
    os.makedirs(output_folder)
    print(f"Created folder: {output_folder}")
    print(f"\n--- Starting {plane_name} Measurement ---")
    print(f"Output folder: {output_folder}")    
        
    centers = []
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    ple_gui._fit_averaged = False
    ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0])
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    if ple_gui._mw.number_of_repeats_SpinBox.value() == field_targets.shape[0] + 1:
        
        ple_gui._mw.actionToggle_scan.setChecked(True)
        time.sleep(0.25)
        ple_gui.toggle_scan()
    else:
        ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0] + 1)
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

    for i, field_target in enumerate(field_targets):
        repump_with_green(0.1)
        vector_magnet.ramp(field_target=field_target)
        while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
            time.sleep(1)
        #print("✅ Field reached:", field_target)
        with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
            
            time.sleep(1)
            dlc.laser1.wide_scan.continuous_mode.set(False)
            dlc.laser1.wide_scan.trigger.output_enabled.set(True)

            laser_state = dlc._laser1.wide_scan.state.get()
            if laser_state == 0:
                dlc._laser1.wide_scan.start()
            time.sleep(0.5)
            laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(0.5)
            while laser_state != 0:
                time.sleep(1)
                laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(1)
            dlc.laser1.wide_scan.trigger.output_enabled.set(False)
            

    tag = f"plane-{plane_name}"
    save_ple(tag=tag, poi_name=None, folder_name=output_folder)
    # Save the array of target fields in the output folder
    np.savetxt(os.path.join(output_folder, "field_targets.csv"), field_targets, delimiter=",", header="Bx,By,Bz", comments="")
while laser_scanner_logic.module_state()=='locked':
    ple_gui._mw.actionToggle_scan.setChecked(False)
    time.sleep(0.25)
    ple_gui.toggle_scan()
    time.sleep(1)

with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
    dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    dlc.laser1.wide_scan.continuous_mode.set(True)
    
    

# %%
all_results = {}
sweep_definitions_ = {i:j for i, j in sweep_definitions.items() if i in ['XY'] } #'XZ','XY'
ple_gui._fit_averaged = False

with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
    dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    dlc.laser1.wide_scan.continuous_mode.set(False)

while laser_scanner_logic.module_state()=='locked':
    ple_gui._mw.actionToggle_scan.setChecked(False)
    time.sleep(0.25)
    ple_gui.toggle_scan()
    time.sleep(1)

time.sleep(1)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.actionToggle_scan.setChecked(True)
time.sleep(0.5)
ple_gui.toggle_scan()
time.sleep(0.5)

for plane, config in sweep_definitions_.items():
    

    plane_name=plane
    field_targets=np.array(config['points'])
    output_folder=config['folder']

    base_output_folder = output_folder
    folder_index = 1
    while os.path.exists(output_folder):
        output_folder = f"{base_output_folder}_{folder_index}"
        folder_index += 1
    os.makedirs(output_folder)
    print(f"Created folder: {output_folder}")
    print(f"\n--- Starting {plane_name} Measurement ---")
    print(f"Output folder: {output_folder}")    
        
    centers = []
    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    ple_gui._fit_averaged = False
    ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0])
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    if ple_gui._mw.number_of_repeats_SpinBox.value() == field_targets.shape[0] + 1:
        
        ple_gui._mw.actionToggle_scan.setChecked(True)
        time.sleep(0.25)
        ple_gui.toggle_scan()
    else:
        ple_gui._mw.number_of_repeats_SpinBox.setValue(field_targets.shape[0] + 1)
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
        time.sleep(1)
        ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

    for i, field_target in enumerate(field_targets):
        #repump_with_green(5)
        vector_magnet.ramp(field_target=field_target)
        while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
            time.sleep(1)
        #print("✅ Field reached:", field_target)
        with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
            
            time.sleep(1)
            dlc.laser1.wide_scan.continuous_mode.set(False)
            dlc.laser1.wide_scan.trigger.output_enabled.set(True)

            laser_state = dlc._laser1.wide_scan.state.get()
            if laser_state == 0:
                dlc._laser1.wide_scan.start()
            time.sleep(0.5)
            laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(0.5)
            while laser_state != 0:
                time.sleep(1)
                laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(1)
            dlc.laser1.wide_scan.trigger.output_enabled.set(False)
            

    tag = f"plane-{plane_name}"
    save_ple(tag=tag, poi_name=None, folder_name=output_folder)
    # Save the array of target fields in the output folder
    np.savetxt(os.path.join(output_folder, "field_targets.csv"), field_targets, delimiter=",", header="Bx,By,Bz", comments="")
    
# %%
sweep_definitions.items()
# %%
ple_gui._fit_averaged = False
repeats = 3
points = 50
with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
    dlc.laser1.wide_scan.trigger.output_enabled.set(True)
    dlc.laser1.wide_scan.continuous_mode.set(False)

while laser_scanner_logic.module_state()=='locked':
    ple_gui._mw.actionToggle_scan.setChecked(False)
    time.sleep(0.25)
    ple_gui.toggle_scan()
    time.sleep(1)

time.sleep(1)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(0.5)
ple_gui._mw.actionToggle_scan.setChecked(True)
time.sleep(0.5)
ple_gui.toggle_scan()
time.sleep(0.5)

with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
    dlc.laser1.wide_scan.trigger.output_enabled.set(True)
ple_gui._fit_averaged = False
ple_gui._mw.number_of_repeats_SpinBox.setValue(repeats * points)
time.sleep(1)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
time.sleep(1)
ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

if ple_gui._mw.number_of_repeats_SpinBox.value() == repeats * points + 1:
    
    ple_gui._mw.actionToggle_scan.setChecked(True)
    time.sleep(0.25)
    ple_gui.toggle_scan()
else:
    ple_gui._mw.number_of_repeats_SpinBox.setValue(repeats * points + 1)
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()
    time.sleep(1)
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

for b in np.linspace(0.07, 0.095, 50):
    vector_magnet.ramp(field_target=[0,0,b])
    while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
        time.sleep(1)
    for i in range(repeats):
        
        #print("✅ Field reached:", field_target)
        with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
            
            time.sleep(1)
            dlc.laser1.wide_scan.continuous_mode.set(False)
            dlc.laser1.wide_scan.trigger.output_enabled.set(True)

            laser_state = dlc._laser1.wide_scan.state.get()
            if laser_state == 0:
                dlc._laser1.wide_scan.start()
            time.sleep(0.5)
            laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(0.5)
            while laser_state != 0:
                time.sleep(1)
                laser_state = dlc._laser1.wide_scan.state.get()
            time.sleep(1)
            dlc.laser1.wide_scan.trigger.output_enabled.set(True)
            

# %%
