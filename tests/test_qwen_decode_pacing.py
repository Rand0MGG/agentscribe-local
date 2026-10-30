"""Slow inference must not become a minimum amount of future speech."""
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow import qwen_accurate
from linguaflow.qwen_revisions import install_revision_bridge


@pytest.mark.p1
@pytest.mark.parametrize('first_text', ['', 'Initial words'])
def test_slow_decode_does_not_hold_following_speech_until_stop(monkeypatch, first_text):
    clock = [0.]
    monkeypatch.setattr(qwen_accurate, 'time', SimpleNamespace(perf_counter=lambda: clock[0]))
    calls = []
    def decode(audio):
        calls.append(len(audio))
        clock[0] += 12 if len(calls) == 1 else .1
        return first_text if len(calls) == 1 else '先说中文 Then English.'
    asr = qwen_accurate.QwenAccurateOnline(decode, 'en',
        token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    store = install_revision_bridge(asr)
    asr.insert_audio_chunk(np.ones(16000), 1.)
    asr.process_iter()
    # The model returns after 12 s; audio captured meanwhile is delivered next.
    asr.insert_audio_chunk(np.ones(12 * 16000), 13.)
    tokens, _ = asr.process_iter()
    snapshot = {}
    store.augment_snapshot(snapshot)
    assert snapshot['revision_text'] == '先说中文 Then English.'
    assert not tokens and snapshot['stable_end'] == 0  # visible before commit/EOF
    assert calls == [16000, 176000, 208000]
    asr.finish()
    assert calls == [16000, 176000, 208000]  # stopping must not trigger the missing decode


@pytest.mark.p1
def test_new_utterance_not_delayed_by_previous_slow_decode(monkeypatch):
    clock = [0.]
    monkeypatch.setattr(qwen_accurate, 'time', SimpleNamespace(perf_counter=lambda: clock[0]))
    calls = []
    def decode(audio):
        calls.append(len(audio))
        clock[0] += 8
        return 'first' if len(calls) == 1 else 'second'
    asr = qwen_accurate.QwenAccurateOnline(decode, 'en',
        token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    asr.insert_audio_chunk(np.ones(8000), .5)
    asr.process_iter()
    asr.finish()
    asr.insert_audio_chunk(np.ones(4000), .75)
    asr.process_iter()
    assert calls == [8000]  # retain the configured minimum fresh-audio interval
    asr.insert_audio_chunk(np.ones(12000), 1.5)
    asr.process_iter()
    assert asr.text == 'second'
    for _ in range(3):
        asr.process_iter()
    assert calls == [8000, 16000]  # idle polling does not infer the same PCM
    asr.insert_audio_chunk(np.ones(2000), 1.625)
    asr.process_iter()
    assert calls == [8000, 16000]
    asr.finish()
    assert calls == [8000, 16000, 18000]  # EOF still decodes the short trailing PCM
    asr.finish()
    assert calls == [8000, 16000, 18000]
