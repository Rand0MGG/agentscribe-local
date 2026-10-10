import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native application menu')
def test_native_version_menu_and_update_entry(tmp_path):
    code = '''
import os
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from linguaflow import __version__
from linguaflow.app import Window
app = QApplication([])
app.setApplicationName('AgentScribe')
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
w.show()
app.processEvents()
assert w.menuBar().isNativeMenuBar()
assert w.about_action.menuRole() == QAction.MenuRole.AboutRole
assert w.update_action.menuRole() == QAction.MenuRole.ApplicationSpecificRole
w.about_action.trigger()
app.processEvents()
assert w.about_dialog.isVisible() and __version__ in w.about_dialog.informativeText()
w.about_dialog.accept()
w.version_action.trigger()
assert w.pages.currentWidget() is w.settings_workspace
assert w.settings_workspace.navigation.currentItem().text() == '运行环境'
assert __version__ in w.model_manager.version_label.text()
assert w.model_manager.version_label.isVisible()
calls = []
w.model_manager.check_updates = lambda: calls.append('check')
w.update_action.trigger()
assert calls == ['check']
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'cocoa',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_startup_update_check_is_independent_quiet_and_nonmodal(tmp_path):
    code = '''
import os, time
from threading import Event
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow import updates
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
calls = []
def check(module, callback, *arguments):
    if module == 'linguaflow.updates':
        calls.append(callback)
    else:
        QTimer.singleShot(0, lambda: callback([]))
    return object()
w.start_background_check = check
w.check_startup_updates()
w.check_startup_updates()
ticks = []
timer = QTimer()
timer.timeout.connect(lambda: ticks.append(1))
timer.start(5)
deadline = time.monotonic()+1
while len(ticks)<3 and time.monotonic()<deadline:
    app.processEvents()
    time.sleep(.005)
assert len(ticks)>=3 and len(calls) == 1 and w.model_manager.worker is None
calls[0]({'kind': 'none'})
app.processEvents()
assert not hasattr(w, 'update_dialog')
w.on_startup_update_checked({'kind':'package', 'version':'0.6.0-beta.2',
    'message':'新版已发布', 'url':updates.RELEASE_PAGE+'/tag/v0.6.0-beta.2'})
assert w.update_dialog.isVisible()
assert w.update_dialog.windowModality() == Qt.WindowModality.NonModal
assert '0.6.0-beta.2' in w.model_manager.version_label.text()
w.update_dialog.accept()
w.close()
w.on_startup_update_checked({'kind':'package', 'url':updates.RELEASE_PAGE+'/tag/v0.6.0-beta.3'})
assert not w.update_dialog.isVisible()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=12,
                            env={**os.environ, 'QT_QPA_PLATFORM':'offscreen',
                                 'AGENTSCRIBE_LIBRARY':str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_hidden_settings_fixed_context_and_responsive_preparation(tmp_path):
    code = '''
import os, time
from threading import Event
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.recording_state import RecordingState
app = QApplication([])
prefs = QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat)
prefs.setValue('translation_before', 10)
prefs.setValue('translation_after', 2)
prefs.setValue('translation_initial_before', 0)
w = Window(discover=False, prefs=prefs)
workspace, manager = w.settings_workspace, w.model_manager
def check(module, callback, *arguments):
    QTimer.singleShot(20, lambda: callback(['Qwen3-ASR 1.7B · MLX 4-bit', 'HY-MT2 1.8B · Q4_K_M']))
    return object()
w.start_background_check = check
visible = [workspace.categories[i] for i in range(workspace.navigation.count())
           if not workspace.navigation.item(i).isHidden()]
assert visible == ['常规', '聆听', '模型管理', '使用指南']
assert manager.translation_before.isHidden() and manager.translation_after.isHidden()
settings = w.settings_binding.session_settings(('file', False))
assert (settings.translation_before, settings.translation_after, settings.translation_initial_before) == (5, 1, 1)
w.set_recording_state(RecordingState.LISTENING)
w.source.setCurrentIndex((w.source.currentIndex()+1) % w.source.count())
assert prefs.value('source') == w.source.currentText()
assert w.settings_panel.isEnabled() and manager.isEnabled()
release = Event()
def action():
    manager.worker.download.emit({'label': 'weights', 'completed': 50, 'total': 100, 'unit': 'B', 'rate': 10})
    assert release.wait(3)
    return 'prepared'
manager.prepare(action)
w.open_settings('使用指南')
ticks = []
timer = QTimer()
timer.timeout.connect(lambda: ticks.append(1))
timer.start(5)
deadline = time.monotonic()+2
while len(ticks) < 3 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.005)
assert len(ticks) >= 3 and manager.worker is not None
assert manager.tabs.isEnabled() and manager.done_button.isEnabled()
assert manager.progress_bar.value() == 500
assert '50' not in manager.status.text() or 'MB' in manager.status.text()
release.set()
while manager.worker is not None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.005)
assert manager.worker is None
if hasattr(w, 'model_guidance'):
    w.check_model_assets()
    deadline = time.monotonic()+2
    while '首次使用' not in w.model_guidance.text() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert '首次使用' in w.model_guidance.text() and 'Qwen3-ASR' in w.model_guidance.text()
w.set_recording_state(RecordingState.IDLE)
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=12,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr


def test_knowledge_cleanup_dispatches_ui_events_and_guards_file_changes(tmp_path):
    code = '''
import os, time
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
class Process:
    stdin = stdout = stderr = None
    code = None
    def poll(self): return self.code
    def terminate(self): pass
    def wait(self, timeout):
        time.sleep(.2)
        self.code = 0
w.knowledge_client.process = Process()
w.knowledge_client.epoch = 'old'
ticks, guards = [], []
timer = QTimer()
def tick():
    ticks.append(1)
    guards.append(w.can_edit_library())
timer.timeout.connect(tick)
timer.start(10)
assert w.close_knowledge()
timer.stop()
assert len(ticks) >= 3 and not any(guards)
assert not w.knowledge_client.closing and w.knowledge_client.process is None
assert 'soundcard' not in __import__('sys').modules
w.close()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=12,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
