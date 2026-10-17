"""Visible feedback stays immediate while single-click safety stays intact."""
from test_beta_features import run_ui


def test_brand_alignment_and_caption_pointer_press_feedback(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from PySide6.QtCore import QEvent, QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from linguaflow.core import Caption
module.Window.start_background_check = lambda *args, **kwargs: None
w.show(); w.reduce_motion.setChecked(True)
assert QTest.qWaitForWindowExposed(w)
w.raise_(); w.activateWindow()
wait(w.isActiveWindow)
w.on_caption(Caption(1, 2, 6, 'Click this sentence.', 'en', '点击这句话。'))
w.playback.setProperty('available', True)
w.update_transport()
for size in ((1280,840), (900,650), (640,480)):
    w.resize(*size)
    settle_geometry(w)
    brand_y = w.brand.mapTo(w, w.brand.rect().center()).y()
    title_y = w.workspace_title.mapTo(w, w.workspace_title.rect().center()).y()
    assert abs(brand_y-title_y) <= 2, (size, brand_y, title_y)
plays = []
w.player = SimpleNamespace(setPosition=lambda _:None, play=lambda:plays.append(True),
    stop=lambda:None, setSource=lambda _:None, playbackState=lambda:SimpleNamespace(name='StoppedState'))
card, text = w.cards[1], w.cards[1].source
point = QPoint(5, text.height()//2)
assert text.hasMouseTracking()
def move(point):
    app.sendEvent(text, QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
        QPointF(text.mapToGlobal(point)), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))
def colour():
    picture = card.grab()
    dpr = picture.devicePixelRatioF()
    return picture.toImage().pixelColor(round(8*dpr), round((card.height()-8)*dpr))
for theme in (0,1):
    w.appearance.setCurrentIndex(theme)
    app.sendEvent(text, QEvent(QEvent.Type.Leave))
    move(QPoint(text.width()-2, text.height()//2))
    base = colour()
    move(point)
    wait(lambda: text.cursor().shape() == Qt.CursorShape.PointingHandCursor)
    assert text.cursor().shape() == Qt.CursorShape.PointingHandCursor, (theme, text._pointer_hit, text._interaction,
        text._text_contains(point), app.widgetAt(text.mapToGlobal(point)))
    assert card.interaction == '' and colour() == base, (theme, card.interaction, colour().name(), base.name())
    card.setProperty('playing', True)
    playing = colour()
    assert playing != base
    for position in (QPoint(text.width()-2, text.height()//2), point):
        move(position)
        assert card.interaction == '' and colour() == playing
    card.setProperty('playing', False)
    hover = colour()
    text.setSelection(0,0)
    QTest.mousePress(text, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert card.interaction == 'pressed' and colour() != hover
    assert not plays
    QTest.mouseRelease(text, Qt.MouseButton.LeftButton, pos=point)
    assert card.interaction == 'pending' and not plays
    QTest.mouseDClick(text, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(text, Qt.MouseButton.LeftButton, pos=point)
    assert not text.activate_timer.isActive()
    text.setSelection(0,0)
    move(QPoint(text.width()-2, text.height()//2))
    wait(lambda: card.interaction == '' and text.cursor().shape() != Qt.CursorShape.PointingHandCursor)
w.set_recording_state(module.RecordingState.LISTENING)
move(point)
assert card.interaction == ''
w.set_recording_state(module.RecordingState.IDLE)
w.session_dirty = False
w.close()
''', tmp_path)


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
