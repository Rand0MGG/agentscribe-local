import os

from ui_support import run_ui_process


def test_knowledge_cleanup_dispatches_ui_events_and_guards_file_changes(tmp_path):
    code = '''
import os
from threading import Event
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
events_serviced = Event()
class Process:
    stdin = stdout = stderr = None
    code = None
    def poll(self): return self.code
    def terminate(self): pass
    def wait(self, timeout):
        # Completion depends on UI dispatch, not on host scheduling in 200 ms.
        assert events_serviced.wait(timeout), 'cleanup blocked the Qt event loop'
        self.code = 0
w.knowledge_client.process = Process()
w.knowledge_client.epoch = 'old'
import linguaflow.process_platform as process_module
process_module.stop_tree = lambda process, **kwargs: process.terminate()
ticks, guards = [], []
timer = QTimer()
def tick():
    if w.knowledge_client.closing:
        ticks.append(1)
        guards.append(w.can_edit_library())
        if len(ticks) >= 3:
            events_serviced.set()
timer.timeout.connect(tick)
timer.start(10)
assert w.close_knowledge()
timer.stop()
assert len(ticks) >= 3 and not any(guards)
assert not w.knowledge_client.closing and w.knowledge_client.process is None
assert 'soundcard' not in __import__('sys').modules
w.close()
'''
    run_ui_process(code, timeout=12,
                   env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
