"""Electron's local JSON-lines service. Owns business resources, never creates widgets.

Requests and worker results are serialized by the standard-library dispatcher.
Python owns recording, persistence and process lifecycle independently of the UI.
stdin EOF requests the same orderly shutdown as the desktop close action.
"""
import argparse
import base64
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from threading import Thread
from uuid import uuid4

from . import diagnostic_log as diag
from .application_lifecycle import Activity, ShutdownWorkflow
from .core import LANGUAGES, Settings, translation_status
from .events import Connection, Dispatcher, Owner, Signal, Timer, Worker
from .library import default_recording_name
from .library_access import (
    check_library_access,
    check_library_migration,
)
from .library_loading import LibraryReader
from .library_startup import open_library
from .model_options import (
    asr_backends,
    asr_devices,
    download_catalog,
    model_catalog,
    recommended_selection,
    translation_devices,
)
from .preferences import PREFERENCES, read_audio_device, read_preferences, write_preferences
from .preparation_workflow import PreparationWorkflow, preparation_command
from .recording_save import RecordingSaver
from .recording_state import RecordingState
from .recording_workflow import (
    RecordingWorkflow,
    locate_seconds,
    preparation_blocks_recording,
    recording_field,
)
from .runtime_paths import packaged, resource_root
from .settings_store import SettingsStore
from .source_preview import preview_captions
from .transcript import Transcript
from .translation_config import CONTEXT_COUNTS

PROTOCOL = 1
MAX_REQUEST_BYTES = 1024 * 1024


class _Task(Worker):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.value = None
        self.error = ''

    def run(self):
        try:
            self.value = self.action()
        except Exception as exc:
            self.error = str(exc)


def caption_value(caption):
    return {**asdict(caption), 'translation_status': translation_status(caption)}


