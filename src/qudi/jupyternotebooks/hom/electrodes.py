#%%
import nidaqmx as ni
import time
import numpy as np
import json
import schedule
import os
from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro,LaserHead,  NetworkConnection, DeviceNotFoundError
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
    return ple_gui.fit_result[1], 

#%%
ao_task = ni.Task('NIAoTask' + 'ao3'.replace(':', ' '))
ao_phys_ch = '/Dev1/ao3'
ao_task.ao_channels.add_ao_voltage_chan(physical_channel=ao_phys_ch,
                                        min_val=-1.5,
                                        max_val=1.5)

# %%
ao_task.write(-0)
# %%
res = do_ple_scan(lines=5, in_range=laser_scanner_logic.scan_ranges["a"])
# %%
