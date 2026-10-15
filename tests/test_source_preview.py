"""ASR can be visible during blocked semantics without changing final captions."""
import asyncio
from dataclasses import asdict
from threading import Event

import pytest
from test_beta_features import run_ui
from test_shared_qwen_worker import stub_worker

from linguaflow.core import Settings
from linguaflow.source_preview import SourcePreview
from linguaflow.wlk_captions import CaptionMapper


def snapshot(text):
    return dict(revision_text=text, stable_end=len(text),
        revision_spans=[(i, i+1, i/10, (i+1)/10, 'en') for i in range(len(text))])


def test_preview_preserves_prefix_reopens_last_row_and_withdraws_corrections():
    mapper = CaptionMapper('en', predictor=lambda text: [i+1 for i, char in enumerate(text) if char == '.'])
    preview = SourcePreview('en')
    first = snapshot('First. Second.')
    seq, event = preview.begin(first)
    assert seq == 1 and event['source'] == 'First. Second.' and event['keep_ids'] == []
    assert mapper.previous == {}  # No readiness, IDs, translations or finalization from previews.
    mapper.update(first, done=True)
    preview.complete(mapper)
    before = {key: asdict(value) for key, value in mapper.previous.items()}
    seq, event = preview.begin(snapshot('First. Second sentence continues'))
    assert event['keep_ids'] == [1] and event['source'] == 'Second sentence continues'
    assert {key: asdict(value) for key, value in mapper.previous.items()} == before
    seq, event = preview.begin(snapshot('Corrected first.'))
    assert event['keep_ids'] == [] and event['source'] == 'Corrected first.'
    assert preview.begin(snapshot('Corrected first.')) == (seq, None)
    _, event = preview.begin(snapshot(''))
    assert event['source'] == '' and event['keep_ids'] == []


def test_whisper_preview_includes_mutable_tail_without_semantic_prediction():
    value = dict(lines=[dict(text='First sentence.', start=0, end=1, detected_language='en')],
                 buffer_transcription='Still speaking', draft_span=dict(start=1, end=2))
    preview = SourcePreview('en')
    _, event = preview.begin(value)
    assert event['source'] == 'First sentence. Still speaking'
    assert event['start'] == 0 and event['end'] == 2


@pytest.mark.parametrize('backend', ['qwen3-streaming', 'qwen3-mlx'])
def test_worker_emits_newest_preview_while_semantics_is_blocked(monkeypatch, backend):
    from linguaflow import mlx_asr, qwen_accurate, semantic_model, wlk_worker
    _, online, _ = stub_worker(monkeypatch, 'darwin' if backend == 'qwen3-mlx' else 'win32')
    build = qwen_accurate.build_official_online
    monkeypatch.setattr(mlx_asr, 'build_mlx_online', lambda model, language, interval, report, **kwargs:
        build(model, 'mlx', language, interval, kwargs['window_seconds']))
    entered, release = Event(), Event()
    def boundaries(text):
        if not release.is_set():
            entered.set()
            assert release.wait(5), 'test did not release semantic inference'
        return []
    monkeypatch.setattr(semantic_model, 'SemanticModel', lambda: type('Semantic', (), {'boundaries': staticmethod(boundaries)})())

    async def exercise():
        events = []
        ready, newest_preview, newest_mapped, stop = (asyncio.Event() for _ in range(4))
        def emit(event):
            events.append(event)
            if event['type'] == 'ready':
                ready.set()
            if event['type'] == 'source_preview' and event['data']['source'] == 'Corrected complete sentence.':
                newest_preview.set()
            if event['type'] == 'source_preview_done' and event['sequence'] >= 2:
                newest_mapped.set()
        async def read():
            await stop.wait()
            return {'type': 'stop'}
        settings = Settings('file', backend=backend, asr_device='mlx' if backend == 'qwen3-mlx' else 'cpu',
                            source='en', translate=False)
        task = asyncio.create_task(wlk_worker.serve(asdict(settings), emit, read))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            await asyncio.to_thread(online[0].revisions.update, 0, 0., 1., 'Wrong initial words', 0, False)
            assert await asyncio.to_thread(entered.wait, 2)
            assert any(e['type'] == 'source_preview' for e in events)
            assert not any(e['type'] == 'caption' for e in events)
            await asyncio.to_thread(online[0].revisions.update, 0, 0., 3., 'Corrected complete sentence.', 28, False)
            await asyncio.wait_for(newest_preview.wait(), 2)
            assert not release.is_set() and not any(e['type'] == 'caption' for e in events)
            release.set()
            await asyncio.wait_for(newest_mapped.wait(), 3)
            stop.set()
            await asyncio.wait_for(task, 3)
            final = [e['data'] for e in events if e['type'] == 'caption' and e['data']['final']]
            assert final[-1]['source'] == 'Corrected complete sentence.'
            assert final[-1]['boundary_final'] and final[-1]['asr_final']
            assert events[-1]['type'] == 'done'
        finally:
            release.set()
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_pending_preview_rebases_when_older_segmentation_changes_the_prefix():
    mapper = CaptionMapper('en', predictor=lambda text: [i+1 for i, c in enumerate(text) if c=='.'])
    preview = SourcePreview('en')
    first = snapshot('First. Second.')
    preview.begin(first)
    mapper.update(first, done=True)
    preview.complete(mapper)
    older = snapshot('Changed first. Second.')
    old_sequence, _ = preview.begin(older)
    _, latest = preview.begin(snapshot('First. Second continues.'))
    assert latest['keep_ids'] == [1]
    mapper.update(older)
    rebased = preview.complete(mapper, old_sequence)
    assert rebased['sequence'] > latest['sequence']
    assert rebased['keep_ids'] == [] and rebased['source'] == 'First. Second continues.'


