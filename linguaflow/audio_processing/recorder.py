"""Bounded audio audition capture worker; no dialog or inference dependencies."""
import threading
import wave
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QThread, Signal

from ..audio import capture
from .health import signal_stats


class Recorder(QThread):
    progress = Signal(float)
    failure = Signal(str)
    level = Signal(float, bool)

    def __init__(self, device, path, seconds, parent=None, *, capture_fn=capture):
        super().__init__(parent)
        self.device, self.path, self.seconds = device, path, seconds
        self.capture_fn = capture_fn
        self.stop = threading.Event()
        self.health = {"samples": 0, "nonzero": 0, "peak": 0., "rms_dbfs": -180.}

    def run(self):
        try:
            settings = SimpleNamespace(device_id=self.device[0], loopback=self.device[1], input_sample_rate=48000)
            with wave.open(str(self.path), "wb") as output:
                output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                count = 0

                def write(samples):
                    nonlocal count
                    samples = samples[:max(0, int(self.seconds * 48000) - count)]
                    health = signal_stats(samples)
                    self.health["nonzero"] += health["nonzero"]
                    self.health["samples"] += len(samples)
                    self.health["peak"] = max(self.health["peak"], health["peak"])
                    self.level.emit(health["rms_dbfs"], bool(self.health["nonzero"]))
                    output.writeframesraw((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                    count += len(samples)
                    self.progress.emit(count / 48000)
                    if count >= self.seconds * 48000:
                        self.stop.set()

                self.capture_fn(settings, self.stop, write)
        except Exception as exc:
            self.failure.emit(str(exc))


