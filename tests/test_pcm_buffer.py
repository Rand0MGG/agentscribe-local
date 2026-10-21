import numpy as np
import pytest

from linguaflow.audio_processing.buffer import PCMBuffer


def test_pcm_append_discard_silence_and_backlog_preserve_every_sample():
    buffer = PCMBuffer(64)
    expected = np.empty(0, np.float32)
    for step in range(100):
        chunk = np.arange(step, step + 17, dtype=np.float32)
        buffer.append(chunk)
        expected = np.concatenate((expected, chunk))
        chunk[:] = -1  # Capture may reuse its input allocation.
        if step % 3 == 0:
            buffer.silence(5)
            expected = np.concatenate((expected, np.zeros(5, np.float32)))
        if step % 5 == 0:
            drop = len(expected) // 2
            buffer.discard(drop)
            expected = expected[drop:]
        np.testing.assert_array_equal(buffer.samples, expected)
    snapshot = buffer.samples.copy()
    buffer.append(np.arange(10000, dtype=np.float32))
    buffer.discard(len(buffer.samples))
    buffer.append(np.ones(10))
    np.testing.assert_array_equal(snapshot, expected)
    np.testing.assert_array_equal(buffer.samples, np.ones(10))
    assert buffer.samples.base.nbytes <= 4 * buffer.reserve * 4
    with pytest.raises(ValueError):
        buffer.discard(11)
    np.testing.assert_array_equal(buffer.samples, np.ones(10))
