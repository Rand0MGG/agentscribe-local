"""Render the real Qt UI with labeled fixture captions; does not record audio."""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from linguaflow.app import STYLE, Window
from linguaflow.core import Caption

app = QApplication([])
if sys.platform == "win32":
    # Qt's offscreen plugin does not enumerate Windows system fonts itself.
    for font in ["msyh.ttc", "msyhbd.ttc", "segoeui.ttf"]:
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
window = Window(discover=False)
window.device.addItem("示例 · 系统声音（预览）", ("preview", True))
window.show()
for caption in [
    Caption(
        1,
        0.4,
        3.8,
        "Welcome. Today we're exploring how language brings people together.",
        "en",
        "欢迎。今天，我们将探讨语言如何将人们联系在一起。",
    ),
    Caption(
        2,
        4.1,
        7.3,
        "Everything you hear is processed locally on your own computer.",
        "en",
        "你听到的所有内容，都在自己的电脑上进行本地处理。",
    ),
    Caption(
        3,
        7.6,
        10.2,
        "Choose a model, start listening, and follow the conversation.",
        "en",
        "选择模型，开始聆听，轻松跟上对话。",
    ),
]:
    window.on_caption(caption)
window.status.setText("界面预览 · 示例字幕，非实际识别结果")
output = "docs/preview.png"
if len(sys.argv) > 1:
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    window.clear_captions()
    window.device.setItemText(0, "系统声音 · 已完成的回环验收")
    window.asr.setCurrentText("large-v3")
    window.compute.setCurrentIndex(window.compute.findData("cuda"))
    window.translation.setCurrentText("facebook/nllb-200-distilled-1.3B")
    for item in result["captions"]:
        window.on_caption(Caption(**item))
    window.diagnostics.setPlainText("\n".join(result["events"]))
    window.diagnostics.show()
    window.pipeline.setText("音频：回环通过   /   识别：GPU 通过   /   翻译：GPU 通过   /   会话：已结束")
    window.status.setText("真实回环验收结果回放 · 固定英文测试音频 · 非正在录音")
    output = "docs/verified-preview.png"
window.export_button.setEnabled(True)
if len(sys.argv) == 1:
    window.on_caption(Caption(4, 11, 13, "The next sentence can change as more audio arrives.", "en", final=False))
app.processEvents()
app.processEvents()
Path("docs").mkdir(exist_ok=True)
window.grab().save(output)
if len(sys.argv) == 1:
    window.model_manager.show()
    app.processEvents()
    window.model_manager.grab().save("docs/models-preview.png")
    window.model_manager.close()
window.close()
