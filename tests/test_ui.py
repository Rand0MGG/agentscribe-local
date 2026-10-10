import os
import subprocess
import sys


def test_main_prepares_runtime_after_show_and_closes_on_quit():
    code = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
import linguaflow.app as module
calls=[]
timers=[]
single_shot=QTimer.singleShot
def schedule(delay, callback):
    timers.append((delay, callback.__name__))
    if callback.__name__ == 'check_startup_updates':
        assert calls == ['shown']
    single_shot(delay, callback)
module.QTimer.singleShot=schedule
class Runtime:
    def prepare(self):
        assert calls==['shown']
        calls.append('prepared')
        QTimer.singleShot(0,QApplication.instance().quit)
    def close(self,wait=True):
        assert not wait
        calls.append('closed')
class Window(QWidget):
    def __init__(self,runtime):
        super().__init__()
        assert isinstance(runtime,Runtime)
    def show(self):
        super().show()
        calls.append('shown')
    def check_startup_updates(self):
        raise AssertionError('Update check must not delay showing or runtime preparation')
module.RuntimePreparation=Runtime
module.Window=Window
try: module.main()
except SystemExit as exc: assert exc.code==0
assert calls==['shown','prepared','closed'],calls
assert (1500, 'check_startup_updates') in timers
"""
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10,
                          env={**os.environ,'QT_QPA_PLATFORM':'offscreen'})
    assert result.returncode==0,result.stderr


def test_background_autosave_keeps_new_revisions_dirty_and_rejects_other_recording_results(tmp_path):
    code = """
import os
from threading import Event, get_ident
from dataclasses import replace
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption
from linguaflow.recording_save import SaveSnapshot
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
assert w.new_recording(name='autosave')
first = Caption(1, 0, 1, 'first', 'en')
w.on_caption(first)
release, original, threads = Event(), w.library.save, []
def slow(item, captions, state):
    threads.append(get_ident())
    assert release.wait(3)
    original(item, captions, state)
w.library.save = slow
main_thread = get_ident()
w.queue_session_save()
assert w.recording_saver.busy and w.session_dirty
w.on_caption(replace(first, source='latest', revision=2))
release.set()
assert w.recording_saver.flush(3000)
assert w.session_dirty  # Older save completion cannot clear the new revision.
assert threads and all(t != main_thread for t in threads)
w.library.save = original
assert w.persist_session('complete') and not w.session_dirty
assert w.library.load(w.current_item)[1][0].source == 'latest'
old = SaveSnapshot((w.save_generation, w.current_item['id']), w.caption_version,
                   w.current_item.copy(), (), 'complete')
assert w.new_recording(name='next')
w.on_caption(Caption(1, 0, 1, 'next recording', 'en'))
w.on_saved(old, 'complete', '')
assert w.session_dirty and w.current_item['state'] == 'draft'
def fail(*args): raise OSError('disk unavailable')
w.library.save = fail
assert not w.persist_session() and w.session_dirty
assert '保存失败' in w.status.text()
w.library.save = original
assert w.persist_session() and not w.session_dirty
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_finish_does_not_dispose_signal_sender_while_background_save_is_pending(tmp_path):
    code = """
import os
from threading import Event
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
assert w.new_recording(name='finish ordering')
w.caption_translation = False
w.on_caption(Caption(1, 0, 1, 'source', 'en'))
saved, original = Event(), w.library.save
emitting = False
submit = w.recording_saver.submit
def submit_after_signal(*args):
    assert not emitting, 'Save worker started inside finished.emit()'
    return submit(*args)
w.recording_saver.submit = submit_after_signal
def write(*args):
    original(*args)
    saved.set()
w.library.save = write
class Session(QObject):
    finished = Signal()
    def deleteLater(self):
        assert saved.is_set(), 'Signal sender disposed before the nested save loop'
        assert not w.recording_saver.busy
        super().deleteLater()
session = Session(w)
w.session = session
session.finished.connect(w.on_finished)
emitting = True
session.finished.emit()
session.finished.emit()  # Duplicate completion cannot dispose/save twice.
emitting = False
assert not saved.is_set() and w.session is session
assert not w.start_button.isEnabled()
app.processEvents()
assert saved.is_set() and not w.session_dirty and w.session is None
assert w.start_button.isEnabled()
assert w.new_recording(name='next session')
w.on_caption(Caption(1, 0, 1, 'new source', 'en'))
next_session = Session(w)
w.session = next_session
next_session.finished.connect(w.on_finished)
session.finished.emit()  # A late sender cannot finish the replacement session.
app.processEvents()
assert w.session is next_session and w.captions[1].source == 'new source'
next_session.finished.emit()
app.processEvents()
assert w.session is None and w.library.load(w.current_item)[1][0].source == 'new source'
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_failed_retranslation_preserves_text_and_corrupt_recording_is_rejected(tmp_path):
    code = """
