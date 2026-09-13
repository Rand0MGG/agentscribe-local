from types import SimpleNamespace

from linguaflow.qwen_revisions import RevisionStore, install_revision_bridge
from linguaflow.revision_audit import audit
from linguaflow.wlk_captions import CaptionMapper
from dataclasses import asdict
from linguaflow.core import export_srt


def test_complete_revisions_reopen_shorten_clear_and_preserve_repetition():
    events = []
    store = RevisionStore('test', events.append)
    mapper = CaptionMapper('en')
    for value in ['Wrong words. Extra sentence.', 'Right words.', '', 'Yes yes.']:
        store.update(0, 0, 5, value, len(value), True)
        snapshot = {}
        store.augment_snapshot(snapshot)
        for caption in mapper.update(snapshot, done=True):
            events.append(dict(type='caption', data=asdict(caption)))
        assert audit(events, True)['status'] == 'match'
    assert audit(events, True)['model_text'] == 'Yes yes.'
    exported = export_srt(list(mapper.previous.values()))
    assert 'Yes yes.' in exported and 'Wrong' not in exported and 'Right' not in exported
    assert any(e['type'] == 'caption' and not e['data']['source'] for e in events)
    assert audit(events, False)['status'] == 'incomplete_or_unavailable'


def test_old_versions_and_other_sessions_are_rejected():
    store = RevisionStore('test')
    store.update(0, 0, 1, 'New.', 4, True)
    row = dict(store.rows[0], text='Old.')
    assert not store.accept(row)
    assert not store.accept(dict(row, revision=2, session_id='other'))
    assert store.rows[0]['text'] == 'New.'


class FakeOnline:
    SAMPLING_RATE = 10
    def __init__(self):
        self.end = 0
        self.streamer = SimpleNamespace(append_mel_chunk=lambda event: event)
    def insert_audio_chunk(self, audio, audio_stream_end_time):
        self.end = audio_stream_end_time
    def _emit_committed(self, text, event_time, flush=False):
        return []  # Simulate upstream dropping a correction entirely.
    def _reset_for_next_utterance(self):
        self.streamer = SimpleNamespace(append_mel_chunk=lambda event: event)


def test_bridge_captures_before_loss_and_survives_reset_and_rollover():
    online = FakeOnline()
    class Normalizer:
        def __init__(self, inner):
            self._inner = inner
        def __getattr__(self, name):
            return getattr(self._inner, name)
    records = []
    store = install_revision_bridge(Normalizer(online), records.append)
    online.insert_audio_chunk([0]*10, 1)
    online.streamer.append_mel_chunk(dict(hypothesis='Wrong words.', committed='Wrong'))
    online.streamer.append_mel_chunk(dict(hypothesis='Right.', committed='Wrong', segment_rollover=True))
    assert store.rows[0]['text'] == 'Right.' and store.rows[0]['stable_end'] == 0
    online._emit_committed('', 1, flush=True)
    assert store.rows[0]['closed'] and store.rows[0]['text'] == ''
    online._reset_for_next_utterance()
    online.insert_audio_chunk([0]*10, 3)
    online.streamer.append_mel_chunk(dict(hypothesis='Yes yes.', committed='Yes'))
    online._emit_committed('Yes yes!', 3, flush=True)
    snapshot = {}
    store.augment_snapshot(snapshot)
    assert snapshot['revision_text'] == 'Yes yes!'
    assert store.rows[1]['start'] == 2 and store.rows[1]['closed']
    n = len(records)
    online._emit_committed('Yes yes!', 3, flush=True)
    assert len(records) == n


def test_audit_exposes_punctuation_loss_with_interval_and_caption_locations():
    store = RevisionStore('s')
    store.update(0, 0, 1, 'Yes yes!', 8, True)
    row = store.rows[0]
    events = [dict(type='model_result', data=row), dict(type='caption', data=dict(
        id=1, revision=1, start=0, source='Yes yes', final=True))]
    result = audit(events, True)
    assert result['status'] == 'mismatch' and result['differences'][0]['model_text'] == '!'
    assert result['model_locations'][0]['interval_id'] == 0
    assert result['caption_locations'][0]['id'] == 1


def test_unchanged_prefix_keeps_order_when_hypothesis_grows():
    store = RevisionStore('s')
    store.update(0, 0, 10, 'First sentence.', 15)
    original = list(store.times[0])
    store.update(0, 0, 11, 'First sentence. ' + 'many words ' * 20, 15)
    assert store.times[0][:15] == original
    assert store.times[0][15][0] >= original[-1][1]
