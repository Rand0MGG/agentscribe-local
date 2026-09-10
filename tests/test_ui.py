import os
import subprocess
import sys


def test_fatal_error_survives_late_status_and_finish():
    # QWidget needs QApplication, whereas the engine suite uses QCoreApplication.
    code = """
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from linguaflow.app import Window
from linguaflow.core import Caption
app = QApplication([])
w = Window(discover=False)
w.on_caption(Caption(1, 0, 1, '错字', 'zh', final=False))
w.on_caption(Caption(1, 0, 2, '正确原文', 'zh', final=False, revision=2))
assert w.cards[1].source.text() == '正确原文'
assert '原文修订' in w.cards[1].change.text()
assert '后文可修正' in w.cards[1].meta.text()
w.on_caption(Caption(1, 0, 1, '过期结果', 'zh', final=False))
assert w.cards[1].source.text() == '正确原文'
w.on_caption(Caption(1, 0, 2, '', 'zh', final=True, revision=3))
assert not w.captions
w.on_caption(Caption(2, 0, 1, 'First phrase.', 'en', final=False))
w.on_caption(Caption(3, 1, 2, 'Second phrase.', 'en', final=False))
w.on_caption(Caption(2, 0, 2, 'First phrase. Second phrase.', 'en', final=False, revision=2))
w.on_caption(Caption(3, 1, 2, '', 'en', final=True, revision=2))
assert 3 not in w.cards and '已合并分段' in w.cards[2].change.text()
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
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
