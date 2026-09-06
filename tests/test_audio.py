import sys
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.audio import capture
from linguaflow.core import Settings


def test_stereo_capture_downmixes_resamples_and_stops(monkeypatch):
    class Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def record(self, numframes):
            assert numframes == 4800
            return np.column_stack([np.full(4800, 0.2), np.full(4800, 0.4)])

    device = SimpleNamespace(id="test", isloopback=True, recorder=lambda **kwargs: Recorder())
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=lambda **kw: [device]))
    stop = Event()
    blocks = []

    def on_block(block):
        blocks.append(block)
        stop.set()

    capture(Settings("test", loopback=True), stop, on_block)
    assert len(blocks) == 1
    assert blocks[0].shape == (1600,)
    assert blocks[0].dtype == np.float32
    assert float(blocks[0][20:-20].mean()) == pytest.approx(0.3, abs=0.001)


def test_disconnected_device_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=lambda **kw: []))
    with pytest.raises(RuntimeError, match="断开"):
        capture(Settings("gone"), Event(), lambda block: None)
