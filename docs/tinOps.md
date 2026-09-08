# tinOps on Windows

`tinOps.cfg` is a standalone offline configuration for local Qudi Core and the
IQO modules. Set `dummy_mode: true` on `QuantumMachineHardware` to activate
without importing the QM SDK or lab configuration and without any connection
attempt. Synthetic acquisitions exercise the actual runner, persistent queue,
threshold snapshots, HDF5 writer, raw-event decoding, analysis and GUI.

On this PC, both local repositories are installed editable in the existing
`C:\Users\Colin\anaconda3\envs\squdi` environment. Start with:

```powershell
& C:\Users\Colin\anaconda3\envs\squdi\python.exe -m qudi.core --config C:\Git\squdi\src\qudi\configs\tinOps.cfg
```

The local core uses `global.startup_modules`, not the older `global.startup`.
Its main GUI also requires `qtconsole`, installed in this environment.

## GUI workflow

1. Select a recipe and click **Load recipe template**.
2. Edit the specification. Scan values, units, execution location and integration
   count are explicit. Import/export buttons exchange JSON specifications.
3. Click **Add to queue**, then **Start queue**. Completion advances to the next
   pending item. **Hold queue** prevents the next experiment from starting.
4. **Pause run** is cooperative at program boundaries. **Cancel run** halts the
   current job. Completed records are preserved after cancellation.
5. Use **Live results & fits** to view acquired points. Select a completed queue
   entry and **Plot selected result** to show saved fit curves and uncertainties.
6. **Reanalyze selected result** uses the thresholds embedded in that run.
7. The threshold editor creates a new version; existing files retain their
   original threshold snapshot. Calibration recommendations are not applied
   automatically.

Data defaults to `~/Documents/qudi/tinOps/runs`, and the queue to
`~/Documents/qudi/tinOps/queue.h5`. The QM dummy seed and dummy marker are stored
in hardware provenance. Dummy mode skips physical lab services; it does not
verify their implementations or simulate QUA timing.

## Recipe and data additions

- The six original finite spin recipes now save individual integration counts
  as well as means. Threshold classification uses the individual counts.
- Optional raw tags cover initial, result, CSR and optical windows. Each record
  concatenates integrations; `<channel>_tag_lengths(record, integration)` gives
  the exact split points. Tags are in ns relative to each readout, not global
  timestamps. Saturated tag buffers invalidate the block.
- The additional recipe module supplies finite optical Rabi, optical voltage
  Rabi, PLE voltage scanning, initialization-duration calibration, field-angle
  scanning and spin-photon correlation. Optical excitation has a separate
  count/tag stream. Spin-photon results include windowed herald counts and
  conditional spin probability with ambiguous SSR outcomes excluded.
- Rabi/Ramsey use damped cosines; Hahn/T1/init use stretched exponentials;
  resonance scans use Lorentzians. Fits are separated by other scan axes,
  excluding sweep counters. Insufficient data and failed fits remain explicit.
- SSR calibration with both prepared states calculates candidate thresholds
  and balanced classification accuracy. These are in-sample diagnostics.

## External gated counter

`acquisition_mode: external_counter` now requires a `NuclearCounterInterface`
connector. `timetagger.nuclear_counter.NuclearTimeTaggerCounter` implements this
using the separately installed Swabian SDK. It arms before QUA execution,
waits with timeout/cancellation, decodes finite counts in scan order, and stops
on success and error. The recipe emits Gate_Trigger/Memory_Trigger pairs around
initial, optical (when present), result and CSR gates. CRC remains QM-controlled.
Raw tags remain QM-sourced; this is not an external raw-timestamp recorder.

Configure actual serial and click/begin/end channels explicitly. Do not wire
the old `GatedCounter` facade to this new interface. The adapter follows
[Swabian's CountBetweenMarkers contract](https://www.swabianinstruments.com/static/documentation/TimeTagger/api/measurements/event_counting.html).

## Limits requiring lab work

This is an offline-testable implementation, **not certified legacy hardware
parity**. Native QUA source generation is tested; compilation and timing on a
specific QOP/controller are not. Keep the legacy userscripts.

Optical power/frequency conversions, laser offsets, digital delays, PPG pulse
shapes and detector routing must use measured setup calibration. Voltage axes
are explicitly volts and must not be interpreted as calibrated nW or MHz.
The spin-photon recipe currently uses one configured QM detector; the old
second-ZPL-APD path and external raw-click processing are not ported.

Setup-specific red-refocus staging, laser-power checks, CW/pulsed ODMR refocus,
interferometer locks and yellow-repump compensation still require dedicated
service migration. Existing generic refocus services remain unchanged. No
simulation result establishes that these legacy procedures are equivalent.

## Checks

Run from outside the repository root to avoid its unrelated top-level `py.py`
shadowing third-party tools:

```powershell
& C:\Users\Colin\anaconda3\envs\squdi\python.exe -m unittest discover -s C:\Git\squdi\tests\nuclear_ops -t C:\Git\squdi -v
```

The QM SDK is optional for dummy use; native-generation tests skip without it.
The external-counter tests use a finite fake counter and do not certify a
physical Time Tagger or its wiring.
