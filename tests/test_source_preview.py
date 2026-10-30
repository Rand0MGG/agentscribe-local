"""ASR can be visible during blocked semantics without changing final captions."""
import asyncio
from dataclasses import asdict
from threading import Event

import pytest
from test_shared_qwen_worker import stub_worker
from ui_support import run_ui

from linguaflow.core import Settings
from linguaflow.source_preview import SourcePreview, preview_captions
from linguaflow.wlk_captions import CaptionMapper


def snapshot(text):
    return dict(revision_text=text, stable_end=len(text),
        revision_spans=[(i, i+1, i/10, (i+1)/10, 'en') for i in range(len(text))])


@pytest.mark.p1
def test_punctuation_preview_preserves_three_cards_and_unaffected_translations():
    mapper = CaptionMapper('en', predictor=lambda text: [i+1 for i, c in enumerate(text) if c in '.!'])
    preview = SourcePreview('en')
    old = snapshot('First sentence. Second sentence. Third sentence.')
    preview.begin(old)
    mapper.update(old, done=True)
    for caption in mapper.previous.values():
        caption.translation = f'translation {caption.id}'
        caption.translation_source = caption.source
        caption.translation_phase = 'final'
    preview.complete(mapper)
    before = {key: asdict(value) for key, value in mapper.previous.items()}
    _, event = preview.begin(snapshot('First sentence! Second sentence. Third sentence.'))
    assert [row['source'] for row in event['rows']] == ['First sentence!', 'Second sentence.', 'Third sentence.']
    saved = preview_captions(mapper.previous, event)
    assert [row.id for row in saved] == [1, 2, 3]
    assert not saved[0].final and saved[0].translation == 'translation 1'
    assert saved[0].translation_source == 'First sentence.'
    assert asdict(saved[1]) == before[2] and asdict(saved[2]) == before[3]
    assert {key: asdict(value) for key, value in mapper.previous.items()} == before


@pytest.mark.p1
@pytest.mark.parametrize('new', ['Changed. Second. Third.', 'First. Third.',
                                'First. Second. Third. More words', '',
                                '全部重写，现在是中文。'])
def test_projected_preview_covers_latest_text_once_without_inventing_semantic_boundaries(new):
    mapper = CaptionMapper('en', predictor=lambda text: [i+1 for i, c in enumerate(text) if c=='.'])
    preview = SourcePreview('en')
    old = snapshot('First. Second. Third.')
    preview.begin(old)
    mapper.update(old, done=True)
    preview.complete(mapper)
    before = {key: asdict(value) for key, value in mapper.previous.items()}
    _, event = preview.begin(snapshot(new))
    saved = preview_captions(mapper.previous, event)
    assert ''.join(c.source for c in saved).replace(' ', '') == new.replace(' ', '')
    assert len({c.id for c in saved}) == len(saved)
    assert len(saved) <= 3
    assert {key: asdict(value) for key, value in mapper.previous.items()} == before


@pytest.mark.p1
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


@pytest.mark.p1
def test_whisper_preview_includes_mutable_tail_without_semantic_prediction():
    value = dict(lines=[dict(text='First sentence.', start=0, end=1, detected_language='en')],
                 buffer_transcription='Still speaking', draft_span=dict(start=1, end=2))
    preview = SourcePreview('en')
    _, event = preview.begin(value)
    assert event['source'] == 'First sentence. Still speaking'
    assert event['start'] == 0 and event['end'] == 2


