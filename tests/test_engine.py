import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QCoreApplication

from linguaflow.core import Settings
from linguaflow.engine import Session


class Recognizer:
    def __init__(self, settings):
        pass

    def recognize(self, samples):
        return [(0, len(samples) / 16000, "Hello")], "en"


class Translator:
    def __init__(self, settings):
        pass

    def translate(self, text, language):
        return "你好"


def capture(settings, stop, on_block):
    for _ in range(8):
        on_block(np.full(1600, 0.1, dtype=np.float32))


def execute(**kwargs):
    app = QCoreApplication.instance() or QCoreApplication([])
    session = Session(
        Settings("fake"),
        recognizer_factory=Recognizer,
        translator_factory=kwargs.get("translator", Translator),
        capture_fn=kwargs.get("capture", capture),
    )
    captions, errors = [], []
    session.caption.connect(captions.append)
    session.failure.connect(errors.append)
    session.start()
    deadline = time.monotonic() + 5
    while session.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    if session.isRunning():
        session.stop(discard=True)
        session.wait(3000)
        raise AssertionError("Session failed to stop")
    app.processEvents()
    return captions, errors


def test_source_then_translation_and_flush_on_stop():
    captions, errors = execute()
    assert not errors
    assert len(captions) == 3
    assert captions[0].source == "Hello"
    assert captions[0].translation == ""
    assert not captions[0].final
    assert captions[1].final
    assert captions[2].translation == "你好"
    assert captions[0].id == captions[1].id
    assert captions[1].end == 0.8


def test_translation_failure_preserves_source():
    class BrokenTranslator(Translator):
        def translate(self, text, language):
            raise RuntimeError("bad model")

    captions, errors = execute(translator=BrokenTranslator)
    assert not errors
    assert captions[-1].source == "Hello"
    assert captions[-1].error == "bad model"


def test_capture_failure_finishes_without_hanging():
    def broken_capture(*args):
        raise RuntimeError("device disconnected")

    captions, errors = execute(capture=broken_capture)
    assert not captions
    assert "device disconnected" in errors[0]


def test_stop_during_model_loading_never_opens_microphone():
    from threading import Event

    entered, release = Event(), Event()
    opened = []

    class SlowRecognizer(Recognizer):
        def __init__(self, settings):
            entered.set()
            release.wait(2)

    session = Session(
        Settings("fake"), recognizer_factory=SlowRecognizer, capture_fn=lambda *args: opened.append(True)
    )
    session.start()
    assert entered.wait(2)
    session.stop()
    release.set()
    assert session.wait(3000)
    assert not opened


def test_no_translation_mode_does_not_load_translator():
    app = QCoreApplication.instance() or QCoreApplication([])
    loaded = []
    captions = []
    session = Session(
        Settings("fake", translate=False),
        recognizer_factory=Recognizer,
        translator_factory=lambda settings: loaded.append(True),
        capture_fn=capture,
    )
    session.caption.connect(captions.append)
    session.start()
    assert session.wait(3000)
    app.processEvents()
    assert not loaded
    assert len(captions) == 2
    assert captions[0].source == "Hello"


def test_model_failure_never_opens_audio_and_finishes():
    app = QCoreApplication.instance() or QCoreApplication([])
    opened, errors = [], []

    def broken_model(settings):
        raise RuntimeError("model unavailable offline")

    session = Session(
        Settings("fake"), recognizer_factory=broken_model, capture_fn=lambda *args: opened.append(True)
    )
    session.failure.connect(errors.append)
    session.start()
    assert session.wait(3000)
    app.processEvents()
    assert not opened
    assert "model unavailable offline" in errors[0]


def test_warmup_failure_prevents_capture_and_translation():
    app = QCoreApplication.instance() or QCoreApplication([])
    opened, loaded, errors = [], [], []

    class MissingCuda(Recognizer):
        def warmup(self):
            raise RuntimeError("cublas64_12.dll missing")

    session = Session(
        Settings("fake"),
        recognizer_factory=MissingCuda,
        translator_factory=lambda s: loaded.append(True),
        capture_fn=lambda *a: opened.append(True),
    )
    session.failure.connect(errors.append)
    session.start()
    assert session.wait(3000)
    app.processEvents()
    assert not opened and not loaded
    assert "cublas64_12.dll" in errors[0]
    assert session.last_error == errors[0]


def test_source_emits_while_translation_is_still_loading():
    from threading import Event

    app = QCoreApplication.instance() or QCoreApplication([])
    release = Event()
    captions = []

    class SlowTranslator(Translator):
        def __init__(self, settings):
            release.wait(3)

    session = Session(
        Settings("fake"), recognizer_factory=Recognizer, translator_factory=SlowTranslator, capture_fn=capture
    )
    session.caption.connect(captions.append)
    session.start()
    deadline = time.monotonic() + 2
    while not captions and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    source_arrived = bool(captions)
    release.set()
    assert session.wait(3000)
    app.processEvents()
    assert source_arrived
    assert captions[-1].translation == "你好"


def test_translation_load_failure_keeps_recognition():
    class BrokenLoader:
        def __init__(self, settings):
            raise RuntimeError("translation unavailable")

    captions, errors = execute(translator=BrokenLoader)
    assert not errors
    assert captions[-1].source == "Hello"
    assert "translation unavailable" in captions[-1].error
