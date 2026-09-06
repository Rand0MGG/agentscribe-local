from queue import Queue

import numpy as np
import pytest

from linguaflow.core import Caption, Segmenter, export_srt, offer_latest, srt_time


def block(value=0):
    return np.full(1600, value, dtype=np.float32)


def test_silence_does_not_generate_captions():
    segmenter = Segmenter()
    assert all(segmenter.push(block()) is None for _ in range(200))
    assert segmenter.flush() is None


def test_speech_keeps_preroll_and_ends_after_silence():
    segmenter = Segmenter()
    for _ in range(10):
        segmenter.push(block())
    for _ in range(6):
        assert segmenter.push(block(0.1)) is None
    for _ in range(4):
        assert segmenter.push(block()) is None
    phrase = segmenter.push(block())
    assert phrase.start == pytest.approx(0.7)
    assert phrase.end == pytest.approx(2.1)
    assert len(phrase.samples) == 22400


def test_continuous_speech_has_no_overlap_or_missing_samples():
    segmenter = Segmenter(max_seconds=2)
    phrases = []
    for _ in range(45):
        phrase = segmenter.push(block(0.1))
        if phrase:
            phrases.append(phrase)
    phrases.append(segmenter.flush())
    assert [(p.start, p.end) for p in phrases] == [(0, 2), (2, 4), (4, 4.5)]
    assert sum(len(p.samples) for p in phrases) == 72000


def test_click_is_not_speech():
    segmenter = Segmenter()
    segmenter.push(block(0.5))
    assert all(segmenter.push(block()) is None for _ in range(10))


def test_queue_discards_oldest_and_reports_gap():
    queue = Queue(maxsize=2)
    assert not offer_latest(queue, 1)
    assert not offer_latest(queue, 2)
    assert offer_latest(queue, 3)
    assert [queue.get_nowait(), queue.get_nowait()] == [2, 3]


def test_srt_rollover_and_bilingual_output():
    assert srt_time(3599.9996) == "01:00:00,000"
    assert export_srt([Caption(7, 1.25, 2.75, "Hello", "en", "你好")]) == (
        "1\n00:00:01,250 --> 00:00:02,750\nHello\n你好\n"
    )
