#%% 
from PySide2.QtCore import QTimer, QTime, Signal
import time
import numpy as np
import os
import os
import sys

# Get the absolute path of the current script
script_path = os.path.abspath(r"C:\Users\YY3\GIT\squdi\src\qudi\jupyternotebooks\hom")
# Get the directory name of the script path
script_dir = os.path.dirname(script_path)
# Change the working directory to the script's directory
os.chdir(script_dir)
from hom import auto
from hom.auto import *
from hom.tools import *
# %gui qt
#%%
folder_save = r'Z:\Vlad\SnV\TPI\Electrodes_e4\F2\atto3-def1\bf_def1\24-07-attempt-I'
current_cryo = 'atto3' #fix the notation of current and non-active cryo
non_active_cryo = 'bf'
integrate_for_mins = 180
values = [0, -.2, -.5, -0.8, -1.13]  #the counts have to be equalized!

params = {
    'ple_gui': ple_gui,
    'laser_scanner_logic': laser_scanner_logic,
    'scanner_gui' : scanner_gui,
    'scanning_data_logic' : scanning_data_logic,
    'pulsestreamer' : pulsestreamer,
    'timetaggerlogic': timetaggerlogic,
    'timetagger': timetagger,
    'timetagger_remote': timetagger_remote,
    'poi_manager_logic_remote': poi_manager_logic_remote,
    'switchlogic': switchlogic,
    'ibeam_smart_remote': ibeam_smart_remote,
    'powercontroller_logic': powercontroller_logic,
    'integrate_for_mins': integrate_for_mins,
    'current_cryo': current_cryo,
    'non_active_cryo': non_active_cryo,
    'folder_save': folder_save,
    'values': values,
}

measurement_e_hom = auto.StarkHOM(ao_electrodes_remote, **params)  

#PREPS
# Define the green BF min and max motor positions
measurement_e_hom.min_position = 110
measurement_e_hom.max_position = 190
#Define the max attorty green power
measurement_e_hom.max_power = 30e3
#Define perpendicular polarizations

# %%
 