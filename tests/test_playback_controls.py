"""Playback following with simulated media; never load audio hardware."""
from test_beta_features import run_ui


def test_playback_follow_eases_retargets_and_yields_to_manual_scrolling(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QWheelEvent
import linguaflow.caption_view as view
from linguaflow.core import Caption
module.Window.start_background_check = lambda *args, **kwargs: None
w.show()
for i in range(30):
    w.on_caption(Caption(i, i*10, i*10+8, 'Recorded content. '*20, 'en', '译文。'*10))
settle_geometry(w)
scroll = w.scroll
scroll.set_playback(True)
w.reduce_motion.setChecked(False)
clock = [0.]
view.time = SimpleNamespace(monotonic=lambda: clock[0])
bar = scroll.verticalScrollBar()
scroll._move(0)
scroll.follow_playback(w.cards[20], seek=True)
assert bar.value() == 0 and scroll.animation.isActive()
def advance(frames):
    for _ in range(frames):
        clock[0] += .016
        scroll.animation.timeout.emit()
advance(4)
assert 0 < bar.value() < scroll._playback_target
before = bar.value()
scroll.follow_playback(w.cards[25], seek=True)
assert bar.value() == before
advance(80)
assert not scroll.animation.isActive()
assert abs(bar.value()-scroll._playback_target) <= 1
scroll.follow_playback(w.cards[3], seek=True)
wheel = QWheelEvent(QPointF(100,100), QPointF(100,100), QPoint(), QPoint(0,120),
    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
app.sendEvent(scroll.viewport(), wheel)
app.processEvents()
stopped = bar.value()
assert not scroll.following and not scroll.animation.isActive()
scroll.follow_playback(w.cards[15])
advance(5)
assert bar.value() == stopped
scroll.latest_button.click()
app.processEvents()
assert scroll.following and scroll.animation.isActive()
w.reduce_motion.setChecked(True)
scroll.follow_playback(w.cards[2], seek=True)
assert not scroll.animation.isActive()
assert bar.value() <= w.cards[2].y()
w.session_dirty = False
w.close()
''', tmp_path)
