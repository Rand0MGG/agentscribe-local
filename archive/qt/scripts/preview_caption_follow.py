"""Preview caption scrolling on native Qt with fake devices and no audio imports."""
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.test_no_audio import GUARD

    output = ROOT / '.work' / 'cache' / 'caption-follow'
    output.mkdir(parents=True, exist_ok=True)
    os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'] = str(output / 'blocked-audio.log')
    exec(GUARD, {})

    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from linguaflow.app import STYLE, Window
    from linguaflow.core import Caption

    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window(discover=False, library_root=output / 'sample-library',
                    prefs=QSettings(str(output / 'preview.ini'), QSettings.Format.IniFormat))
    window.device.addItem('麦克风 · 示例输入', ('preview-mic', False))
    window.device.addItem('系统声音 · 示例扬声器', ('preview-system', True))
    window.quick_device.setCurrentIndex(1)
    window.status.setText('界面预览 · 示例字幕')
    window.reduce_motion.setChecked(False)
    window.resize(1280, 840)
    window.show()
    examples = [
        ('Language is a way of sharing ideas.', '语言是分享想法的方式。'),
        ('Context helps us understand what comes next.', '上下文帮助我们理解接下来的内容。'),
        ('You can scroll back to read earlier captions.', '向上滚动，查看前面的字幕。'),
        ('Return to the bottom to follow the conversation.', '回到底部，继续跟随最新内容。'),
    ]
    for i in range(1, 21):
        source, translation = examples[(i-1) % len(examples)]
        window.on_caption(Caption(i, i*4, i*4+4, source, 'en', translation))
    QTest.qWait(1200)
    bar = window.scroll.verticalScrollBar()
    assert window.scroll.following and bar.value() == bar.maximum()
    window.grab().save(str(output / 'following.png'))
    before = bar.value()
    window.on_caption(Caption(21, 84, 88, 'New captions arrive smoothly.', 'en', '新字幕平滑进入视野。'))
    samples = [before]
    for _ in range(25):
        QTest.qWait(20)
        samples.append(bar.value())
    QTest.qWait(500)
    assert bar.value() == bar.maximum()
    assert any(before < value < bar.maximum() for value in samples)
    assert samples == sorted(samples), samples
    bar.setValue(max(0, bar.maximum()-400))
    QTest.qWait(150)
    assert window.scroll.latest_button.isVisible()
    window.grab().save(str(output / 'paused.png'))
    window.resize(900, 650)
    QTest.qWait(300)
    window.grab().save(str(output / 'compact.png'))
    window.quick_device.showPopup()
    QTest.qWait(200)
    window.quick_device.view().window().grab().save(str(output / 'audio-sources.png'))
    window.quick_device.hidePopup()
    QTest.mouseClick(window.scroll.latest_button, Qt.MouseButton.LeftButton)
    QTest.qWait(1200)
    assert window.scroll.following and bar.value() == bar.maximum()
    evidence = {'system': platform.platform(), 'architecture': platform.machine(),
                'python': platform.python_version(), 'qt_platform': app.platformName(),
                'device_pixel_ratio': window.devicePixelRatioF(),
                'audio': 'simulated devices only; native imports blocked',
                'new_caption_scroll_samples_20ms': samples,
                'checks': ['native window at 1280x840 and 900x650',
                           'intermediate monotonic scroll positions', 'arrow click returns to bottom']}
    (output / 'verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    window.close()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
