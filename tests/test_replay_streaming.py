"""File replay must consume actual backend signals after removal of Qt."""
import json
from dataclasses import asdict

import numpy as np

from linguaflow import wlk_session
from linguaflow.core import Caption, Settings
from scripts.replay_streaming import replay, sha256


def test_replay_records_threaded_results_and_preview_with_backend_dispatcher(tmp_path, monkeypatch):
    text = 'Exact replay result.'

    class FileSession(wlk_session.Session):
        def run(self):
            self.capture_fn(self.settings, self.stop_capture, lambda block: None)
            self.source_preview.emit(dict(sequence=1, keep_ids=[], source=text,
                                          start=0., end=.1, language='en'))
            self.model_result.emit(dict(session_id='fixture', interval_id=0, revision=1,
                                        start=0., end=.1, text=text, closed=True))
            self.caption.emit(Caption(1, 0., .1, text, 'en'))
            self.source_preview.emit(dict(sequence=1, done=True))

    monkeypatch.setattr(wlk_session, 'Session', FileSession)
    pcm = tmp_path/'source.f32'
    pcm.write_bytes(np.zeros(4800, dtype='<f4').tobytes())
    manifest = tmp_path/'prepared.json'
    manifest.write_text(json.dumps(dict(rate=48000, format='float32le-mono', samples=4800,
        pcm_path=str(pcm), source_path=str(pcm), pcm_sha256=sha256(pcm), source_sha256=sha256(pcm))))
    settings = tmp_path/'settings.json'
    settings.write_text(json.dumps(asdict(Settings('file', input_sample_rate=48000, translate=False))))
    output = tmp_path/'output'
    replay(manifest, output, settings)
    events = [json.loads(line) for line in (output/'events.jsonl').read_text().splitlines()]
    assert [e['type'] for e in events] == [
        'source_preview', 'model_result', 'caption', 'source_preview', 'session_finished']
    assert events[0]['data']['source'] == text and events[3]['data']['done']
    assert events[-1]['complete']
    assert json.loads((output/'revision-audit.json').read_text())['status'] == 'match'