import os, json
from dataclasses import replace
from types import SimpleNamespace
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox
from linguaflow.app import Window
from linguaflow.core import Caption
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY']+'/prefs.ini', QSettings.Format.IniFormat))
assert w.new_recording(name='regression')
w.caption_translation = True
c = Caption(1, 0, 1, 'source', 'en', translation='usable translation')
w.on_caption(c)
w.on_caption(replace(c, translation='', error='inference failed'))
assert w.captions[1].translation == 'usable translation'
assert w.captions[1].error == 'inference failed'
# A source correction must not inherit a translation of the old source.
w.on_caption(replace(c, id=2, source='old'))
w.on_caption(replace(c, id=2, source='new', revision=2, translation='', error='failed'))
assert not w.captions[2].translation
w.on_caption(Caption(3, 2, 3, 'final source', 'en', translation='initial translation',
                     translation_phase='initial', translation_source='old source'))
w.translate.setChecked(False)  # Completion uses the recorded session settings.
w.session = SimpleNamespace(deleteLater=lambda: None)
w.on_finished()
app.processEvents()
data, captions = w.library.load(w.current_item)
assert data['session']['state'] == 'incomplete'
assert captions[0].translation == 'usable translation'
assert captions[2].translation == 'initial translation' and captions[2].error
assert '部分翻译未完成' in w.status.text()
# Successful retry clears the error and permits complete state.
w.on_caption(replace(c, translation='updated'))
w.on_caption(replace(c, id=2, source='new', revision=2, translation='new translated'))
w.on_caption(Caption(3, 2, 3, 'final source', 'en', translation='final translation',
                     translation_phase='final', translation_source='final source'))