def test_ui_newer_preview_survives_old_semantics_and_reconciles_without_duplicates(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QObject, Signal
from linguaflow.core import Caption
class Session(QObject):
    source_preview = Signal(object)
session = Session(w)
w.session = session
session.source_preview.connect(w.on_source_preview)
w.show();w.reduce_motion.setChecked(False)
w.set_recording_state(module.RecordingState.LISTENING)
w.on_caption(Caption(1,0,1,'First.','en','第一句。'))
w.on_caption(Caption(2,1,2,'Wrong.','en','原译文', final=False))
event = dict(sequence=1, keep_ids=[1], source='Corrected continuing sentence',start=1.,end=3.,language='en')
session.source_preview.emit(event)
assert w.source_preview_card.source.text() == event['source']
assert not w.source_preview_card.source.reveal.isActive()
assert w.cards[1].isVisible() and w.cards[2].isHidden()
assert w.overlay.source.text() == event['source'] and w.overlay.target.isHidden()
assert w.captions[2].source == 'Wrong.'  # Preview is display-only.
event = dict(event, sequence=2, source='Corrected complete sentence. A following sentence.')
session.source_preview.emit(event)
session.source_preview.emit(dict(sequence=1,done=True))
assert w.source_preview['sequence'] == 2
w.on_caption(Caption(2,1,3,'Corrected complete sentence.','en',revision=2))
w.on_caption(Caption(3,3,4,'A following sentence.','en'))
assert w.cards[2].isHidden() and w.source_preview_card.isVisible()
session.source_preview.emit(dict(sequence=2,done=True))
assert w.source_preview is None and w.source_preview_card.isHidden()
assert all(card.isVisible() for card in w.cards.values())
assert all(not card.source.reveal.isActive() for card in w.cards.values())
assert [c.source for c in w.captions.values()] == ['First.', 'Corrected complete sentence.', 'A following sentence.']
session.source_preview.emit(dict(event, sequence=1, source='Late obsolete'))
assert w.source_preview is None
w.session=None
w.set_recording_state(module.RecordingState.IDLE)
w.session_dirty=False
w.close()
''', tmp_path)


def test_unfinished_preview_is_saved_as_draft_with_existing_translations(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QObject
from linguaflow.core import Caption
assert w.new_recording(name='保留最新草稿',check_models=False)
w.session=QObject(w)
w.set_recording_state(module.RecordingState.LISTENING)
w.on_caption(Caption(1,0,1,'Earlier words','en','已有译文',final=False))
w.on_source_preview(dict(sequence=1,keep_ids=[],source='Latest corrected words',start=0.,end=2.,language='en'))
w.retain_source_preview()
assert w.source_preview is None and len(w.captions)==1
caption=next(iter(w.captions.values()))
assert caption.source=='Latest corrected words' and not caption.final
assert caption.translation=='已有译文' and caption.translation_source=='Earlier words'
assert caption.error and w.last_error
w.session=None
assert w.persist_session('incomplete')
_,saved=w.library.load(w.current_item)
assert saved[0].source=='Latest corrected words' and saved[0].translation=='已有译文' and not saved[0].final
w.set_recording_state(module.RecordingState.IDLE)
w.close()
''', tmp_path)
