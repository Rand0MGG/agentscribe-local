"""User interaction acceptance without capturing or playing audio."""
from ui_support import run_ui


def test_live_overlay_catches_up_and_controls_release_reading_space(tmp_path):
    run_ui(r'''
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from linguaflow.core import Caption
module.Window.start_background_check = lambda *args, **kwargs: None
class Session(QObject):
    caption = Signal(object)
session = Session()
session.caption.connect(w.on_caption)
w.show()
w.set_recording_state(module.RecordingState.LISTENING)
w.caption_translation = True
session.caption.emit(Caption(10, 0, 3, 'Earlier source', 'en', '早先译文'))
latest = Caption(2, 4, 7, 'Current live source', 'en', '当前译文')
session.caption.emit(latest)
w.toggle_overlay()
wait(w.overlay.isVisible)
assert w.overlay.source.text() == latest.source and w.overlay.target.text() == latest.translation
session.caption.emit(replace(latest, source='Revised live source', revision=2, translation='更新译文'))
assert w.overlay.source.text() == 'Revised live source' and w.overlay.target.text() == '更新译文'
w.toggle_overlay()
session.caption.emit(Caption(3, 8, 10, 'Received while hidden', 'en', '隐藏期间字幕'))
w.toggle_overlay()
assert w.overlay.source.text() == 'Received while hidden'
o = w.overlay
o.set_controls_visible(True)
settle_geometry(o, o.scroll)
geometry, reading_height = o.geometry(), o.scroll.height()
o.set_controls_visible(False)
settle_geometry(o, o.scroll)
assert o.geometry() == geometry and o.scroll.height() > reading_height
w.set_recording_state(module.RecordingState.IDLE)
w.close()
''', tmp_path)


def test_click_only_on_caption_text_plays_but_selection_and_live_recording_do_not(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from linguaflow.core import Caption
module.Window.start_background_check = lambda *args, **kwargs: None
w.show(); w.reduce_motion.setChecked(True)
w.on_caption(Caption(1, 12, 20, 'A short sentence.', 'en', '一句话。'))
w.playback.setProperty('available', True)
w.update_transport()
settle_geometry(w)
positions, plays = [], []
w.player = SimpleNamespace(setPosition=positions.append, play=lambda: plays.append(True),
    stop=lambda: None, setSource=lambda _: None)
text = w.cards[1].source
point = QPoint(5, text.height()//2)
QTest.mouseClick(text, Qt.MouseButton.LeftButton, pos=QPoint(text.width()-2, text.height()//2))
QTest.qWait(app.doubleClickInterval()+20)
assert not plays
QTest.mousePress(text, Qt.MouseButton.LeftButton, pos=point)
QTest.mouseMove(text, point+QPoint(60,0))
QTest.mouseRelease(text, Qt.MouseButton.LeftButton, pos=point+QPoint(60,0))
QTest.qWait(app.doubleClickInterval()+20)
assert not plays
text.setSelection(0,0)
QTest.mouseClick(text, Qt.MouseButton.LeftButton, pos=point)
QTest.mouseDClick(text, Qt.MouseButton.LeftButton, pos=point)
QTest.qWait(app.doubleClickInterval()+20)
assert not plays
text.setSelection(0,0)
QTest.mouseClick(text, Qt.MouseButton.LeftButton, pos=point)
wait(lambda: bool(plays))
assert positions == [12000] and plays == [True]
w.set_recording_state(module.RecordingState.LISTENING)
QTest.mouseClick(text, Qt.MouseButton.LeftButton, pos=point)
QTest.qWait(app.doubleClickInterval()+20)
assert plays == [True]
w.set_recording_state(module.RecordingState.IDLE)
w.session_dirty = False
w.close()
''', tmp_path)


def test_player_reads_real_gain_stream_and_closes_it_without_changing_original(tmp_path):
    run_ui(r'''
import sys, types, wave
from enum import Enum
from PySide6.QtCore import QObject, Signal
module.Window.start_background_check = lambda *args, **kwargs: None
class State(Enum):
    StoppedState = 0
    PlayingState = 1
class Output(QObject):
    def setVolume(self, value):
        assert 0 <= value <= 1
        self.volume = value
class Player(QObject):
    durationChanged = Signal(int)
    positionChanged = Signal(int)
    playbackStateChanged = Signal(object)
    errorOccurred = Signal(object, str)
    PlaybackState = State
    def __init__(self, parent):
        super().__init__(parent); self.state = State.StoppedState; self.offset = 0
    def setAudioOutput(self, output): self.output = output
    def setSourceDevice(self, stream, url): self.device = stream
    def setSource(self, url): self.device = None
    def setPosition(self, value): self.offset = value
    def position(self): return self.offset
    def playbackState(self): return self.state
    def play(self): self.state = State.PlayingState
    def pause(self): self.state = State.StoppedState
    def stop(self): self.state = State.StoppedState
sys.modules['PySide6.QtMultimedia'] = types.SimpleNamespace(QAudioOutput=Output, QMediaPlayer=Player)
assert w.new_recording(name='增益验证', check_models=False)
path = w.library.directory(w.current_item['id'])/'录音.wav'
with wave.open(str(path), 'wb') as writer:
    writer.setparams((1,2,16000,0,'NONE','not compressed'))
    writer.writeframes(b'\xe8\x03'*16000)
original = path.read_bytes()
w.prepare_playback()
stream = w.playback_stream
assert w.player.device is stream and stream.supports_gain
w.playback_volume.slider.setValue(250)
assert stream.gain == 2.5 and w.audio_output.volume == 1
assert stream.seek(stream.data_start) and bytes(stream.read(2)) == b'\xc4\x09'
w.playback_volume.slider.setValue(25)
assert stream.gain == 1 and w.audio_output.volume == .25
w.release_playback()
assert not stream.isOpen() and stream._file.closed and w.playback_stream is None
assert path.read_bytes() == original
w.close()
''', tmp_path)
