"""Capture the real desktop surfaces with isolated sample data and no audio access."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from linguaflow.app import STYLE, Window
    from linguaflow.audio_processing.lab import AudioLab
    from linguaflow.core import Caption
    from linguaflow.deleted_dialog import DeletedDialog
    from linguaflow.recording_state import RecordingState
    from linguaflow.ui_components import ActionMenu, Disclosure, NameDialog
    from linguaflow.workspace_widgets import RecordingDialog
    from scripts.test_no_audio import GUARD

    output = ROOT / '.work' / 'ui-experience'
    output.mkdir(parents=True, exist_ok=True)
    os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'] = str(output / 'blocked-audio.log')
    exec(GUARD, {})
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window(discover=False, library_root=output / 'sample-library',
                    prefs=QSettings(str(output / 'preview.ini'), QSettings.Format.IniFormat))
    window.setWindowTitle('AgentScribe · UI 预览（示例数据，无音频）')
    window.resize(1280, 840)
    window.device.addItem('示例麦克风 · 不访问设备', ('preview', False))
    window.source.setCurrentIndex(2)
    window.status.setText('设计预览 · 示例字幕 · 未连接音频设备')
    for caption in [
        Caption(1, 0, 4, 'Language is a way of sharing ideas.', 'en', '语言是分享想法的方式。'),
        Caption(2, 4, 8, 'Context helps us understand what comes next.', 'en', '上下文帮助我们理解接下来的内容。'),
        Caption(3, 8, 12, 'The plan has a budget of 9000.', 'en', '这个项目有预算。',
                final=False, ready=True, translation_phase='initial', translation_source='The project has a budget.'),
        Caption(4, 12, 15, 'Thank you for listening.', 'en', '谢谢聆听。',
                translation_phase='final', translation_source='Thank you for listening.'),
    ]:
        window.on_caption(caption)
    window.show()
    steps = []

    def capture(name, setup, target=lambda: window):
        def run():
            setup()
            QTimer.singleShot(250, lambda: (target().grab().save(str(output / (name + '.png'))), advance()))
        steps.append(run)

    capture('home', window.leave_settings)
    for category, name in [('常规', 'general'), ('聆听', 'listening'), ('识别模型', 'models'),
                           ('翻译模型', 'translation'), ('字幕与延迟', 'captions'),
                           ('音频处理', 'audio'), ('运行环境', 'runtime'), ('使用指南', 'guide')]:
        capture(name, lambda category=category: window.open_settings(category))
    capture('search-empty', lambda: window.settings_workspace.search.setText('不存在的设置'))
    capture('search-sat', lambda: window.settings_workspace.search.setText('SaT'))
    capture('models-compact', lambda: (window.resize(900, 650), window.open_settings('识别模型')))
    capture('home-compact', window.leave_settings)
    def recording_state(state):
        window.set_recording_state(state)
        window.status.setText(state.status())
    capture('recording-listening', lambda: recording_state(RecordingState.LISTENING))
    capture('recording-paused', lambda: recording_state(RecordingState.PAUSED))
    steps.append(lambda: (recording_state(RecordingState.IDLE), advance()))
    capture('models-wide', lambda: (window.resize(1600, 900), window.open_settings('识别模型')))
    capture('models-local', lambda: window.model_manager.findChild(Disclosure).toggle.setChecked(True))
    steps.append(lambda: (window.leave_settings(), advance()))
    dialogs = []
    for name, make in [('new-recording', lambda: RecordingDialog(window.library, window.folder_id, window)),
                       ('deleted', lambda: DeletedDialog(window.library, window)),
                       ('audio-lab', lambda: AudioLab({}, parent=window))]:
        def setup(make=make):
            window.resize(1280, 840)
            dialog = make()
            dialogs.append(dialog)
            dialog.show()
        capture(name, setup, lambda: dialogs[-1])
        steps.append(lambda: (dialogs[-1].reject(), advance()))
    menu = ActionMenu(window)
    menu.addAction('复制最新字幕')
    menu.addSeparator()
    menu.addAction('重命名录音…')
    menu.addAction('打开保存位置')
    menu.addSeparator()
    menu.addAction('移到最近删除…')
    capture('menu', lambda: menu.popup(window.mapToGlobal(window.rect().center())), lambda: menu)
    steps.append(lambda: (menu.close(), advance()))
    # Keep the actual modal available for keyboard testing without editing files.
    window.preview_name_dialog = NameDialog

    def advance():
        if steps:
            QTimer.singleShot(0, steps.pop(0))
        elif '--interactive' in sys.argv:
            window.open_settings('常规')
            print('UI preview ready; audio backends blocked.', flush=True)
        else:
            window.close()

    QTimer.singleShot(500, advance)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
