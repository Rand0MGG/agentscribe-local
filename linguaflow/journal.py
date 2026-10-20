"""Lossless audio queue; consumed temporary chunks release disk space."""
import tempfile
from collections import deque
from threading import Lock

import numpy as np


class AudioJournal:
    chunk_bytes = 4 * 1024 * 1024

    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.chunks = deque()
        self.lock = Lock()
        # Absolute byte offsets survive chunk reclamation for clocks and pause markers.
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
            offset = 0
            while offset < len(data):
                if not self.chunks or self.written - self.chunks[-1][0] == self.chunk_bytes:
                    self.chunks.append((self.written, tempfile.TemporaryFile(
                        prefix="linguaflow-", suffix=".pcm")))
                start, stream = self.chunks[-1]
                position = self.written - start
                size = min(len(data) - offset, self.chunk_bytes - position)
                stream.seek(position)
                stream.write(data[offset:offset + size])
                self.written += size
                offset += size

    def read(self, count):
        with self.lock:
            end = self.pauses[0] if self.pauses else self.written
            remaining = min(count * 4, end - self.read_position)
            blocks = []
            while remaining > 0:
                start, stream = self.chunks[0]
                chunk_end = min(start + self.chunk_bytes, self.written)
                stream.seek(self.read_position - start)
                data = stream.read(min(remaining, chunk_end - self.read_position))
                if not data:
                    raise OSError("Audio journal ended before committed samples.")
                blocks.append(data)
                self.read_position += len(data)
                remaining -= len(data)
                if self.read_position == chunk_end:
                    if len(self.chunks) == 1:
                        # Keep one empty file for the next block instead of
                        # creating/deleting a file at capture frequency.
                        stream.seek(0)
                        stream.truncate()
                        self.chunks[0] = (self.written, stream)
                    else:
                        stream.close()
                        self.chunks.popleft()
        return np.frombuffer(b''.join(blocks), dtype="<f4").copy()

    @property
    def pending_seconds(self):
        with self.lock:
            return (self.written - self.read_position) / (self.sample_rate * 4)

    def close(self):
        with self.lock:
            while self.chunks:
                self.chunks.popleft()[1].close()
