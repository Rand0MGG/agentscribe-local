"""Seekable, bounded WAV gain on read; never rewrite or duplicate recordings."""
import logging
import os
import struct
from pathlib import Path
from threading import RLock

import numpy as np
from PySide6.QtCore import QIODevice


class PlaybackStream(QIODevice):
    def __init__(self, path, parent=None, *, recover_recording=False):
        super().__init__(parent)
        self._lock = RLock()
        self._file = Path(path).open('rb')
        self._size = os.fstat(self._file.fileno()).st_size
        self.gain = 1.
        self.recovered = False
        self._header = b''
        self.data_start, self.data_size, self.encoding, self.bits = 0, 0, 0, 0
        try:
            if recover_recording:
                from .library_access import acquire_recording_lock
                lock = acquire_recording_lock(Path(path).parent)
                try:
                    self._recover_header()
                finally:
                    lock.unlock()
            self._inspect()
            self._file.seek(0)
            self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        except BaseException:
            self._file.close()
            raise

    def _recover_header(self):
        """Expose complete persisted frames of our interrupted mono PCM writer.

        Never rewrite the original or interpret arbitrary WAV trailing chunks as
        audio. The caller must identify an unfinished app recording; its lock
        prevents inspecting a live writer. Only our exact 44-byte layout qualifies.
        """
        self._file.seek(0)
        header = self._file.read(44)
        if (len(header) != 44 or header[:4] != b'RIFF' or header[8:16] != b'WAVEfmt '
                or header[36:40] != b'data'):
            return
        fmt_size, encoding, channels, rate, byte_rate, align, bits = struct.unpack_from('<IHHIIHH', header, 16)
        if (fmt_size, encoding, channels, align, bits) != (16, 1, 1, 2, 16) or not rate or byte_rate != rate*2:
            return
        size = (self._size-44)//align*align
        if size > 0xffffffff-36:
            raise ValueError('录音超出 WAV 长度上限，请保留原件并使用音频恢复工具。')
        fixed = bytearray(header)
        struct.pack_into('<I', fixed, 4, size+36)
        struct.pack_into('<I', fixed, 40, size)
        self.recovered = bytes(fixed) != header or self._size != size+44
        self._header = bytes(fixed)
        self._size = size+44

    def _inspect(self):
        self._file.seek(0)
        header = self._header[:12] or self._file.read(12)
        self._file.seek(12)
        if header[:4] != b'RIFF' or header[8:] != b'WAVE':
            return
        limit = min(self._size, struct.unpack_from('<I', header, 4)[0]+8)
        while self._file.tell()+8 <= limit:
            offset = self._file.tell()
            raw = self._file.read(8)
            kind, size = struct.unpack('<4sI', self._header[offset:offset+8] or raw)
            start = self._file.tell()
            if start+size > self._size:
                raise ValueError('录音 WAV 数据不完整。')
            if kind == b'fmt ':
                info = self._file.read(min(size, 40))
                if len(info) >= 16:
                    self.encoding, self.bits = struct.unpack_from('<H', info)[0], struct.unpack_from('<H', info, 14)[0]
                    if self.encoding == 65534 and len(info) >= 40:
                        self.encoding = struct.unpack_from('<H', info, 24)[0]
            elif kind == b'data':
                self.data_start, self.data_size = start, size
            self._file.seek(start+size+(size % 2))

    @property
    def supports_gain(self):
        return self.data_size > 0 and ((self.encoding == 1 and self.bits in (8, 16, 24, 32))
                                      or (self.encoding == 3 and self.bits == 32))

    def set_gain(self, gain):
        if not 1 <= gain <= 3:
            raise ValueError('回放增益必须在 100% 至 300% 之间。')
        if gain > 1 and not self.supports_gain:
            raise ValueError('该录音格式不支持增益放大。')
        with self._lock:
            self.gain = float(gain)

    def isSequential(self):
        return False

    def size(self):
        return self._size

    def seek(self, position):
        with self._lock:
            if self._file.closed or not 0 <= position <= self._size or not super().seek(position):
                return False
            self._file.seek(position)
            return True

    def readData(self, maximum):
        with self._lock:
            if self._file.closed:
                return b''
            try:
                start = self._file.tell()
                raw = self._file.read(min(maximum, 1024*1024, self._size-start))
                end = start+len(raw)
                if self._header and start < len(self._header):
                    count = min(end, len(self._header))-start
                    raw = self._header[start:start+count]+raw[count:]
                if self.gain == 1 or end <= self.data_start or start >= self.data_start+self.data_size:
                    return raw
                width = self.bits//8
                first, last = max(start, self.data_start), min(end, self.data_start+self.data_size)
                # Decoder reads may split a PCM sample. Transform whole samples,
                # then return exactly the requested bytes, including odd offsets.
                aligned = first-(first-self.data_start) % width
                limit = min(self.data_start+self.data_size, last+(-(last-self.data_start) % width))
                self._file.seek(aligned)
                amplified = amplify(self._file.read(limit-aligned), self.encoding, self.bits, self.gain)
                self._file.seek(end)
                return raw[:first-start]+amplified[first-aligned:last-aligned]+raw[last-start:]
            except (OSError, ValueError) as exc:
                self.setErrorString(str(exc))
                logging.getLogger(__name__).exception('Could not read recording playback stream')
                return b''

    def writeData(self, data):
        return -1

    def close(self):
        with self._lock:
            super().close()
            self._file.close()


def amplify(data, encoding, bits, gain):
    """Saturate peaks instead of overflowing signed PCM; float output stays finite."""
    if encoding == 3:
        values = np.frombuffer(data, dtype='<f4').astype(np.float64)
        return np.clip(np.nan_to_num(values, nan=0., posinf=1., neginf=-1.)*gain, -1, 1).astype('<f4').tobytes()
    if bits == 24:
        packed = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
        values = packed[:, 0].astype(np.int32) | (packed[:, 1].astype(np.int32) << 8) | (packed[:, 2].astype(np.int32) << 16)
        values = ((values ^ 0x800000)-0x800000).astype(np.float64)
        values = np.clip(np.rint(values*gain), -8388608, 8388607).astype(np.int32)
        return np.stack([values & 255, (values >> 8) & 255, (values >> 16) & 255], axis=1).astype(np.uint8).tobytes()
    dtype = 'u1' if bits == 8 else f'<i{bits//8}'
    offset = 128 if bits == 8 else 0
    values = np.frombuffer(data, dtype=dtype).astype(np.float64)-offset
    peak = 2**(bits-1)
    return (np.clip(np.rint(values*gain), -peak, peak-1)+offset).astype(dtype).tobytes()
