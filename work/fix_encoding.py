from pathlib import Path
p=Path('src/qudi/gui/nuclear_ops/nuclear_ops_gui.py')
s=p.read_bytes().decode('utf-8', errors='surrogateescape')
s=''.join(bytes([ord(c)-0xdc00]).decode('cp1252') if 0xdc80<=ord(c)<=0xdcff else c for c in s)
p.write_text(s,encoding='utf-8')
p=Path('tests/nuclear_ops/test_offline.py');s=p.read_text();s=s.replace("self.assertIn('result_tags', source)", "self.assertNotIn('result_tags', source)\n                self.assertEqual(source.count('time_tagging.analog'), 1)");p.write_text(s)
