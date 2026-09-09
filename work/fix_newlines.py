from pathlib import Path
p=Path('work/threshold_gui.py');s=p.read_text();s=s.replace("s=p.read_text(encoding='utf-8')", "s=p.read_text(encoding='utf-8').replace('\\n\\n', '\\n')");p.write_text(s)