@pytest.mark.p1
def test_slow_empty_qwen_then_mixed_source_visible_before_stop_and_hy_ready(monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from linguaflow import backends, qwen_accurate, wlk_worker
    from linguaflow.translation_models import HY_MODEL
    _, online, _ = stub_worker(monkeypatch)
    loading, release = Event(), Event()
    def translator(*args):
        loading.set()
        assert release.wait(5), 'test did not release translation loading'
        return SimpleNamespace(translate=lambda *args: '译文')
    monkeypatch.setattr(backends, 'create_translator', translator)
    clock = [0.]
    monkeypatch.setattr(qwen_accurate, 'time', SimpleNamespace(perf_counter=lambda: clock[0]))

    async def exercise():
        events = []
        ready, visible, stop = (asyncio.Event() for _ in range(3))
        text = '先说中文 Then English.'
        def emit(event):
            events.append(event)
            if event['type'] == 'ready':
                ready.set()
            if event['type'] == 'source_preview' and event['data']['source'] == text:
                visible.set()
        async def read():
            await stop.wait()
            return {'type': 'stop'}
        settings = Settings('file', backend='qwen3-streaming', asr_device='cpu',
                            source='en', translate=True, translation_model=HY_MODEL)
        task = asyncio.create_task(wlk_worker.serve(asdict(settings), emit, read))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            assert await asyncio.to_thread(loading.wait, 2)
            calls = []
            def decode(audio):
                calls.append(len(audio))
                clock[0] += 12 if len(calls) == 1 else .1
                return '' if len(calls) == 1 else text
            online[0].decode = decode
            online[0].insert_audio_chunk(np.ones(8000), .5)
            await asyncio.to_thread(online[0].process_iter)
            online[0].insert_audio_chunk(np.ones(12 * 16000), 12.5)
            await asyncio.to_thread(online[0].process_iter)
            await asyncio.wait_for(visible.wait(), 2)
            assert not release.is_set() and not stop.is_set()
            assert online[0].confirmed_end == 0
            assert not any(e['type'] == 'caption' and e['data']['final'] for e in events)
            release.set()
            stop.set()
            await asyncio.wait_for(task, 3)
            assert events[-1]['type'] == 'done'
        finally:
            release.set()
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
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


@pytest.mark.p1
def test_preview_autosaves_before_semantics_and_completed_rows_replace_draft(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QObject
from linguaflow.core import Caption
assert w.new_recording(name='崩溃恢复',check_models=False)
w.session=QObject(w)
w.set_recording_state(module.RecordingState.LISTENING)
w.on_caption(Caption(1,0,1,'Saved prefix','en'))
w.on_caption(Caption(2,1,2,'Old tail','en','旧译文',final=False))
w.on_source_preview(dict(sequence=1,keep_ids=[1],source='Latest words',start=1.,end=3.,language='en'))
assert w.recording_saver.flush()
_,saved=w.library.load(w.current_item)
assert [c.source for c in saved]==['Saved prefix','Latest words']
assert not saved[-1].final and saved[-1].translation=='旧译文'
assert saved[-1].translation_source=='Old tail'
assert w.captions[2].source=='Old tail' and w.source_preview is not None
assert not w.session_dirty
w.on_source_preview(dict(sequence=2,keep_ids=[1],source='Corrected words',start=1.,end=3.,language='en'))
w.on_source_preview(dict(sequence=1,done=True))
assert w.recording_saver.flush()
assert w.library.load(w.current_item)[1][-1].source=='Corrected words'
w.on_caption(Caption(2,1,3,'Corrected words','en',revision=2))
w.on_source_preview(dict(sequence=2,done=True))
assert w.recording_saver.flush()
_,saved=w.library.load(w.current_item)
assert len(saved)==2 and saved[-1].final and not saved[-1].error
w.session=None
w.set_recording_state(module.RecordingState.IDLE)
assert w.persist_session('complete')
w.close()
''', tmp_path)


@pytest.mark.p1
@pytest.mark.parametrize('cancel_session', [False, True])
def test_stop_or_cancel_joins_inflight_semantics_before_finalization(monkeypatch, cancel_session):
    from linguaflow import wlk_captions, wlk_worker
    _, online, _ = stub_worker(monkeypatch)
    entered, release, overlap = Event(), Event(), []
    update = wlk_captions.CaptionMapper.update
    active = [False]
    def blocked_update(self, value, done=False):
        if value.get('revision_text') and not done and not entered.is_set():
            active[0] = True
            entered.set()
            assert release.wait(5)
            try:
                return update(self, value, done=done)
            finally:
                active[0] = False
        if done and active[0]:
            overlap.append(True)
        return update(self, value, done=done)
    monkeypatch.setattr(wlk_captions.CaptionMapper, 'update', blocked_update)

    async def exercise():
        events = []
        ready, stop, initial_output = asyncio.Event(), asyncio.Event(), asyncio.Event()
        def emit(event):
            events.append(event)
            if event['type']=='ready':
                ready.set()
            elif event['type']=='metrics':
                initial_output.set()
        async def read():
            await stop.wait()
            return {'type':'stop'}
        settings=Settings('file', backend='qwen3-streaming',asr_device='cpu',source='en',translate=False)
        task=asyncio.create_task(wlk_worker.serve(asdict(settings),emit,read))
        try:
            await asyncio.wait_for(ready.wait(),3)
            await asyncio.wait_for(initial_output.wait(),3)
            online[0].revisions.update(0,0.,1.,'Retained sentence.',18,False)
            assert await asyncio.to_thread(entered.wait,2)
            if cancel_session:
                task.cancel()
            else:
                stop.set()
            # Give cancellation a chance to reach the blocked mapper.
            await asyncio.sleep(.05)
            assert not task.done() and not overlap
            release.set()
            if cancel_session:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task,3)
                assert not any(e['type']=='caption' for e in events)
            else:
                await asyncio.wait_for(task,3)
                final=[e['data'] for e in events if e['type']=='caption' and e['data']['final']]
                assert final[-1]['source']=='Retained sentence.'
                assert events[-1]['type']=='done'
            assert not active[0] and not overlap
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.p1
def test_abrupt_process_exit_recovers_preview_and_partial_audio_without_cleanup(tmp_path):
    run_ui(r'''
import wave
from linguaflow.library_access import acquire_recording_lock
assert w.new_recording(name='异常退出 原件保留',check_models=False)
directory=w.library.directory(w.current_item['id'])
w.recording_lock=acquire_recording_lock(directory)
w.library.begin(w.current_item,{})
w.session=QObject(w)
w.set_recording_state(module.RecordingState.LISTENING)
raw=(directory/'录音.wav').open('wb')
writer=wave.open(raw,'wb')
writer.setparams((1,2,48000,0,'NONE','not compressed'))
writer.writeframes(b'\x01\x00'*40)
raw.flush()
# Terminate after physical PCM reaches disk but before the data header update.
raw.write(b'\x02\x00'*5+b'\x03')
raw.flush()
w.on_source_preview(dict(sequence=1,keep_ids=[],source='Latest before crash',start=0.,end=1.,language='en'))
wait(lambda: not w.session_dirty)
# No Session.stop, wave.close, window.close, saver.flush or lock release.
if os.name=='nt':
    # os._exit on Windows runs DLL detach, which can crash Qt TLS teardown.
    # Terminate only this test child, as an external hard kill would.
    import ctypes
    terminate=ctypes.WinDLL('kernel32',use_last_error=True).TerminateProcess
    terminate.argtypes=[ctypes.c_void_p,ctypes.c_uint]
    assert terminate(ctypes.c_void_p(-1),0)
os._exit(0)
''', tmp_path)
    import io
    import wave

    from linguaflow.library import Library
    from linguaflow.playback_stream import PlaybackStream
    library=Library(tmp_path)
    item=library.index['sessions'][0]
    data,captions=library.load(item)
    assert data['session']['state']=='recording'
    assert len(captions)==1 and captions[0].source=='Latest before crash' and not captions[0].final
    path=library.directory(item['id'])/'录音.wav'
    original=path.read_bytes()
    stream=PlaybackStream(path,recover_recording=True)
    try:
        with wave.open(io.BytesIO(bytes(stream.read(stream.size())))) as reader:
            assert reader.getnframes()==45
            assert reader.readframes(100)==b'\x01\x00'*40+b'\x02\x00'*5
    finally:
        stream.close()
    assert path.read_bytes()==original
