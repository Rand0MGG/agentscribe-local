"""UI-independent recording completion and navigation rules."""
import math
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, QTimer, Signal

from . import diagnostic_log as diag
from .library_access import acquire_recording_lock
from .recording_save import RecordingSaver
from .recording_state import RecordingState
from .source_preview import preview_captions
from .transcript import Transcript


@dataclass
class RecordingData:
    """The authoritative recording state, independent of either presentation."""
    library: object = None
    item: object = None
    session: object = None
    lock: object = None
    state: RecordingState = RecordingState.IDLE
    captions: Transcript = field(default_factory=Transcript)
    preview: object = None
    preview_sequence: int = 0
    pending_source_revision: object = None
    translating: bool = True
    failure: str = ''
    save_error: str = ''
    dirty: bool = False
    loading: bool = False
    closing: bool = False
    generation: int = 0
    revision: int = 0
    save_target: object = None


def recording_field(name):
    """Adapter aliases refer to the same state; they never keep a second copy."""
    return property(lambda owner: getattr(owner.recording.data, name),
                    lambda owner, value: setattr(owner.recording.data, name, value))


class RecordingWorkflow(QObject):
    saved = Signal(object, object, str)
    lock_released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = RecordingData()
        self.saver = RecordingSaver(self)
        self.saver.completed.connect(self._saved)
        self.saver.idle.connect(self.release_lock)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self.save)
        self.knowledge = None

    def start(self, settings, launch):
        """Acquire, mark durable start, launch, and recover failures as one transaction."""
        from dataclasses import asdict
        data = self.data
        if data.closing:
            raise ValueError('正在退出，请等待当前任务结束。')
        if data.session is not None or data.state.active:
            raise ValueError('正在聆听，请先停止录音。')
        data.lock = acquire_recording_lock(data.library.directory(data.item['id']))
        begun = False
        try:
            data.library.begin(data.item, asdict(settings))
            begun = True
            data.translating = settings.translate
            data.failure = ''
            data.state = RecordingState.STARTING
            launch(settings)
        except Exception as exc:
            data.failure = f'无法启动录音：{exc}'
            if data.session is not None:
                # A thread may have started before launch reported failure. Keep
                # ownership until its real finished event; never discard it.
                data.state = RecordingState.STOPPING
                data.session.stop()
                if not data.session.isRunning():
                    data.session.deleteLater()
                    data.session = None
            if data.session is None:
                data.state = RecordingState.IDLE
                if begun:
                    data.dirty = True
                    data.revision += 1
                    self.save('incomplete')
                    self.flush()
                self.release_lock()
            raise

    def launch(self, settings, *, runtime, callbacks, factory=None):
        if factory is None:
            from .wlk_session import Session
            factory = Session
        data = self.data
        session = factory(settings, self, runtime=runtime,
                          recording_path=data.library.directory(data.item['id']) / '录音.wav')
        data.session = session
        diag.event('recording_session_link', session=getattr(session, 'log_session', None), recording_id=data.item['id'])
        for name, callback in callbacks.items():
            def deliver(*args, callback=callback):
                if data.session is session:
                    callback(*args)
            getattr(session, name).connect(deliver)
        session.start()

    def source_changed(self, revision):
        data = self.data
        started = bool(data.session and data.state == RecordingState.STARTING and not data.failure)
        if started:
            data.state = RecordingState.LISTENING
        matched = revision == data.pending_source_revision
        if matched:
            data.pending_source_revision = None
        return started, matched

    def preview(self, event):
        data = self.data
        if not data.session or not data.state.active:
            return False
        sequence = event['sequence']
        if event.get('done'):
            if data.preview is None or sequence != data.preview_sequence:
                return False
            data.preview = None
        else:
            if sequence <= data.preview_sequence:
                return False
            data.preview, data.preview_sequence = event, sequence
        if data.item and not data.loading:
            data.revision += 1
            data.dirty = True
            self.save()
        return True

    def stop(self):
        data = self.data
        if data.session is None and data.state.active:
            # A cancelled start can have a durable draft but no worker owner.
            data.state = RecordingState.IDLE
            if data.item:
                state, _ = completion_state(data.library, data.item, data.captions.values(),
                    translating=data.translating, failure=data.failure)
                self.save(state)
            self.release_lock()
            return True
        if data.session and data.state.can_stop:
            data.state = RecordingState.STOPPING
            data.session.stop()
            return True
        return False

    def pause(self):
        data = self.data
        if not data.session or data.failure:
            return False
        if data.state == RecordingState.LISTENING and data.session.pause():
            data.state = RecordingState.PAUSING
            return True
        if data.state == RecordingState.PAUSED and data.session.resume():
            data.state = RecordingState.RESUMING
            return True
        return False

    def paused(self, paused):
        data = self.data
        expected = RecordingState.PAUSING if paused else RecordingState.RESUMING
        if data.state != expected or not data.session or data.failure:
            return False
        data.state = RecordingState.PAUSED if paused else RecordingState.LISTENING
        return True

    def caption(self, caption):
        data = self.data
        previous = data.captions.get(caption.id)
        if previous and (caption.revision < previous.revision or
                         caption.revision == previous.revision and caption.source != previous.source):
            return None
        if (caption.source and previous and previous.source == caption.source and previous.language == caption.language
                and not caption.translation and (caption.ready or caption.final)):
            caption = replace(caption, translation=previous.translation, translation_source=previous.translation_source,
                              translation_phase=previous.translation_phase)
        if caption.source:
            data.captions[caption.id] = caption
        elif caption.id in data.captions:
            del data.captions[caption.id]
        if data.item and not data.loading:
            data.revision += 1
            data.dirty = True
            if self.knowledge and self.knowledge.identifier == data.item['id']:
                self.knowledge.observe(caption)
            if not caption.source:
                self.autosave.start(800)
            elif not self.autosave.isActive():
                self.autosave.start(1500)
        return caption

    def finish(self, session, *, retain_preview, caption, wait=False):
        data = self.data
        if data.session is not session:
            return None
        if getattr(session, 'isRunning', lambda: False)():
            return None
        retain_preview()
        for row in unfinished_translations(data.captions.values(), data.translating):
            caption(row)
        final_state, incomplete = completion_state(data.library, data.item, data.captions.values(),
            translating=data.translating, failure=data.failure)
        data.session = None
        data.state = RecordingState.STOPPING
        data.revision += 1
        data.dirty = data.item is not None
        self.save(final_state)
        if wait:
            self.flush()
        session.deleteLater()
        data.state = RecordingState.IDLE
        self.release_lock()
        return final_state, incomplete

    def save(self, state=None):
        data = self.data
        if not data.item or data.loading or not data.dirty and state is None:
            return
        if state is not None:
            data.save_target = state
        self.saver.submit(data.library.save, (data.generation, data.item['id']), data.revision, data.item,
                          preview_captions(data.captions, data.preview), data.save_target)

    def flush(self, state=None):
        self.autosave.stop()
        if self.saver.waiting:
            return False
        self.save(state)
        return self.saver.flush() and not self.data.dirty

    def _saved(self, snapshot, state, error):
        data = self.data
        fields = dict(session=None, recording_id=snapshot.token[1], revision=snapshot.revision,
                      state=state, success=not bool(error), level='ERROR' if error else 'INFO')
        if error or state in ('complete', 'incomplete'):
            diag.event('recording_save_result', **fields)
        else:
            diag.periodic('recording_save_result', key=snapshot.token[1], **fields)
        if not data.item or snapshot.token != (data.generation, data.item['id']):
            return
        if error:
            data.save_error = error
            data.dirty = True
            data.save_target = data.save_target or snapshot.state
        else:
            data.item['state'] = state
            if self.knowledge and self.knowledge.identifier == data.item['id']:
                self.knowledge.saved(snapshot.captions, final=state in ('complete', 'incomplete'))
            if snapshot.revision == data.revision and (data.save_target is None or data.save_target == state):
                data.dirty = False
                data.save_error = ''
                data.save_target = None
        self.saved.emit(snapshot, state, error)

    def release_lock(self):
        data = self.data
        if (data.lock and data.session is None and not data.state.active
                and not self.saver.busy and not data.dirty and not data.save_error):
            data.lock.unlock()
            data.lock = None
            self.lock_released.emit()


def unfinished_translations(captions, translating):
    return [replace(row, error='会话已结束，此条翻译未完成') for row in captions
            if translating and row.final and (not row.translation or row.translation_phase == 'initial') and not row.error]


def completion_state(library, item, captions, *, translating, failure):
    rows = list(captions)
    incomplete = bool(translating and any(
        row.source and (row.error or not row.translation or row.translation_phase == 'initial') for row in rows))
    if failure or incomplete:
        return 'incomplete', incomplete
    if item and not rows:
        try:
            if not (library.directory(item['id']) / '录音.wav').exists():
                return 'draft', False
        except (OSError, ValueError):
            return 'incomplete', False
    return 'complete', False


def locate_seconds(item, captions, identifier, *, caption_id=None, seconds=None):
    """Validate ownership before changing either selection or playback position."""
    if not item or item['id'] != identifier:
        raise ValueError('录音内容已变化，请重新查找。')
    if caption_id is not None:
        if type(caption_id) is not int or caption_id not in captions:
            raise ValueError('字幕内容已变化，请重新查找。')
        seconds = captions[caption_id].start
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('无效的播放位置。')
    return seconds


def preparation_blocks_recording(task):
    return task is not None and task.affects_runtime