w.session = SimpleNamespace(deleteLater=lambda: None)
w.on_finished()
app.processEvents()
assert w.library.load(w.current_item)[0]['session']['state'] == 'complete'
path = w.library.directory(w.current_item['id'])/'session.json'
data = json.loads(path.read_text(encoding='utf8'))
data.pop('captions')
path.write_text(json.dumps(data), encoding='utf8')
before = path.read_bytes()
warnings = []
QMessageBox.warning = lambda *args: warnings.append(args[-1])
row = SimpleNamespace(data=lambda *_: ('session', w.current_item['id']))
w.open_library_item(row, 0)
assert warnings and '录音元数据格式无效' in warnings[0]
assert not w.loading_saved and w.captions[1].translation == 'updated'
assert path.read_bytes() == before
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_preferences_roundtrip_and_recording_guards(tmp_path):
    code = """
import os
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QCheckBox
import linguaflow.app as module
app = QApplication([])
path = os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini'
def window():
    return module.Window(discover=False, prefs=QSettings(path, QSettings.Format.IniFormat))
# Previously enabled offline preferences must not reappear in controls or sessions.
prefs = QSettings(path, QSettings.Format.IniFormat)
prefs.setValue('offline', True)
prefs.setValue('semantic_device', 'cuda')
prefs.setValue('semantic_lookahead', 12)
prefs.setValue('audio_processing', '{"deepfilter": true, "output_db": 10}')
prefs.sync()
w = window()
assert not hasattr(w, 'offline')
assert not any('严格离线' in control.text() for control in w.findChildren(QCheckBox))
w.asr.setCurrentText('fixture-model')
w.translation.setCurrentText('fixture-translator')
w.translation.setCurrentText('tencent/Hy-MT2-1.8B')
assert w.model_manager.translation_before.isEnabled()
w.model_manager.translation_before.setCurrentIndex(2)
w.model_manager.translation_after.setCurrentIndex(2)
w.translate.setChecked(False)
w.model_manager.update_seconds.setValue(1.75)
assert not hasattr(w.model_manager, "semantic_device")
assert not hasattr(w.model_manager, "semantic_lookahead")
w.device.addItem('fixture', ('device-id', True))
w.close()
w = window()
assert w.asr.currentText() == 'fixture-model'
assert w.translation.currentText() == 'tencent/Hy-MT2-1.8B'
assert w.model_manager.translation_before.currentData() == 5
assert w.model_manager.translation_after.currentData() == 1
settings = w.settings_binding.session_settings(('fixture', True))
assert settings.translation_before == 5 and settings.translation_after == 1
assert not hasattr(settings, 'offline')
w.translation.setCurrentText('facebook/nllb-200-distilled-600M')
assert not w.model_manager.translation_before.isEnabled()
w.translation.setCurrentText('tencent/Hy-MT2-1.8B')
assert w.model_manager.translation_after.isEnabled()
assert not w.translate.isChecked()
assert w.model_manager.update_seconds.value() == 1.75
assert not hasattr(settings, "semantic_device")
assert not hasattr(settings, "semantic_lookahead")
assert not any("SaT" in button.text() for button in w.findChildren(module.QPushButton))
from linguaflow.audio_processing.config import automatic_audio_config
assert settings.audio_processing == automatic_audio_config()
assert not hasattr(w, 'audio_config') and not hasattr(w, 'manage_audio')
assert '音频处理' not in w.settings_workspace.categories
assert not any('音频实验室' in button.text() for button in w.findChildren(module.QPushButton))
from types import SimpleNamespace
module.list_devices = lambda: [SimpleNamespace(name='fixture', id='device-id', loopback=True)]
w.refresh_devices()
assert w.device.currentData() == ('device-id', True), (w.device.currentData(), w.device.itemData(0), w.status.text())
assert w.new_recording(name='guarded')
item = w.current_item
original_path = w.library.directory(item['id'])
folder = w.library.folder('destination')
def unexpected(*args, **kwargs): raise AssertionError('guard should reject before dialog')
QInputDialog.getText = unexpected
QMessageBox.question = unexpected
w.session = object()
w.rename_item(item)
w.move_recording(item, folder['id'])
w.delete_item(item)
assert not w.new_recording(name='blocked')
assert original_path.exists() and w.library.directory(item['id']) == original_path
w.session = None
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_start_validation_and_cancelled_naming_do_not_launch(tmp_path):
    code = """
import os
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
import linguaflow.app as module
app = QApplication([])
w = module.Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat))
messages = []
QMessageBox.warning = lambda parent, title, text: messages.append(title)
QMessageBox.information = QMessageBox.warning
def unexpected(*args, **kwargs): raise AssertionError('session must not launch')
module.Session = unexpected
w.start(models_checked=True)
assert messages.pop() == '没有音频来源'
w.device.addItem('fixture', ('fixture', True))
w.model_manager.backend.setCurrentIndex(0)
w.asr.setCurrentText('')
w.start(models_checked=True)
assert messages.pop() == '模型为空'
w.asr.setCurrentText('small')
from linguaflow.management import Preparation
w.model_manager.worker = Preparation(lambda: 'ready', w.model_manager)
w.start(models_checked=True)
assert messages.pop() == '模型准备中'
w.model_manager.worker = None
w.model_manager.backend.setCurrentIndex(w.model_manager.backend.findData('qwen3-streaming'))
w.source.setCurrentIndex(0)
w.start(models_checked=True)
assert messages.pop() == '请选择原文语言'
w.model_manager.backend.setCurrentIndex(0)
from linguaflow.workspace_widgets import RecordingDialog
RecordingDialog.exec = lambda self: 0
w.start(models_checked=True)
assert w.current_item is None and not w.library.index['sessions']
assert w.session is None and w.start_button.isEnabled()
w.close()
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                                 'AGENTSCRIBE_LIBRARY': str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_fatal_error_survives_late_status_and_finish(tmp_path):
    # QWidget needs QApplication, whereas the engine suite uses QCoreApplication.
    code = """
from types import SimpleNamespace
import os
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat))
w.on_caption(Caption(1, 0, 1, '错字', 'zh', final=False))
w.on_caption(Caption(1, 0, 2, '正确原文', 'zh', final=False, revision=2))
assert w.cards[1].source.text() == '正确原文'
assert not hasattr(w.cards[1], 'change')
assert '优化中' in w.cards[1].meta.text()
w.on_caption(Caption(1, 0, 1, '过期结果', 'zh', final=False))
assert w.cards[1].source.text() == '正确原文'
w.on_caption(Caption(1, 0, 2, '', 'zh', final=True, revision=3))
assert not w.captions
w.on_caption(Caption(2, 0, 1, 'First phrase.', 'en', final=False))
w.on_caption(Caption(3, 1, 2, 'Second phrase.', 'en', final=False))
w.on_caption(Caption(2, 0, 2, 'First phrase. Second phrase.', 'en', final=False, revision=2))
w.on_caption(Caption(3, 1, 2, '', 'en', final=True, revision=2))
assert 3 not in w.cards and w.cards[2].source.text() == 'First phrase. Second phrase.'
assert w.model_manager.draft_seconds.value() >= .25
assert not hasattr(w.model_manager, 'profile')
assert w.model_manager.draft_seconds.value() == .5
w.clear_captions()
assert w.model_manager.tabs.count() == 4
assert w.model_manager.tabs.tabText(3) == '运行环境'
w.model_manager.backend.setCurrentIndex(w.model_manager.backend.findData('qwen3-streaming'))
assert 'Qwen' in w.model_manager.behavior_hint.text()
w.session = SimpleNamespace(deleteLater=lambda: None)
w.on_failure('GPU 运行库缺失: cublas64_12.dll')
w.on_status('音频队列已满')
assert 'cublas64_12.dll' in w.status.text()
w.on_finished()
app.processEvents()
assert 'cublas64_12.dll' in w.status.text()
assert w.start_button.isEnabled()
assert 'cublas64_12.dll' in w.empty.text()
w.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "AGENTSCRIBE_LIBRARY": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_library_navigation_preserves_session_and_draft(tmp_path):
    code = """
