"""Read actual 8-bit RGB/RGBA PNG evidence without a GUI/image dependency."""
import struct
import zlib
from pathlib import Path

import numpy as np


def png_pixels(path):
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset, compressed = 8, bytearray()
    while offset < len(data):
        length = struct.unpack_from('>I', data, offset)[0]
        kind, value = data[offset+4:offset+8], data[offset+8:offset+8+length]
        assert zlib.crc32(kind + value) == struct.unpack_from('>I', data, offset+8+length)[0]
        if kind == b'IHDR':
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', value)
            assert depth == 8 and color in (2, 6) and compression == filtering == interlace == 0
        elif kind == b'IDAT':
            compressed.extend(value)
        offset += length + 12
    channels = 3 if color == 2 else 4
    stride = width * channels
    raw = zlib.decompress(compressed)
    assert len(raw) == height * (stride + 1)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        mode, row = raw[start], bytearray(raw[start+1:start+stride+1])
        previous = rows[-1] if rows else bytearray(stride)
        assert mode in range(5)
        for x in range(stride):
            a, b, c = (row[x-channels] if x >= channels else 0), previous[x], (previous[x-channels] if x >= channels else 0)
            p = a + b - c
            distances = abs(p-a), abs(p-b), abs(p-c)
            paeth = (a, b, c)[distances.index(min(distances))]
            row[x] = (row[x] + (0, a, b, (a+b)//2, paeth)[mode]) & 255
        rows.append(row)
    return np.frombuffer(b''.join(rows), dtype=np.uint8).reshape(height, width, channels)
