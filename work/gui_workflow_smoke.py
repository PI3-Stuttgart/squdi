import sys
import json
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, 'C:/Git/squdi/src')
from PySide2 import QtCore, QtWidgets
from qudi.core.application import Qudi

root = Path(__file__).parent.resolve()
output = root / ('gui-smoke-' + uuid4().hex[:8]); output.mkdir()
config = Path('C:/Git/squdi/src/qudi/configs/tinOps.cfg').read_text()
config = config.replace('~/Documents/qudi/tinOps', output.as_posix())
config = config.replace('18862', '18863')
config = config.replace("output_directory:", "setup_file: '" + (output/'setup.h5').as_posix() + "'\n            output_directory:")
(output/'test.cfg').write_text(config)
app = QtWidgets.QApplication([])
q = Qudi(config_file=str(output/'test.cfg'), log_dir=str(output))
state = {'phase': 'start', 'ticks': 0, 'counter': False, 'live': False}

def tick():
    if not q.is_running:
        return
    state['ticks'] += 1
    try:
        gui = q.module_manager['tinOps'].instance
        queue = q.module_manager['tinOps_queue'].instance
        runner = q.module_manager['tinOps_runner'].instance
        if state['phase'] == 'start':
            assert gui.window.isVisible()
            assert len(gui._scripts) == 12
            gui.recipe.setCurrentText('nuclear_rabi'); gui.load_template()
            assert 'def pulses' in gui.editor.toPlainText()
            gui.enqueue(); gui.sigStart.emit()
            state['phase'] = 'running'
        if gui.counter_progress.value() > 0:
            state['counter'] = True
        items = queue.queue_snapshot['items']
        if state['phase'] == 'running' and state['counter'] and not state['live']:
            gui.setup_widgets['mw_amplitude'].setValue(.6)
            gui.apply_setup(); state['live'] = True
        if items and items[-1]['status'] in ('completed', 'failed', 'cancelled'):
            assert items[-1]['status'] == 'completed', items[-1]
            from qudi.logic.nuclear_ops.hdf5_store import NuclearDataset
            run = NuclearDataset.open(items[-1]['run_file'])
            assert run.dataset.attrs['count_source'] == 'Swabian'
            assert run.dataset.attrs['raw_time_unit'] == 'ps'
            assert state['counter'] and state['live']
            assert runner.setup_snapshot['revision'] > 1
            assert 'def pulses' in run.store.load_section('experiment')['metadata']['userscript']['source']
            assert run.store.load_section('provenance')['hardware']['source_archive']
            for index, name in [(0, 'userscript'), (3, 'setup'), (4, 'counter')]:
                gui.tabs.setCurrentIndex(index)
                gui.window.grab().save(str(output/(name+'.png')))
            (output/'passed.json').write_text(json.dumps({'status': 'passed', 'run': items[-1]['run_file']}))
            print('GUI_WORKFLOW_PASS', output, flush=True)
            timer.stop(); q.quit()
        elif state['ticks'] > 120:
            raise TimeoutError(str(items))
    except Exception:
        import traceback
        (output/'error.txt').write_text(traceback.format_exc())
        traceback.print_exc(); timer.stop(); q.quit()

timer = QtCore.QTimer(); timer.timeout.connect(tick); timer.start(250)
q.run()
