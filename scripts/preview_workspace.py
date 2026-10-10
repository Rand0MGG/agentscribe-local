"""Capture the actual shared UI with isolated fixtures and no audio-device access."""
import argparse
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QTextLayout
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from linguaflow.app import Window
from linguaflow.audio import Device
from linguaflow.core import Caption, Settings
from linguaflow.library import Library
from linguaflow.recording_state import RecordingState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='capture then close only this preview')
    parser.add_argument('--output', type=Path, default=Path('.work/browser/ui-design'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / '.work/workspace-preview/shared-ui'
    root.mkdir(parents=True, exist_ok=True)
    prefs = QSettings(str(root/'preview.ini'), QSettings.Format.IniFormat)
    prefs.clear()
    library = Library(root/'library')
    if not library.index['sessions']:
        folder = library.folder('课程笔记 · 示例')
        item = library.create(folder['id'], asdict(Settings('preview')))
        library.rename(item, '理解语言与上下文 · 示例')
        library.save(item, [
            Caption(1, 0, 5, 'Language is more than a sequence of words. It is a way of sharing ideas.',
                    'en', '语言不只是词语的排列，也是分享想法的方式。'),
            Caption(2, 5, 10, 'Context helps us understand what comes next.',
                    'en', '上下文帮助我们理解接下来的内容。'),
            Caption(3, 10, 14, 'Each new sentence brings the meaning into focus.',
                    'en', '每一句新话都让意思更加清楚。'),
        ], 'complete')
    app = QApplication([])
    app.setStyle('Fusion')
    if sys.platform == 'win32':
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'msyh.ttc', 'msyhbd.ttc'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
    devices = [Device('speaker-preview', '系统音频 · 扬声器（示例）', True),
               Device('mic-preview', '外部输入 · 麦克风（示例）', False)]
    # Discovery, background network checks and multimedia loading stay blocked
    # even while sample recordings are opened. No audio file is made or played.
    with patch('linguaflow.app.list_devices', return_value=devices), \
         patch.object(Window, 'start_background_check', return_value=None), \
         patch.object(Window, 'check_model_assets', return_value=None), \
         patch.object(Window, 'prepare_playback', return_value=None):
        w = Window(discover=False, library_root=library.root, prefs=prefs)
        w.reduce_motion.setChecked(True)
        w.refresh_devices()
        w.start = lambda **kwargs: w.set_recording_state(RecordingState.LISTENING)
        w.start_button.clicked.disconnect()
        w.start_button.clicked.connect(lambda: w.start())
        w.new_recording = lambda **kwargs: False
        w.model_manager.prepare_selected = lambda *args, **kwargs: None
        w.model_manager.prepare = lambda *args, **kwargs: None
        w.refresh_library()
        for row in w.library_tree.findItems('', Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive):
            data = row.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == 'session':
                w.open_library_item(row, 0)
                w.library_tree.setCurrentItem(row)
                break
        w.setWindowTitle('AgentScribe · 设计参考（示例数据）')
        w.show()

        def screenshots():
            output = args.output.resolve()
            output.mkdir(parents=True, exist_ok=True)
            records = []
            def capture(name, widget=w):
                QTest.qWait(100)
                assert widget.grab().save(str(output/(name+'.png')))
                records.append(dict(image=name+'.png', logical_size=widget.size().toTuple(),
                                    dpr=widget.devicePixelRatioF()))

            geometry = []
            for mode, name in ((0, 'light'), (1, 'dark')):
                w.appearance.setCurrentIndex(mode)
                w.resize(1280, 840)
                w.set_recording_state(RecordingState.IDLE)
                capture('workspace-'+name)
                geometry.append(w.control_island.geometry().getRect())
            assert geometry[0] == geometry[1], 'Themes must preserve layout geometry'
            w.appearance.setCurrentIndex(0)
            QTest.mouseMove(w.settings_button)
            w.settings_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
            app.sendEvent(w.settings_button, QEvent(QEvent.Type.Enter))
            capture('navigation-hover')
            w.settings_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            app.sendEvent(w.settings_button, QEvent(QEvent.Type.Leave))
            QTest.mouseMove(w.workspace_title)
            for width, height in ((900, 650), (640, 480), (700, 960)):
                w.resize(width, height)
                capture(f'workspace-{width}x{height}')
            w.resize(1280, 840)
            w.quick_device.setCurrentIndex(1)
            w.set_recording_state(RecordingState.LISTENING)
            w.meter.set_rms(.025)
            capture('recording')
            w.set_recording_state(RecordingState.IDLE)
            w.playback.setProperty('available', True)
            w.playback_duration(94_000)
            w.playback_position(27_000)
            w.update_transport()
            capture('playback')
            w.playback.setProperty('available', False)
            w.update_transport()
            w.quick_device.showPopup()
            capture('audio-sources', w.quick_device.view().window())
            w.quick_device.hidePopup()
            for category, name in (('常规', 'settings'), ('字幕与延迟', 'settings-captions'),
                                   ('运行环境', 'settings-runtime')):
                w.open_settings(category)
                capture(name)
            w.open_settings('模型管理')
            from linguaflow.model_options import recommended_selection
            selection = recommended_selection()
            w.model_manager.apply_selection(selection)
            w.settings_workspace.model_browser.receive({'models': [
                dict(id='preview-asr', name='Qwen3-ASR 1.7B · 示例', kind='asr',
                     engine=selection['backend'], path=str(root/'models/qwen'),
                     selection=selection['asr_model'], size=1024**3, deletable=False),
                dict(id='preview-hy', name='HY-MT2 1.8B Q4_K_M · 示例', kind='translation',
                     engine='llama', path=str(root/'models/hy.gguf'),
                     selection=selection['translation_model'], size=1280*1024**2, deletable=False),
            ]})
            dialog = w.settings_workspace.open_model_catalog()
            capture('model-catalog', dialog)
            dialog.reject()
            from linguaflow.model_dialog import ModelCatalogDialog
            snapshot = w.model_manager.model_settings_snapshot()
            snapshot['selection'] = recommended_selection('darwin')
            snapshot['asr_device'] = 'mlx'
            # Mac data on the current Qt renderer; this is not a Cocoa screenshot.
            with patch('linguaflow.model_dialog.sys', SimpleNamespace(platform='darwin')):
                dialog = ModelCatalogDialog(snapshot, parent=w)
                dialog.open()
                capture('model-catalog-mac-layout', dialog)
                dialog.reject()
            w.model_manager.download_card.show()
            w.model_manager.status.setText('正在下载示例模型文件；可离开此页。')
            w.model_manager.progress_bar.show()
            w.model_manager.cancel_button.setEnabled(True)
            w.model_manager.cancel_button.show()
            w.model_manager.show_download(dict(label='HY-MT2 Q4_K_M · 示例进度',
                completed=640*1024**2, total=1280*1024**2, rate=12*1024**2, unit='B'))
            capture('model-download')
            w.model_manager.download_card.hide()
            w.leave_settings()
            overlay = w.overlay
            overlay.update_caption(w.captions[1], animate=False)
            overlay.background_opacity.setValue(70)
            overlay.show()
            overlay.set_controls_visible(True)
            capture('overlay-controls', overlay)
            overlay.set_controls_visible(False)
            capture('overlay-reading', overlay)
            overlay.hide()
            w.current_item = None
            w.session_dirty = False
            w.reset_recording_view()
            w.meter.set_rms(0)
            capture('workspace-empty')
            missing = []
            for widget in w.findChildren(QLabel) + w.findChildren(QPushButton):
                if not widget.isVisibleTo(w):
                    continue
                layout = QTextLayout(widget.text().replace('\n', ' '), widget.font())
                layout.beginLayout()
                line = layout.createLine()
                if line.isValid():
                    line.setLineWidth(10000)
                layout.endLayout()
                if any(glyph == 0 for run in layout.glyphRuns() for glyph in run.glyphIndexes()):
                    missing.append(widget.text())
            assert not missing, f'Missing glyphs: {missing}'
            evidence = dict(system=platform.platform(), architecture=platform.machine(),
                            python=platform.python_version(), renderer='Qt native widget grab',
                            fixture='sample captions; simulated levels, playback and download', images=records)
            (root/'render.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(evidence, ensure_ascii=False), flush=True)
            if args.capture:
                w.current_item = None
                w.session_dirty = False
                w.close()

        QTimer.singleShot(100, screenshots)
        if args.capture:
            QTimer.singleShot(20000, lambda: app.exit(2))
        return app.exec()


if __name__ == '__main__':
    sys.exit(main())
