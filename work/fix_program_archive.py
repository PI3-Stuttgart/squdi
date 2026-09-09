from pathlib import Path
p=Path('src/qudi/logic/nuclear_ops/execution_engine.py');s=p.read_text().replace('if not getattr(self.quantum_machine, "dummy_mode", False):\n                from qm import generate_qua_script', 'if type(bundle.program).__module__.startswith("qm."):\n                from qm import generate_qua_script');p.write_text(s)
