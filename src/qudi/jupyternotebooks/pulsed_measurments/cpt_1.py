#%%
import numpy as np
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro, NetworkConnection
import time
z_bs = np.linspace(0.4, 0.45, 50)  # in Tesla]

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


def prepare_laser_scanner():
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
#%%
prepare_laser_scanner()
z_bs = np.linspace(0, 0.2, 300)  # in Tesla]
for i, zb in enumerate(z_bs):
    # vector_magnet.ramp(field_target= [0.05, -0.3, 0.0])
    vector_magnet.ramp(field_target= [0.05, -0.3, zb])
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
            



    
# %%
