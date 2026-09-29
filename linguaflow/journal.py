"""Lossless session audio queue, backed by a temporary file instead of dropping PCM."""
import tempfile
from collections import deque
from threading import Lock

import numpy as np


class AudioJournal:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.file = tempfile.TemporaryFile(prefix="linguaflow-", suffix=".pcm")
        self.lock = Lock()
        self.written = 0
        self.read_position = 0
        self.pauses = deque()

    def mark_pause(self):
        with self.lock:
            self.pauses.append(self.written)

    def take_pause(self):
        with self.lock:
            if self.pauses and self.pauses[0] == self.read_position:
                self.pauses.popleft()
                return True
            return False

    def append(self, samples):
        data = np.asarray(samples, dtype="<f4").tobytes()
        with self.lock:
            self.file.seek(self.written)
            self.file.write(data)
            self.written += len(data)

    def read(self, count):
        with self.lock:
            self.file.seek(self.read_position)
            end = self.pauses[0] if self.pauses else self.written
            data = self.file.read(min(count * 4, end - self.read_position))
            self.read_position += len(data)
        return np.frombuffer(data, dtype="<f4").copy()

    @property
    def pending_seconds(self):
        with self.lock:
            return (self.written - self.read_position) / (self.sample_rate * 4)

    def close(self):
        self.file.close()