class DesktopService(Owner):
    """IPC adapter for shared backend workflows; no widget or browser dependency."""

    preparation = property(lambda self: self.preparation_workflow.worker,
                           lambda self, value: setattr(self.preparation_workflow, 'worker', value))

    closing = property(lambda self: self.shutdown.closing,
                       lambda self, value: setattr(self.shutdown, 'closing', value))

    @property
    def migration_locks(self):
        return self.library_workflow.locks

    library = recording_field('library')
    item = recording_field('item')
    pending_source_revision = recording_field('pending_source_revision')
    session = recording_field('session')
    recording_lock = recording_field('lock')
    state = recording_field('state')
    failure = recording_field('failure')
    save_error = recording_field('save_error')
    dirty = recording_field('dirty')
    generation = recording_field('generation')
    revision = recording_field('revision')
    save_target = recording_field('save_target')
    translating = recording_field('translating')
    captions = recording_field('captions')
    preview = recording_field('preview')
    preview_sequence = recording_field('preview_sequence')
    knowledge = property(lambda self: self.recording.knowledge,
        lambda self, value: setattr(self.recording, "knowledge", value))

    incoming = Signal(object)
    disconnected = Signal()
    output = Signal(dict)

    def __init__(self, *, library_root=None, prefs=None, no_audio=False):
        super().__init__()
        self.recording = RecordingWorkflow(self)
        self.shutdown = ShutdownWorkflow(recording=self.recording, activity=self.activity_snapshot,
            cancel={
                'checks': self.cancel_model_check,
                'reader': lambda: self.reader.cancel(),
                'migration': self.cancel_migration,
                'preparation': self.cancel_preparation,
                'recording': self.stop,
                'update_release': lambda: self.native_updater.cancel()},
            save=self._shutdown_save, resources=self._shutdown_resources,
            runtime=lambda: self.runtime, released=self._runtime_released, parent=self)
        self.shutdown.retry.connect(self._continue_close)
        self.shutdown.failed.connect(self._shutdown_failed)
        self.prefs = prefs if prefs is not None else SettingsStore('LinguaFlow', 'LocalCaptions')
        self.no_audio = no_audio or bool(os.environ.get('AGENTSCRIBE_AUDIO_GUARD_LOG'))
        self.library = open_library(self.prefs, resource_root(), explicit_root=library_root,
                                    choose_directory=self._directory_failed,
                                    migration_failed=self._directory_failed)
        self.values = read_preferences(self.prefs)
        defaults = {'asr': 'small', 'translation': Settings('').translation_model, 'target': '简体中文',
                    'compute': 'CPU（通用）', 'translation_device': 'cpu'}
        self.values = {key: defaults.get(key) if value is None else value for key, value in self.values.items()}
        if not any(self.prefs.contains(key) for key in ('backend', 'asr', 'qwen_model', 'translation',
                   'translation_engine', 'llama_model', 'translation_device', 'compute', 'translate')):
            recommended = recommended_selection()
            self.values.update(backend=recommended['backend'], qwen_model=recommended['asr_model'],
                               translation_engine=recommended['translation_engine'],
                               llama_model=recommended['translation_model'],
                               translation_device=recommended['translation_device'],
                               compute='mlx' if sys.platform == 'darwin' else 'cuda')
        self.values['compute'] = {'cpu': 'CPU（通用）', 'cuda': 'NVIDIA GPU · 半精度',
                                  'mlx': 'Apple GPU · Metal / MLX'}.get(self.values['compute'], self.values['compute'])
        if self.values['backend'] != 'wlk-whisper' and self.values['source'] == '自动检测':
            self.values['source'] = 'English'
        self.device = read_audio_device(self.prefs)
        self.devices = []
        self.item = None
        self.draft = {'name': default_recording_name(), 'folder': self.library.ensure_default_folder()['id']}
        self.has_audio = False
        self.playback_metadata = {"duration": 0, "supports_gain": False}
        self.playback_volume = 100
        self.located_position = None
        self.captions = Transcript()
        self.preview = None
        self.preview_sequence = 0
        self.pending_source_revision = None
        self.session = None
        self.recording_lock = None
        self.state = RecordingState.IDLE
        self.audio_stage = ''
        self.failure = self.save_error = ''
        self.status = '就绪'
        self.dirty = False
        self.generation = self.revision = 0
        self.save_target = None
        self.translating = bool(self.values['translate'])
        self.closing = False
        self.connection_lost = False
        self.frontend_handoff = None
        self.frontend_ready = False
        self.preparation_workflow = PreparationWorkflow(self)
        self.preparation_workflow.result.connect(self._preparation_result)
        self.preparation_workflow.download.connect(self._progress)
        self.preparation_workflow.finished.connect(self._preparation_finished)
        self.preparation_command = None
        self.preparation_recovery = ''
        self.asset_check = None
        self.asset_selection = None
        self.missing_assets = None
        self.asset_check_cancelled = False
        self.model_refresh = Timer(self)
        self.model_refresh.setSingleShot(True)
        self.model_refresh.timeout.connect(self._refresh_models)
        self.tasks = {}
        self.task_callbacks = {}
        self.runtime = None
        self.runtime_action = None
        self.reader = LibraryReader(self)
        self.read_request = None
        self.reader.completed.connect(self._read_completed)
        self.pending_library = None
        from .library_workflow import LibraryWorkflow
        self.library_workflow = LibraryWorkflow(self.recording, self.prefs, self)
        self.migration = self.library_workflow.worker
        self.migration.progress.connect(lambda value: self.emit('migration', {'busy': True, 'progress': value}))
        self.library_workflow.adopted.connect(self._library_adopted)
        self.library_workflow.finished.connect(self._library_migrated)
        self.preparation_status = ''
        self.progress = None
        self.knowledge = None
        self.player = None
        self.saver = self.recording.saver
        self.recording.saved.connect(self._saved)
        self.recording.lock_released.connect(self._after_lock_released)
        self.saver.idle.connect(self._continue_close)
        self.exporter = RecordingSaver(self)
        self.export_sequence = 0
        self.export_errors = []
        self.recovery_receipt = None
        from .knowledge.lifecycle import KnowledgeState
        self.knowledge_state = KnowledgeState()
        self.knowledge_view = self.knowledge_state.view
        self.unsaved_edits = False
        self.update_fenced = False
        from .native_updates import NativeUpdater
        from .update_workflow import UpdateWorkflow
        self.native_updater = NativeUpdater(self)
        self.update_workflow = UpdateWorkflow(self.native_updater, activity=self.update_activity_snapshot,
            close_knowledge=self.close_update_knowledge, runtime=lambda: self.runtime,
            fence=self.fence_for_update, restore=self.restore_after_update,
            notify=lambda text, busy: self.emit('updates', {'stage': 'waiting', 'text': text, 'releasing': busy}))
        self.native_updater.event.connect(self.on_native_update)
        self.native_updater.shutdown_complete.connect(lambda _: self._continue_close())
        self.exporter.completed.connect(self._exported)
        self.exporter.idle.connect(self._exports_finished)
        self.exporter.idle.connect(self._continue_close)
        self.autosave = self.recording.autosave
        self.autosave.setSingleShot(True)
        self.incoming.connect(self.dispatch, Connection.Queued)
        self.disconnected.connect(self._disconnect, Connection.Queued)
        self.clock = Timer(self)
        self.clock.setInterval(500)
        self.clock.timeout.connect(self._clock)
        self.clock.start()
        Timer.singleShot(0, self._warm_runtime)
        self.routes = {name: method for name, method in (
            ('bootstrap', self.bootstrap), ('settings.set', self.set_settings),
            ('library.refresh', self.refresh), ('recording.open', self.open_recording),
            ('recording.new', self.new_recording), ('folder.create', self.create_folder),
            ('item.rename', self.rename), ('item.move', self.move), ('item.trash', self.trash),
            ('trash.list', self.deleted), ('trash.restore', self.restore), ('trash.purge', self.purge),
            ('captions.locate', self.locate), ('captions.page', self.page), ('captions.search', self.search),
            ('recording.save', self.retry_save), ('recording.export', self.export),
            ('recording.close_recovered', self.close_recovered),
            ('audio.refresh', self.refresh_devices), ('audio.select', self.select_device),
            ('recording.start', self.start), ('recording.stop', self.stop), ('recording.pause', self.pause),
            ('playback.event', self.playback_event), ('playback.toggle', self.play), ('playback.seek', self.seek), ('playback.volume', self.volume),
            ('models.prepare', self.prepare), ('models.cancel', self.cancel_preparation),
            ('models.retry', self.retry_preparation),
            ('models.check', self.check_models), ('models.cancel_check', self.cancel_model_check),
            ('models.inventory', self.model_inventory), ('models.delete', self.delete_model),
            ('updates.check', self.check_updates), ('updates.action', self.update_action), ('app.edited', self.set_edited), ('library.migrate', self.migrate_library),
            ('library.cancel_migration', self.cancel_migration),
            ('knowledge.open', self.open_knowledge), ('knowledge.command', self.knowledge_command),
            ('knowledge.image', self.knowledge_image),
            ('app.close', self.close), ('path.recording', self.recording_path),
            ('frontend.prepare', self.prepare_frontend), ('frontend.ready', self.mark_frontend_ready),
            ('frontend.cancel', self.cancel_frontend),
            ('layout.sidebar', self.set_sidebar_width),
            ('overlay.get', self.overlay_preferences), ('overlay.set', self.set_overlay_preferences),
            ('path.diagnostics', lambda: str(diag.log_directory())),
        )}

    @staticmethod
    def _directory_failed(_root, error):
        raise ValueError(f'无法打开保存位置，请检查目录权限或选择其他保存位置：{error}')

    def emit(self, event, data):
        self.output.emit({'event': event, 'data': data})

    def dispatch(self, request):
        identifier = request.get('id') if isinstance(request, dict) else None
        try:
            if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier < 0:
                raise ValueError('无效的请求标识。')
            if request.get('version') != PROTOCOL:
                raise ValueError('桌面与后台协议版本不一致，请重新构建桌面。')
            operation = request.get('method')
            if not isinstance(operation, str) or operation not in self.routes:
                raise ValueError('不支持的桌面操作。')
            if self.closing and operation != 'app.close':
                raise ValueError('正在退出，请等待当前任务结束。')
            if self.update_fenced and operation not in ('bootstrap', 'app.close', 'updates.action', 'app.edited', 'updates.check'):
                raise ValueError('正在准备重启更新，请等待完成或取消更新。')
            params = request.get('params', {})
            if not isinstance(params, dict):
                raise ValueError('操作参数必须是对象。')
            if operation not in ('bootstrap', 'captions.page', 'captions.search', 'overlay.get', 'overlay.set'):
                diag.event('desktop_request', operation=operation, request_id=identifier)
            if operation in ('library.refresh', 'recording.open'):
                self._read_library(identifier, refresh=operation == 'library.refresh', **params)
                return  # Reply only after the owned reader has completed.
            result = self.routes[operation](**params)
            self.output.emit({'id': identifier, 'result': result})
        except Exception as exc:
            # Keep requests alive after recoverable user/data errors. No request
            # body is logged: it can contain captions or an API credential.
            diag.exception('desktop_request_failed', exc, request_id=identifier)
            self.output.emit({'id': identifier, 'error': {'message': str(exc), 'kind': type(exc).__name__}})

    def snapshot(self):
        from .recording_state import capture_feedback
        ready = getattr(self.session, 'model_ready', None)
        capture = capture_feedback(self.state, model_ready=ready.is_set() if ready is not None else None,
            failed=bool(self.failure), source_pending=self.pending_source_revision is not None, audio_stage=self.audio_stage)
        return {'item': self.item, 'draft': self.draft, 'state': self.state.name, 'status': self.status, 'capture': capture,
                'failure': self.failure, 'save_error': self.save_error,
                'saving': self.saver.busy, 'dirty': self.dirty, 'generation': self.generation,
                'revision': self.revision, 'count': len(self.captions), 'preview': self.preview,
                'preparing': self.preparation is not None or self.runtime_action is not None, 'preparation_status': self.preparation_status,
                'preparation_kind': self.preparation_command[1] if self.preparation_command else None,
                'preparation_blocks_recording': preparation_blocks_recording(self.preparation) or self.runtime_action is not None,
                'preparation_cancelling': bool(self.preparation and self.preparation.cancelled),
                'preparation_recovery': self.preparation_recovery,
                'checking_models': self.asset_check is not None,
                'model_missing': self.missing_assets if self.asset_selection == self._selection() else None,
                'translation_available': not (self.asset_selection == self._selection() and self.missing_assets
                                             and any(row.startswith('翻译') for row in self.missing_assets)),
                'progress': self.progress, 'closing': self.closing, 'has_audio': self.has_audio, 'playback': {**self.playback_metadata, 'volume': self.playback_volume}, 'translating': self.translating,
                'migrating': self.migration.busy or bool(self.pending_library),
                'update_fenced': self.update_fenced, 'recovery_ready': self._recovery_ready()}

    def changed(self):
        self.emit('state', self.snapshot())

    def bootstrap(self):
        from . import __version__
        from .translation_models import HY_GENERATION, NLLB_GENERATION
        return {'version': __version__, 'protocol': PROTOCOL, 'platform': sys.platform, 'installed': packaged(), 'no_audio': self.no_audio,
                'settings': self.values, 'library': self.library.index, 'root': str(self.library.root),
                'state': self.snapshot(), 'captions': self.page(), 'devices': self.devices, 'device': self.device,
                'audio_refreshing': 'audio-discovery' in self.tasks,
                'layout': {'sidebar_width': self.prefs.value('electron_sidebar_width', type=int)
                           if self.prefs.contains('electron_sidebar_width') else None},
                'options': {'languages': LANGUAGES, 'backends': asr_backends(), 'devices': asr_devices(),
                            'models': {key: model_catalog(key) for key in (*asr_backends(), 'llama', 'pytorch')},
                            'translation_devices': {key: translation_devices(key) for key in ('llama', 'pytorch')},
                            'recommended': recommended_selection(), 'downloads': download_catalog(),
                            'generation': {'hy': f"HY-MT2 生成参数 · 最大 {HY_GENERATION['max_new_tokens']} tokens · 温度 {HY_GENERATION['temperature']} · top-p {HY_GENERATION['top_p']} · top-k {HY_GENERATION['top_k']} · 重复惩罚 {HY_GENERATION['repetition_penalty']}\n初译参考前后各 1 段；定稿参考前 5 段、后 1 段。仅使用已有的定稿原文。",
                                           'nllb': f"NLLB 生成参数 · 最大 {NLLB_GENERATION['max_new_tokens']} tokens · beams {NLLB_GENERATION['num_beams']}\n逐段翻译；单段输入最多 512 tokens，超长时保留原文并提示。"}}}

    def mark_frontend_ready(self, owner_pid=None):
        if owner_pid is not None:
            from .frontend_switch import validate_owner
            validate_owner(owner_pid)
        if not self.frontend_ready:
            from .frontend_switch import ready
            ready('electron', self.prefs)
            self.frontend_ready = True
            from .desktop_startup import frontend_healthy
            frontend_healthy(owner_pid)
            if not self.no_audio:
                Timer.singleShot(1500, lambda: self.check_updates(manual=False))

    def cancel_frontend(self):
        self.frontend_handoff = None

    def activity_snapshot(self):
        return Activity(recording=self.session is not None or self.state.active,
            saving=self.saver.busy or self.exporter.busy, unsaved=self.dirty or bool(self.save_error),
            reader=self.reader.busy, migration=self.migration.busy or bool(self.pending_library),
            preparation=self.preparation is not None or self.runtime_action is not None,
            checks=bool(self.tasks) or self.asset_check is not None,
            fenced=self.update_fenced, update_release=self.native_updater.shutdown_job is not None,
            update_pending=self.update_fenced or self.native_updater.pending,
            knowledge=self.knowledge_state.busy, edits=self.unsaved_edits)

    def prepare_frontend(self, owner_pid, geometry, updates=False):
        reason = self.activity_snapshot().switch_reason()
        if reason or self.closing:
            raise ValueError(reason or '正在退出，请稍候。')
        self._idle()
        from .frontend_switch import prepare
        self.frontend_handoff = prepare('qt', library=self.library, prefs=self.prefs,
            recording=self.item['id'] if self.item else None, draft=self.draft,
            no_audio=self.no_audio, owner_pid=owner_pid, geometry=geometry, purpose='updates' if updates else None)
        return {'ready': True}

    def _idle(self):
        if self.update_fenced:
            raise ValueError('正在准备重启更新，请等待完成或取消更新。')
        if 'runtime-release' in self.tasks:
            raise ValueError('正在释放推理环境，请稍候。')
        if self.reader.busy:
            raise ValueError('正在读取录音，请稍后重试。')
        if self.session is not None or self.state.active:
            raise ValueError('正在聆听，请先停止录音再切换。')
        if self.saver.busy or self.exporter.busy:
            raise ValueError('正在保存，请稍后重试。')
        if self.migration.busy:
            raise ValueError('录音库正在迁移，请完成或取消后重试。')
        if self.dirty or self.save_error:
            raise ValueError('字幕尚未保存，请先重试保存或备份全部文字。')
        check_library_migration(self.library.root)

    def _find(self, identifier, *, folders=True):
        rows = self.library.index['sessions'] + (self.library.index['folders'] if folders else [])
        item = next((row for row in rows if row['id'] == identifier), None)
        if item is None:
            raise ValueError('文件已变化，请刷新列表后重试。')
        return item

    def _close_resources(self):
        if self.knowledge is not None and not self.knowledge.close():
            raise ValueError('课程后台仍在退出，请稍后重试。')
        if self.player is not None:
            self.player.release()

    def refresh(self):
        # Library mutations refresh their own index. Do not scan it twice.
        self.emit('library', self.library.index)
        return {'index': self.library.index, 'warnings': self.library.warnings}

    def _read_library(self, request_id, *, refresh=False, identifier=None):
        self._idle()
        if not refresh:
            if not isinstance(identifier, str):
                raise ValueError('请选择录音。')
            check_library_access(self.library, self._find(identifier, folders=False))
        self.read_request = request_id, refresh
        self.reader.start(self.library, refresh=refresh, identifier=identifier)

    def _read_completed(self, result, error):
        request_id, refresh = self.read_request
        self.read_request = None
        try:
            if error or result is None or self.closing:
                raise ValueError(error or '读取已取消，原视图保留。')
            library, item, loaded = result
            if not refresh:
                check_library_access(library, item)
                self._close_resources()
            self.library = library
            if refresh:
                value = self.refresh()
            else:
                data, captions = loaded
                self.status = '已打开录音'
                self._select(item, captions, data.get('settings', {}).get('translate', True))
                value = self.snapshot()
            self.output.emit({'id': request_id, 'result': value})
        except Exception as exc:
            self.output.emit({'id': request_id, 'error': {'message': str(exc), 'kind': type(exc).__name__}})
        self._continue_close()

    def _audio_metadata(self):
        item = self.item
        audio = self.library.directory(item['id']) / '录音.wav' if item else None
        self.has_audio = bool(audio and audio.is_file() and audio.stat().st_size > 44)
        self.playback_metadata = {'duration': 0, 'supports_gain': False}
        if self.has_audio:
            from .playback_stream import PlaybackStream
            try:
                stream = PlaybackStream(audio, recover_recording=item['state'] in ('incomplete', 'recording'))
                try:
                    self.playback_metadata = {'duration': stream.duration_ms, 'supports_gain': stream.supports_gain}
                finally:
                    stream.close()
            except (OSError, ValueError) as exc:
                self.emit('notice', {'text': '音频暂不可读取：' + str(exc), 'error': True})
        if self.has_audio:
            self.playback_volume = min(self.playback_volume, 300 if self.playback_metadata['supports_gain'] else 100)

    def _select(self, item, captions=(), translating=None):
        self.located_position = None
        self.audio_stage = ''
        self.generation += 1
        self.revision = 0
        self.item = item
        self.draft = None if item else {'name': default_recording_name(), 'folder': self.library.ensure_default_folder()['id']}
        self._audio_metadata()
        self.captions = Transcript((row.id, row) for row in captions)
        self.preview = None
        self.preview_sequence = 0
        self.failure = self.save_error = ''
        self.save_target = None
        self.recovery_receipt = None
        self.translating = self.values['translate'] if translating is None else translating
        self.changed()
        self.emit('captions', self.page())
        self.attach_knowledge()

    def open_recording(self, identifier):
        self._idle()
        item = self._find(identifier, folders=False)
        check_library_access(self.library, item)
        # Read and validate before releasing the currently visible recording.
        data, captions = self.library.load(item)
        self._close_resources()
        self.status = '已打开录音'
        self._select(item, captions, data.get('settings', {}).get('translate', True))
        return self.snapshot()

    def new_recording(self, folder_id=None, name=None):
        self._idle()
        folder_id = folder_id or (self.draft or self.item or {}).get('folder')
        if not any(row['id'] == folder_id for row in self.library.index['folders']):
            folder_id = self.library.ensure_default_folder()['id']
        name = name or default_recording_name()
        self.library.validate_name(name)
        self._close_resources()
        self._select(None)
        self.draft = {'name': name, 'folder': folder_id}
        self.status = '准备开始录音'
        self.changed()
        return self.snapshot()

    def _create_recording(self, folder_id=None, name=None):
        """Commit a pending workspace only when capture is explicitly started."""
        self._idle()
        if folder_id is None:
            folder_id = self.library.ensure_default_folder()['id']
        folder = self._find(folder_id)
        if 'parent' not in folder:
            raise ValueError('请选择保存文件夹。')
        check_library_access(self.library, folder)
        self._close_resources()
        item = self.library.create(folder_id, asdict(self.settings()), name)
        self.status = '准备开始录音'
        self._select(item)
        self.refresh()
        return self.snapshot()

    def create_folder(self, name, parent=None):
        self._idle()
        if parent:
            item = self._find(parent)
            if 'parent' not in item:
                raise ValueError('请选择父文件夹。')
            check_library_access(self.library, item)
        item = self.library.folder(name, parent)
        self.refresh()
        return item

    def rename(self, identifier, name):
        if identifier is None and self.draft:
            self.library.validate_name(name)
            self.draft['name'] = name.strip()
            self.changed()
            return
        item = self._find(identifier)
        active_current = bool(self.session and self.item and identifier == self.item['id'])
        self.library_workflow.ensure_edit(item, activity=self.activity_snapshot(),
            close_resources=self._close_resources, rename_current=True)
        self.library.rename(item, name, defer_directory=active_current)
        if self.item and self.item['id'] == identifier:
            self.item = item
        self.refresh()
        self.changed()

    def move(self, identifier, folder_id):
        item, folder = self._find(identifier), self._find(folder_id)
        if 'parent' not in folder:
            raise ValueError('请选择目标文件夹。')
        self._edit_item(item)
        check_library_access(self.library, folder)
        self.library.move(item, folder_id)
        self.refresh()
        if self.item:
            self.item = self._find(self.item['id'], folders=False)
        self.changed()

    def trash(self, identifier):
        item = self._find(identifier)
        self._edit_item(item)
        token = self.library.trash(item)
        if self.item and not any(row['id'] == self.item['id'] for row in self.library.index['sessions']):
            self._select(None)
        self.library.ensure_default_folder()
        self.refresh()
        return token

    def _edit_item(self, item):
        if self.closing:
            raise ValueError('正在退出，请稍后重试。')
        self.library_workflow.ensure_edit(item, activity=self.activity_snapshot(), close_resources=self._close_resources)

    def deleted(self):
        return self.library.deleted()

    def restore(self, token):
        self._idle()
        self.library.restore_deleted(token)
        self.refresh()
        return self.deleted()

    def purge(self, token):
        self._idle()
        self._close_resources()
        self.library.purge_deleted(token)
        return self.deleted()

    def page(self, start=None, locate=None, seconds=None):
        if start is not None and (type(start) is not int or start < 0):
            raise ValueError('无效的字幕分页。')
        ids = self.captions.ordered_ids
        if seconds is not None:
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError('无效的字幕时间。')
            locate = next((key for key in ids if self.captions[key].start <= seconds < self.captions[key].end), None)
        # Saved recordings are one complete transcript. The live tail window is
        # only for recording, never the starting point for reviewing a class.
        if self.state is RecordingState.IDLE:
            start = 0
        elif locate is not None:
            start = (ids.index(locate) // 200) * 200 if locate in ids else 0
        elif start is None:
            start = max(0, len(ids) - 200)
        if type(start) is not int or start < 0:
            raise ValueError('无效的字幕分页。')
        start = min(start, max(0, len(ids) - 1))
        return {'generation': self.generation, 'revision': self.revision, 'start': start,
                'total': len(ids), 'rows': [caption_value(self.captions[key]) for key in
                                         (ids if self.state is RecordingState.IDLE else ids[start:start+200])]}

    def search(self, query, start=0):
        if not isinstance(query, str) or len(query) > 1024 or type(start) is not int or start < 0:
            raise ValueError('无效的搜索条件。')
        query = query.strip().casefold()
        rows = [caption_value(self.captions[key]) for key in self.captions.ordered_ids
                if query in (self.captions[key].source + '\n' + self.captions[key].translation).casefold()]
        return {'generation': self.generation, 'total': len(rows), 'rows': rows[start:start+100]}

    def set_settings(self, values):
        if not isinstance(values, dict) or set(values) - {p.key for p in PREFERENCES}:
            raise ValueError('无效的设置项。')
        candidate = {**self.values, **values}
        for pref in PREFERENCES:
            value = candidate[pref.key]
            if pref.kind == 'bool' and type(value) is not bool:
                raise ValueError('开关设置必须是布尔值。')
            if pref.kind == 'float' and (type(value) not in (float, int) or not math.isfinite(value)
                                        or not (.25 if pref.key == 'draft_seconds' else .5) <= value <= 3):
                raise ValueError('字幕时间参数超出范围。')
            if pref.kind in ('text', 'editable') and (not isinstance(value, str) or len(value) > 4096):
                raise ValueError('无效的文字设置。')
        if candidate['backend'] not in asr_backends() or candidate['appearance'] not in ('light', 'dark'):
            raise ValueError('不支持的引擎或外观。')
        if candidate['translation_engine'] not in ('llama', 'pytorch'):
            raise ValueError('不支持的翻译引擎。')
        if candidate['backend'] == 'qwen3-streaming' and candidate['qwen_model'].startswith('mlx-community/'):
            raise ValueError('MLX 权重需要 Apple Silicon Mac 的 MLX 引擎，当前引擎不能使用。')
        if candidate['translation_engine'] == 'llama' and candidate['llama_model'].startswith('hf://'):
            from .llama_assets import hub_gguf
            hub_gguf(candidate['llama_model'])
        if candidate['translation_device'] not in translation_devices(candidate['translation_engine']):
            raise ValueError('翻译设备不适用于当前平台和引擎。')
        if candidate['source'] not in ['自动检测', *(row[0] for row in LANGUAGES)] or candidate['target'] not in [row[0] for row in LANGUAGES]:
            raise ValueError('不支持的语言。')
        if candidate['backend'] != 'wlk-whisper' and candidate['source'] == '自动检测':
            candidate['source'] = 'English'
        if candidate['source'] == candidate['target']:
            candidate['translate'] = False
        if candidate['compute'] not in ('cpu', 'cuda', 'mlx', 'CPU（通用）', 'NVIDIA GPU · 半精度', 'Apple GPU · Metal / MLX'):
            raise ValueError('不支持的识别设备。')
        compute = {'CPU（通用）': 'cpu', 'NVIDIA GPU · 半精度': 'cuda',
                   'Apple GPU · Metal / MLX': 'mlx'}.get(candidate['compute'], candidate['compute'])
        if compute not in asr_devices():
            raise ValueError('识别设备不适用于当前平台。')
        candidate['compute'] = {'cpu': 'CPU（通用）', 'cuda': 'NVIDIA GPU · 半精度', 'mlx': 'Apple GPU · Metal / MLX'}[compute]
        candidate.update({key: default for key, (default, _maximum) in CONTEXT_COUNTS.items()})
        if self.knowledge is not None and not candidate['beta_features'] and not self.knowledge.close():
            raise ValueError('课程后台尚未退出，设置未保存。')
        write_preferences(self.prefs, candidate)
        self.prefs.sync()
        if self.prefs.status().value != 0:
            raise OSError('设置写入失败，请检查配置目录权限。')
        selection_changed = any(candidate[key] != self.values[key] for key in (
            'backend', 'asr', 'qwen_model', 'translation_engine', 'translation', 'llama_model', 'translation_device', 'translate'))
        self.values = candidate
        if not candidate['beta_features'] and self.preparation and self.preparation.beta_only:
            self.cancel_preparation()
        if selection_changed:
            self.model_refresh.start(100)
        self.changed()
        self.emit('settings', candidate)
        return candidate

    def settings(self):
        from .session_settings import session_settings
        return session_settings(self.values, self.device or ('', False))

    def _audio_allowed(self):
        if self.no_audio:
            raise ValueError('当前为无音频验证模式，设备访问和播放已禁用。')

    def overlay_preferences(self):
        result = {}
        for name, key, default, minimum, maximum in (
                ('font', 'overlay_font_size', 23, 12, 56),
                ('opacity', 'overlay_background_opacity', 80, 0, 100)):
            try:
                result[name] = max(minimum, min(maximum, int(self.prefs.value(key, default))))
            except (ValueError, TypeError):
                result[name] = default
        try:
            bounds = json.loads(self.prefs.value('electron_overlay_bounds', '{}'))
            if isinstance(bounds, dict) and set(bounds) == {'x', 'y', 'width', 'height'} and all(type(value) is int and abs(value) <= 100000 for value in bounds.values()):
                result['bounds'] = bounds
        except (ValueError, TypeError):
            pass
        return result

    def set_overlay_preferences(self, font=None, opacity=None, bounds=None):
        if bounds is not None and (not isinstance(bounds, dict) or set(bounds) != {'x', 'y', 'width', 'height'}
                                   or any(type(value) is not int or abs(value) > 100000 for value in bounds.values())
                                   or bounds['width'] < 1 or bounds['height'] < 1):
            raise ValueError('无效的悬浮窗口位置。')
        for value, minimum, maximum in ((font, 12, 56), (opacity, 0, 100)):
            if value is not None and (type(value) is not int or not minimum <= value <= maximum):
                raise ValueError('无效的悬浮字幕设置。')
        for value, key in ((font, 'overlay_font_size'), (opacity, 'overlay_background_opacity')):
            if value is not None:
                self.prefs.setValue(key, value)
        if bounds is not None:
            self.prefs.setValue('electron_overlay_bounds', json.dumps(bounds))
        return self.overlay_preferences()

    def refresh_devices(self):
        self._audio_allowed()
        if 'audio-discovery' in self.tasks or self.closing:
            return self.devices
        def discover():
            from .audio import discover_devices
            return [asdict(row) for row in discover_devices()]
        def completed(error):
            if not error and not self.closing:
                self.devices = task.value
                if not self.device and self.devices and not self.session:
                    self.device = (self.devices[0]['id'], self.devices[0]['loopback'])
                    self.prefs.setValue('audio_device', json.dumps(self.device))
                self.emit('devices', self.devices)
                self.emit('device', self.device)
        task = self._start_task('audio-discovery', discover, completed)
        return self.devices

    def select_device(self, identifier, loopback):
        if not isinstance(identifier, str) or type(loopback) is not bool:
            raise ValueError('无效的音频来源。')
        if not any(row['id'] == identifier and row['loopback'] == loopback for row in self.devices):
            raise ValueError('音频来源已变化，请刷新后重选。')
        self._audio_allowed()
        if self.session:
            if self.state not in (RecordingState.LISTENING, RecordingState.PAUSED):
                raise ValueError('请等待当前录音状态切换完成。')
            revision = self.session.switch_source(identifier, loopback)
            if revision is None:
                raise ValueError('录音正在停止，来源未切换。')
            self.pending_source_revision = revision
            self.emit('level', 0)
        self.device = (identifier, loopback)
        self.prefs.setValue('audio_device', json.dumps(self.device))
        self.changed()
        return self.device

    def start(self):
        self._audio_allowed()
        self._idle()
        if preparation_blocks_recording(self.preparation) or self.runtime_action or 'inventory' in self.tasks:
            raise ValueError('模型准备中，请完成或取消后再开始。')
        if self.runtime is not None and self.runtime.closed:
            raise ValueError('推理环境尚未安全释放，请重试修复运行环境或关闭应用。')
        if not self.device or not any(row['id'] == self.device[0] and row['loopback'] == self.device[1] for row in self.devices):
            raise ValueError('请刷新并选择音频来源。')
        self.cancel_model_check()
        if not self.item or self.item['state'] != 'draft':
            draft = self.draft or {'name': default_recording_name(), 'folder': self.item['folder']}
            self._create_recording(folder_id=draft['folder'], name=draft['name'])
        self._close_resources()
        settings = self.settings()
        # Session starts capture and loading in parallel. Do not scan model
        # caches or import inference environments on the command event loop.
        if settings.translate and not self.snapshot()['translation_available']:
            settings = replace(settings, translate=False)
            self.emit('notice', {'text': '翻译模型或组件尚未准备，本次仅识别。'})
        if self.values['beta_features'] and settings.backend in ('qwen3-streaming', 'qwen3-mlx'):
            from .knowledge.session import session_context
            settings = replace(settings, asr_context=session_context(self.library, self.item['id']))
        self._select(self.item)
        try:
            self.recording.start(settings, self._launch_session)
        except Exception:
            self._failed(self.failure or '无法启动录音，请检查保存位置及运行环境。')
            raise
        self.changed()
        return self.snapshot()

    def _launch_session(self, settings):
        self.recording.launch(settings, runtime=self.runtime, callbacks={
            'status': self._status, 'stage': self._stage, 'ready': self._ready,
            'paused': self._paused, 'caption': self._caption, 'source_preview': self._preview,
            'source_changed': self._source_changed, 'level': self._level, 'failure': self._failed,
            'finished': self._session_finished})

    def _session_finished(self):
        session = self.session
        # RecordingWorkflow.launch already rejects signals from stale sessions.
        # Capture this owner before deferring until the worker has actually exited.
        if session is not None:
            Timer.singleShot(0, lambda: self._finished(session))

    def _ready(self):
        if self.session and not self.failure and self.state != RecordingState.STOPPING:
            self.status = '正在聆听' if self.state == RecordingState.LISTENING else self.status
            self.emit('model-loading', {'busy': False})
            self.changed()

    def _source_changed(self, revision):
        started, matched = self.recording.source_changed(revision)
        if started:
            self.status = '录音已开始' if not self.session.model_ready.is_set() else '正在聆听'
            self.emit('model-loading', {'busy': not self.session.model_ready.is_set()})
        if started or matched:
            self.audio_stage = '连续采集'
            self.changed()

    def _level(self, value):
        self.emit('level', value if self.state == RecordingState.LISTENING and self.pending_source_revision is None else 0)

    def stop(self):
        if self.recording.stop():
            self.emit('model-loading', {'busy': False})
            self.changed()

    def pause(self):
        if self.recording.pause():
            self.changed()

    def _paused(self, paused):
        if self.recording.paused(paused):
            self.status = '已暂停聆听' if paused else '正在聆听'
            if paused:
                self.emit('level', 0)
            self.changed()

    def _status(self, value):
        self.emit('diagnostic', value)
        # Loading/catch-up diagnostics must not replace the capture fact shown
        # in the island or create repeated notifications.

    def _stage(self, name, value):
        self.emit('stage', {'name': name, 'value': value})
        if name == '音频':
            self.audio_stage = value
            self.changed()

    def _failed(self, value):
        self.emit('model-loading', {'busy': False})
        self.failure = value
        self.status = '识别未完成，已有录音和字幕会保留。'
        self.changed()

    def _caption(self, caption):
        caption = self.recording.caption(caption)
        if caption is not None:
            self.emit('caption', {'generation': self.generation, 'revision': self.revision,
                                 'caption': caption_value(caption), 'total': len(self.captions)})

    def _preview(self, event):
        if self.recording.preview(event):
            self.changed()

    def _finished(self, session):
        if self.session is not session:
            return
        result = self.recording.finish(session, retain_preview=self._retain_preview, caption=self._caption)
        if result is None:
            Timer.singleShot(20, lambda: self._finished(session))
            return
        self.status = '正在保存录音与字幕…'
        self._audio_metadata()
        self.emit('captions', self.page())
        self.changed()

    def _retain_preview(self):
        if self.preview:
            self.captions = Transcript((row.id, row) for row in preview_captions(self.captions, self.preview))
            self.preview = None
            self._failed('原文分句未完成，最新识别结果已作为草稿保留，请对照录音。')

    def _save(self, state=None):
        self.recording.save(state)

    def _saved(self, snapshot, state, error):
        if error:
            self.status = '保存失败，请重试保存；已有文字仍保留。'
        elif not self.dirty and not self.session:
            self.status = '已取消 · 录音尚未开始' if state == 'draft' else '已保存录音与字幕'
            self.refresh()
            if self.pending_library and not self.closing:
                Timer.singleShot(0, self._begin_pending_migration)
        self.changed()

    def retry_save(self):
        self._save()
        self.changed()

    def _release_lock(self):
        self.recording.release_lock()

    def _after_lock_released(self):
        if self.item and 'pending_name' in self.item:
            try:
                self._close_resources()
                self.library.rename(self.item, self.item['pending_name'])
                self.refresh()
            except (OSError, ValueError) as exc:
                self.emit('notice', {'text': '名称已保存，文件夹名暂未同步：' + str(exc), 'error': True})
        self._audio_metadata()
        self.changed()

    def export(self, path, format='srt', recovery=False):
        from .recording_export import FORMATS, write_export, write_recovery
        if not self.item or not isinstance(path, str) or not Path(path).is_absolute() or format not in FORMATS:
            raise ValueError('请选择有效的导出位置和格式。')
        if self.session and not recovery:
            raise ValueError('请先停止录音再导出定稿。')
        target = Path(path).resolve()
        # A native save dialog is required by the Electron main process. Still
        # reject overwriting source/session data inside any recording directory.
        if target == self.library.root or self.library.root in target.parents:
            raise ValueError('请导出到录音库之外，避免覆盖录音或课程原件。')
        if not self.exporter.busy:
            self.export_errors = []
        self.export_sequence += 1
        item = {'recording_token': (self.generation, self.item['id']), 'path': str(target), 'format': format, 'name': self.item['name'], 'recovery': recovery,
                'state': 'recovery' if recovery else 'export'}
        self.exporter.submit(write_recovery if recovery else write_export,
                             (-self.export_sequence, str(target)), self.revision, item,
                             preview_captions(self.captions, self.preview))
        self.emit('notice', {'key': 'export', 'text': '正在导出…', 'busy': True})

    def _exported(self, snapshot, _state, error):
        if not error and snapshot.item.get('recovery'):
            try:
                digest = hashlib.sha256(Path(snapshot.item['path']).read_bytes()).hexdigest()
                self.recovery_receipt = (snapshot, digest)
            except OSError as exc:
                error = str(exc)
        self.changed()
        if error:
            self.export_errors.append(f"{Path(snapshot.item['path']).name}：{error}")

    def _exports_finished(self):
        self.emit('notice', {'key': 'export', 'text': '导出失败：' + '；'.join(self.export_errors)
                            if self.export_errors else '导出完成', 'error': bool(self.export_errors)})

    def _recovery_ready(self):
        receipt = self.recovery_receipt
        return bool(receipt and self.item and not self.session and not self.saver.busy and self.dirty
                    and self.save_error and receipt[0].item.get('recording_token') == (self.generation, self.item['id'])
                    and receipt[0].revision == self.revision)

    def close_recovered(self):
        if not self._recovery_ready():
            raise ValueError('录音内容已变化，请先停止并重新备份全部文字。')
        snapshot, digest = self.recovery_receipt
        if hashlib.sha256(Path(snapshot.item['path']).read_bytes()).hexdigest() != digest:
            raise ValueError('备份已被修改，请重新备份再关闭。')
        self.autosave.stop()
        self.dirty = False
        self.save_error = ''
        self._release_lock()
        self._select(None)
        self.refresh()

    def recording_path(self, identifier=None):
        if identifier is not None:
            item = self._find(identifier)
            return str(self.library.directory(item['id']))
        return str(self.library.directory(self.item['id']) if self.item else self.library.root)

    def set_sidebar_width(self, width):
        if type(width) is not int or not 180 <= width <= 420:
            raise ValueError('录音库宽度必须在 180–420 之间。')
        previous = self.prefs.value('electron_sidebar_width')
        self.prefs.setValue('electron_sidebar_width', width)
        self.prefs.sync()
        if self.prefs.status().value != 0:
            if previous is None:
                self.prefs.remove('electron_sidebar_width')
            else:
                self.prefs.setValue('electron_sidebar_width', previous)
            raise OSError('录音库宽度未能保存，请检查设置目录权限。')
        return width

    def migrate_library(self, path):
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('请选择有效的保存目录。')
        if Path(path).resolve() == self.library.root:
            return
        if self.session:
            self.pending_library = path
            self.emit('notice', {'text': '录音结束并保存后，自动迁移到新位置。'})
            self.changed()
            return
        self._idle()
        self._close_resources()
        self.library_workflow.start(path)
        self.changed()

    def cancel_migration(self):
        self.pending_library = None
        if self.migration.busy:
            self.migration.cancel()
        self.changed()

    def _begin_pending_migration(self):
        if not self.pending_library or self.session or self.saver.busy or self.dirty or self.closing:
            return
        path, self.pending_library = self.pending_library, None
        try:
            self.migrate_library(path)
        except (OSError, ValueError) as exc:
            self.emit('notice', {'text': str(exc), 'error': True})



    def _library_adopted(self, library):
        self.emit('library-root', str(library.root))
        self.refresh()

    def _library_migrated(self, retained, error=''):
        self.emit('notice', {'key': 'migration', 'text': error or (
            '录音已迁移；部分发生变化的旧文件仍保留。' if retained else '录音已迁移到新位置。'), 'error': bool(error)})
        self.changed()
        self._continue_close()

    def _start_task(self, name, action, completed=None):
        if name in self.tasks:
            raise ValueError('相同任务正在处理，请稍候。')
        task = _Task(action, self)
        self.tasks[name] = task
        if completed:
            self.task_callbacks[name] = completed
        task.finished.connect(lambda: Timer.singleShot(0, lambda: self._task_finished(name, task)))
        task.start()
        self.emit(name, {'busy': True})
        return task

    def _task_finished(self, name, task):
        if task.isRunning():
            Timer.singleShot(20, lambda: self._task_finished(name, task))
            return
        self.tasks.pop(name, None)
        if name == 'startup-updates':
            if not self.closing and not task.error and isinstance(task.value, dict) and task.value.get('kind') in ('source', 'package'):
                self.emit('updates', {'busy': False, 'result': task.value})
        elif task.error:
            self.emit(name, {'busy': False, 'error': task.error})
            self.emit('notice', {'text': task.error, 'error': True})
        else:
            self.emit(name, {'busy': False, 'result': task.value})
        callback = self.task_callbacks.pop(name, None)
        if callback:
            callback(task.error)
        task.deleteLater()
        self._continue_close()

    def _selected_models(self):
        values = self.values
        return [{'path': values['asr'] if values['backend'] == 'wlk-whisper' else values['qwen_model'],
                 'kind': 'asr', 'engine': values['backend']},
                {'path': values['llama_model'] if values['translation_engine'] == 'llama' else values['translation'],
                 'kind': 'translation', 'engine': values['translation_engine']}]

    def _selection(self):
        values = self.values
        return dict(backend=values['backend'],
                    asr_model=values['asr'] if values['backend'] == 'wlk-whisper' else values['qwen_model'],
                    translation_engine=values['translation_engine'],
                    translation_model=values['llama_model'] if values['translation_engine'] == 'llama' else values['translation'],
                    translation_device=values['translation_device'])

    def _refresh_models(self):
        if self.closing or self.update_fenced:
            return
        if self.preparation or self.asset_check:
            self.model_refresh.start(100)
            return
        self.check_models()

    def check_models(self):
        if self.asset_check:
            raise ValueError('模型检查正在进行，可取消后重试。')
        from .ui_checks import BackgroundCheck
        selection = self._selection()
        translating = self.values['translate']
        arguments = ['--check', '--selection', json.dumps(selection)]
        if not translating:
            arguments += ['--only', 'asr']
        check = BackgroundCheck('linguaflow.recommended_prepare', arguments, self)
        self.asset_check = check
        self.asset_check_cancelled = False
        def result(value):
            if self.closing or self.asset_check_cancelled:
                return
            if selection != self._selection() or translating != self.values['translate']:
                self.model_refresh.start(100)
            elif isinstance(value, list) and all(isinstance(row, str) for row in value):
                self.asset_selection, self.missing_assets = selection, value
                self.emit('model-check', {'busy': False, 'missing': value,
                                         'message': '所选模型已就绪。' if not value else '所选模型与组件尚需准备。'})
            else:
                message = '模型检查未完成：' + (check.failure_reason or '返回内容不符合预期，请重新检查。')
                self.emit('model-check', {'busy': False, 'error': message})
                self.emit('notice', {'text': message, 'error': True})
        def finished():
            if self.asset_check_cancelled and not self.closing:
                self.emit('model-check', {'busy': False, 'message': '模型检查已取消，已有结果保留。'})
            if self.asset_check is check:
                self.asset_check = None
            check.deleteLater()
            self.changed()
            self._continue_close()
        check.result.connect(result)
        check.completed.connect(finished)
        check.begin()
        self.emit('model-check', {'busy': True, 'message': '正在检查所选模型…'})
        self.changed()

    def cancel_model_check(self):
        if self.asset_check:
            self.asset_check_cancelled = True
            self.asset_check.kill()
            self.emit('model-check', {'busy': True, 'message': '正在取消模型检查…'})

    def model_inventory(self):
        from .model_inventory import inventory
        selected = self._selected_models()
        self._start_task('inventory', lambda: inventory(selected))

    def delete_model(self, identifier):
        self._idle()
        if self.preparation:
            raise ValueError('请先完成或取消模型准备。')
        from .model_inventory import delete_model, inventory
        selected = self._selected_models()
        def remove():
            delete_model(identifier, selected)
            return inventory(selected)
        self._start_task('inventory', remove)

    def update_activity_snapshot(self):
        from .update_workflow import UpdateActivity
        return UpdateActivity(unsaved_edits=self.unsaved_edits,
            recording=self.session is not None or self.state.active,
            unsaved_recording=bool(self.dirty or self.save_error),
            files=any((self.saver.busy, self.exporter.busy, self.migration.busy, self.reader.busy)),
            preparation=self.preparation is not None or self.runtime_action is not None,
            knowledge_closing=bool(self.knowledge and self.knowledge.closing),
            checks=bool(self.tasks or self.asset_check))

    def set_edited(self, dirty):
        if type(dirty) is not bool:
            raise ValueError('无效的编辑状态。')
        self.unsaved_edits = dirty

    def close_update_knowledge(self):
        return self.knowledge is None or self.knowledge.close()

    def fence_for_update(self):
        self.update_fenced = True
        self.model_refresh.stop()
        self.changed()

    def restore_after_update(self):
        if self.runtime is not None and self.runtime.closed:
            self.runtime = None
        self.update_fenced = False
        if not self.closing:
            self._warm_runtime()
        self.changed()

    def on_native_update(self, event):
        if event.get('stage') == 'quit':
            self.close()
        elif event.get('stage') not in ('waiting', 'dismissed'):
            self.emit('updates', event)

    def update_action(self, action):
        if action == 'cancel':
            self.native_updater.cancel()
        elif action == 'cancel_wait':
            self.update_workflow.cancel_wait()
        elif action == 'download':
            if not self.native_updater.download():
                raise ValueError('更新状态已变化，请重新检查。')
        elif action == 'install':
            if not self.native_updater.confirm_install():
                raise ValueError('更新状态已变化，请重新检查。')
        else:
            raise ValueError('更新状态已变化，请重新检查。')

    def check_updates(self, manual=True):
        if self.closing:
            return
        if self.native_updater.installed:
            return self.native_updater.check(manual=manual)
        from .updates import check_updates
        if manual:
            self._start_task('updates', check_updates)
        else:
            self._start_task('startup-updates', check_updates)

    def locate(self, identifier, generation, caption_id=None, seconds=None):
        if type(generation) is not int or generation != self.generation:
            raise ValueError('录音内容已变化，请重新查找。')
        seconds = locate_seconds(self.item, self.captions, identifier, caption_id=caption_id, seconds=seconds)
        if self.state.active or self.session:
            if caption_id is None:
                raise ValueError('录音结束后可定位课堂来源。')
            # Searching live captions remains available, without seeking or
            # changing the future replay position of an active recording.
            return {'page': self.page(locate=caption_id), 'identifier': caption_id}
        if caption_id is None:
            caption_id = next((row.id for row in self.captions.values() if row.start <= seconds < row.end), None)
        self.located_position = round(seconds * 1000)
        # Position an existing player only. Navigating text must not open audio devices.
        if self.player is not None:
            self.player.seek(round(seconds * 1000), play=False)
        self.emit('playback', {'position': round(seconds * 1000), 'caption_id': caption_id, 'seek': True})
        return {'page': self.page(seconds=seconds), 'identifier': caption_id}

    def _player(self):
        self._audio_allowed()
        self._idle()
        if not self.item:
            raise ValueError('请先打开录音。')
        if self.player is None:
            from .playback_controller import PlaybackController
            self.player = PlaybackController(self)
            self.player.command.connect(lambda value: self.emit('audio-command', value))
            self.player.position_changed.connect(lambda value: self.emit('playback', {
                'position': value, 'caption_id': self.player.index.at(value / 1000)}))
            self.player.seeked.connect(lambda value: self.emit('playback', {
                'position': value, 'caption_id': self.player.index.at(value / 1000), 'seek': True}))
            self.player.duration_changed.connect(lambda value: self.emit('playback', {'duration': value}))
            self.player.state_changed.connect(lambda value: self.emit('playback', {'state': value}))
            self.player.failed.connect(lambda value: self.emit('notice', {'text': value, 'error': True}))
            self.player.notice.connect(lambda value: self.emit('notice', {'text': value}))
        if self.player.stream is None:
            check_library_access(self.library, self.item)
            self.player.load(self.library.directory(self.item['id']) / '录音.wav', self.captions.values(),
                             recover_recording=self.item['state'] in ('incomplete', 'recording'))
            if self.located_position is not None:
                self.player.seek(self.located_position, play=False)
            self.player.set_volume(self.playback_volume)
        return self.player

    def playback_event(self, epoch, state, position=0, error=''):
        if self.player is not None:
            self.player.receive(epoch, state, position, error)

    def play(self):
        self._player().toggle()

    def seek(self, milliseconds, play=False):
        if type(play) is not bool:
            raise ValueError('无效的播放请求。')
        if type(milliseconds) not in (int, float) or not math.isfinite(milliseconds) or milliseconds < 0:
            raise ValueError('无效的播放位置。')
        controller = self._player()
        controller.seek(milliseconds, play=play)

    def volume(self, value):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 300:
            raise ValueError('音量必须在 0–300% 之间。')
        self._player().set_volume(value)
        self.playback_volume = value

    def prepare(self, only=None, kind='models', selection=None):
        if kind != 'documents':
            self._idle()
        elif self.update_fenced or self.migration.busy or self.pending_library or self.closing:
            raise ValueError('请等待当前文件操作完成。')
        if self.preparation or self.runtime_action or 'inventory' in self.tasks:
            raise ValueError('已有准备任务正在运行。')
        if only not in (None, 'all', 'asr', 'translation'):
            raise ValueError('无效的准备范围。')
        if kind not in ('models', 'runtime', 'documents') or (kind == 'documents' and not self.values['beta_features']):
            raise ValueError('无效的准备任务，请先启用对应功能。')
        settings = self.settings()
        current = dict(backend=settings.backend,
                         asr_model=settings.asr_model if settings.backend == 'wlk-whisper' else settings.qwen_model,
                         translation_engine=settings.translation_engine,
                         translation_model=settings.llama_model if settings.translation_engine == 'llama' else settings.translation_model,
                         translation_device=settings.translation_device)
        if selection is None:
            selection = current
        elif kind != 'models':
            raise ValueError('无效的模型下载快照。')
        if kind == 'models' and only is None and not settings.translate:
            only = 'asr'
        command = preparation_command(selection, kind=kind, only=only)
        self.cancel_model_check()
        self.preparation_command = command, kind
        self._start_preparation(command, kind)

    def retry_preparation(self):
        if not self.preparation_command or self.preparation_command[1] != 'documents':
            self._idle()
        elif self.update_fenced or self.migration.busy or self.pending_library or self.closing:
            raise ValueError('请等待当前文件操作完成。')
        if self.preparation or not self.preparation_command or not self.preparation_recovery:
            raise ValueError('没有可恢复的准备任务。')
        command, kind = self.preparation_command
        if kind == 'documents' and not self.values['beta_features']:
            raise ValueError('请先启用课程助手 Beta。')
        self._start_preparation(command, kind)

    def _warm_runtime(self):
        if self.no_audio or self.closing or self.update_fenced or self.preparation or self.runtime_action:
            return
        if self.runtime is None:
            from .runtime_preparation import RuntimePreparation
            self.runtime = RuntimePreparation()
        self.runtime.prepare()

    def _retire_runtime(self, completed):
        runtime = self.runtime
        def finished(error):
            if not error and self.runtime is runtime:
                self.runtime = None
            completed(error)
        self._start_task('runtime-release', runtime.close, finished)

    def _start_preparation(self, command, kind):
        if self.runtime is not None and kind != 'documents':
            self.runtime_action = (command, kind)
            self.preparation_status = '正在释放推理环境…'
            def released(error):
                action, self.runtime_action = self.runtime_action, None
                if error:
                    self.preparation_status = '准备未完成：' + error
                    self.preparation_recovery = '重试'
                elif action and not self.closing:
                    self._start_preparation(*action)
                self.changed()
            self._retire_runtime(released)
            self.changed()
            return
        self.preparation_recovery = ''
        self.preparation_status = '正在准备所选模型与组件…'
        self.preparation_workflow.start(lambda: self.preparation.run_command(command),
                                        affects_runtime=kind != 'documents', beta_only=kind == 'documents')
        self.changed()

    def _progress(self, value):
        if not self.preparation or self.preparation.cancelled:
            return
        self.progress = value
        self.changed()

    def _preparation_result(self, value):
        self.emit('diagnostic', value)
        from .preparation_task import preparation_error_message
        self.preparation_status = preparation_error_message(value) if value.startswith('未完成：') else value
        self.changed()

    def _preparation_finished(self, task):
        self.preparation_recovery = '继续准备' if task.cancelled else ('重试' if self.preparation_status.startswith('准备未完成：') else '')
        self.progress = None
        if not self.closing:
            self._warm_runtime()
            self.model_refresh.start(100)
            if 'inventory' not in self.tasks:
                self.model_inventory()
        self.changed()
        self._continue_close()

    def cancel_preparation(self):
        if self.runtime_action:
            self.runtime_action = None
            self.preparation_status = '准备已取消，已完成文件保留。'
            self.preparation_recovery = '继续准备'
            self.changed()
        if self.preparation:
            self.preparation_workflow.cancel()
            self.preparation_status = '正在取消，已完成文件保留…'
            self.changed()

    def attach_knowledge(self):
        from .knowledge.lifecycle import should_attach
        try:
            if should_attach(self.library, self.item, enabled=self.values['beta_features']):
                self.open_knowledge()
        except (OSError, ValueError, RuntimeError) as exc:
            self.emit('notice', {'text': f'课程资料未就绪：{exc}', 'error': True})

    def open_knowledge(self):
        if not self.values['beta_features']:
            raise ValueError('请先在设置中启用课程助手 Beta。')
        if not self.item:
            raise ValueError('请先新建或打开录音。')
        if self.knowledge is None:
            from .knowledge.client import KnowledgeClient
            self.knowledge = KnowledgeClient(self, state=self.knowledge_state)
            self.knowledge.changed.connect(self._knowledge_event)
        if self.knowledge.identifier != self.item['id']:
            self.knowledge_state.reset()
        self.knowledge.open(self.library, self.item, self.captions.values())

    def _knowledge_event(self, value):
        self.emit('knowledge', self.knowledge_state.receive(value))

    def knowledge_image(self, identifier):
        if not self.values['beta_features'] or not self.knowledge or not self.knowledge.connected:
            raise ValueError('课程后台未连接。')
        from .knowledge.files import checked_path
        row = next((row for row in self.knowledge_view.get('blocks', []) if row['id'] == identifier), None)
        filename = (row or {}).get('image_path') or (row or {}).get('preview_image_path')
        if not filename:
            return None
        path = checked_path(self.library.root, Path(filename))
        with path.open('rb') as stream:
            image = stream.read(8 * 1024 * 1024 + 1)
        if len(image) > 8 * 1024 * 1024 or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('课件预览图片无效或超过显示大小限制，请重新准备原页。')
        return 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')

    def knowledge_command(self, operation, values=None):
        allowed = {'view', 'permission', 'import', 'associate', 'credential', 'terms', 'preview', 'extract',
                   'notes', 'organize', 'question', 'edit', 'export', 'cancel'}
        if operation not in allowed or not isinstance(values or {}, dict):
            raise ValueError('不支持的课程操作。')
        if not self.values['beta_features'] or not self.knowledge or not self.knowledge.connected:
            raise ValueError('课程后台未连接，请重新打开课程资料。')
        if not self.item or self.knowledge.identifier != self.item['id']:
            raise ValueError('当前录音已变化，请重新打开课程资料。')
        if self.session and operation in ('import', 'associate', 'terms', 'preview', 'extract', 'organize', 'question'):
            raise ValueError('请先停止录音再修改课程资料。')
        if operation in ('notes', 'organize', 'question') and (self.dirty or self.saver.busy or self.save_error):
            raise ValueError('请等待字幕保存完成，再处理笔记。')
        if (values or {}).keys() & {'operation', 'root', 'identifier', 'epoch'}:
            raise ValueError('课程操作不能更改后台归属。')
        if operation == 'cancel':
            from .knowledge.lifecycle import cancel_task
            return cancel_task(self.knowledge, self.knowledge.operation)
        return self.knowledge.send(operation, **(values or {}))

    def _clock(self):
        if self.native_updater.pending and not self.closing:
            self.update_workflow.try_install()
        if self.session:
            self.emit('clock', {'seconds': self.session.recorded_seconds})

    def close(self):
        if self.dirty and not self.session and not self.saver.busy and self.save_error:
            raise ValueError('保存失败，不能退出。请先重试保存或备份全部文字。')
        self.closing = True
        self.cancel_model_check()
        self.changed()
        Timer.singleShot(0, self._continue_close)
        return {'closing': True}

    def _shutdown_save(self):
        if self.connection_lost and (self.dirty or self.save_error) and not self.saver.busy and self.save_error:
            self._recover_disconnected()
            self.dirty = False
            self.save_error = ''
        self._save()
        return not self.saver.busy and not self.dirty and not self.save_error

    def _shutdown_resources(self):
        self._close_resources()
        return True

    def _runtime_released(self, runtime):
        if self.runtime is runtime:
            self.runtime = None

    def _shutdown_failed(self, error):
        self.status = error
        self.cancel_frontend()
        self.changed()

    def _continue_close(self):
        if not self.closing or not self.shutdown.advance():
            return
        self.model_refresh.stop()
        self._release_lock()
        if self.frontend_handoff:
            from .frontend_switch import launch
            try:
                launch(self.frontend_handoff)
                self.frontend_handoff = None
            except OSError as exc:
                self.closing = False
                self.emit('notice', {'text': f'无法切换界面：{exc}', 'error': True})
                self.changed()
                return
        self.native_updater.close()
        self.emit('closed', {})
        Timer.singleShot(0, Dispatcher.instance().quit)

    def _disconnect(self):
        # The desktop may crash during capture. Stop and save through the normal
        # path; never tear down a running Session or writer to meet a UI timeout.
        if self.connection_lost:
            return
        self.connection_lost = True
        if self.native_updater.shutdown_job is not None:
            self.native_updater.cancel()
        self.closing = True
        self.reader.cancel()
        self.stop()
        self.cancel_preparation()
        self.cancel_model_check()
        self.cancel_migration()
        self._save()
        Timer.singleShot(0, self._continue_close)

    def _recover_disconnected(self):
        from .recording_export import write_recovery
        name = '桌面中断-文字恢复-' + uuid4().hex + '.txt'
        try:
            path = self.library.directory(self.item['id']) / name
            write_recovery({'path': str(path), 'name': self.item['name']}, preview_captions(self.captions, self.preview))
        except (OSError, ValueError):
            # An unwritable recording volume must not discard the only remaining
            # transcript after its UI has crashed. The recovery path is unique.
            directory = Path(tempfile.mkdtemp(prefix='agentscribe-recovery-'))
            path = directory / name
            write_recovery({'path': str(path), 'name': self.item['name']}, preview_captions(self.captions, self.preview))
        sys.stderr.write(f'桌面中断，文字恢复备份：{path}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--persist-library', action='store_true')
    parser.add_argument('--preferences', type=Path)
    parser.add_argument('--no-audio', action='store_true')
    args = parser.parse_args()
    transport = sys.stdout
    # Third-party logging must not corrupt the reserved protocol channel.
    sys.stdout = sys.stderr
    # Windows native NumPy initialization can block while another thread reads
    # piped stdin (numpy/numpy#24290). Initialize before starting IPC on both
    # platforms, rather than first importing it when a recording is opened.
    import numpy  # noqa: F401

    diag.start_logging('desktop-electron')
    diag.install_exception_hooks()
    from .process_platform import hold_installation_mutex
    hold_installation_mutex(installed=packaged())
    app = Dispatcher([])
    if packaged() and sys.platform == 'darwin':
        from .native_dispatch import cocoa_pump
        app.native_pump = cocoa_pump()
    from .frontend_switch import context
    saved = context()
    prefs = (SettingsStore(str(args.preferences), SettingsStore.Format.IniFormat) if args.preferences else
             SettingsStore(saved['preferences'], SettingsStore.Format(saved.get('preferences_format', 1))) if saved.get('preferences') else None)
    service = DesktopService(library_root=args.library or saved.get('library'), prefs=prefs,
                             no_audio=args.no_audio or saved.get('no_audio', False))
    if args.persist_library:
        if not args.library:
            raise ValueError('恢复保存位置需要明确选择目录。')
        previous_root = service.prefs.value('library_directory')
        service.prefs.setValue('library_directory', str(service.library.root))
        service.prefs.sync()
        if service.prefs.status().value != 0:
            service.prefs.setValue('library_directory', previous_root)
            raise OSError('无法保存新位置，请检查配置目录权限。')
    if saved.get('recording'):
        service.open_recording(saved['recording'])
    elif saved.get('draft'):
        service.new_recording(folder_id=saved['draft'].get('folder'), name=saved['draft']['name'])

    def send(value):
        try:
            transport.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
            transport.flush()
        except (BrokenPipeError, OSError):
            service.disconnected.emit()

    service.output.connect(send)

    def read():
        try:
            while line := sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1):
                if len(line) > MAX_REQUEST_BYTES:
                    break
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    value = {}
                service.incoming.emit(value)
        finally:
            service.disconnected.emit()

    reader = Thread(target=read, name='desktop-protocol', daemon=True)
    reader.start()
    send({'event': 'ready', 'data': {'protocol': PROTOCOL}})
    from .resource_monitor import ResourceMonitor, ResourceSampler
    resources = ResourceMonitor(sampler_factory=lambda: ResourceSampler(root_pid=os.getppid()))
    resources.start()
    try:
        return app.exec()
    finally:
        resources.close()
        # Electron acknowledges the closed event by ending its input pipe.
        # Let the reader release stdin before Python finalizes buffered IO.
        reader.join(timeout=5)
        diag.close_logging()


if __name__ == '__main__':
    raise SystemExit(main())
