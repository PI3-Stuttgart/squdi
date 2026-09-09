from pathlib import Path
root=Path('src/qudi/UserScripts/nuclear_ops');root.mkdir(parents=True, exist_ok=True)
examples={
'nuclear_rabi': ('q.mw(p["pulse_length"])', 'pulse_length', 'np.arange(40, 4040, 100)', 'ns'),
'ramsey': ('q.mw(p["electron_pi_duration_ns"] / 2)\n    q.wait(p["tau"])\n    q.phase(p.get("last_phase", 0.0))\n    q.mw(p["electron_pi_duration_ns"] / 2)\n    q.reset_phase()', 'tau', 'np.arange(40, 4040, 100)', 'ns'),
'hahn_echo': ('q.mw(p["electron_pi_duration_ns"] / 2)\n    q.wait(p["tau"])\n    q.mw(p["electron_pi_duration_ns"])\n    q.wait(p["tau"])\n    q.mw(p["electron_pi_duration_ns"] / 2)', 'tau', 'np.arange(40, 8040, 200)', 'ns'),
't1': ('q.wait(p["readout_delay"])', 'readout_delay', 'np.arange(40, 80040, 2000)', 'ns'),
'pulsed_odmr': ('q.qua.update_frequency("MW", p["MW_f"])\n    q.mw(p["electron_pi_duration_ns"])', 'MW_f', 'np.arange(190000000, 210000001, 500000)', 'Hz'),
'ssr_calibration': ('q.align()  # Common initialization and SSR gates only.', 'sweeps', 'range(40)', ''),
'initialization_calibration': ('q.align()  # Sweep the shared initialization pulse duration.', 'electron_init_duration_ns', 'np.arange(40, 8040, 200)', 'ns'),
'field_alignment': ('q.mw(p["electron_pi_duration_ns"])', 'B_theta', 'np.linspace(0, 20, 21)', 'deg'),
'ple_iterator': ('q.align()  # Shared PLE voltage update and optical readout gates.', 'laser_frequency_voltage', 'np.linspace(-0.1, 0.1, 41)', 'V'),
'optical_rabi': ('q.laser("Laser_620_pi", p["optical_duration_ns"])', 'optical_duration_ns', 'np.arange(16, 816, 20)', 'ns'),
'optical_power_rabi': ('q.laser("Laser_620_pi", p["optical_duration_ns"])', 'optical_voltage', 'np.linspace(0, 0.2, 41)', 'V'),
'spin_photon_correlation': ('q.laser("Laser_620_pi", p["optical_duration_ns"])', 'sweeps', 'range(40)', ''),
}
for name,(body,axis,values,unit) in examples.items():
    fixed='{"integrations": 20}' if name!='field_alignment' else '{"integrations": 20, "B_amp": 0.0}'
    repeat='"init_state": ("e1", "e2")' if name=='ssr_calibration' else '"repeat": range(4)'
    repeat_name='init_state' if name=='ssr_calibration' else 'repeat'
    execution='host' if name=='field_alignment' else 'qua'
    text=f'''"""{name.replace('_',' ').title()}: pulses above, experiment settings below.
CRC/initialization/SSR/CSR and Swabian gate markers are shared snippets.
Setup defaults come from the live Setup tab; PARAMETERS overrides are explicit.
"""
import numpy as np


def pulses(q, p):
    {body}


# ---- Sweeping parameters ----
NAME = "{name.replace('_',' ').title()}"
PROTOCOL = "{name}"
PARAMETERS = {fixed}
SWEEPS = {{{repeat}, "{axis}": {values}}}
UNITS = {{"{axis}": "{unit}"}}
AXIS_EXECUTION = {{"{repeat_name}": "recompile", "{axis}": "{execution}"}}
SAVE_RAW = True
'''
    (root/(name+'.py')).write_text(text)
p=Path('src/qudi/logic/nuclear_ops/snv_qua_recipes.py');s=p.read_text();s=s.replace('            def manipulate():\n                custom', '            def custom_pulses():\n                custom')
s=s.replace('                    return\n                pi_ns =', '''                    return

            def manipulate():
                if getattr(self, "pulse_function", None) is not None:
                    if self.protocol not in (SnVProtocol.OPTICAL_RABI, SnVProtocol.OPTICAL_POWER_RABI, SnVProtocol.SPIN_PHOTON):
                        custom_pulses()
                    return
                pi_ns =''',1)
s=s.replace('                    custom(q, dict(parameters, **axis_variables))\n                    qua.align()', '                    custom(q, dict(parameters, **axis_variables))')
s=s.replace('                pulse(optical_laser, value("optical_duration_ns", default=48))\n','')
s=s.replace('                qua.align()\n                if external:\n                    marker("Memory_Trigger")\n                qua.save(counts, streams["optical_counts"])', '''                if getattr(self, "pulse_function", None) is not None:
                    custom_pulses()
                else:
                    pulse(optical_laser, value("optical_duration_ns", default=48))
                qua.align()
                if external:
                    marker("Memory_Trigger")
                qua.save(counts, streams["optical_counts"])''')
p.write_text(s)
