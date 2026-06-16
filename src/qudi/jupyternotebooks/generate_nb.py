import nbformat as nbf
import json

nb = nbf.v4.new_notebook()

text = """\
# PLE Peak Analysis — Per-Line Detection
For each scan file, works on INDIVIDUAL scan lines (rows of the cumulative 2D array).
Each line has background ~ 0; a photon burst appears as a clear spike.
Peaks are detected per-line and then only frequencies that are "hot" in
>= MIN_LINE_HITS lines are kept as real peaks. This avoids background buildup
when many lines are summed and makes the result robust for both few and many repetitions."""

code_config = """\
import os, glob
import numpy as np
import matplotlib.pyplot as plt

# ==================== Configuration ====================
DATA_DIR = r'Z:\\Vlad\\heavyIV\\JK\\waveguides_tin_\\annealed-1200\\2\\ple_scan_by_pints\\fast-full'

# --- Per-line peak threshold ---
# A pixel is "hot" if its count > LINE_SIGMA_THRESH * std(line)
# (background ~ 0, so std ≈ noise; tune this if too many/few per-line hits)
LINE_SIGMA_THRESH = 3.0

# Alternative: just use an absolute count threshold per line
# Set to None to use the sigma-based threshold above
LINE_ABS_THRESH = None   # e.g. 50

# --- Consistency filter ---
# How many scan lines must a frequency appear in to be kept as a real peak?
MIN_LINE_HITS = 1   # 1 = take all; 2+ = requires repeatability

# --- Cluster merge: pixels within this many bins are one peak ---
GAP_MERGE_PX = 3

# --- Histogram ---
CENTER_FREQ_THZ = 619.25   # 484 nm ~ 619.4 THz
HIST_RANGE_THZ  = 0.05
BINS = 80

# --- Debug ---
PLOT_DEBUG = True
MAX_PLOTS  = None   # set to int e.g. 5 to limit output
# =======================================================
"""

code_helpers = """\
def extract_metadata(filepath):
    meta = {}
    with open(filepath, 'r') as f:
        for line in f:
            if '---- END HEADER ----' in line:
                break
            if line.startswith('# ') and '=' in line:
                k, v = line[2:].strip().split('=', 1)
                meta[k.strip()] = v.strip().strip("'")
    return meta

def parse_float(meta, key, default=None):
    try:
        return float(meta.get(key, default))
    except (TypeError, ValueError):
        return default

def peaks_in_line(line, sigma_thresh=3.0, abs_thresh=None, gap_px=3):
    \"\"\"
    Find hot clusters in ONE scan line.
    Returns array of pixel indices (position of max in each cluster).
    \"\"\"
    # Threshold: absolute OR sigma-based
    noise = line.std()
    if abs_thresh is not None:
        threshold = abs_thresh
    else:
        # Use median (robust to outliers) + sigma * noise
        threshold = np.median(line) + sigma_thresh * noise if noise > 0 else sigma_thresh

    above = np.where(line > threshold)[0]
    if len(above) == 0:
        return np.array([], dtype=int)

    # Cluster neighbouring pixels
    clusters, current = [], [above[0]]
    for idx in above[1:]:
        if idx - current[-1] <= gap_px:
            current.append(idx)
        else:
            clusters.append(current)
            current = [idx]
    clusters.append(current)

    # Return position of maximum in each cluster
    return np.array([np.array(c)[np.argmax(line[np.array(c)])] for c in clusters], dtype=int)
"""

code_detect = """\
all_peak_freqs = []
scan_debug = {}

file_pattern = os.path.join(DATA_DIR, '*__cummulative_1D-scan_*APD2*.dat')
file_list = sorted(glob.glob(file_pattern))
print(f'Found {len(file_list)} cumulative APD2 scan files.')

for filepath in file_list:
    fname = os.path.basename(filepath)
    meta  = extract_metadata(filepath)

    wm_nm = parse_float(meta, 'wavemeter_start_wl_nm', 0.0)
    if not wm_nm:
        print(f'  SKIP (no wavemeter): {fname}')
        continue

    a_min = parse_float(meta, 'a axis min', 0.0)
    a_max = parse_float(meta, 'a axis max', 21600.0)
    a_res = int(parse_float(meta, 'a axis resolution', 2000))

    try:
        raw = np.loadtxt(filepath, comments='#')
    except Exception as e:
        print(f'  Could not load {fname}: {e}')
        continue

    if raw.ndim == 1:
        raw = raw[np.newaxis, :]
    n_lines, n_px = raw.shape

    # Frequency axis
    c    = 299792458.0
    f0   = (c / (wm_nm * 1e-9)) / 1e12
    f_ax = f0 + np.linspace(a_min, a_max, a_res)[:n_px] * 1e6 / 1e12

    # ---- Per-line peak detection ----
    hit_count = np.zeros(n_px, dtype=int)   # how many lines have a hot pixel here

    line_peaks_list = []
    for line in raw:
        lp = peaks_in_line(line,
                           sigma_thresh=LINE_SIGMA_THRESH,
                           abs_thresh=LINE_ABS_THRESH,
                           gap_px=GAP_MERGE_PX)
        line_peaks_list.append(lp)
        hit_count[lp] += 1

    # ---- Consistency filter: keep pixels hot in >= MIN_LINE_HITS lines ----
    consistent = np.where(hit_count >= MIN_LINE_HITS)[0]

    # Re-cluster the consistent pixels and take max of hit_count in each cluster
    if len(consistent) > 0:
        clusters, current = [], [consistent[0]]
        for idx in consistent[1:]:
            if idx - current[-1] <= GAP_MERGE_PX:
                current.append(idx)
            else:
                clusters.append(current)
                current = [idx]
        clusters.append(current)

        final_peaks = np.array([
            np.array(c)[np.argmax(hit_count[np.array(c)])] for c in clusters
        ], dtype=int)
    else:
        final_peaks = np.array([], dtype=int)

    for p in final_peaks:
        all_peak_freqs.append(f_ax[p])

    scan_debug[fname] = dict(
        f=f_ax, raw=raw, hit_count=hit_count,
        final_peaks=final_peaks, n_lines=n_lines,
        line_peaks_list=line_peaks_list
    )

print(f'\\nTotal peaks found: {len(all_peak_freqs)}')
"""

