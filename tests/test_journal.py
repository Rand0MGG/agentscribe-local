import numpy as np
import pytest

from linguaflow.journal import AudioJournal


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

