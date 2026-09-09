from pathlib import Path
p=Path('src/qudi/logic/nuclear_ops/snv_qua_recipes.py');s=p.read_text()
s=s.replace('            save_tags = context.experiment.execution.save_raw_events', '            external = context.experiment.execution.acquisition_mode == AcquisitionMode.EXTERNAL_COUNTER\n            save_tags = context.experiment.execution.save_raw_events and not external')
s=s.replace('            def readout(lasers, duration_ns):', '            def readout(lasers, duration_ns, count_with_qm=True):')
a=s.index('                qua.measure(\n', s.index('            def readout('));b=s.index('                for laser in lasers:',a)
old=s[a:b];s=s[:a]+'                if count_with_qm:\n'+''.join('    '+line+'\n' for line in old.splitlines())+'                else:\n                    qua.wait(self._cycles(duration_ns), spcm)\n                    qua.assign(counts, 0)\n'+s[b:]
s=s.replace('                qua.play("trigit", element, duration=4)', '                qua.play("trigit", element, duration=self._cycles(parameters.get("gate_trigger_ns", 20)))')
s=s.replace('                readout(lasers, duration_ns)\n', '                readout(lasers, duration_ns, count_with_qm=not external)\n')
s=s.replace('            def manipulate():\n', '''            def manipulate():
                custom = getattr(self, "pulse_function", None)
                if custom is not None:
                    from types import SimpleNamespace
                    q = SimpleNamespace(qua=qua, mw=mw, laser=pulse, align=qua.align,
                        wait=lambda duration: qua.wait(self._cycles(duration)),
                        phase=lambda turns: qua.frame_rotation_2pi(turns, mw_element),
                        reset_phase=lambda: qua.reset_frame(mw_element))
                    custom(q, dict(parameters, **axis_variables))
                    qua.align()
                    return
''')
a=s.index('                qua.measure("readout", spcm, None,', s.index('            def optical_readout():'));b=s.index('                qua.align()',a)
old=s[a:b];s=s[:a]+'                if not external:\n'+''.join('    '+line+'\n' for line in old.splitlines())+'                else:\n                    qua.wait(self._cycles(parameters.get("optical_window_ns", 1000)), spcm)\n                    qua.assign(counts, 0)\n'+s[b:]
s=s.replace('            def point():\n', '''            def point():
                if "mw_frequency" in parameters:
                    qua.update_frequency(mw_element, int(parameters["mw_frequency"]))
                for key, element, inputs in (
                    ("laser_620_voltage", "Laser_620", ("AOM_1", "AOM_2")),
                    ("laser_620_det_voltage", "Laser_620_det", ("single",)),
                    ("laser_520_voltage", "Laser_520", ("single",))):
                    if key in parameters:
                        for input_name in inputs:
                            qua.set_dc_offset(element, input_name, parameters[key])
''')
s=s.replace('        if context.experiment.execution.save_raw_events:\n            width', '''        if context.experiment.execution.save_raw_events and context.experiment.execution.acquisition_mode == AcquisitionMode.EXTERNAL_COUNTER:
            if not hasattr(job, "raw_events"):
                raise ValueError("External counting requires Swabian raw data, not QM tags")
            raw = job.raw_events
            for name, lengths in job.raw_lengths.items():
                dataset[name + "_tag_lengths"] = (("record", "integration"), lengths)
            dataset.attrs["raw_time_unit"] = "ps"
            dataset.attrs["raw_source"] = "Swabian"
        elif context.experiment.execution.save_raw_events:
            width''')
s=s.replace('        return AcquisitionResult(MeasurementBatch(dataset, raw))', '        dataset.attrs["count_source"] = "Swabian" if context.experiment.execution.acquisition_mode == AcquisitionMode.EXTERNAL_COUNTER else "QM"\n        dataset.attrs["crc_source"] = "QM"\n        return AcquisitionResult(MeasurementBatch(dataset, raw))')
p.write_text(s)
p=Path('src/qudi/logic/nuclear_ops/counter_streams.py');s=p.read_text().replace('        self._streams = streams', '        self._streams = dict(streams)\n        self.raw_events = self._streams.pop("_raw_events", {})\n        self.raw_lengths = self._streams.pop("_raw_lengths", {})');p.write_text(s)
p=Path('src/qudi/logic/nuclear_ops/extended_recipes.py');s=p.read_text().replace('        lengths = ds.optical_tag_lengths.values', '        if ds.attrs.get("raw_time_unit") == "ps":\n            windows = windows * 1000\n        lengths = ds.optical_tag_lengths.values');p.write_text(s)
