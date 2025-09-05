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


BASE_FOLDER = r'Z:\Vlad\heavyIV\202-2-ARed\CPW-V\B_large4'
B_AMPLITUDE = 0.8  # Tesla
NUM_STEPS = 10     # Number of points
Bx_offset = 0

# Parameters for the small-angle arc sweep
# This defines a 30-degree sweep (+/- 15 degrees) around the Y-axis in the YZ plane.
ARC_SPAN_DEGREES = 20.0 

print("Generating B-field target points for all sweep types...")

# --- Define angles for the full circle sweeps ---
full_circle_angles = np.linspace(0, 2 * np.pi, NUM_STEPS)

# --- Define angles for the YZ arc sweep ---
# The Y-axis in the YZ plane is at 90 degrees (pi/2 radians).
center_angle_rad = np.pi / 2
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
ax.set_ylim([-B_AMPLITUDE, B_AMPLITUDE])
ax.set_zlim([-B_AMPLITUDE, B_AMPLITUDE])
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

def check_charge_state(min_counts=1000):
    def check_counts():
        arr = timetaggerlogic.trace_data[1][1][-5:]
        arr.sort()
        crc_cts = arr[::-1][:5].mean()
        return crc_cts
    attempts = 0
    crc_cts = check_counts()
    while crc_cts < min_counts and attempts < 20:
        repump_with_green(0.25)
        time.sleep(0.25)
        crc_cts = check_counts()
        attempts += 1
    if crc_cts < min_counts:
        raise RuntimeError(f"Charge state could not be restored after {attempts} attempts (counts={crc_cts}).")


def run_planar_sweep(plane_name: str, field_targets: list, output_folder: str):
    """
    Executes a full B-field sweep measurement for a given set of points.
    
    Args:
        plane_name (str): Name of the plane being swept (e.g., 'XY').
        field_targets (list): A list of [Bx, By, Bz] target tuples.
        output_folder (str): The full path to the folder where data will be saved.
    """
    print(f"\n--- 🚀 Starting Measurement for Plane: {plane_name} ---")
    
    # --- Create and verify destination folder ---
    if os.path.exists(output_folder):
        raise FileExistsError(f"The folder '{output_folder}' already exists. Please rename or delete it.")
    os.makedirs(output_folder)
    print(f"Created folder: {output_folder}")
    
    field_targets = np.array(field_targets)

    ple_gui._fit_averaged = False

    ple_gui._mw.number_of_repeats_SpinBox.setValue(
            field_targets.shape[0]
        )
    ple_gui._mw.number_of_repeats_SpinBox.editingFinished.emit()

    ple_gui._mw.actionToggle_scan.setChecked(True)
    ple_gui.toggle_scan()
    time.sleep(0.5)

    with DLCpro(NetworkConnection(dl_pro.tcp_address)) as dlc:
        rngs = tt_laser_scanner._current_scan_ranges[0]
        pos_s = np.linspace(rngs[0], rngs[1], 100)
        v_start, v_end = dlc.laser1.wide_scan.scan_begin.get(), dlc.laser1.wide_scan.scan_end.get()
        vs = np.linspace(v_start, v_end, 100)
        voltage_center = lambda cur_center: vs[np.argmin(np.abs(pos_s - float(cur_center)))]

        dlc.laser1.wide_scan.continuous_mode.set(False)
        centers = []
        c_voltages = []
        while laser_scanner_logic.module_state()=='locked':
            i = 0
            for field_target in tqdm(field_targets, desc=f"{plane_name} Sweep Progress"):
                
                # 1. Ramp the field
                vector_magnet.ramp(field_target=field_target)
                while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
                    time.sleep(1)
                dlc._laser1.wide_scan.start()
                time.sleep(0.5)
                laser_state = dlc._laser1.wide_scan.state.get()
                while laser_state != 0:
                    time.sleep(0.5)
                    laser_state = dlc._laser1.wide_scan.state.get()


                ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("TwoLorentz")
                time.sleep(0.2)
                fit = ple_gui.fit_result[1]
                current_center = fit.params["center_1"].value
                if fit.rsquared < 0.2:
                    ple_gui._fit_dockwidget.fit_widget.sigDoFit.emit("Lorentzian")
                    time.sleep(0.2)
                    fit = ple_gui.fit_result[1]
                    current_center = fit.params["center"].value

                    if fit.rsquared < 0.2:
                        
                        dlc.laser1.wide_scan.value_set.set(voltage_center(current_center))
                        check_charge_state(min_counts=1000)
                        
                       

                else:
                    
                    if i % 3 == 0:
                        dlc.laser1.wide_scan.value_set.set(voltage_center(current_center))
                        check_charge_state(min_counts=1000)
                        # dlc.laser1.scan.enabled.set(True)
                        # dlc.laser1.amp.cc.current_set.set(2600)
                        # go_to_ple_target(current_center_1)
                        
                        poi_manager_logic._optimizelogic().start_optimize()
                        time.sleep(0.5)
                        while poi_manager_logic._optimizelogic().module_state()=='locked':
                            time.sleep(1) # wait for a long time to 

                        time.sleep(0.5)
                        # dlc.laser1.scan.enabled.set(False)
                        # dlc.laser1.amp.cc.current_set.set(2000)

                    

                i+=1
                # 5. Save Data
            tag = f"plane-{plane_name}"
            save_ple(tag=tag, poi_name=None, folder_name=output_folder)
            # Save the array of target fields in the output folder
            np.savetxt(os.path.join(output_folder, "field_targets.csv"), field_targets, delimiter=",", header="Bx,By,Bz", comments="")
        
    print(f"\n✅ --- {plane_name} Measurement Complete! ---")
    return 1

#%%
all_results = {}
sweep_definitions_ = {i:j for i, j in sweep_definitions.items() if i == 'XY_arc' } #
#%%
try:
    print("Waiting for initial vector magnet state...")
    print(f"Ramping:  - Waiting...")
    while list(vector_magnet.get_ramping_state()) != [2, 2, 2]:
        time.sleep(5)
    print("✅ Vector magnet is ready to begin the measurement sequence.")
    # fit = do_ple_scan(lines=1, in_range=laser_scanner_logic.scan_ranges['a'], channel='APD1')
    # if fit.rsquared < 0.4:
    #     exception = RuntimeError(f"Initial PLE scan fit quality is too low (R²={fit.rsquared:.2f}). Please check the system and try again.")
    for plane, config in sweep_definitions_.items():
        results = run_planar_sweep(
            plane_name=plane,
            field_targets=config['points'],
            output_folder=config['folder']
        )
        all_results[plane] = results

except (Exception, KeyboardInterrupt) as e:
    print(f"\n\n❌ An error occurred or the script was interrupted: {e}")
    print("Measurement sequence aborted.")

finally:

    # vector_magnet.ramp(field_target= [0.0,0.0,0.0]) 
    if not all_results:
        print("No measurements were completed.")
    else:
        for plane, splits in all_results.items():
            print(f"\nResults for {plane} Plane:")
            # print(f"  - Data saved in: {sweep_definitions[plane]['folder']}")

    print("\n--- Script finished. ---")

# %%
