"""Contiguous PCM storage: append without copying the retained window each time."""
import numpy as np


class PCMBuffer:
    def __init__(self, reserve):
        self.reserve = reserve
        self._data = np.empty(0, dtype=np.float32)
        self._start = self._end = 0

    @property
    def samples(self):
        return self._data[self._start:self._end]

    def _space(self, count):
        length = self._end - self._start
        if self._end + count > len(self._data):
            if length + count <= len(self._data) and self._start >= len(self._data) // 2:
                self._data[:length] = self.samples
            else:
                data = np.empty(max(self.reserve, length + count, len(self._data) * 2), dtype=np.float32)
                data[:length] = self.samples
                self._data = data
            self._start, self._end = 0, length
        start = self._end
        self._end += count
        return self._data[start:self._end]

    def append(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError('PCM 音频必须为一维单声道采样。')
        self._space(len(samples))[:] = samples

    def silence(self, count):
        self._space(count).fill(0)

    def discard(self, count):
        if not 0 <= count <= self._end - self._start:
            raise ValueError('PCM 丢弃范围超过已有采样。')
        self._start += count
        length = self._end - self._start
        if len(self._data) > 4 * max(self.reserve, length):
            # A temporary backlog must not pin its peak allocation forever.
            data = np.empty(max(self.reserve, length * 2), dtype=np.float32)
            data[:length] = self.samples
            self._data = data
            self._start, self._end = 0, length
        elif not length:
            self._start = self._end = 0
