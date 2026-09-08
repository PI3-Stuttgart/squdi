"""Direct Swabian gated counter for finite NuclearOps programs.

The SDK is imported only on activation. Raw event streams remain QM-sourced;
this module replaces gated counts, not the QM CRC decision or time tags.
"""
import time
import numpy as np
from qudi.core.configoption import ConfigOption
from qudi.interface.nuclear_counter_interface import NuclearCounterInterface


def gate_names(context):
    names = ["initial_counts", "result_counts", "csr_counts"]
    if context.experiment.recipe in ("optical_rabi", "optical_power_rabi", "spin_photon_correlation"):
        names.insert(1, "optical_counts")
    return names


class NuclearTimeTaggerCounter(NuclearCounterInterface):
    serial = ConfigOption(name="serial", default="")
    click_channel = ConfigOption(name="click_channel", default=1)
    begin_channel = ConfigOption(name="begin_channel", default=2)
    end_channel = ConfigOption(name="end_channel", default=3)

    def on_activate(self):
        import TimeTagger
        self._api = TimeTagger
        self._tagger = TimeTagger.createTimeTagger(str(self.serial))
        self._measurement = None

    def on_deactivate(self):
        self.stop()
        self._api.freeTimeTagger(self._tagger)

    def arm(self, context):
        self.stop()
        names = gate_names(context)
        n = context.block.qua_points * int(context.parameters.get("integrations", 1)) * len(names)
        channel = int(context.parameters.get("click_channel", self.click_channel))
        self._measurement = self._api.CountBetweenMarkers(
            self._tagger, channel, int(self.begin_channel), int(self.end_channel), n_values=n)

    def read_streams(self, context, control, timeout_s):
        deadline = time.monotonic() + timeout_s
        while not self._measurement.ready():
            control.check_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("External counter did not receive all gate markers")
            # Pausing is acknowledged at a program boundary; acquisition must drain.
            time.sleep(.01)
        values = np.asarray(self._measurement.getData())
        names = gate_names(context)
        integrations = int(context.parameters.get("integrations", 1))
        expected = integrations * context.block.qua_points * len(names)
        if values.size != expected or not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("External counter returned incomplete or invalid counts")
        values = values.reshape(integrations, context.block.qua_points, len(names))
        result = {}
        for i, name in enumerate(names):
            result[name + "_shots"] = values[:, :, i]
            result[name] = values[:, :, i].mean(axis=0)
        return result

    def stop(self):
        if getattr(self, "_measurement", None) is not None:
            self._measurement.stop()
            self._measurement = None
