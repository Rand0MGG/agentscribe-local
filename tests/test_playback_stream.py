"""Read and seek amplified WAV bytes without loading an audio backend."""
import hashlib
import io
import struct
import wave

import numpy as np
import pytest

from linguaflow.playback_stream import PlaybackStream, amplify


@pytest.mark.p0
@pytest.mark.parametrize('cut', [0, 1, 7])
def test_interrupted_recording_recovers_physical_frames_without_modifying_original(tmp_path, cut):
    path = tmp_path/'录音.wav'
    pcm = np.arange(100, dtype='<i2').tobytes()
    with wave.open(str(path), 'wb') as writer:
        writer.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        writer.writeframes(pcm[:80])
    with path.open('ab') as output:
        output.write(pcm[80:len(pcm)-cut] if cut else pcm[80:])
    original = path.read_bytes()
    stream = PlaybackStream(path, recover_recording=True)
    try:
        assert stream.recovered
        restored = bytes(stream.read(stream.size()))
        expected = pcm[:(len(pcm)-cut)//2*2]
        with wave.open(io.BytesIO(restored)) as reader:
            assert reader.getnframes() == len(expected)//2
            assert reader.readframes(1000) == expected
        for start in (3, 5, 39, 41, len(restored)-1):
            assert stream.seek(start)
            assert bytes(stream.read(8)) == restored[start:start+8]
        stream.set_gain(2)
        assert stream.seek(44)
        assert bytes(stream.read(stream.size())) == amplify(expected, 1, 16, 2)
    finally:
        stream.close()
    assert path.read_bytes() == original


@pytest.mark.p2
def test_live_recording_cannot_be_recovered_and_generic_wav_tail_is_not_audio(tmp_path):
    from linguaflow.library_access import acquire_recording_lock
    path = tmp_path/'录音.wav'
    with wave.open(str(path), 'wb') as writer:
        writer.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        writer.writeframes(b'\x01\x00'*20)
    lock = acquire_recording_lock(tmp_path)
    try:
        with pytest.raises(ValueError, match='另一个窗口'):
            PlaybackStream(path, recover_recording=True)
    finally:
        lock.unlock()
    with path.open('ab') as output:
        output.write(b'physical tail outside RIFF')
    stream = PlaybackStream(path)
    try:
        assert not stream.recovered and stream.data_size == 40
    finally:
        stream.close()


@pytest.mark.p0
def test_gain_stream_preserves_headers_original_and_random_byte_seeks(tmp_path):
    path = tmp_path/'课堂录音.wav'
    samples = np.array([-20000, -1200, 0, 1400, 20000]*400, dtype='<i2')
    with wave.open(str(path), 'wb') as writer:
        writer.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
        writer.writeframes(samples.tobytes())
    original = path.read_bytes()
    digest = hashlib.sha256(original).digest()
    stream = PlaybackStream(path)
    try:
        assert stream.supports_gain and bytes(stream.read(stream.size())) == original
        stream.set_gain(3)
        expected = (original[:stream.data_start]
                    +np.clip(samples.astype(np.int32)*3, -32768, 32767).astype('<i2').tobytes())
        assert stream.seek(0)
        assert bytes(stream.read(45))+bytes(stream.read(stream.size())) == expected
        for position in (0, 13, 43, 44, 45, 47, len(expected)-1, len(expected)):
            assert stream.seek(position)
            assert bytes(stream.read(7)) == expected[position:position+7]
        stream.set_gain(1)
        assert stream.seek(0) and bytes(stream.read(stream.size())) == original
        assert not stream.seek(len(original)+1)
    finally:
        stream.close()
    assert hashlib.sha256(path.read_bytes()).digest() == digest
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.p2
@pytest.mark.parametrize('bits', [8, 16, 24, 32])
def test_pcm_gain_saturates_instead_of_wrapping(bits):
    if bits == 24:
        raw = bytes.fromhex('000080ffffff000000010000ffff7f')
        assert amplify(raw, 1, 24, 3) == bytes.fromhex('000080fdffff000000030000ffff7f')
    else:
        dtype = 'u1' if bits == 8 else f'<i{bits//8}'
        limits = np.iinfo(dtype)
        centre = 128 if bits == 8 else 0
        values = np.array([limits.min, centre-1, centre, centre+1, limits.max], dtype=dtype)
        out = np.frombuffer(amplify(values.tobytes(), 1, bits, 3), dtype=dtype)
        assert out.tolist() == [limits.min, centre-3, centre, centre+3, limits.max]


@pytest.mark.p2
def test_float_gain_is_finite_and_read_chunks_are_bounded(tmp_path):
    samples = np.array([-.2, .2, -2, 2, np.nan, np.inf], dtype='<f4')
    out = np.frombuffer(amplify(samples.tobytes(), 3, 32, 3), dtype='<f4')
    assert np.allclose(out, [-.6, .6, -1, 1, 0, 1])
    path = tmp_path/'float.wav'
    payload = samples.tobytes()*100000
    fmt = struct.pack('<HHIIHH', 3, 1, 16000, 64000, 4, 32)
    path.write_bytes(b'RIFF'+struct.pack('<I', 36+len(payload))+b'WAVEfmt '+struct.pack('<I', 16)+fmt
                     +b'data'+struct.pack('<I', len(payload))+payload)
    stream = PlaybackStream(path)
    try:
        assert stream.supports_gain
        stream.set_gain(2)
        assert len(stream.readData(len(payload)+100)) <= 1024*1024
    finally:
        stream.close()


@pytest.mark.p2
def test_unknown_encoding_is_readonly_passthrough_without_fake_boost(tmp_path):
    path = tmp_path/'unsupported.wav'
    path.write_bytes(b'not a WAV')
    stream = PlaybackStream(path)
    try:
        assert not stream.supports_gain
        with pytest.raises(ValueError, match='不支持'):
            stream.set_gain(2)
        assert bytes(stream.read(stream.size())) == path.read_bytes()
    finally:
        stream.close()
