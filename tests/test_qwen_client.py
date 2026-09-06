import numpy as np
import pytest

from linguaflow.core import Settings
from linguaflow.qwen_client import LocalService, QwenStream


def test_file_transcription_service_is_rejected(monkeypatch):
    monkeypatch.setattr(LocalService, "request", lambda *a, **k: {"model": "file-only"})
    with pytest.raises(RuntimeError, match="持续音频"):
        LocalService("http://127.0.0.1:8765").health()


def test_stream_protocol_revisions_and_final(monkeypatch):
    calls = []

    def request(self, path, payload=None, **kwargs):
        if path == "/health":
            return {"protocol": "linguaflow-stream-v1", "continuous_audio": True,
                    "revisable_source": True, "model": "Qwen/Qwen3-ASR-0.6B"}
        if path == "/start":
            return {"id": "session"}
        calls.append(payload)
        return {"text": "错字" if len(calls) == 1 else "正确原文", "language": "zh",
                "final": payload["final"]}

    monkeypatch.setattr(LocalService, "request", request)
    stream = QwenStream(Settings("fake"))
    first = stream.update(np.zeros(16000, np.float32))[0]
    second = stream.update(np.zeros(16000, np.float32))[0]
    final = stream.update(np.empty(0, np.float32), final=True)[0]
    assert first.id == second.id == final.id
    assert first.source == "错字" and second.source == final.source == "正确原文"
    assert not second.final and final.final and final.end == 2
    assert stream.session_id is None


def test_remote_service_is_rejected():
    with pytest.raises(ValueError):
        LocalService("https://example.com")
