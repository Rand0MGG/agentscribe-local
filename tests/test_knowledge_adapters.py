"""Check actual adapter call arguments; simulated inference does not certify GPU quality."""
import base64
import json
import sys
from dataclasses import asdict, replace
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


def test_pytorch_and_mlx_adapters_share_revision_finalization_and_translation_policy(monkeypatch):
    import asyncio

    from linguaflow import mlx_asr
    from linguaflow.qwen_revisions import install_revision_bridge
    from linguaflow.translation_context import ContextPlanner
    from linguaflow.translation_service import publish_translation_result
    from linguaflow.wlk_captions import CaptionMapper
    closed, outcomes = [], []
    model = SimpleNamespace(model=SimpleNamespace(generation_config=SimpleNamespace()),
        transcribe=lambda *args, **kwargs: [SimpleNamespace(text='The value is five.')])
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float32='float32'))
    monkeypatch.setitem(sys.modules, 'qwen_asr', SimpleNamespace(Qwen3ASRModel=SimpleNamespace(
        from_pretrained=lambda *args, **kwargs: model)))
    monkeypatch.setitem(sys.modules, 'whisperlivekit.timed_objects', SimpleNamespace(
        ASRToken=SimpleNamespace, Transcript=SimpleNamespace))
    class Client:
        def __init__(self, *args, own, **kwargs):
            self.closed = False
            own(self)
        def decode(self, audio):
            return 'The value is five.'
        def close(self):
            if not self.closed:
                self.closed = True
                closed.append(True)
    monkeypatch.setattr(mlx_asr, 'MLXClient', Client)

    for system in ('win32', 'darwin'):
        with monkeypatch.context() as platform:
            platform.setattr(sys, 'platform', system)
            resources, clock = [], [0.]
            asr = (build_official_online('model', 'cpu', 'en', .5, 30) if system == 'win32' else
                   mlx_asr.build_mlx_online('model', 'en', .5, lambda _: None,
                       window_seconds=30, own=resources.append))
            store = install_revision_bridge(asr)
            mapper = CaptionMapper('en', predictor=lambda _: [], lookahead=1, clock=lambda: clock[0])
            planner, history, applied = ContextPlanner(), [], []
            def publish(done=False):
                snapshot = {}
                store.augment_snapshot(snapshot)
                changes = mapper.update(snapshot, done=done)
                history.extend(asdict(row) for row in changes)
                return planner.update_changes(changes)
            def apply(caption):
                mapper.previous[caption.id] = caption
                applied.append(asdict(caption))
            async def translate(request, text):
                await publish_translation_result(replace(request, translation=text), mapper.previous.get,
                                                asyncio.Lock(), apply, planner=planner)
            try:
                asr.insert_audio_chunk(np.ones(16000, np.float32), 1)
                asr.start_silence()
                assert publish() == []
                clock[0] = 2
                assert publish() == []  # A short pause alone cannot confirm the source.
                asr.observe_capture_event('silence_started', 1)
                asr.observe_capture_event('audio_advanced', 4)
                asr.get_buffer()
                assert publish() == []
                clock[0] = 4
                first, = publish()
                assert first.translation_phase == 'initial'
                store.update(0, 0, 2.75, 'The value is six.', len('The value is six.'))
                corrected, = publish()
                assert corrected.id == first.id and not planner.accepts(first)
                asyncio.run(translate(first, '旧译文'))
                assert not applied
                asyncio.run(translate(corrected, '修订译文'))
                assert applied[-1]['source'] == 'The value is six.'
                final, = publish(done=True)
                assert final.translation_phase == 'final' and final.id == first.id
                asyncio.run(translate(corrected, '迟到的初译'))
                assert len(applied) == 1
                asyncio.run(translate(final, '最终译文'))
                assert applied[-1]['final'] and applied[-1]['translation'] == '最终译文'
                outcomes.append((history, applied, asr.window_seconds, asr.pause_context_seconds))
            finally:
                for resource in resources:
                    resource.close()
                    resource.close()
    assert outcomes[0] == outcomes[1]
    assert closed == [True]