code_debug = """\
# =============================================================
# DEBUG: for each scan, show:
#   Top  - hit-count bar chart with final peaks
#   Mid  - summed spectrum for reference
#   Bot  - 2D waterfall (as in PLE GUI)
# =============================================================
if PLOT_DEBUG:
    n_shown = 0
    for fname, d in scan_debug.items():
        if MAX_PLOTS is not None and n_shown >= MAX_PLOTS:
            break

        fig, axes = plt.subplots(3, 1, figsize=(13, 7), sharex=True,
                                  gridspec_kw={'height_ratios': [1.5, 1.5, 1]})

        # ---- top: hit count (how many lines triggered at each frequency) ----
        ax0 = axes[0]
        ax0.bar(d['f'], d['hit_count'], width=(d['f'][1]-d['f'][0]),
                color='dodgerblue', alpha=0.7, label='line hit-count')
        ax0.axhline(MIN_LINE_HITS, color='grey', ls=':', lw=0.8,
                    label=f'MIN_LINE_HITS = {MIN_LINE_HITS}')
        if len(d['final_peaks']) > 0:
            ax0.plot(d['f'][d['final_peaks']], d['hit_count'][d['final_peaks']],
                     'rv', ms=10, zorder=6, label=f'{len(d["final_peaks"])} peaks')
        ax0.set_ylabel('Lines triggered')
        ax0.legend(loc='upper right', fontsize=8)
        ax0.set_title(fname, fontsize=8)

        # ---- mid: summed spectrum ----
        ax1 = axes[1]
        summed = d['raw'].sum(axis=0)
        ax1.plot(d['f'], summed, color='steelblue', lw=0.9, label='summed counts')
        if len(d['final_peaks']) > 0:
            for p in d['final_peaks']:
                ax1.axvline(d['f'][p], color='red', lw=0.8, ls='--', alpha=0.6)
        ax1.set_ylabel('Counts (sum)')
        ax1.legend(loc='upper right', fontsize=8)

        # ---- bottom: 2D waterfall ----
        ax2 = axes[2]
        ax2.imshow(d['raw'], aspect='auto',
                   extent=[d['f'][0], d['f'][-1], 0, d['n_lines']],
                   cmap='hot', origin='lower', vmin=0)
        for p in d['final_peaks']:
            ax2.axvline(d['f'][p], color='cyan', lw=1.0, ls='--', alpha=0.9)
        ax2.set_xlabel('Absolute Frequency (THz)')
        ax2.set_ylabel('Line #')

        plt.tight_layout()
        plt.show()
        n_shown += 1
"""

code_hist = """\
# =============================================================
# Global histogram
# =============================================================
if len(all_peak_freqs) > 0:
    arr = np.array(all_peak_freqs)
    print(f'Peak range: {arr.min():.6f} to {arr.max():.6f} THz  ({len(arr)} total)')

    plt.figure(figsize=(10, 5))
    bounds = (CENTER_FREQ_THZ - HIST_RANGE_THZ, CENTER_FREQ_THZ + HIST_RANGE_THZ)
    inside = arr[(arr >= bounds[0]) & (arr <= bounds[1])]
    print(f'Plotting {len(inside)} peaks in [{bounds[0]:.5f}, {bounds[1]:.5f}] THz')

    plt.hist(inside, bins=BINS, color='skyblue', edgecolor='black')
    plt.axvline(CENTER_FREQ_THZ, color='red', ls='--', lw=2,
                label=f'Center: {CENTER_FREQ_THZ:.4f} THz')
    plt.title('Distribution of PLE Peaks')
    plt.xlabel('Absolute Frequency (THz)')
    plt.ylabel('Occurrences')
    plt.xlim(bounds)
    plt.legend()
    plt.tight_layout()
    plt.show()
else:
    print('No peaks found. Try lowering LINE_SIGMA_THRESH or MIN_LINE_HITS.')
"""

nb['cells'] = [
    nbf.v4.new_markdown_cell(text),
    nbf.v4.new_code_cell(code_config),
    nbf.v4.new_code_cell(code_helpers),
    nbf.v4.new_code_cell(code_detect),
    nbf.v4.new_markdown_cell("## Debug\n"
        "**Top**: hit-count per frequency bin across all scan lines (real peaks repeat).  \n"
        "**Mid**: summed spectrum for reference.  \n"
        "**Bottom**: raw 2D waterfall as in PLE GUI, with detected peaks as cyan lines."),
    nbf.v4.new_code_cell(code_debug),
    nbf.v4.new_markdown_cell("## Global Histogram"),
    nbf.v4.new_code_cell(code_hist),
]

out = r'c:/Users/yy3/GIT/squdi/src/qudi/jupyternotebooks/ple_peak_analysis.ipynb'
with open(out, 'w', encoding='utf-8') as fh:
    nbf.write(nb, fh)
print("Done:", out)
