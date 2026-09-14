"""Preview the actual workspace with isolated, explicitly labeled sample data."""

import sys
import wave
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from linguaflow.app import STYLE, Window
from linguaflow.core import Caption, Settings
from linguaflow.library import Library

root = Path(__file__).resolve().parents[1] / ".work" / "workspace-preview"
library = Library(root)
if not library.index["sessions"]:
    course = library.folder("机器学习课程 · 示例")
    library.folder("灵感与讨论 · 示例")
    item = library.create(course["id"], asdict(Settings("preview")))
    library.rename(item, "01 · 理解语言与上下文（示例）")
    library.save(item, [
        Caption(1, 0, 5, "Language is more than a sequence of words. It is a way of sharing ideas.",
                "en", "语言不只是词语的排列，也是分享想法的方式。"),
        Caption(2, 5, 10, "When we listen, context helps us understand what comes next.",
                "en", "当我们聆听时，上下文帮助我们理解接下来的内容。"),
        Caption(3, 10, 14, "Each new sentence brings the meaning into focus.",
                "en", final=False),
    ], "incomplete")
    with wave.open(str(library.directory(item["id"]) / "录音.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000 * 15)

app = QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
window = Window(discover=False, library_root=root,
                prefs=QSettings(str(root / "preview.ini"), QSettings.Format.IniFormat))
window.device.addItem("系统声音 · 示例设备", ("preview", True))
window.setWindowTitle("AgentScribe · 设计预览（示例数据）")
window.show()
row = window.library_tree.topLevelItem(1).child(0)
window.open_library_item(row, 0)
window.library_tree.setCurrentItem(row)
window.status.setText("设计预览 · 示例字幕与静音音频")


def screenshots():
    output = root.parent / "browser"
    output.mkdir(exist_ok=True)
    window.grab().save(str(output / "workspace.png"))
    window.overlay.update_caption(window.captions[2])
    window.overlay.show()
    app.processEvents()
    window.overlay.grab().save(str(output / "overlay.png"))
    window.overlay.hide()
    window.open_settings()
    app.processEvents()
    window.grab().save(str(output / "settings.png"))
    window.open_settings("聆听")
    app.processEvents()
    window.grab().save(str(output / "settings-listening.png"))
    window.open_settings("识别模型")
    app.processEvents()
    window.grab().save(str(output / "settings-models.png"))
    window.open_settings("字幕与延迟")
    app.processEvents()
    window.grab().save(str(output / "settings-semantic.png"))
    window.leave_settings()
    from linguaflow.workspace_widgets import RecordingDialog
    naming = RecordingDialog(window.library, window.folder_id, window)
    naming.name.setText("第 02 讲 · 梯度与优化")
    naming.show()
    app.processEvents()
    naming.grab().save(str(output / "new-recording.png"))
    naming.reject()
    window.resize(900, 650)
    app.processEvents()
    window.grab().save(str(output / "workspace-compact.png"))
    window.open_settings("识别模型")
    app.processEvents()
    window.grab().save(str(output / "settings-compact.png"))
    window.leave_settings()
    window.resize(1600, 900)
    app.processEvents()
    window.grab().save(str(output / "workspace-wide.png"))
    window.resize(1280, 840)
    if "--capture" in sys.argv:
        window.close()


QTimer.singleShot(1500, screenshots)
sys.exit(app.exec())
