"""Playback layout and motion with simulated media; never load audio hardware."""
from test_beta_features import run_ui


def test_long_seek_and_volume_circle_expand_without_shortening_timeline(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from PySide6.QtTest import QTest
module.Window.start_background_check = lambda *args, **kwargs: None
w.show()
w.playback.setProperty('available', True)
w.playback_duration(7_200_000)
w.update_transport()
volume = w.playback_volume
for theme in (0, 1):
    w.appearance.setCurrentIndex(theme)
    for width, height in ((1280, 840), (900, 650), (640, 480)):
        w.resize(width, height)
        settle_geometry(w, w.control_island, volume)
        centres = [widget.mapTo(w.playback, widget.rect().center()).y()
                   for widget in (w.play_button, w.seek, w.play_time)]
        assert max(centres)-min(centres) <= 1
        assert w.seek.geometry().right() < w.play_time.x()
        assert w.seek.width() >= (400 if width == 1280 else 120), (width, w.seek.width())
        assert volume.width() == volume.height() == w.control_island.height()
        assert volume.x() > w.control_island.geometry().right()
        assert volume.geometry().bottom() == w.control_island.geometry().bottom()
        assert w.scroll.viewport().rect().contains(volume.geometry())
w.reduce_motion.setChecked(False)
closed_height = volume.height()
seek_width = w.seek.width()
QTest.mouseClick(volume.button, Qt.MouseButton.LeftButton)
assert volume.animation.state() == volume.animation.State.Running
volume.animation.setCurrentTime(100)
assert closed_height < volume.height() < closed_height+112
volume.animation.setCurrentTime(200)
settle_geometry(w.control_island, volume)
assert volume.slider.isVisibleTo(volume)
assert w.seek.width() == seek_width
assert w.scroll.viewport().rect().contains(volume.geometry())
values = []
w.audio_output = SimpleNamespace(setVolume=values.append)
for value in (0, 25, 100):
    volume.slider.setValue(value)
assert values == [0., .25, 1.]
positions = []
w.player = SimpleNamespace(setPosition=positions.append, stop=lambda: None, setSource=lambda _: None)
w.seek.setSliderDown(True)
w.seek.setValue(2000)
w.playback_position(1000)
assert w.seek.value() == 2000 and w.play_time.text().startswith('00:02')
assert positions == [2000]
w.seek.setSliderDown(False)
volume.button.click()
volume.animation.setCurrentTime(60)
volume.button.click()
volume.animation.setCurrentTime(200)
assert volume.button.isChecked() and volume.height() > closed_height
w.release_playback()
assert volume.isHidden() and not volume.button.isChecked()
assert volume.animation.state() == volume.animation.State.Stopped
w.reduce_motion.setChecked(True)
w.playback.setProperty('available', True)
w.update_transport()
settle_geometry(w.control_island, volume)
volume.button.click()
assert volume.slider.isVisibleTo(volume) and volume.animation.state() == volume.animation.State.Stopped
w.close()
''', tmp_path)


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
