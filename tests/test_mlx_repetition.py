"""Only capped, overwhelmingly repetitive output enters bounded recovery."""
import io
import json
from threading import Lock
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.asr_review import checked_generate, repetitive_tail
from linguaflow.qwen_accurate import QwenAccurateOnline


@pytest.mark.p1
@pytest.mark.parametrize('text,tokens,rejected', [
    ('Oh, ' + 'yeah, ' * 255, 512, True),
    ('Oh, ' + 'yeah, ' * 255, 511, False),
    ('yeah, yeah, I agree.', 512, False),
    ('go on! ' * 32, 512, True),
    ('好的，' * 32, 512, True),
    ('yeah, ' * 31, 512, False),
    ('yeah, ' * 32, 512, True),
    ('prefix ' * 32 + 'yeah, ' * 32, 512, False),
    (' '.join(f'word{i}' for i in range(64)) + ' yeah' * 32, 512, False),
    ('yeah, ' * 64 + ' now a different ending', 512, False),
    (' '.join(f'word{i}' for i in range(512)), 512, False),
])
def test_capped_tail_review_requires_both_repetition_and_majority(text, tokens, rejected):
    assert bool(repetitive_tail(text, tokens)) is rejected


@pytest.mark.p1
def test_normal_generation_keeps_one_call_parameters_pcm_and_text():
    calls = []
    audio = np.linspace(-.1, .1, 16000, dtype=np.float32)
    result = SimpleNamespace(text=' yeah, yeah, I agree. ', generation_tokens=512)
    def generate(pcm, **kwargs):
        calls.append((pcm, kwargs))
        return result
    params = dict(language='English', temperature=0., max_tokens=512,
                  prefill_step_size=256, verbose=False, system_prompt='course context')
    output, review = checked_generate(SimpleNamespace(generate=generate), audio, **params)
    assert output is result and review is None and len(calls) == 1
    assert calls[0][0] is audio and calls[0][1] == params


@pytest.mark.p1
def test_recovery_sees_identical_audio_and_only_valid_result_reaches_submission():
    audio = np.ones(16000, dtype=np.float32)
    calls = []
    outputs = iter([SimpleNamespace(text='Oh, ' + 'yeah, ' * 255, generation_tokens=512),
                    SimpleNamespace(text='Oh, yeah.', generation_tokens=4)])
    def generate(pcm, **kwargs):
        calls.append((pcm.copy(), kwargs))
        return next(outputs)
    reviews = []
    def decode(pcm):
        result, review = checked_generate(SimpleNamespace(generate=generate), pcm,
                                         language='English', max_tokens=512, temperature=0.)
        reviews.append(review)
        return result.text
    online = QwenAccurateOnline(decode, 'en', token_type=SimpleNamespace,
                               transcript_type=SimpleNamespace)
    online.insert_audio_chunk(audio, 1.)
    online.process_iter()
    assert online.text == 'Oh, yeah.' and online.processed_end == 1.
    assert len(calls) == 2 and calls[1][1]['repetition_penalty'] == 1.1
    assert 'repetition_penalty' not in calls[0][1]
    np.testing.assert_array_equal(calls[0][0], calls[1][0])
    assert reviews[0]['outcome'] == 'recovered'
    assert reviews[0]['repeats'] == 255
    tokens, _ = online.finish()
    assert 'yeah, yeah' not in ''.join(t.text for t in tokens)
    assert len(calls) == 2  # EOF cannot add a retry or a confirmation observation.


@pytest.mark.p1
def test_recovery_does_not_change_the_next_normal_call_or_prompt():
    calls = []
    outputs = iter([SimpleNamespace(text='yeah, ' * 255, generation_tokens=512),
                    SimpleNamespace(text='Oh, yeah.', generation_tokens=4),
                    SimpleNamespace(text='Next normal sentence.', generation_tokens=5)])
    def generate(pcm, **kwargs):
        calls.append(kwargs)
        return next(outputs)
    model = SimpleNamespace(generate=generate)
    params = dict(language='English', max_tokens=512, temperature=0., system_prompt='terms')
    checked_generate(model, np.ones(16000), **params)
    result, review = checked_generate(model, np.ones(32000), **params)
    assert result.text == 'Next normal sentence.' and review is None
    assert calls[0] == calls[2] == params
    assert calls[1] == {**params, 'repetition_penalty': 1.1}


@pytest.mark.p1
@pytest.mark.parametrize('failed', [False, True])
def test_client_surfaces_review_metadata_without_logging_text(monkeypatch, failed):
    from linguaflow import diagnostic_log as diag
    from linguaflow.mlx_asr import MLXClient
    review = dict(outcome='failed' if failed else 'recovered', repeats=255, attempts=2)
    response = dict(type='error' if failed else 'result', text='private transcript',
                    repetition_review=review)
    client = MLXClient.__new__(MLXClient)
    client.request_lock, client.close_lock = Lock(), Lock()
    client.closed, client.exchange = False, None
    client.process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(json.dumps(response)+'\n'))
    events = []
    monkeypatch.setattr(diag, 'event', lambda name, **fields: events.append((name, fields)))
    if failed:
        with pytest.raises(RuntimeError):
            client.request({'pcm': 'fixture'})
    else:
        assert client.request({'pcm': 'fixture'})['text'] == 'private transcript'
    assert events == [('asr_repetition_review', review)]


@pytest.mark.p1
@pytest.mark.parametrize('failure', ['repeated', 'empty', 'exception'])
@pytest.mark.parametrize('at_eof', [False, True])
def test_failed_recovery_retains_previous_text_and_unprocessed_audio(failure, at_eof):
    calls = []
    bad = SimpleNamespace(text='yeah, ' * 255, generation_tokens=512)
    def generate(pcm, **kwargs):
        calls.append(pcm.copy())
        if len(calls) == 1 or failure == 'repeated':
            return bad
        if failure == 'exception':
            raise RuntimeError('fixture inference failed')
        return SimpleNamespace(text='', generation_tokens=0)
    online = QwenAccurateOnline(lambda _: 'previous valid words', 'en',
                               token_type=SimpleNamespace, transcript_type=SimpleNamespace)
    online.insert_audio_chunk(np.ones(16000, np.float32), 1.)
    online.process_iter()
    before = online.submission.snapshot()
    online.decode = lambda pcm: checked_generate(SimpleNamespace(generate=generate), pcm,
                                                 language='English', max_tokens=512)[0].text
    online.insert_audio_chunk(np.ones(16000, np.float32), 2.)
    with pytest.raises(RuntimeError):
        online.finish() if at_eof else online.process_iter()
    assert len(calls) == 2
    assert online.submission.snapshot() == before
    assert online.text == 'previous valid words'
    assert online.processed_end == online.decoded_end == 1.
    assert len(online.audio_buffer) == 32000
