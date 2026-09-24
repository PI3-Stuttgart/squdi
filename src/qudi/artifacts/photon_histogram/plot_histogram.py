from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

source = Path(r'C:\Users\yy3\qudi\Data\2026\09\2026-09-12\timetaggerlogic\20260912-0853-08_hist_data_trace_godd_tins_everywhere_2.dat')
output = Path(__file__).resolve().parent
raw = source.read_text()
bin_width_s = float(re.search(r'^# bin width=(.+)$', raw, re.MULTILINE).group(1))
expected_bins = int(re.search(r'^# number of bins=(.+)$', raw, re.MULTILINE).group(1))
counts = np.loadtxt(source)
assert counts.ndim == 1 and len(counts) == expected_bins
assert np.all(np.isfinite(counts)) and np.all(counts >= 0)
bin_width_ns = bin_width_s * 1e9
edges = np.arange(len(counts) + 1) * bin_width_ns
centers = (edges[:-1] + edges[1:]) / 2
positive = counts > 0

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
fig, ax = plt.subplots(figsize=(9, 5.3), constrained_layout=True)
ax.stairs(np.where(positive, counts, np.nan), edges, baseline=None,
          color='#176b9b', linewidth=1.3)
ax.scatter(centers[positive], counts[positive], s=10, color='#176b9b', zorder=3)
ax.set_yscale('log')
ax.set_xlim(0, edges[-1])
ax.set_ylim(max(0.5, counts[positive].min() * 0.7), counts.max() * 1.6)
ax.set_xlabel('Delay from trigger (ns)')
ax.set_ylabel('Photon counts per 0.5 ns bin (log scale)')
ax.set_title('Photon arrival-time histogram', loc='left', fontsize=17, pad=28)
ax.text(0, 1.025, '12 Sep 2026, 08:53:08  |  Channel 2  |  Trigger 5  |  140 bins',
        transform=ax.transAxes, fontsize=10, color='#555555')
ax.grid(which='major', color='#dddddd', linewidth=0.7)
ax.grid(which='minor', axis='y', color='#eeeeee', linewidth=0.5)
ax.set_axisbelow(True)
ax.spines[['top', 'right']].set_visible(False)
if not np.all(positive):
    ax.text(0.98, 0.95, f'Zero-count bins omitted: {np.count_nonzero(~positive)}',
            transform=ax.transAxes, ha='right', va='top', fontsize=9, color='#555555')
for extension in ('png', 'svg'):
    fig.savefig(output / f'photon_histogram_log.{extension}', dpi=200)
print(f'Bins: {len(counts)}; bin width: {bin_width_ns:g} ns; total counts: {counts.sum():g}; zero bins: {np.count_nonzero(~positive)}')
print(output / 'photon_histogram_log.png')
