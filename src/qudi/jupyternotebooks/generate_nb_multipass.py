import nbformat as nbf
import json

nb = nbf.v4.new_notebook()

text = """# Multipass PLE Peak Analysis
This notebook analyzes automated multi-point PLE scans that cover overlapping frequency ranges for a single spatial point. It extracts wavemeter measurements from the headers to assign absolute frequencies to scans. Crucially, it resolves overlapping peaks by merging identical peaks detected across different voltage passes (Central, Lower, Higher)."""

code1 = """import os
import glob
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks

# --- Configuration ---
DATA_DIR = r'Z:\\Vlad\\heavyIV\\JK\\waveguides_tin_\\annealed-1200\\2\\ple_scan_by_pints\\fast-full'
PLOT_ALL_SCANS = False # Set to True to see individual scan peak detections

# Peak finding settings
PEAK_PROMINENCE = 1.0  
PEAK_WIDTH = (10, 200)

# Deduplication Threshold in THz (e.g. 0.002 = 2 GHz)
DEDUPE_THRESHOLD_THZ = 0.002

# Histogram settings
CENTER_FREQ_THZ = 484.130
HIST_RANGE_THZ = 0.05 # +- 0.05 THz around center
BINS = 100
"""

code2 = """def extract_metadata(filepath):
    metadata = {}
    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('# ---- END HEADER ----'):
                break
            if line.startswith('# '):
                line_clean = line[2:].strip()
                if '=' in line_clean:
                    parts = line_clean.split('=', 1)
                    if len(parts) == 2:
                        metadata[parts[0].strip()] = parts[1].strip()
    return metadata

def parse_val(val_str):
    try:
        if val_str.startswith("'") and val_str.endswith("'"):
             val_str = val_str[1:-1]
        return float(val_str)
    except:
        return None

# Dictionary to hold peak lists per point_index
point_peaks = {}

file_pattern = os.path.join(DATA_DIR, '*__averaged_1D-scan_*.dat')
file_list = glob.glob(file_pattern)
print(f'Found {len(file_list)} averaged scan files.')

for file_idx, filepath in enumerate(file_list):
    meta = extract_metadata(filepath)
    
    # Needs to be a valid wavemeter reading
    wm_start_nm = parse_val(meta.get('wavemeter_start_wl_nm', '0.0'))
    
    if wm_start_nm is None or wm_start_nm == 0.0:
        continue # skip invalid wavemeter readings
        
    point_idx = parse_val(meta.get('automated_point_index', '-1'))
    if point_idx is None or point_idx < 0:
        continue
        
    c = 299792458.0 # m/s (in vacuum)
    f_start_thz = (c / (wm_start_nm * 1e-9)) / 1e12
    
    a_min = parse_val(meta.get('a axis min', '0.0'))
    a_max = parse_val(meta.get('a axis max', '21600.0'))
    a_res = parse_val(meta.get('a axis resolution', '2000'))
    
    if None in [a_min, a_max, a_res]:
        continue
    
    # Load data array
    try:
        data = np.loadtxt(filepath, comments='#') 
    except Exception as e:
        print(f"Could not load {os.path.basename(filepath)}: {e}")
        continue
        
    if data.ndim > 1:
        data = data.flatten()
    
    # Make frequency axis
    f_axis_mhz = np.linspace(a_min, a_max, int(a_res))
    f_axis_thz = f_start_thz + (f_axis_mhz * 1e6) / 1e12
    
    if len(f_axis_thz) != len(data):
        min_len = min(len(f_axis_thz), len(data))
        f_axis_thz = f_axis_thz[:min_len]
        data = data[:min_len]
    
    # Peak Detection
    peaks, properties = find_peaks(data, prominence=PEAK_PROMINENCE, width=PEAK_WIDTH)
    
    if point_idx not in point_peaks:
        point_peaks[point_idx] = []
        
    for p in peaks:
        point_peaks[point_idx].append(f_axis_thz[p])
        
    if PLOT_ALL_SCANS and len(peaks) > 0:
        plt.figure(figsize=(8,3))
        plt.plot(f_axis_thz, data, alpha=0.7)
        plt.plot(f_axis_thz[peaks], data[peaks], 'rx')
        plt.title(f"Point {int(point_idx)} - Peaks: {os.path.basename(filepath)}")
        plt.xlabel('Abs Freq (THz)')
        plt.ylabel('Counts')
        plt.show()

# --- Deduplicate overlapping peaks ---
# A feature might be picked up on both the Central and Lower scans.
# If they are within DEDUPE_THRESHOLD_THZ, merge them.
all_unique_peaks = []
total_duplicate_merges = 0
total_raw_peaks = 0

for pt, freqs in point_peaks.items():
    total_raw_peaks += len(freqs)
    if not freqs:
        continue
        
    freqs.sort()
    merged_peaks = [freqs[0]]
    
    for f in freqs[1:]:
        # Compare to last accepted peak
        last_f = merged_peaks[-1]
        if f - last_f <= DEDUPE_THRESHOLD_THZ:
             # Merge (average them)
             merged_peaks[-1] = (last_f + f) / 2.0
             total_duplicate_merges += 1
        else:
             merged_peaks.append(f)
             
    all_unique_peaks.extend(merged_peaks)

print(f"Analysis complete.")
print(f"Found {total_raw_peaks} raw peaks across all scans.")
print(f"Merged {total_duplicate_merges} duplicate peaks from overlapping passes.")
print(f"Total unique peaks across all points: {len(all_unique_peaks)}")
"""

code3 = """# Generate Histogram
if len(all_unique_peaks) > 0:
    plt.figure(figsize=(10, 6))
    
    # Filter bounds
    bounds = (CENTER_FREQ_THZ - HIST_RANGE_THZ, CENTER_FREQ_THZ + HIST_RANGE_THZ)
    filtered_freqs = [f for f in all_unique_peaks if bounds[0] <= f <= bounds[1]]
    
    print(f"Plotting {len(filtered_freqs)} peaks in the range {bounds[0]:.3f} to {bounds[1]:.3f} THz")
    
    plt.hist(filtered_freqs, bins=BINS, color='mediumpurple', edgecolor='black')
    plt.axvline(CENTER_FREQ_THZ, color='red', linestyle='dashed', linewidth=2, label=f'Center: {CENTER_FREQ_THZ} THz')
    
    plt.title('Distribution of De-duplicated Multi-Pass PLE Peaks')
    plt.xlabel('Absolute Frequency (THz)')
    plt.ylabel('Number of Occurrences')
    plt.xlim(bounds)
    plt.legend()
    plt.tight_layout()
    plt.show()
else:
    print("No unique peaks found within the filtering range.")
"""

nb['cells'] = [nbf.v4.new_markdown_cell(text),
               nbf.v4.new_code_cell(code1),
               nbf.v4.new_code_cell(code2),
               nbf.v4.new_code_cell(code3)]

nb_path = 'c:/Users/yy3/GIT/squdi/src/qudi/jupyternotebooks/ple_multipass_peak_analysis.ipynb'
with open(nb_path, 'w') as f:
    nbf.write(nb, f)
print("Multipass setup Notebook generated successfully!")
