"""Check actual adapter call arguments; simulated inference does not certify GPU quality."""
import base64
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from linguaflow.knowledge.glossary import compile_context, context_text
from linguaflow.knowledge.schemas import Term
from linguaflow.qwen_accurate import build_official_online


def test_same_context_reaches_pytorch_transcribe_and_mlx_generate(monkeypatch, tmp_path):
    context = context_text(compile_context([Term('gradient descent', approved=True)]).to_dict())
    calls = []
    model = SimpleNamespace(model=SimpleNamespace(generation_config=SimpleNamespace()),
                            transcribe=lambda *args, **kwargs: calls.append(kwargs) or [SimpleNamespace(text='gradient descent')])
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float32='float32'))
    monkeypatch.setitem(sys.modules, 'qwen_asr', SimpleNamespace(Qwen3ASRModel=SimpleNamespace(from_pretrained=lambda *args, **kwargs: model)))
    monkeypatch.setitem(sys.modules, 'whisperlivekit.timed_objects', SimpleNamespace(ASRToken=SimpleNamespace, Transcript=SimpleNamespace))
    online = build_official_online('model', 'cpu', 'en', 1, 30, context=context)
    online.decode(np.ones(16000, np.float32))
    assert calls[-1]['context'] == context
    from linguaflow.mlx_asr_worker import serve
    # The fake models are local protocol stand-ins; no Apple/GPU runtime is imported.
    mx = SimpleNamespace(metal=SimpleNamespace(is_available=lambda: True), gpu='gpu',
        set_default_device=lambda device: None, default_device=lambda: 'gpu',
        set_cache_limit=lambda _: None, set_memory_limit=lambda _: None, get_active_memory=lambda: 0,
        get_peak_memory=lambda: 0, synchronize=lambda: None, clear_cache=lambda: None)
    monkeypatch.setitem(sys.modules, 'mlx', SimpleNamespace(core=mx))
    monkeypatch.setitem(sys.modules, 'mlx.core', mx)
    monkeypatch.setitem(sys.modules, 'mlx_audio.stt.utils', SimpleNamespace(load_model=lambda _: SimpleNamespace(
        generate=lambda *args, **kwargs: calls.append(kwargs) or SimpleNamespace(text='gradient descent'))))
    (tmp_path / 'config.json').write_text(json.dumps({'model_type': 'qwen3_asr', 'quantization': {'bits': 4}}))
    pcm = np.ones(16000, dtype='<f4')
    messages = iter([{'model': str(tmp_path), 'language': 'English', 'context': context},
                     {'pcm': base64.b64encode(pcm.tobytes()).decode()}, {'type': 'stop'}])
    serve(lambda: next(messages), lambda _: None)
    assert calls[-1]['system_prompt'] == context and 'context' not in calls[-1]


def test_context_is_rejected_before_loading_pytorch():
    with pytest.raises(ValueError, match='超长'):
        build_official_online('none', 'cpu', 'en', 1, 30, context='x' * 513)
