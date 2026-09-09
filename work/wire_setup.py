from pathlib import Path
p=Path('src/qudi/logic/nuclear_ops/execution_engine.py');s=p.read_text()
s=s.replace('        run_path_factory: Callable', '        setup_provider=None,\n        run_path_factory: Callable')
s=s.replace('        self.recipes = recipes', '        self.setup_provider = setup_provider\n        self.recipes = recipes')
s=s.replace('                observations = self.services.before_block(experiment, block, self._control)', '''                setup = self.setup_provider() if self.setup_provider else {"revision": 0, "values": {}}
                effective = replace(experiment, parameters=dict(setup["values"], **experiment.parameters))
                observations = dict(self.services.before_block(effective, block, self._control))
                observations["setup_revision"] = setup["revision"]''')
s=s.replace('                    recipe, experiment, block, threshold_snapshot, observations, run', '                    recipe, effective, block, threshold_snapshot, observations, run')
s=s.replace('            run.store.save_program_metadata(block.index, attempt, bundle.metadata)', '''            program_metadata = dict(bundle.metadata)
            program_metadata.update(effective_parameters=context.parameters,
                                    setup_revision=observations.get("setup_revision", 0),
                                    thresholds=threshold_snapshot.to_dict(), scan_block=block.to_dict())
            if not getattr(self.quantum_machine, "dummy_mode", False):
                from qm import generate_qua_script
                program_metadata["qua_source"] = generate_qua_script(bundle.program)
            run.store.save_program_metadata(block.index, attempt, program_metadata)''')
p.write_text(s)
p=Path('src/qudi/logic/nuclear_ops/nuclear_operations_logic.py');s=p.read_text()
s=s.replace('    sigDataUpdated =', '    setup_file = ConfigOption(name="setup_file", default="~/Documents/qudi/tinOps/setup.h5")\n    userscript_directory = ConfigOption(name="userscript_directory", default="")\n    sigSetupChanged = QtCore.Signal(object)\n    sigSetupError = QtCore.Signal(str)\n    sigCounterUpdated = QtCore.Signal(object)\n    sigDataUpdated =')
s=s.replace('    def on_activate(self):\n        self._recipes', '    def on_activate(self):\n        from .setup_parameters import SetupRegistry\n        self._setup = SetupRegistry(self.setup_file)\n        self._recipes')
s=s.replace('        self.sigRecipesChanged.emit(self._recipes.names)\n\n    def on_deactivate', '''        from .userscripts import UserScriptRecipe
        self._recipes.register(UserScriptRecipe())
        self._counter = self._optional(self.external_counter)
        if self._counter is not None and hasattr(self._counter, "sigCounterUpdated"):
            self._counter.sigCounterUpdated.connect(self.sigCounterUpdated)
        self.sigRecipesChanged.emit(self._recipes.names)

    @property
    def setup_snapshot(self):
        return self._setup.snapshot()

    @QtCore.Slot(object)
    def update_setup(self, values):
        try:
            self.sigSetupChanged.emit(self._setup.update(values))
        except Exception as exc:
            self.sigSetupError.emit(str(exc))

    @property
    def userscript_paths(self):
        path = Path(str(self.userscript_directory)).expanduser() if self.userscript_directory else Path(__file__).parents[2] / "UserScripts/nuclear_ops"
        return tuple(sorted(path.glob("*.py")))

    def script_specification(self, source, filename):
        from .userscripts import specification
        return specification(source, filename)

    def on_deactivate''')
s=s.replace('        self._engine = None\n        self._worker = None\n        self._active_item_id = ""\n\n    @property', '        if self._counter is not None and hasattr(self._counter, "sigCounterUpdated"):\n            self._counter.sigCounterUpdated.disconnect(self.sigCounterUpdated)\n        self._engine = None\n        self._worker = None\n        self._active_item_id = ""\n\n    @property')
s=s.replace('        return NuclearExperimentEngine(\n', '''        if machine.dummy_mode:
            services = RunServices()
            services.external_counter = self._counter
        return NuclearExperimentEngine(
            setup_provider=self._setup.snapshot,
''').replace('            services=RunServices() if machine.dummy_mode else services,', '            services=services,')
s=s.replace('    @staticmethod\n    def _provenance(machine):', '    def _provenance(self, machine):')
s=s.replace('        snapshot = machine.configuration_snapshot', '        from .userscripts import source_archive\n        snapshot = machine.configuration_snapshot')
s=s.replace('            hardware={"quantum_machine": snapshot},', '''            hardware={"quantum_machine": snapshot,
                      "counter": getattr(self._counter, "configuration_snapshot", {}),
                      "initial_setup": self.setup_snapshot,
                      "source_archive": source_archive()},''')
s=s.replace('("qudi", "qm-qua", "xarray", "h5py")', '("qudi-core", "qudi-iqo-modules", "qm-qua", "xarray", "h5py", "numpy", "scipy", "PySide2", "Swabian-TimeTagger")')
p.write_text(s)
p=Path('src/qudi/hardware/OPX/quantum_machine_hardware.py');s=p.read_text().replace('            "module": str(self.configuration_module),', '            "configuration": configuration,\n            "module": str(self.configuration_module),');p.write_text(s)
p=Path('src/qudi/configs/tinOps.cfg');s=p.read_text().replace('hardware:\n', '''hardware:
    tinOps_timetagger:
        module.Class: 'timetagger.nuclear_counter.NuclearTimeTaggerCounter'
        options:
            dummy_mode: true
''').replace('            quantum_machine: tinOps_qm', '            quantum_machine: tinOps_qm\n            external_counter: tinOps_timetagger');p.write_text(s)
