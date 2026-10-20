"""Visible feedback stays immediate while single-click safety stays intact."""
from test_beta_features import run_ui


def test_hit_area_updates_after_text_size_and_font_change_and_overlay_recovers(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPointF
from linguaflow.caption_view import CaptionText
from linguaflow.core import Caption
text = CaptionText()
text.resize(500,80)
text.setText('Short')
assert not text._text_contains(QPointF(400,40))
text.setText('W'*80)
assert text._text_contains(QPointF(400,40))
text.resize(120,160)
assert not text._text_contains(QPointF(400,40))
text.setStyleSheet('font-size: 24px;')
text.ensurePolished()
assert text._text_contains(QPointF(5,80))
caption = Caption(1,0,1,'Same caption','en','已有译文')
o = w.overlay
o.update_caption(caption, animate=False)
o.target.clear()
o.update_caption(caption, animate=False)
assert o.target.text() == '已有译文' and not o.target.isHidden()
text.close()
w.close()
''', tmp_path)


def test_tooltip_destroyed_before_application_stops_receiving_events(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from linguaflow.ui_tooltips import install_tooltips
manager = install_tooltips(app)
manager.show(w, '关闭前的提示', QPoint(50,50))
assert manager.timeout.isActive()
manager.bubble.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
assert manager.bubble is None and manager._closed
assert not manager.timeout.isActive() and manager.anchor is None
app.sendEvent(w, QEvent(QEvent.Type.WindowDeactivate))
manager.hide()
manager.show(w, '已关闭', QPoint(50,50))
manager.shutdown()
w.close()
''', tmp_path)
