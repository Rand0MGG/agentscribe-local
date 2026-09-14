import os
import subprocess
import sys


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
assert '●' in w.cards[1].meta.text()
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
w.model_manager.classroom_drafts()
assert w.model_manager.draft_seconds.value() == .5
assert w.model_manager.endpoint_seconds.value() == 1.5
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
assert 'cublas64_12.dll' in w.status.text()
assert w.start_button.isEnabled()
assert 'cublas64_12.dll' in w.empty.text()
from linguaflow.audio_processing.lab import AudioLab
from linguaflow.audio_processing.config import PRESETS
lab = AudioLab(parent=w)
assert not lab.record.isEnabled()
lab.preset.setCurrentText('课堂远场 · 去混响')
assert lab.config() == PRESETS['课堂远场 · 去混响'].to_dict()
lab.original = 'fixture.wav'
lab.processed = 'processed.wav'
lab.refresh()
assert lab.play_processed.isEnabled()
lab.controls['df_mix'].setValue(.4)
assert lab.processed is None and not lab.play_processed.isEnabled()
assert lab.preset.currentText() == '自定义'
lab.apply_config()
assert lab.result_config['df_mix'] == .4
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
from PySide6.QtWidgets import QApplication, QMessageBox
import linguaflow.app as module
from linguaflow.core import Caption
class FakeSession(QObject):
    status = Signal(str)
    stage = Signal(str, str)
    ready = Signal()
    caption = Signal(object)
    level = Signal(float)
    failure = Signal(str)
    finished = Signal()
    def __init__(self, settings, parent, recording_path):
        super().__init__(parent)
        self.model_ready = Event()
        self.recording_path = recording_path
    def start(self):
        self.model_ready.set()
        self.ready.emit()
    def stop(self):
        self.finished.emit()
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
w.settings_workspace.search.setText('xxx-unmatched')
assert w.settings_workspace.pages.isHidden()
w.leave_settings()
w.start()
assert w.session is not None and w.current_item['id'] == identifier
assert not w.settings_panel.isEnabled() and not w.model_manager.isEnabled()
w.on_caption(Caption(1, 0, 1, 'saved', 'en'))
w.stop()
assert w.session is None and w.settings_panel.isEnabled() and w.model_manager.isEnabled()
assert w.library.load(w.current_item)[1][0].source == 'saved'
assert not (w.library.directory(identifier) / '.recording.lock').exists()
assert w.new_recording(name='取消的录音')
w.start()
w.stop()
assert w.current_item['state'] == 'draft'
assert w.new_recording(name='另一个课堂')
# Failed begin restores all controls rather than leaving settings disabled.
original = w.library.begin
def failed(*args): raise OSError('fixture disk failure')
w.library.begin = failed
w.start()
assert w.session is None and w.settings_panel.isEnabled() and w.model_manager.isEnabled()
w.library.begin = original
# Deletion is reversible and clears the active view without recreating the item.
QMessageBox.question = lambda *args: QMessageBox.StandardButton.Yes
item = w.current_item
w.delete_item(item)
assert w.current_item is None and item['id'] not in w.library.paths
token = w.library.deleted()[0]['token']
w.library.restore_deleted(token)
assert item['id'] in w.library.paths
w.close()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "AGENTSCRIBE_LIBRARY": str(tmp_path)})
    assert result.returncode == 0, result.stderr
