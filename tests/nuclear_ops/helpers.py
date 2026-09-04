from qudi.logic.nuclear_ops.models import (
    ExperimentSpec,
    ReadoutStep,
    ScanAxis,
    StabilizationPolicy,
)


def experiment_spec(name="Nuclear Rabi"):
    return ExperimentSpec(
        recipe="nuclear_rabi",
        name=name,
        scan_axes=(
            ScanAxis("sweep", (0, 1), execution="qua"),
            ScanAxis("tau", (10.0, 20.0), unit="ns", execution="qua"),
        ),
        parameters={"mw_frequency": 202.36e6},
        readout=(ReadoutStep("ssr", "ssr_e1", "electron_state", repetitions=5),),
        stabilization=StabilizationPolicy(
            ple_refocus_interval_s=120.0,
            lock_laser_to_wavemeter=True,
        ),
        metadata={"purpose": "storage test"},
    )
