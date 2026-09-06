import numpy as np

from linguaflow.core import Caption, Settings, export_srt
from linguaflow.journal import AudioJournal
from linguaflow.streaming import WhisperReviser


def test_source_is_revised_before_finalization():
    class Recognizer:
        calls = 0

        def recognize_words(self, audio, prompt):
            self.calls += 1
            text = "我们去公园" if self.calls == 1 else "我们去公演现场"
            return [(0, len(audio) / 16000, text)], "zh"

    processor = WhisperReviser(Recognizer(), Settings("fake"))
    first = processor.update(np.ones(16000, np.float32))[0]
    second = processor.update(np.ones(16000, np.float32))[0]
    final = processor.update(np.empty(0, np.float32), final=True)[0]
    assert first.id == second.id == final.id
    assert first.source != second.source == final.source
    assert not first.final and not second.final and final.final
    assert first.revision < second.revision < final.revision
    assert export_srt([first, second]) == ""


def test_journal_preserves_quiet_samples_and_backlog():
    journal = AudioJournal()
    samples = np.linspace(-0.00001, 0.00001, 160000, dtype=np.float32)
    try:
        for block in np.split(samples, 100):
            journal.append(block)
        assert journal.pending_seconds == 10
        restored = np.concatenate([journal.read(1600) for _ in range(100)])
        np.testing.assert_array_equal(restored, samples)
        assert journal.pending_seconds == 0
    finally:
        journal.close()


def test_long_stream_checkpoint_keeps_unconfirmed_tail():
    class Recognizer:
        def recognize_words(self, audio, prompt):
            return [(0, 3, " Hello"), (3, 7, " world"), (18, 20, " tail")], "en"

    processor = WhisperReviser(Recognizer(), Settings("fake"))
    processor.update(np.ones(19 * 16000, np.float32))
    result = processor.update(np.ones(16000, np.float32))
    assert len(result) == 2
    assert result[0].final and result[0].source == "Hello world"
    assert not result[1].final and result[1].source == "tail"
    assert processor.offset == 6
    assert processor.cutoff == 7


def test_draft_retraction_is_emitted():
    class Recognizer:
        calls = 0

        def recognize_words(self, audio, prompt):
            self.calls += 1
            return ([(0, 1, "noise")] if self.calls == 1 else []), "en"

    processor = WhisperReviser(Recognizer(), Settings("fake"))
    processor.update(np.zeros(16000, np.float32))
    result = processor.update(np.zeros(16000, np.float32), final=True)
    assert len(result) == 1 and result[0].source == "" and result[0].final


def test_drafts_are_never_queued_for_translation():
    from linguaflow.engine import Session

    session = Session(Settings("fake"))
    session._publish([Caption(1, 0, 1, "draft", "en", final=False)])
    assert session.text_queue.empty()
    session._publish([Caption(1, 0, 2, "corrected", "en", final=True, revision=2)])
    assert session.text_queue.get_nowait().source == "corrected"
