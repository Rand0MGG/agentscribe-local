"""Capture all Qt reference pages for Electron parity, with a no-audio guard."""
# ruff: noqa: E402 -- install the audio guard before importing any UI modules.
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.test_no_audio import GUARD

os.environ.setdefault('AGENTSCRIBE_AUDIO_GUARD_LOG', str(Path(__file__).resolve().parents[1] / '.work/reports/ui-parity-qt-audio.log'))
exec(GUARD)

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from linguaflow.app import Window
from linguaflow.audio import Device
from linguaflow.core import Caption, Settings
from linguaflow.library import Library
from linguaflow.recording_state import RecordingState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='capture then close only this preview')
    parser.add_argument('--output', type=Path, default=Path('.work/browser/ui-parity/qt'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / '.work/workspace-preview/qt-parity'
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
        from linguaflow.model_options import recommended_selection
        selection = recommended_selection()
        w.model_manager.apply_selection(selection)
        w.settings_workspace.set_storage_root('/录音示例')
        w.settings_workspace.model_browser.receive({'models': [
            dict(id='preview-asr',name='Qwen3-ASR 1.7B · 示例',kind='asr',engine=selection['backend'],path='/preview/models/qwen',selection=selection['asr_model'],size=1024**3,deletable=False),
            dict(id='preview-hy',name='HY-MT2 1.8B Q4_K_M · 示例',kind='translation',engine='llama',path='/preview/models/hy.gguf',selection=selection['translation_model'],size=1280*1024**2,deletable=False),
        ]})
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
            from linguaflow.knowledge.panel import KnowledgePanel
            from linguaflow.playback import PlaybackIndex
            output = args.output.resolve()
            output.mkdir(parents=True, exist_ok=True)
            records = []
            def capture(name, widget=w):
                QTest.qWait(160)
                backdrop = w.centralWidget()
                deadline = time.monotonic() + 5
                while backdrop._rendered != backdrop._key() and time.monotonic() < deadline:
                    QTest.qWait(10)
                assert backdrop._rendered == backdrop._key()
                pixmap = widget.grab()
                # Store both renderers at the same logical pixel size.
                image = pixmap.toImage().scaled(widget.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                image.setDevicePixelRatio(1)
                assert image.save(str(output/(name+'.png')))
                record = dict(name=name, width=widget.width(), height=widget.height())
                if widget is w:
                    island = w.control_island
                    pos = island.mapTo(w, island.rect().topLeft())
                    record['island'] = dict(x=pos.x(), y=pos.y(), width=island.width(), height=island.height())
                    if w.settings_workspace.isVisible():
                        record['settings_margins'] = list(w.settings_workspace.content_layout.getContentsMargins())
                records.append(record)
            sizes = [(1280,797),(900,650),(640,480)]
            for mode, theme in [(0,'light'),(1,'dark')]:
                w.appearance.setCurrentIndex(mode)
                w.set_recording_state(RecordingState.IDLE)
                w.leave_settings()
                for width,height in sizes:
                    w.resize(width,height)
                    capture(f'workspace-{theme}-{width}x{height}')
                for category,slug in [('常规','general'),('聆听','listening'),('模型管理','models'),('字幕与延迟','captions'),('运行环境','runtime'),('使用指南','guide')]:
                    w.open_settings(category)
                    for width,height in sizes:
                        w.resize(width,height)
                        capture(f'settings-{slug}-{theme}-{width}x{height}')
                w.model_manager.advanced_toggle.setChecked(True)
                w.open_settings('字幕与延迟')
                capture(f'settings-advanced-{theme}-640x480')
                w.model_manager.advanced_toggle.setChecked(False)
                w.resize(900,650)
                w.open_settings('模型管理')
                dialog = w.settings_workspace.open_model_catalog()
                capture('catalog-'+theme,dialog)
                dialog.reject()
                dialog = w.settings_workspace.open_model_settings('asr')
                capture('model-editor-'+theme,dialog)
                dialog.advanced_toggle.setChecked(True)
                capture('model-advanced-'+theme,dialog)
                dialog.reject()
                w.leave_settings()
                w.set_recording_state(RecordingState.LISTENING)
                w.capture_time.setText('00:12:34')
                w.meter.set_rms(.024)
                for width,height in sizes:
                    w.resize(width,height)
                    capture(f'recording-{theme}-{width}x{height}')
                w.set_recording_state(RecordingState.IDLE)
                w.playback.setProperty('available',True)
                w.playback_index = PlaybackIndex(w.captions.values())
                w.scroll.set_playback(True)
                w.playback_duration(94000)
                w.playback_position(7000)
                w.update_transport()
                for width,height in sizes:
                    w.resize(width,height)
                    capture(f'playback-{theme}-{width}x{height}')
                w.playback.setProperty('available',False)
                w.scroll.set_playback(False)
                w.highlight_playback(0)
                w.update_transport()
                class Client(QObject):
                    changed = Signal(dict)
                    connected = True
                    closing = False
                    def send(self,*args,**kwargs):
                        return False
                client = Client()
                panel = KnowledgePanel(client,lambda:None,lambda:None,w)
                panel.receive(dict(type='view',manifest=dict(notes_cloud=False),course=dict(id='fixture',terms=[],documents=[]),course_options=[dict(id='fixture',name='课程笔记 · 示例')],course_folder_id='fixture',blocks=[],notes=[],pending=[]))
                panel.show()
                assert QTest.qWaitForWindowExposed(panel)
                for i,slug in enumerate(['materials','terms','notes']):
                    panel.tabs.setCurrentIndex(i)
                    capture(f'knowledge-{slug}-{theme}',panel)
                panel.close()
                w.overlay.resize(780,220)
                w.overlay.update_caption(w.captions[3],animate=False)
                w.overlay.show()
                QTest.qWait(200)
                w.overlay.set_controls_visible(True)
                capture(f'overlay-controls-{theme}',w.overlay)
                w.overlay.set_controls_visible(False)
                capture(f'overlay-reading-{theme}',w.overlay)
                w.overlay.hide()
            assert not Path(os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG']).exists(), 'Attempted native audio access'
            (output/'manifest.json').write_text(json.dumps(dict(records=records,audioAttempts=0),ensure_ascii=False,indent=2))
            print(f'Captured {len(records)} Qt reference states.',flush=True)
            w.current_item = None
            w.session_dirty = False
            w.close()
        QTimer.singleShot(100,screenshots)
        QTimer.singleShot(60000,lambda:app.exit(2))
        return app.exec()

if __name__ == '__main__':
    sys.exit(main())
