"""Actual app workflow preview, with isolated files and simulated external work."""
import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout

from linguaflow.app import Window
from linguaflow.audio import Device
from linguaflow.core import Caption, Settings
from linguaflow.library import Library
from linguaflow.qt_controls import text_label
from linguaflow.recording_state import RecordingState
from scripts.preview_components import button

ROOT = Path(__file__).resolve().parents[1]


class SimulatedRecording(QObject):
    """Presentation-only session; no devices, models or background work."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.model_ready = Event()
        self.recorded_seconds = 3

    def pause(self):
        QTimer.singleShot(0, lambda: self.window.on_paused(True))
        return True

    def resume(self):
        QTimer.singleShot(0, lambda: self.window.on_paused(False))
        return True

    def stop(self):
        self.window.on_finished()


class SimulatedPreparation:
    """Replace only subprocess work; keep the real task, progress and retry wiring."""
    def __init__(self, manager):
        self.manager = manager
        self.attempts = {}
        self.delay = .05

    def run(self, command, *, show_progress=True):
        key = tuple(command)
        attempt = self.attempts.get(key, 0)
        self.attempts[key] = attempt + 1
        worker = self.manager.worker
        runtime = 'linguaflow.runtime_install' in command
        worker.download.emit(dict(label='示例：检查已有运行组件', unit='stage'))
        for _ in range(20):
            if worker.cancelled:
                return '示例准备已取消'
            time.sleep(self.delay)
        if runtime:
            for stage in ('示例：校验本地环境', '示例：复用已就绪组件'):
                worker.download.emit(dict(label=stage, unit='stage'))
                for _ in range(25):
                    if worker.cancelled:
                        return '示例准备已取消'
                    time.sleep(self.delay)
            return '示例：运行环境检查完成。未修改真实环境。'
        start, stop = (55, 101) if attempt else (0, 56)
        for value in range(start, stop):
            if worker.cancelled:
                return '示例准备已取消'
            worker.download.emit(dict(label='示例模型文件 · 续传' if attempt else '示例模型文件',
                                      unit='B', completed=value*1024**2, total=100*1024**2,
                                      rate=20*1024**2))
            time.sleep(self.delay)
        if not attempt:
            raise ConnectionError('示例网络中断；点击重试，从保留的 55% 继续。')
        return '示例：准备完成。未下载模型或修改运行环境。'


@contextmanager
def preview_window(root):
    root.mkdir(parents=True, exist_ok=True)
    prefs = QSettings(str(root/'prefs.ini'), QSettings.Format.IniFormat)
    prefs.clear()
    library = Library(root/'library')
    if not library.index['sessions']:
        for folder_name in ('课堂录音 · 示例', '讨论 · 示例'):
            folder = library.folder(folder_name)
            for number in (1, 2):
                item = library.create(folder['id'], asdict(Settings('preview')))
                library.rename(item, f'{folder_name} {number}')
                library.save(item, [Caption(1, 0, 4, 'Context gives words their meaning.', 'en',
                                            '上下文赋予词语意义。')], 'complete')
    devices = [Device('preview', '系统音频 · 示例来源', True)]
    with patch('linguaflow.app.list_devices', return_value=devices), \
         patch.object(Window, 'start_background_check', return_value=None), \
         patch.object(Window, 'check_model_assets', return_value=None), \
         patch.object(Window, 'prepare_playback', return_value=None), \
         patch.object(Window, 'start', lambda self, **kwargs: None):
        w = Window(discover=False, library_root=library.root, prefs=prefs)
        w.setWindowTitle('AgentScribe · 正式流程 Demo（隔离示例）')
        w.settings_workspace.model_browser.start_check = None
        w.refresh_devices()
        scenario = SimulatedPreparation(w.model_manager)
        w.model_manager.run_preparation = scenario.run
        w.reduce_motion.setChecked(False)
        w.refresh_library()
        w.show()
        try:
            yield w, scenario
        finally:
            from scripts.probe_package import close_window
            if w.session is not None:
                w.session.deleteLater()
                w.session = None
            w.set_recording_state(RecordingState.IDLE)
            w.current_item = None
            w.session_dirty = False
            close_window(w, QApplication.instance())


def controls(w, scenario):
    panel = QDialog(w, Qt.WindowType.Tool)
    panel.setWindowTitle('Demo 场景 · 使用正式窗口和控件')
    layout = QVBoxLayout(panel)
    layout.addWidget(text_label('录音、网络与下载均为示例；目录和偏好独立。\n在主窗口直接尝试文件夹、菜单、下载与重试。', 'muted'))
    for name, category in [('模型下载：55% 失败 → 重试续传', '模型管理'),
                           ('运行环境：点击检查 / 修复看进度', '运行环境'),
                           ('常规：主题、开关和窄布局', '常规')]:
        layout.addWidget(button(name, lambda checked=False, category=category: w.open_settings(category)))
    def state(recording=False, playback=False, loading=False):
        w.leave_settings()
        if w.session is not None:
            w.session.deleteLater()
            w.session = None
        if recording:
            w.clear_captions()
            w.session = SimulatedRecording(w)
            if not loading:
                w.session.model_ready.set()
        w.set_recording_state(RecordingState.LISTENING if recording else RecordingState.IDLE)
        if recording:
            w.empty.setText(w.capture_wait_text())
            w.update_activity()
        w.playback.setProperty('available', playback)
        w.scroll.set_playback(playback)
        if playback:
            w.playback_duration(60000)
            w.playback_position(15000)
        w.update_transport()
    layout.addWidget(button('小岛 → 录音中，模型加载', lambda: state(recording=True, loading=True)))
    layout.addWidget(button('小岛 → 正在聆听，尚无首句', lambda: state(recording=True)))
    layout.addWidget(button('小岛 → 回放进度条', lambda: state(playback=True)))
    layout.addWidget(button('回到待录音小岛', lambda: state()))
    layout.addWidget(button('浅色 / 深色', lambda: w.appearance.setCurrentIndex(1-w.appearance.currentIndex())))
    layout.addWidget(button('640×480 / 1280×840', lambda: w.resize(640, 480) if w.width()>800 else w.resize(1280,840)))
    layout.addWidget(text_label('模型示例首次失败，重试成功；用于验证界面链路，\n不代表真实服务器续传验收。', 'muted'))
    panel.show()
    return panel


def main():
    from scripts.test_no_audio import GUARD
    output = ROOT/'.work/browser/workflow-demo'
    output.mkdir(parents=True, exist_ok=True)
    os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'] = str(output/'blocked-audio.log')
    exec(GUARD)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle('Fusion')
    with preview_window(ROOT/'.work/workspace-preview/workflows') as (w, scenario):
        if args.capture:
            from PySide6.QtTest import QTest
            QTest.qWait(300)
            for mode, name in ((0,'light'),(1,'dark')):
                w.appearance.setCurrentIndex(mode)
                w.resize(900,650)
                QTest.qWait(100)
                w.grab().save(str(output/f'window-{name}.png'))
            from tests.ui_support import wait_until
            w.appearance.setCurrentIndex(0)
            w.resize(900,650)
            w.open_settings('运行环境')
            scenario.delay = .01
            w.model_manager.install_runtime()
            QTest.qWait(100)
            w.grab().save(str(output/'runtime-progress.png'))
            wait_until(lambda:w.model_manager.worker is None)
            w.open_settings('模型管理')
            dialog = w.settings_workspace.open_model_catalog()
            QTest.qWait(100)
            dialog.download_buttons[0].click()
            wait_until(lambda:w.model_manager.worker is None)
            w.grab().save(str(output/'download-failed-retry.png'))
            w.model_manager.retry_button.click()
            QTest.qWait(300)
            w.grab().save(str(output/'download-resumed.png'))
            wait_until(lambda:w.model_manager.worker is None)
            w.leave_settings()
            w.resize(640,480)
            QTest.qWait(100)
            trigger = next(b for b in w.findChildren(QPushButton) if b.menu() is not None)
            menu = trigger.menu()
            menu.popup(trigger.mapToGlobal(trigger.rect().bottomLeft()))
            QTest.qWait(100)
            menu.grab().save(str(output/'bounded-menu.png'))
            menu.hide()
            print(json.dumps(dict(directory=str(output), dpr=w.devicePixelRatioF())), flush=True)
            return 0
        panel = controls(w, scenario)
        QTimer.singleShot(300, lambda: print('WORKFLOW_DEMO_READY', flush=True))
        result = app.exec()
        panel.close()
        return result


if __name__ == '__main__':
    raise SystemExit(main())
