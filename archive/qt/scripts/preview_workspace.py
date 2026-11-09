"""Capture the actual shared UI with isolated fixtures and no audio-device access."""
import argparse
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QMouseEvent, QTextLayout
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
        # Inventory is supplied below as sample data. A suppressed check must
        # not leave the interactive preview stuck in a fake "reading" state.
        w.settings_workspace.model_browser.start_check = None
        w.reduce_motion.setChecked(True)
        w.refresh_devices()
        w.start = lambda **kwargs: w.set_recording_state(RecordingState.LISTENING)
        w.start_button.clicked.disconnect()
        w.start_button.clicked.connect(lambda: w.start())
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
        assert QTest.qWaitForWindowExposed(w)
        # Let Cocoa finish its initial screen-constrained placement before
        # applying the explicit comparison sizes below.
        QTest.qWait(200)

        def screenshots():
            output = args.output.resolve()
            output.mkdir(parents=True, exist_ok=True)
            records = []
            def capture(name, widget=w):
                QTest.qWait(100)
                backdrop = w.centralWidget()
                deadline = time.monotonic() + 5
                while backdrop._rendered != backdrop._key() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert backdrop._rendered == backdrop._key(), 'Background material did not settle'
                assert widget.grab().save(str(output/(name+'.png')))
                records.append(dict(image=name+'.png', logical_size=widget.size().toTuple(),
                                    dpr=widget.devicePixelRatioF()))
                if widget is w:
                    records[-1]['island_rect'] = w.control_island.geometry().getRect()
                    records[-1]['title_font_px'] = w.workspace_title.label.font().pixelSize()

            geometry = []
            comparison_size = None
            for mode, name in ((0, 'light'), (1, 'dark')):
                w.appearance.setCurrentIndex(mode)
                if comparison_size is None:
                    w.resize(1280, 840)
                else:
                    w.resize(comparison_size)
                w.set_recording_state(RecordingState.IDLE)
                capture('workspace-'+name)
                comparison_size = w.size()
                geometry.append(w.control_island.geometry().getRect())
            assert geometry[0] == geometry[1], f'Themes must preserve layout geometry: {geometry}'
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
            w.capture_time.setText('00:12:34')  # Display fixture, not measured capture.
            w.meter.set_rms(.025)
            capture('recording')
            for width,height in ((900,650),(640,480)):
                w.resize(width,height)
                capture(f'recording-{width}x{height}')
            w.appearance.setCurrentIndex(1)
            capture('recording-dark-640x480')
            w.appearance.setCurrentIndex(0)
            w.resize(1280,840)
            w.set_recording_state(RecordingState.IDLE)
            w.playback.setProperty('available', True)
            from linguaflow.playback import PlaybackIndex
            w.playback_index = PlaybackIndex(w.captions.values())
            w.scroll.set_playback(True)
            w.playback_duration(94_000)
            w.playback_position(7_000)
            w.update_transport()
            capture('playback')
            w.appearance.setCurrentIndex(1)
            capture('playback-dark')
            text = w.cards[1].source
            point = QPoint(5, text.height()//2)
            for mode, name in ((0, 'light'), (1, 'dark')):
                w.appearance.setCurrentIndex(mode)
                QTest.qWait(50)
                text._text_contains(QPoint(0, 0))
                point = text._hit_rects[0].center().toPoint()
                text.setSelection(0, 0)
                app.sendEvent(text, QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                    QPointF(text.mapToGlobal(point)), Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
                assert text._interaction == 'hover' and w.cards[1].interaction == ''
                capture('caption-hover-'+name)
                QTest.mousePress(text, Qt.MouseButton.LeftButton, pos=point)
                assert w.cards[1].interaction == 'pressed'
                capture('caption-pressed-'+name)
                # Release outside the glyphs to cancel activation: screenshots
                # must never invoke media playback.
                QTest.mouseRelease(text, Qt.MouseButton.LeftButton,
                    pos=QPoint(text.width()-2, text.height()//2))
                app.sendEvent(text, QEvent(QEvent.Type.Leave))
            w.appearance.setCurrentIndex(0)
            w.playback_volume.button.click()
            w.playback_volume.slider.setValue(200)
            capture('playback-volume')
            for width, height in ((900, 650), (640, 480)):
                w.resize(width, height)
                capture(f'playback-volume-{width}x{height}')
            w.playback_volume.button.click()
            capture('playback-640x480')
            from linguaflow.ui_tooltips import install_tooltips
            tooltips = install_tooltips(app)
            tooltips.show(w.playback_volume.button, '回放音量 200% · 点击展开或收起',
                          w.playback_volume.mapToGlobal(w.playback_volume.rect().topLeft()))
            capture('tooltip-playback', tooltips.bubble)
            tooltips.hide()
            w.resize(1280, 840)
            w.playback.setProperty('available', False)
            w.scroll.set_playback(False)
            w.highlight_playback(0)
            w.update_transport()
            w.quick_device.showPopup()
            capture('audio-sources', w.quick_device.view().window())
            w.quick_device.hidePopup()
            index = w.device.currentIndex()
            device_name = w.device.itemText(index)
            w.device.setItemText(index, '外部输入 · 麦克风（Realtek High Definition Audio，USB-C 扩展坞连接设备）')
            capture('workspace-long-device')
            w.quick_device.showPopup()
            capture('audio-sources-long', w.quick_device.view().window())
            w.quick_device.hidePopup()
            w.device.setItemText(index, device_name)
            for category, name in (('常规', 'settings'), ('字幕与延迟', 'settings-captions'),
                                   ('运行环境', 'settings-runtime')):
                w.open_settings(category)
                capture(name)
                for mode, theme in ((0, 'light'), (1, 'dark')):
                    w.appearance.setCurrentIndex(mode)
                    w.resize(640, 480)
                    capture(name+'-'+theme+'-640x480')
                w.appearance.setCurrentIndex(0)
                w.resize(1280, 840)
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
            w.model_manager.show_download(dict(label='HY-MT2 Q4_K_M · 示例进度',
                completed=640*1024**2, total=1280*1024**2, rate=12*1024**2, unit='B'))
            capture('model-download')
            capture('download-popup', w.notifications)
            w.leave_settings()
            capture('download-other-page')
            w.notifications.clear('preparation')
            w.notifications.post('fixture-error', '保存失败，字幕仍保留。', kind='error',
                                 action=lambda: None, action_text='重试保存', details='示例错误，不是实际保存失败。')
            capture('feedback-error')
            capture('feedback-popup', w.notifications)
            w.resize(640, 480)
            capture('feedback-error-640x480')
            capture('feedback-popup-640x480', w.notifications)
            w.appearance.setCurrentIndex(1)
            capture('feedback-popup-dark', w.notifications)
            w.appearance.setCurrentIndex(0)
            w.resize(1280, 840)
            w.notifications.clear('fixture-error')
            w.missing_model_assets = ('识别模型：示例文件尚未准备',)
            w.show_first_run()
            capture('first-run', w.first_run)
            w.first_run.reject()
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
            w.refresh_library()
            w.meter.set_rms(0)
            capture('workspace-empty')
            w.new_button.click()
            assert w.current_item is None and w.recording_pages.currentIndex() == 0
            for mode, theme in ((0, 'light'), (1, 'dark')):
                w.appearance.setCurrentIndex(mode)
                for width, height in ((900, 650), (640, 480)):
                    w.resize(width, height)
                    capture(f'new-recording-{theme}-{width}x{height}')
                    QTest.mouseMove(w.new_button)
                    w.new_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
                    app.sendEvent(w.new_button, QEvent(QEvent.Type.Enter))
                    capture(f'new-recording-hover-{theme}-{width}x{height}')
                    w.new_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    app.sendEvent(w.new_button, QEvent(QEvent.Type.Leave))
                    QTest.mouseClick(w.quick_language, Qt.MouseButton.LeftButton)
                    w.language_popup.reject()
                    QTest.mouseMove(w.workspace_title.label)
                    capture(f'language-dismissed-{theme}-{width}x{height}')
            original_title = w.workspace_title.text()
            w.workspace_title.setText('这是一个很长的录音标题 · Language and Context · 课堂笔记与讨论')
            capture('long-title-640x480')
            w.beta_features.setChecked(True)
            capture('beta-header-640x480')
            w.beta_features.setChecked(False)
            w.workspace_title.setText(original_title)
            w.reduce_motion.setChecked(False)
            w.set_recording_state(RecordingState.STARTING)
            w.empty.setText('正在准备录音…')
            w.control_island.place()
            w.control_island.resize_motion.pause()
            for moment in (0, 80, 200):
                w.control_island.resize_motion.setCurrentTime(moment)
                capture(f'island-expansion-{moment:03}ms')
            if w.control_island.resize_motion.state() == w.control_island.resize_motion.State.Paused:
                w.control_island.resize_motion.resume()
            QTest.qWait(30)
            w.reduce_motion.setChecked(True)
            w.set_recording_state(RecordingState.IDLE)
            w.update_recording_hint()
            w.workspace_title.label.setFocus()
            w.workspace_title.begin_edit()
            capture('inline-title')
            w.workspace_title.setText(w.workspace_title.text())
            w.quick_device.showPopup()
            capture('new-recording-sources', w.quick_device.view().window())
            w.quick_device.hidePopup()
            w.quick_language.click()
            capture('new-recording-language', w.language_popup)
            w.language_popup.source_choice.showPopup()
            capture('new-recording-language-choices', w.language_popup.source_choice.view().window())
            w.language_popup.source_choice.hidePopup()
            w.language_popup.hide()
            def capture_folder_menu():
                menu = app.activePopupWidget()
                assert menu is not None
                capture('new-recording-folders', menu)
                menu.close()
            QTimer.singleShot(30, capture_folder_menu)
            w.quick_folder.click()
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
            QTimer.singleShot(45000, lambda: app.exit(2))
        return app.exec()


if __name__ == '__main__':
    sys.exit(main())
