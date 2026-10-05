"""Exercise both historical Windows Qwen settings through the actual worker."""
import asyncio
import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from linguaflow import model_cache, qwen_accurate, qwen_revisions, runtime_compat, semantic_model, wlk_worker
from linguaflow.core import Settings
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.qwen_revisions import install_revision_bridge


@pytest.mark.parametrize('old_mode', ['fast', 'accurate'])
def test_windows_worker_installs_the_same_qwen_revision_pipeline(monkeypatch, old_mode):
    configured, online, stores = [], [], []
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(semantic_model, 'SemanticModel', lambda: SimpleNamespace(boundaries=lambda text: []))
    monkeypatch.setattr(model_cache, 'resolve_qwen_cached', lambda model: 'local-model')
    monkeypatch.setattr(runtime_compat, 'prepare_qwen_dependencies', lambda: None)
    monkeypatch.setattr(runtime_compat, 'configure_vad_float32', lambda processor: None)
    monkeypatch.setattr(runtime_compat, 'configure_vad_pause', lambda *args: None)
    monkeypatch.setattr(runtime_compat, 'results_with_final_snapshot', lambda processor, results: results)

    def engine(config):
        configured.append(config.transcription)
        return SimpleNamespace(config=config)

    class Processor:
        def __init__(self, transcription_engine, stream_event_queue):
            self.args = transcription_engine.config
        async def create_tasks(self):
            async def results():
                yield SimpleNamespace(lines=[], to_dict=lambda: {}, error='',
                    remaining_time_transcription_processing=0, remaining_time_transcription_policy=0)
            return results()
        async def process_audio(self, pcm):
            assert pcm == b''
            self.transcription.finish()
        async def cleanup(self):
            pass

    monkeypatch.setitem(sys.modules, 'whisperlivekit', SimpleNamespace(
        AudioProcessor=Processor, TranscriptionEngine=engine))
    monkeypatch.setitem(sys.modules, 'whisperlivekit.config', SimpleNamespace(
        WhisperLiveKitConfig=lambda **kwargs: SimpleNamespace(**kwargs)))

    def build(model_path, device, language, update_seconds, window_seconds):
        value = QwenAccurateOnline(lambda audio: 'words', lambda audio, seconds: len(audio), language,
            update_seconds, window_seconds, pause_context_seconds=3,
            token_type=SimpleNamespace, transcript_type=SimpleNamespace)
        online.append(value)
        return value
    monkeypatch.setattr(qwen_accurate, 'build_official_online', build)
    def bridge(processor, emit):
        store = install_revision_bridge(processor, emit)
        stores.append(store)
        return store
    monkeypatch.setattr(qwen_revisions, 'install_revision_bridge', bridge)
    async def read_message():
        return {'type': 'stop'}
    events = []
    settings = Settings('fake', backend='qwen3-streaming', qwen_mode=old_mode,
                        asr_device='cpu', source='en', translate=False)
    asyncio.run(wlk_worker.serve(asdict(settings), events.append, read_message))
    assert len(configured) == len(online) == len(stores) == 1
    assert configured == [False]  # No second/native ASR load even with legacy fast settings.
    assert online[0].revisions is stores[0]
    assert online[0].pause_context_seconds == 3
    assert any(event['type'] == 'ready' for event in events)
    assert events[-1]['type'] == 'done'
