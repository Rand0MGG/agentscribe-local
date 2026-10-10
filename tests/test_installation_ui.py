"""Shared settings display; isolated preferences, mocked updates, no audio."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('width,height', [(1280, 900), (900, 650)])
def test_update_settings_and_inline_storage_path(tmp_path, width, height):
    code = '''
import os
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QPushButton
from linguaflow.app import STYLE, Window
from linguaflow.updates import RELEASE_PAGE
app = QApplication([])
app.setStyleSheet(STYLE)
folder = Path(os.environ['FIXTURE_DIRECTORY'])
w = Window(discover=False, library_root=folder/'recordings',
           prefs=QSettings(str(folder/'prefs.ini'), QSettings.Format.IniFormat))
w.resize(int(os.environ['FIXTURE_WIDTH']), int(os.environ['FIXTURE_HEIGHT']))
w.reduce_motion.setChecked(True)
w.show()
app.processEvents()
w.open_settings('运行环境')
w.settings_workspace.search.setText('更新')
assert w.settings_workspace.title.text() == '运行环境'
manager = w.model_manager
button = next(b for b in manager.findChildren(QPushButton) if b.text() == '检查软件更新')
assert button.isEnabled()
assert manager.update_link.isHidden()
manager.show_update({'url': RELEASE_PAGE + '/tag/v0.6.0'})
assert not manager.update_link.isHidden()
manager.show_update({'url': 'https://evil.example/file.exe'})
assert manager.update_link.isHidden()
manager.show_update({'url': RELEASE_PAGE + '/tag/v0.6.0'})
manager.status.setText('发现 0.6.0。当前为源码运行，请在发行页查看对应源码；更新前保留本地修改。')
app.processEvents()
w.grab().save(str(folder/'runtime.png'))
w.settings_workspace.search.clear()
w.open_settings('常规')
from linguaflow.runtime_paths import resource_root
w.settings_workspace.set_storage_root(resource_root()/'录音')
assert w.settings_workspace.storage_path.text() == str(resource_root()/'录音')
assert w.settings_workspace.storage_path.parentWidget().objectName() == 'settingsRow'
assert not hasattr(w.settings_workspace, 'storage_warning')
app.processEvents()
w.grab().save(str(folder/'storage.png'))
assert w.session is None
assert 'soundcard' not in __import__('sys').modules
w.close()
'''
    environment = {**os.environ, 'FIXTURE_DIRECTORY': str(tmp_path), 'FIXTURE_WIDTH': str(width), 'FIXTURE_HEIGHT': str(height)}
    if os.environ.get('AGENTSCRIBE_NATIVE_UI') == '1':
        environment.pop('QT_QPA_PLATFORM', None)
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30, env=environment)
    assert result.returncode == 0, result.stdout + result.stderr


def test_slow_update_check_does_not_block_local_recording_and_save(tmp_path):
    from test_beta_features import run_ui
    run_ui('''
from threading import Event
from linguaflow.core import Caption
from PySide6.QtWidgets import QMessageBox
w.device.addItem('fixture',('fixture',False));w.translate.setChecked(False)
assert w.new_recording(name='更新期间录音')
started,finish=Event(),Event()
def slow_download():
    started.set()
    assert finish.wait(8)
    return '下载完成'
jobs=[]
def update_check(module, callback, *args):
    assert module=='linguaflow.updates'
    jobs.append(callback)
w.model_manager.start_check=update_check
w.model_manager.prepare(slow_download)
assert w.model_manager.update_button.isEnabled()
w.model_manager.check_updates()
assert w.model_manager.update_busy
w.model_manager.check_updates()
assert len(jobs)==1
wait(started.is_set)
def unexpected(*args): raise AssertionError('Update checks must not prevent recording')
QMessageBox.information=unexpected
class FakeSession(QObject):
    status=Signal(str);stage=Signal(str,str);ready=Signal();paused=Signal(bool)
    caption=Signal(object);level=Signal(float);source_changed=Signal(int);failure=Signal(str);finished=Signal()
    def __init__(self,settings,parent,recording_path,runtime=None):
        super().__init__(parent);self.model_ready=Event()
    def start(self): self.model_ready.set();self.ready.emit()
    def stop(self): self.finished.emit()
module.Session=FakeSession
try:
    w.start(models_checked=True);assert w.session is not None
    w.session.caption.emit(Caption(1,0,1,'Saved during update','en'))
    w.stop();wait(lambda:w.session is None)
    assert w.library.load(w.current_item)[1][0].source=='Saved during update'
    assert w.model_manager.worker is not None
    jobs[0]({'url':'','message':'当前已是最新版本（0.6.0-beta.2）。','version':'0.6.0-beta.2','kind':'none'})
    assert not w.model_manager.update_busy
    assert '最新版本' in w.model_manager.update_status.text()
    assert w.model_manager.worker is not None
    w.model_manager.check_updates()
    assert w.model_manager.update_busy
    jobs[1](None)
    assert not w.model_manager.update_busy and w.model_manager.update_button.isEnabled()
    assert '无法检查更新' in w.model_manager.update_status.text()
    assert w.model_manager.update_link.isHidden()
finally:
    finish.set();wait(lambda:w.model_manager.worker is None)
    w.close();app.processEvents()
''', tmp_path)