import os
from dataclasses import asdict
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption, Settings
app = QApplication([])
w = Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat))
folder = w.library.folder('课程')
item = w.library.create(folder['id'], asdict(Settings('fixture')))
w.current_item = item
w.on_caption(Caption(1, 0, 1, 'draft', 'en', final=False))
w.on_caption(Caption(2, 1, 2, 'hello', 'en', '你好'))
assert w.persist_session('complete')
w.refresh_library()
assert w.new_recording(name='新的录音')
assert not w.captions and len(w.library.index['sessions']) == 2
row = w.library_tree.topLevelItem(1).child(0)
w.open_library_item(row, 0)
assert w.captions[1].source == 'draft' and not w.captions[1].final
assert w.captions[2].translation == '你好'
assert w.export_button.isEnabled()
w.move_recording(item, 'inbox')
assert w.library.index['sessions'][0]['folder'] == 'inbox'
w.session = object()
assert not w.new_recording()
assert w.captions[2].translation == '你好'
w.session = None
w.close()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "AGENTSCRIBE_LIBRARY": str(tmp_path)})
    assert result.returncode == 0, result.stderr


def test_named_recording_start_finish_and_settings_routes(tmp_path):
    code = """
import os
from threading import Event
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
import linguaflow.app as module
from linguaflow.core import Caption
class FakeSession(QObject):
    status = Signal(str)
    stage = Signal(str, str)
    ready = Signal()
    paused = Signal(bool)
    caption = Signal(object)
    level = Signal(float)
    source_changed = Signal(int)
    failure = Signal(str)
    finished = Signal()
    def __init__(self, settings, parent, recording_path, runtime=None):
        super().__init__(parent)
        self.settings = settings
        self.model_ready = Event()
        self.recording_path = recording_path
    def start(self):
        self.model_ready.set()
        self.ready.emit()
    def stop(self):
        self.finished.emit()
    def pause(self):
        return True
    def resume(self):
        return True
module.Session = FakeSession
app = QApplication([])
w = module.Window(discover=False, prefs=QSettings(os.environ['AGENTSCRIBE_LIBRARY'] + '/prefs.ini', QSettings.Format.IniFormat))
w.device.addItem('fixture', ('fixture', True))
w.translate.setChecked(False)
w.model_manager.backend.setCurrentIndex(0)
assert w.new_recording(name='测试课堂')
identifier = w.current_item['id']
w.open_settings('聆听')
assert w.pages.currentIndex() == 1
assert w.settings_workspace.title.text() == '聆听'
back = next(b for b in w.settings_workspace.findChildren(QPushButton) if b.text() == '←  返回录音')
back.click()
assert w.pages.currentIndex() == 0
w.open_settings('聆听')
w.settings_workspace.search.setText('xxx-unmatched')
assert w.settings_workspace.pages.isHidden()
w.leave_settings()
w.start(models_checked=True)
assert w.session is not None and w.current_item['id'] == identifier
assert w.settings_panel.isEnabled() and w.model_manager.isEnabled()
assert w.pause_button.isEnabled() and w.pause_button.text() == '暂停'
w.pause_button.click()
assert not w.pause_button.isEnabled() and w.stop_button.isEnabled()
w.session.paused.emit(True)
assert w.pause_button.text() == '继续录音' and w.pause_button.isEnabled()
assert not w.new_button.isEnabled() and w.settings_panel.isEnabled()
w.on_ready()
assert w.pause_button.text() == '继续录音'
w.pause_button.click()
assert not w.pause_button.isEnabled()
w.session.paused.emit(False)
assert w.pause_button.text() == '暂停' and w.pause_button.isEnabled()
assert w.current_item['id'] == identifier
before = w.session.settings.audio_processing['output_db']
next_settings = w.settings_binding.session_settings(w.device.currentData())
next_settings.audio_processing['output_db'] = before + 1
assert w.session.settings.audio_processing['output_db'] == before
w.on_caption(Caption(1, 0, 1, 'saved', 'en'))
w.stop()
app.processEvents()
assert w.session is None and w.settings_panel.isEnabled() and w.model_manager.isEnabled()
assert w.library.load(w.current_item)[1][0].source == 'saved'
assert not (w.library.directory(identifier) / '.recording.lock').exists()
assert w.new_recording(name='取消的录音')
w.start(models_checked=True)
w.stop()
app.processEvents()
assert w.current_item['state'] == 'draft'
assert w.new_recording(name='另一个课堂')
# Failed begin restores all controls rather than leaving settings disabled.
original = w.library.begin
def failed(*args): raise OSError('fixture disk failure')
w.library.begin = failed
w.start(models_checked=True)
assert w.session is None and w.settings_panel.isEnabled() and w.model_manager.isEnabled()
w.library.begin = original
# Deletion is reversible and clears the active view without recreating the item.
QMessageBox.question = lambda *args: QMessageBox.StandardButton.Yes
item = w.current_item
w.delete_item(item)
assert w.current_item is None and item['id'] not in w.library.paths
token = w.library.deleted()[0]['token']
from linguaflow.deleted_dialog import DeletedDialog
deleted = DeletedDialog(w.library)
changes = []
deleted.changed.connect(lambda: changes.append(True))
deleted.recover()
assert changes == [True] and deleted.entries.count() == 0
deleted.close()
assert item['id'] in w.library.paths
# Late status/ready events cannot turn a stopping session back into listening.
assert w.new_recording(name='收尾状态')
w.start(models_checked=True)
w.session.stop = lambda: None
w.stop()
w.on_status('late model progress')
w.on_ready()
w.session.paused.emit(True)
w.update_activity()
assert '正在停止' in w.status.text() and not w.stop_button.isEnabled()
assert not w.start_button.isEnabled() and w.model_manager.isEnabled()
w.on_finished()
app.processEvents()
# Closing a paused recording follows the same drain/save path as Stop.
assert w.new_recording(name='暂停后关闭')
w.start(models_checked=True)
w.toggle_pause()
w.session.paused.emit(True)
from PySide6.QtGui import QCloseEvent
event = QCloseEvent()
w.closeEvent(event)
app.processEvents()
assert w.session is None and w.recording_lock is None
assert not w.pause_button.isEnabled()
w.closing = False
# A constructor failure also releases the recording lock and restores controls.
assert w.new_recording(name='启动失败')
def failed_constructor(*args, **kwargs): raise RuntimeError('cannot construct session')
module.Session = failed_constructor
w.start(models_checked=True)
assert w.session is None and w.recording_lock is None
assert w.start_button.isEnabled() and w.library_tree.isEnabled()
assert 'cannot construct session' in w.status.text()
w.close()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "AGENTSCRIBE_LIBRARY": str(tmp_path)})
    assert result.returncode == 0, result.stderr
