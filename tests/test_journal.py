import numpy as np
import pytest

from linguaflow.journal import AudioJournal


def test_consumed_chunks_release_disk_and_preserve_absolute_pause_positions(monkeypatch):
    import tempfile

    streams = []
    create = tempfile.TemporaryFile

    def tracked(*args, **kwargs):
        stream = create(*args, **kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr('linguaflow.journal.tempfile.TemporaryFile', tracked)
    journal = AudioJournal()
    journal.chunk_bytes = 64
    try:
        for cycle in range(20):
            samples = np.arange(45, dtype=np.float32) + cycle * 45
            journal.append(samples[:20])
            journal.mark_pause()
            journal.append(samples[20:])
            np.testing.assert_array_equal(journal.read(100), samples[:20])
            assert streams[-3].closed  # Consumed prefix freed with backlog still present.
            assert journal.take_pause()
            np.testing.assert_array_equal(journal.read(100), samples[20:])
            assert journal.pending_seconds == 0
            live = [stream for stream in streams if not stream.closed]
            assert len(live) == 1
            live[0].seek(0, 2)
            assert live[0].tell() == 0  # One reusable empty file, no consumed PCM.
            assert journal.written == (cycle + 1) * 45 * 4
        journal.append(np.ones(17, dtype=np.float32))
    finally:
        journal.close()
    assert all(stream.closed for stream in streams)


def test_live_draining_reuses_one_empty_file_and_keeps_pause_clock(monkeypatch):
    import tempfile

    streams = []
    create = tempfile.TemporaryFile

    def tracked(*args, **kwargs):
        stream = create(*args, **kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr('linguaflow.journal.tempfile.TemporaryFile', tracked)
    journal = AudioJournal()
    samples = np.arange(1600, dtype=np.float32)
    try:
        for _ in range(1000):
            journal.append(samples)
            journal.mark_pause()
            np.testing.assert_array_equal(journal.read(16000), samples)
            assert journal.take_pause() and not journal.take_pause()
        assert journal.written == journal.read_position == 1000 * 1600 * 4
        assert len(streams) == 1 and journal.pending_seconds == 0
        streams[0].seek(0, 2)
        assert streams[0].tell() == 0
    finally:
        journal.close()
    assert streams[0].closed


@pytest.mark.parametrize("rate", [16000, 48000])
def test_journal_preserves_quiet_samples_and_backlog(rate):
    journal = AudioJournal(rate)
    samples = np.linspace(-0.00001, 0.00001, 160000, dtype=np.float32)
    try:
        for block in np.split(samples, 100):
            journal.append(block)
        assert journal.pending_seconds == 160000 / rate
        restored = np.concatenate([journal.read(1600) for _ in range(100)])
        np.testing.assert_array_equal(restored, samples)
        assert journal.pending_seconds == 0
    finally:
        journal.close()


def test_pause_markers_stay_between_audio_segments_even_with_backlog():
    journal = AudioJournal()
    try:
        journal.append(np.ones(3, dtype=np.float32))
        journal.mark_pause()
        journal.mark_pause()
        journal.append(np.ones(2, dtype=np.float32) * 2)
        assert not journal.take_pause()
        assert journal.read(100).tolist() == [1, 1, 1]
        assert not len(journal.read(100))
        assert journal.take_pause() and journal.take_pause()
        assert journal.read(100).tolist() == [2, 2]
        assert not journal.take_pause()
    finally:
        journal.close()
