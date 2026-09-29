import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from linguaflow.recording_document import read_recording_document
from linguaflow.semantic_model import SemanticModel, _sat_input
from linguaflow.translation_context import ContextPlanner
from linguaflow.wlk_captions import CaptionMapper
from linguaflow.wlk_worker import serve


def model_with_split(split):
    model = SemanticModel.__new__(SemanticModel)
    model.model = SimpleNamespace(split=split)
    return model


def test_sat_offsets_preserve_whitespace_and_pending_tail():
    def split(text, **kwargs):
        assert kwargs == dict(threshold=.5, strip_whitespace=False, split_on_input_newlines=False)
        assert text == '好 接着讲未完'
        return ['好 ', '接着讲', '未完']
    model = model_with_split(split)
    assert model.boundaries('好。 接着讲未完') == [3, 6]
    model.model.split = lambda text, **kwargs: [text]
    assert model.boundaries('Hello world.') == []


@pytest.mark.parametrize(('original', 'expected'), [
    ('Hello,world! Next;sentence?', 'Hello world Next sentence'),
    ('中文。中文，继续！', '中文中文继续'),
    ("Don't change the one-dimensional model: rate=0.01; version v1.2.3.",
     "Don't change the one-dimensional model rate=0.01 version v1.2.3"),
    ('Dr. Li works in the U.S. Today.', 'Dr. Li works in the U.S. Today'),
    ('Visit https://example.com/a?q=1. Mail a.b+c@example.org!',
     'Visit https://example.com/a?q=1 Mail a.b+c@example.org'),
    ('访问https://example.com/a。继续。', '访问https://example.com/a 继续'),
    ('Value: -0.01. Then -2!', 'Value -0.01 Then -2'),
    ('（这是第一句。）“Next sentence!”', '这是第一句 Next sentence'),
])
def test_predictor_copy_preserves_words_case_and_structured_text(original, expected):
    cleaned, owners = _sat_input(original)
    assert cleaned == expected
    assert len(owners) == len(cleaned)
    assert owners == sorted(set(owners))


@pytest.mark.parametrize(('original', 'pieces', 'expected'), [
    ('Hello,world!', ['Hello', ' world'], ['Hello,', 'world!']),
    ('第一句。第二句！', ['第一句', '第二句'], ['第一句。', '第二句！']),
    ('One! “Two?”', ['One ', 'Two'], ['One!', '“Two?”']),
    ('“One!” “Two?”', ['One ', 'Two'], ['“One!”', '“Two?”']),
    ('One. "Two!"', ['One ', 'Two'], ['One.', '"Two!"']),
    ('One. (Two!)', ['One ', 'Two'], ['One.', '(Two!)']),
    ('Budget: 3.14. Next!', ['Budget 3.14 ', 'Next'], ['Budget: 3.14.', 'Next!']),
])
def test_cleaned_boundaries_map_back_without_losing_punctuation(original, pieces, expected):
    def split(text, **kwargs):
        assert text == ''.join(pieces)
        return pieces
    cuts = [0, *model_with_split(split).boundaries(original), len(original)]
    slices = [original[a:b] for a, b in zip(cuts, cuts[1:])]
    assert ''.join(slices) == original
    assert [s.strip() for s in slices] == expected


@pytest.mark.parametrize('text', ['', '。！？', '  …  '])
def test_empty_predictor_copy_does_not_call_inference(text):
    def unexpected(*args, **kwargs):
        pytest.fail('empty text must not be sent to the model')
    assert model_with_split(unexpected).boundaries(text) == []


def test_caption_translation_and_recording_keep_original_text(tmp_path):
    original = "We can sample such. Data points. Next, don't change 0.01!"
    def split(text, **kwargs):
        assert text == "We can sample such Data points Next don't change 0.01"
        return ['We can sample such Data points ', "Next don't change 0.01"]
    model = model_with_split(split)
    mapper = CaptionMapper('en', predictor=model.boundaries)
    mapper.update({'lines': [{'text': original, 'start': 0, 'end': 8}]}, done=True)
    captions = list(mapper.previous.values())
    expected = ['We can sample such. Data points.', "Next, don't change 0.01!"]
    assert [c.source for c in captions] == expected
    assert [c.source for c in ContextPlanner().update(captions)] == expected
    data = {'session': dict(id='a'*32, name='test', folder='inbox', created='2026', state='complete'),
            'settings': {}, 'captions': [asdict(c) for c in captions]}
    saved = tmp_path / 'session.json'
    saved.write_text(json.dumps(data), encoding='utf8')
    _, restored = read_recording_document(json.loads(saved.read_text(encoding='utf8')))
    assert [c.source for c in restored] == expected


def test_sat_rejects_changed_text_and_reports_inference_failure():
    model = model_with_split(lambda text, **kwargs: ['changed'])
    with pytest.raises(ValueError, match='改变了输入文本'):
        model.boundaries('original')
    def broken(*args, **kwargs):
        raise OSError('inference unavailable')
    model.model.split = broken
    with pytest.raises(RuntimeError, match='SaT 分句推理失败'):
        model.boundaries('original')


def test_worker_requires_sat_before_accepting_audio(monkeypatch):
    import linguaflow.semantic_model as module
    def unavailable(device):
        raise FileNotFoundError('missing weights')
    monkeypatch.setattr(module, 'SemanticModel', unavailable)
    async def read_message():
        pytest.fail('worker must initialize SaT before accepting audio')
    events = []
    with pytest.raises(RuntimeError, match='SaT 分句模型加载失败'):
        asyncio.run(serve({}, events.append, read_message))
    assert not any(event['type'] in {'ready', 'caption', 'done'} for event in events)
