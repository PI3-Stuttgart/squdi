# NuclearOps replacement

This package is the Quantum-Machines-native execution path for nuclear
experiments. It does not import the legacy `qudi.logic.NuclearOPs` runner or
the Keysight compatibility layer. The legacy module remains present while
recipes are migrated and compared on hardware.

## Architectural rules

1. An `ExperimentSpec` is immutable and fully serializable. Queue entries store
   specifications, never imported userscript modules or live callables.
2. All CRC, CSR, and SSR thresholds are named rules in a versioned global
   `ReadoutThresholdProfile`. The runner resolves a profile when a run starts
   and stores the resulting `ThresholdSnapshot` in the run file.
3. Acquired and derived numerical data use `xarray.Dataset`. Every streaming
   acquisition batch has a leading `record` dimension. Scan axes are
   record-dependent coordinates; readout names and histogram bins can be
   static trailing coordinates.
4. Everything required to reproduce a run is stored in one HDF5 file. Metadata,
   experiment configuration, provenance, thresholds, queue state, raw events,
   numerical data, and logs occupy separate HDF5 groups. Pickle and JSON
   sidecars are not used.
5. Queue state is persisted to its own HDF5 file after every mutation. Only one
   item may be active. An item left active after process termination is marked
   failed by default or explicitly requeued through configuration.

## Run-file layout

```text
run.h5
  /data/coordinates
  /data/variables
  /data/coordinate_attributes
  /data/variable_attributes
  /raw/<channel>/events
  /raw/<channel>/shot_offsets
  /analysis
  /programs/block_<n>/attempt_<n>
  /metadata
  /experiment
  /provenance
  /thresholds
  /queue
  /logs
```

The root attribute `committed_records` is the transaction boundary. Data arrays
are extended first and the marker advances only after the entire batch has been
flushed. Opening a run file invokes recovery and truncates incomplete writes.

Raw time tags are represented by a flattened event array and one offset per
shot. This avoids object arrays and variable-length pickled Python objects.

## Qudi modules

- `ReadoutCalibrationLogic` owns the persistent threshold registry.
- `ExperimentQueueLogic` owns the sequential persistent queue and communicates
  with a `NuclearOperationsRunnerInterface` implementation only through queued
  Qt signals.
- `NuclearOperationsLogic` is the queue-facing runner. It owns no GUI state and
  performs work in one cooperative worker thread.
- `QuantumMachineHardware` executes and simulates QUA programs directly. It
  intentionally has no `mcas_dict`, AWG facade, or sequence-name cache.

Recipes subclass `ExperimentRecipe`; finite native result streams should use
`QmStreamRecipe`. Recipe modules configured on `NuclearOperationsLogic` expose
one function:

```python
def register_recipes(registry):
    registry.register(MyRabiRecipe())
```

The additive Qudi wiring is shown in
`qudi/configs/nuclear_ops_qm_example.cfg`. Optional connectors may be omitted;
the runner raises a focused error only if an experiment requests the missing
service.

A queue item is a value object rather than an executable user script:

```python
ExperimentSpec(
    recipe="nuclear_rabi",
    name="SnV nuclear Rabi",
    scan_axes=(
        ScanAxis("B_amp", (120, 130), unit="mT", execution="host"),
        ScanAxis("pulse_length", tuple(range(20, 4000, 100)), unit="ns", execution="qua"),
    ),
    parameters={"mw_frequency": 202.36e6},
    readout=(ReadoutStep("ssr", "ssr_e1", "ssr_counts"),),
    threshold_profile="default",
)
```

## Retained operational behavior

The execution and service layers retain deterministic fast/slow scan grouping,
arbitrarily many QUA axes, recompilation axes, magnet scans (including the SnV
defect-frame transform), live SMIQ changes, fixed SMIQ setup, click-channel
selection, PPG waveform changes, periodic green/red confocal and PLE refocus,
wavemeter locking, quiet hours, manual pause/resume, cooperative cancellation,
debug simulation, invalid-readout retries, raw time tags, threshold analysis,
progress reporting, and sequential queue continuation.

The empty `dowork`/ZPL placeholders, DataFrame/object-column storage, pickle or
CSV fallbacks, GUI calls from the runner, two-fast-axis limit, and AWG-shaped
Keysight compatibility are deliberately absent.

Pulse-sequence parity is recipe-specific. Do not delete a legacy Qinu script
until its new recipe has passed simulation and a hardware comparison using the
same threshold-profile snapshot.

`snv_qua_recipes` currently supplies finite native-stream implementations for
Nuclear Rabi, Ramsey, Hahn echo, T1, pulsed ODMR and SSR calibration. Optical
Rabi/power-Rabi, PLE iterator, initialization calibration, field alignment and
spin-photon-correlation scripts still need dedicated recipe migration because
their hardware timing and result shapes are not interchangeable with the
common spin protocol.
