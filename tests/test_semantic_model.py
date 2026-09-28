import asyncio
from types import SimpleNamespace

import pytest

from linguaflow.semantic_model import SemanticModel
from linguaflow.wlk_worker import serve


def model_with_split(split):
    model = SemanticModel.__new__(SemanticModel)
    model.model = SimpleNamespace(split=split)
    return model


def test_sat_offsets_preserve_whitespace_and_pending_tail():
    def split(text, **kwargs):
        assert kwargs == dict(threshold=.5, strip_whitespace=False, split_on_input_newlines=False)
        return ['好。 ', '接着讲', '未完']
    model = model_with_split(split)
    assert model.boundaries('好。 接着讲未完') == [3, 6]
    model.model.split = lambda text, **kwargs: [text]
    assert model.boundaries('Hello world.') == []


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
