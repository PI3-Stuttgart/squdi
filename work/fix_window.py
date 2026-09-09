from pathlib import Path
p=Path('src/qudi/logic/nuclear_ops/extended_recipes.py');s=p.read_text().replace('windows[:, 0] >= windows_ns[:, 1]', 'windows[:, 0] >= windows[:, 1]');p.write_text(s)
