"""Electron's local JSON-lines service. Owns business resources, never creates widgets.

Requests and events are dispatched on the Qt core event loop so existing Session,
RecordingSaver and process ownership rules remain usable during the UI migration.
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

from PySide6.QtCore import QCoreApplication, QObject, QSettings, Qt, QThread, QTimer, Signal

from . import diagnostic_log as diag
from .core import LANGUAGES, Settings, translation_status
from .library import default_recording_name
from .library_access import (
    acquire_library_migration_lock,
    acquire_recording_lock,
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
from .recording_save import RecordingSaver
from .recording_state import RecordingState
from .runtime_paths import packaged, resource_root
from .source_preview import preview_captions
from .transcript import Transcript
from .translation_config import CONTEXT_COUNTS

PROTOCOL = 1
MAX_REQUEST_BYTES = 1024 * 1024


class _Task(QThread):
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


class DesktopService(QObject):
    """One recording owner. No Window object, UI control proxy or browser dependency."""
    incoming = Signal(object)
    disconnected = Signal()
    output = Signal(dict)

    def __init__(self, *, library_root=None, prefs=None, no_audio=False):
        super().__init__()
        self.prefs = prefs if prefs is not None else QSettings('LinguaFlow', 'LocalCaptions')
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
        self.captions = Transcript()
        self.preview = None
        self.preview_sequence = 0
        self.pending_source_revision = None
        self.session = None
        self.recording_lock = None
        self.state = RecordingState.IDLE
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
        self.preparation = None
        self.preparation_command = None
        self.preparation_recovery = ''
        self.asset_check = None
        self.asset_selection = None
        self.missing_assets = None
        self.asset_check_cancelled = False
        self.model_refresh = QTimer(self)
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
        self.migration_locks = []
        self.migration_source = None
        from .library_migration import LibraryMigration
        self.migration = LibraryMigration(self)
        self.migration.progress.connect(lambda value: self.emit('migration', {'busy': True, 'progress': value}))
        self.migration.copied.connect(self._library_copied)
        self.migration.cleaned.connect(self._library_migrated)
        self.preparation_status = ''
        self.progress = None
        self.knowledge = None
        self.player = None
        self.saver = RecordingSaver(self)
        self.saver.completed.connect(self._saved)
        self.saver.idle.connect(self._release_lock)
        self.saver.idle.connect(self._continue_close)
        self.exporter = RecordingSaver(self)
        self.export_sequence = 0
        self.export_errors = []
        self.recovery_receipt = None
        self.knowledge_view = {}
        self.exporter.completed.connect(self._exported)
        self.exporter.idle.connect(self._exports_finished)
        self.exporter.idle.connect(self._continue_close)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self._save)
        self.incoming.connect(self.dispatch, Qt.ConnectionType.QueuedConnection)
        self.disconnected.connect(self._disconnect, Qt.ConnectionType.QueuedConnection)
        self.clock = QTimer(self)
        self.clock.setInterval(500)
        self.clock.timeout.connect(self._clock)
        self.clock.start()
        QTimer.singleShot(0, self._warm_runtime)
        self.routes = {name: method for name, method in (
            ('bootstrap', self.bootstrap), ('settings.set', self.set_settings),
            ('library.refresh', self.refresh), ('recording.open', self.open_recording),
            ('recording.new', self.new_recording), ('folder.create', self.create_folder),
            ('item.rename', self.rename), ('item.move', self.move), ('item.trash', self.trash),
            ('trash.list', self.deleted), ('trash.restore', self.restore), ('trash.purge', self.purge),
            ('captions.page', self.page), ('captions.search', self.search),
            ('recording.save', self.retry_save), ('recording.export', self.export),
            ('recording.close_recovered', self.close_recovered),
            ('audio.refresh', self.refresh_devices), ('audio.select', self.select_device),
            ('recording.start', self.start), ('recording.stop', self.stop), ('recording.pause', self.pause),
            ('playback.toggle', self.play), ('playback.seek', self.seek), ('playback.volume', self.volume),
            ('models.prepare', self.prepare), ('models.cancel', self.cancel_preparation),
            ('models.retry', self.retry_preparation),
            ('models.check', self.check_models), ('models.cancel_check', self.cancel_model_check),
            ('models.inventory', self.model_inventory), ('models.delete', self.delete_model),
            ('updates.check', self.check_updates), ('library.migrate', self.migrate_library),
            ('library.cancel_migration', self.cancel_migration),
            ('knowledge.open', self.open_knowledge), ('knowledge.command', self.knowledge_command),
            ('knowledge.image', self.knowledge_image),
            ('app.close', self.close), ('path.recording', self.recording_path),
            ('frontend.prepare', self.prepare_frontend), ('frontend.ready', self.mark_frontend_ready),
            ('frontend.cancel', self.cancel_frontend),
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
        return {'item': self.item, 'draft': self.draft, 'state': self.state.name, 'status': self.status,
                'failure': self.failure, 'save_error': self.save_error,
                'saving': self.saver.busy, 'dirty': self.dirty, 'generation': self.generation,
                'revision': self.revision, 'count': len(self.captions), 'preview': self.preview,
                'preparing': self.preparation is not None or self.runtime_action is not None, 'preparation_status': self.preparation_status,
                'preparation_cancelling': bool(self.preparation and self.preparation.cancelled),
                'preparation_recovery': self.preparation_recovery,
                'checking_models': self.asset_check is not None,
                'model_missing': self.missing_assets if self.asset_selection == self._selection() else None,
                'translation_available': not (self.asset_selection == self._selection() and self.missing_assets
                                             and any(row.startswith('翻译') for row in self.missing_assets)),
                'progress': self.progress, 'closing': self.closing, 'has_audio': self.has_audio, 'playback': {**self.playback_metadata, 'volume': self.playback_volume}, 'translating': self.translating,
                'migrating': self.migration.busy or bool(self.pending_library),
                'recovery_ready': self._recovery_ready()}

    def changed(self):
        self.emit('state', self.snapshot())

    def bootstrap(self):
        from . import __version__
        from .translation_models import HY_GENERATION, NLLB_GENERATION
        return {'version': __version__, 'protocol': PROTOCOL, 'platform': sys.platform, 'installed': packaged(), 'no_audio': self.no_audio,
                'settings': self.values, 'library': self.library.index, 'root': str(self.library.root),
                'state': self.snapshot(), 'captions': self.page(), 'devices': self.devices, 'device': self.device,
                'options': {'languages': LANGUAGES, 'backends': asr_backends(), 'devices': asr_devices(),
                            'models': {key: model_catalog(key) for key in (*asr_backends(), 'llama', 'pytorch')},
                            'translation_devices': {key: translation_devices(key) for key in ('llama', 'pytorch')},
                            'recommended': recommended_selection(), 'downloads': download_catalog(),
                            'generation': {'hy': f"HY-MT2 生成参数 · 最大 {HY_GENERATION['max_new_tokens']} tokens · 温度 {HY_GENERATION['temperature']} · top-p {HY_GENERATION['top_p']} · top-k {HY_GENERATION['top_k']} · 重复惩罚 {HY_GENERATION['repetition_penalty']}\n初译参考前后各 1 段；定稿参考前 5 段、后 1 段。仅使用已有的定稿原文。",
                                           'nllb': f"NLLB 生成参数 · 最大 {NLLB_GENERATION['max_new_tokens']} tokens · beams {NLLB_GENERATION['num_beams']}\n逐段翻译；单段输入最多 512 tokens，超长时保留原文并提示。"}}}

    def mark_frontend_ready(self):
        if not self.frontend_ready:
            from .frontend_switch import ready
            ready('electron', self.prefs)
            self.frontend_ready = True

    def cancel_frontend(self):
        self.frontend_handoff = None

    def prepare_frontend(self, owner_pid, geometry, updates=False):
        self._idle()
        if self.preparation or self.tasks or self.closing or self.knowledge_view.get('busy'):
            raise ValueError('请先完成或取消当前后台任务，再切换界面。')
        from .frontend_switch import prepare
        self.frontend_handoff = prepare('qt', library=self.library, prefs=self.prefs,
            recording=self.item['id'] if self.item else None, draft=self.draft,
            no_audio=self.no_audio, owner_pid=owner_pid, geometry=geometry, purpose='updates' if updates else None)
        return {'ready': True}

    def _idle(self):
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
        if active_current:
            if not self.recording_lock or self.saver.waiting or self.migration.busy:
                raise ValueError('当前录音正在处理文件，请稍后重试。')
            self._save()
            if not self.saver.flush() or self.dirty or self.save_error:
                raise ValueError('请等待字幕成功保存后再改名。')
        else:
            self._edit_item(item)
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
        if self.migration.busy or self.closing or self.reader.busy:
            raise ValueError('正在迁移或退出，请稍后重试。')
        check_library_migration(self.library.root)
        if self.session and self.item:
            current, target = self.library.directory(self.item['id']), self.library.directory(item['id'])
            if current == target or target in current.parents:
                raise ValueError('请先停止录音再移动或删除当前录音及其文件夹。')
        else:
            self._idle()
            self._close_resources()
        check_library_access(self.library, item)

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
        ids = self.captions.ordered_ids
        if seconds is not None:
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError('无效的字幕时间。')
            locate = next((key for key in ids if self.captions[key].start <= seconds < self.captions[key].end), None)
        if locate is not None:
            start = (ids.index(locate) // 200) * 200 if locate in ids else 0
        elif start is None:
            start = max(0, len(ids) - 200)
        if type(start) is not int or start < 0:
            raise ValueError('无效的字幕分页。')
        start = min(start, max(0, len(ids) - 1))
        return {'generation': self.generation, 'revision': self.revision, 'start': start,
                'total': len(ids), 'rows': [caption_value(self.captions[key]) for key in ids[start:start+200]]}

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
        if self.prefs.status() != QSettings.Status.NoError:
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
        from .audio_processing.config import automatic_audio_config
        values = self.values
        language = next((row for row in LANGUAGES if row[0] == values['source']), (None, None, None))
        target = next((row[2] for row in LANGUAGES if row[0] == values['target']), 'zho_Hans')
        compute = {'CPU（通用）': 'cpu', 'NVIDIA GPU · 半精度': 'cuda',
                   'Apple GPU · Metal / MLX': 'mlx'}.get(values['compute'], values['compute'])
        device = self.device or ('', False)
        return Settings(device_id=device[0], loopback=device[1], asr_model=values['asr'].strip(),
                        asr_device=compute, translation_model=values['translation'].strip(),
                        source=language[1], source_nllb=language[2], target=target, input_sample_rate=48000,
                        audio_processing=automatic_audio_config(), **{key: values[key] for key in (
                            'translate', 'backend', 'qwen_model', 'llama_model', 'translation_engine',
                            'translation_device', 'translation_before', 'translation_after',
                            'translation_initial_before', 'update_seconds', 'draft_seconds', 'endpoint_seconds')})

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
        from .audio import list_devices
        self.devices = [asdict(row) for row in list_devices()]
        self.emit('devices', self.devices)
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
        return self.device

    def start(self):
        self._audio_allowed()
        self._idle()
        if self.preparation or self.runtime_action or 'inventory' in self.tasks:
            raise ValueError('模型准备中，请完成或取消后再开始。')
        if self.runtime is not None and self.runtime.closed:
            raise ValueError('推理环境尚未安全释放，请重试修复运行环境或关闭应用。')
        if not self.device or not any(row['id'] == self.device[0] and row['loopback'] == self.device[1] for row in self.devices):
            raise ValueError('请刷新并选择音频来源。')
        self.cancel_model_check()
        from .wlk_session import Session
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
        self.recording_lock = acquire_recording_lock(self.library.directory(self.item['id']))
        try:
            self.library.begin(self.item, asdict(settings))
            self._select(self.item)
            self.translating = settings.translate
            self.state = RecordingState.STARTING
            session = Session(settings, self, runtime=self.runtime, recording_path=self.library.directory(self.item['id']) / '录音.wav')
            self.session = session
            session.status.connect(self._status)
            session.stage.connect(lambda name, value: self.emit('stage', {'name': name, 'value': value}))
            session.ready.connect(self._ready)
            session.paused.connect(self._paused)
            session.caption.connect(self._caption)
            session.source_preview.connect(self._preview)
            session.source_changed.connect(self._source_changed)
            session.level.connect(self._level)
            session.failure.connect(self._failed)
            session.finished.connect(lambda: QTimer.singleShot(0, lambda: self._finished(session)))
            session.start()
        except Exception:
            self.session = None
            self.state = RecordingState.IDLE
            self.recording_lock.unlock()
            self.recording_lock = None
            raise
        self.changed()
        return self.snapshot()

    def _ready(self):
        if self.session and not self.failure and self.state != RecordingState.STOPPING:
            self.status = '正在聆听' if self.state == RecordingState.LISTENING else self.status
            self.emit('model-loading', {'busy': False})
            self.changed()

    def _source_changed(self, revision):
        if self.session and self.state == RecordingState.STARTING and not self.failure:
            self.state = RecordingState.LISTENING
            self.status = '录音已开始' if not self.session.model_ready.is_set() else '正在聆听'
            self.emit('model-loading', {'busy': not self.session.model_ready.is_set()})
            self.changed()
        if revision == self.pending_source_revision:
            self.pending_source_revision = None

    def _level(self, value):
        self.emit('level', value if self.state == RecordingState.LISTENING and self.pending_source_revision is None else 0)

    def stop(self):
        if self.session and self.state.can_stop:
            self.state = RecordingState.STOPPING
            self.emit('model-loading', {'busy': False})
            self.session.stop()
            self.changed()

    def pause(self):
        if self.session and not self.failure:
            if self.state == RecordingState.LISTENING and self.session.pause():
                self.state = RecordingState.PAUSING
            elif self.state == RecordingState.PAUSED and self.session.resume():
                self.state = RecordingState.RESUMING
            self.changed()

    def _paused(self, paused):
        expected = RecordingState.PAUSING if paused else RecordingState.RESUMING
        if self.state == expected and self.session and not self.failure:
            self.state = RecordingState.PAUSED if paused else RecordingState.LISTENING
            self.status = '已暂停聆听' if paused else '正在聆听'
            if paused:
                self.emit('level', 0)
            self.changed()

    def _status(self, value):
        self.emit('diagnostic', value)
        # Loading/catch-up diagnostics must not replace the capture fact shown
        # in the island or create repeated notifications.

    def _failed(self, value):
        self.emit('model-loading', {'busy': False})
        self.failure = value
        self.status = '识别未完成，已有录音和字幕会保留。'
        self.changed()

    def _caption(self, caption):
        previous = self.captions.get(caption.id)
        if previous and (caption.revision < previous.revision or
                         caption.revision == previous.revision and caption.source != previous.source):
            return
        if (caption.source and previous and previous.source == caption.source
                and previous.language == caption.language and not caption.translation and (caption.ready or caption.final)):
            caption = replace(caption, translation=previous.translation, translation_source=previous.translation_source,
                              translation_phase=previous.translation_phase)
        if caption.source:
            self.captions[caption.id] = caption
        elif caption.id in self.captions:
            del self.captions[caption.id]
        self.revision += 1
        self.dirty = True
        self.emit('caption', {'generation': self.generation, 'revision': self.revision,
                              'caption': caption_value(caption), 'total': len(self.captions)})
        if self.knowledge and self.item and self.knowledge.identifier == self.item['id']:
            self.knowledge.observe(caption)
        if not self.autosave.isActive():
            self.autosave.start(1500)

    def _preview(self, event):
        if not self.session or not self.state.active:
            return
        sequence = event['sequence']
        if event.get('done'):
            if self.preview is None or sequence != self.preview_sequence:
                return
            self.preview = None
        else:
            if sequence <= self.preview_sequence:
                return
            self.preview, self.preview_sequence = event, sequence
        self.revision += 1
        self.dirty = True
        self._save()
        self.changed()

    def _finished(self, session):
        if self.session is not session:
            return
        if session.isRunning():
            QTimer.singleShot(20, lambda: self._finished(session))
            return
        if self.preview:
            rows = preview_captions(self.captions, self.preview)
            self.captions = Transcript((row.id, row) for row in rows)
            self.preview = None
            self._failed('原文分句未完成，最新识别结果已作为草稿保留，请对照录音。')
        if self.translating:
            for row in list(self.captions.values()):
                if row.final and (not row.translation or row.translation_phase == 'initial') and not row.error:
                    self._caption(replace(row, error='会话已结束，此条翻译未完成'))
        incomplete = self.failure or self.translating and any(
            row.source and (row.error or not row.translation or row.translation_phase == 'initial')
            for row in self.captions.values())
        self.session = None
        session.deleteLater()
        audio = self.library.directory(self.item['id']) / '录音.wav'
        self.has_audio = audio.is_file() and audio.stat().st_size > 44
        self.state = RecordingState.IDLE
        self.status = '正在保存录音与字幕…'
        self.revision += 1
        self.dirty = True
        self._save('incomplete' if incomplete else 'complete')
        self.emit('captions', self.page())
        self.changed()

    def _save(self, state=None):
        if not self.item or not self.dirty and state is None:
            return
        if state is not None:
            self.save_target = state
        self.saver.submit(self.library.save, (self.generation, self.item['id']), self.revision, self.item,
                          preview_captions(self.captions, self.preview), self.save_target)

    def _saved(self, snapshot, state, error):
        if not self.item or snapshot.token != (self.generation, self.item['id']):
            return
        if error:
            self.save_error = error
            self.dirty = True
            self.status = '保存失败，请重试保存；已有文字仍保留。'
        else:
            self.item['state'] = state
            if self.knowledge and self.knowledge.identifier == self.item['id']:
                self.knowledge.saved(snapshot.captions, final=state in ('complete', 'incomplete'))
            if snapshot.revision == self.revision and (self.save_target is None or self.save_target == state):
                self.dirty = False
                self.save_error = ''
                self.save_target = None
                if not self.session:
                    self.status = '已保存录音与字幕'
                    self.refresh()
                    if self.pending_library and not self.closing:
                        QTimer.singleShot(0, self._begin_pending_migration)
        self.changed()

    def retry_save(self):
        self._save()
        self.changed()

    def _release_lock(self):
        if self.recording_lock and not self.session and not self.saver.busy and not self.dirty and not self.save_error:
            self.recording_lock.unlock()
            self.recording_lock = None
            if self.item and 'pending_name' in self.item:
                try:
                    self._close_resources()
                    self.library.rename(self.item, self.item['pending_name'])
                    self.refresh()
                    self.changed()
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

    def recording_path(self):
        return str(self.library.directory(self.item['id']) if self.item else self.library.root)

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
        try:
            self.migration_locks.append(acquire_library_migration_lock(self.library.root))
            self.library.refresh()
            for item in self.library.index['sessions']:
                self.migration_locks.append(acquire_recording_lock(self.library.directory(item['id'])))
            self.migration_source = self.library
            self.migration.start(self.library, path)
        except Exception:
            self._release_migration_locks()
            raise
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

    def _release_migration_locks(self):
        for lock in self.migration_locks:
            lock.unlock()
        self.migration_locks = []
        self.migration_source = None

    def _library_copied(self, library, verified, error):
        if error:
            self.emit('notice', {'key': 'migration', 'text': '迁移未完成，原录音保留：' + error, 'error': True})
            self._release_migration_locks()
            self.changed()
            self._continue_close()
            return
        old_root = self.library.root
        self.prefs.setValue('library_directory', str(library.root))
        self.prefs.sync()
        if self.prefs.status() != QSettings.Status.NoError:
            self.prefs.setValue('library_directory', str(old_root))
            self.emit('notice', {'key': 'migration', 'text': '新位置无法保存到设置，原录音保留；新位置已有校验副本。', 'error': True})
            self._release_migration_locks()
            self.changed()
            self._continue_close()
            return
        self.library = library
        if self.item:
            self.item = self._find(self.item['id'], folders=False)
        self.emit('library-root', str(library.root))
        self.refresh()
        self.migration.cleanup(old_root, verified)

    def _library_migrated(self, retained):
        self._release_migration_locks()
        self.emit('notice', {'key': 'migration', 'text': '录音已迁移；部分发生变化的旧文件仍保留。' if retained else '录音已迁移到新位置。'})
        self.changed()
        self._continue_close()

    def _start_task(self, name, action, completed=None):
        if name in self.tasks:
            raise ValueError('相同任务正在处理，请稍候。')
        task = _Task(action, self)
        self.tasks[name] = task
        if completed:
            self.task_callbacks[name] = completed
        task.finished.connect(lambda: QTimer.singleShot(0, lambda: self._task_finished(name, task)))
        task.start()
        self.emit(name, {'busy': True})

    def _task_finished(self, name, task):
        if task.isRunning():
            QTimer.singleShot(20, lambda: self._task_finished(name, task))
            return
        self.tasks.pop(name, None)
        if task.error:
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
        if self.closing:
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

    def check_updates(self):
        from .updates import check_updates
        self._start_task('updates', check_updates)

    def _player(self):
        self._audio_allowed()
        self._idle()
        if not self.item:
            raise ValueError('请先打开录音。')
        if self.player is None:
            from .playback_controller import PlaybackController
            self.player = PlaybackController(self)
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
            self.player.set_volume(self.playback_volume)
        return self.player

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
        self._idle()
        if self.preparation or self.runtime_action or 'inventory' in self.tasks:
            raise ValueError('已有准备任务正在运行。')
        if only not in (None, 'all', 'asr', 'translation'):
            raise ValueError('无效的准备范围。')
        if kind not in ('models', 'runtime', 'documents') or (kind == 'documents' and not self.values['beta_features']):
            raise ValueError('无效的准备任务，请先启用对应功能。')
        from .runtime_paths import installation_command
        settings = self.settings()
        current = dict(backend=settings.backend,
                         asr_model=settings.asr_model if settings.backend == 'wlk-whisper' else settings.qwen_model,
                         translation_engine=settings.translation_engine,
                         translation_model=settings.llama_model if settings.translation_engine == 'llama' else settings.translation_model,
                         translation_device=settings.translation_device)
        if selection is None:
            selection = current
        elif kind != 'models' or not isinstance(selection, dict) or set(selection) != set(current):
            raise ValueError('无效的模型下载快照。')
        else:
            if (any(not isinstance(value, str) or not value.strip() or len(value) > 4096 for value in selection.values())
                    or selection['backend'] not in asr_backends()
                    or selection['translation_engine'] not in ('llama', 'pytorch')
                    or selection['translation_device'] not in translation_devices(selection['translation_engine'])):
                raise ValueError('模型或计算设备不适用于当前平台。')
            if selection['backend'] == 'qwen3-streaming' and selection['asr_model'].startswith('mlx-community/'):
                raise ValueError('MLX 权重需要 Apple Silicon Mac 的 MLX 引擎。')
            if selection['translation_engine'] == 'llama' and selection['translation_model'].startswith('hf://'):
                from .llama_assets import hub_gguf
                hub_gguf(selection['translation_model'])
            selection = dict(selection)
        if kind == 'models' and only is None and not settings.translate:
            only = 'asr'
        if kind == 'runtime':
            command = installation_command('linguaflow.runtime_install', 'all', '--maintain', '--selection', json.dumps(selection))
        elif kind == 'documents':
            command = installation_command('linguaflow.document_install')
        else:
            command = installation_command('linguaflow.recommended_prepare', '--selection', json.dumps(selection))
        if only in ('asr', 'translation') and kind == 'models':
            command += ['--only', only]
        self.cancel_model_check()
        self.preparation_command = command, kind
        self._start_preparation(command, kind)

    def retry_preparation(self):
        self._idle()
        if self.preparation or not self.preparation_command or not self.preparation_recovery:
            raise ValueError('没有可恢复的准备任务。')
        command, kind = self.preparation_command
        if kind == 'documents' and not self.values['beta_features']:
            raise ValueError('请先启用课程助手 Beta。')
        self._start_preparation(command, kind)

    def _warm_runtime(self):
        if self.no_audio or self.closing or self.preparation or self.runtime_action:
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
        from .preparation_task import Preparation
        task = Preparation(lambda: task.run_command(command), self,
                           affects_runtime=kind != 'documents', beta_only=kind == 'documents')
        self.preparation = task
        self.preparation_recovery = ''
        self.preparation_status = '正在准备所选模型与组件…'
        task.download.connect(self._progress)
        task.result.connect(self._preparation_result)
        task.finished.connect(lambda: QTimer.singleShot(0, lambda: self._preparation_finished(task)))
        task.start()
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
        if task.isRunning():
            QTimer.singleShot(20, lambda: self._preparation_finished(task))
            return
        if self.preparation is task:
            self.preparation_recovery = '继续准备' if task.cancelled else ('重试' if self.preparation_status.startswith('准备未完成：') else '')
            self.preparation = None
            self.progress = None
            if not self.closing:
                self._warm_runtime()
                self.model_refresh.start(100)
                if 'inventory' not in self.tasks:
                    self.model_inventory()
        task.deleteLater()
        self.changed()
        self._continue_close()

    def cancel_preparation(self):
        if self.runtime_action:
            self.runtime_action = None
            self.preparation_status = '准备已取消，已完成文件保留。'
            self.preparation_recovery = '继续准备'
            self.changed()
        if self.preparation:
            self.preparation.cancel()
            self.preparation_status = '正在取消，已完成文件保留…'
            self.changed()

    def open_knowledge(self):
        if not self.values['beta_features']:
            raise ValueError('请先在设置中启用课程助手 Beta。')
        if not self.item:
            raise ValueError('请先新建或打开录音。')
        if self.knowledge is None:
            from .knowledge.client import KnowledgeClient
            self.knowledge = KnowledgeClient(self)
            self.knowledge.changed.connect(self._knowledge_event)
        if self.knowledge.identifier != self.item['id']:
            self.knowledge_view = {}
        self.knowledge.open(self.library, self.item, self.captions.values() if self.session else None)

    def _knowledge_event(self, value):
        if value.get('type') == 'view':
            self.knowledge_view.update(value)
            # The existing worker emits partial views after the initial
            # snapshot. A newly mounted renderer still needs the full course.
            value = dict(self.knowledge_view)
        self.emit('knowledge', value)

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
        return self.knowledge.send(operation, **(values or {}))

    def _clock(self):
        if self.session:
            self.emit('clock', {'seconds': self.session.recorded_seconds})

    def close(self):
        if self.dirty and not self.session and not self.saver.busy and self.save_error:
            raise ValueError('保存失败，不能退出。请先重试保存或备份全部文字。')
        self.closing = True
        self.reader.cancel()
        self.stop()
        self.cancel_preparation()
        self.cancel_model_check()
        self.cancel_migration()
        self._save()
        self.changed()
        QTimer.singleShot(0, self._continue_close)
        return {'closing': True}

    def _continue_close(self):
        if (not self.closing or self.session or self.saver.busy or self.exporter.busy
                or self.preparation or self.tasks or self.migration.busy or self.reader.busy or self.asset_check):
            return
        if self.dirty or self.save_error:
            if self.connection_lost:
                self._recover_disconnected()
                self.dirty = False
                self.save_error = ''
                self._continue_close()
                return
            self.closing = False
            self.cancel_frontend()
            self.changed()
            return
        try:
            self._close_resources()
        except ValueError as exc:
            self.closing = False
            self.status = str(exc)
            self.cancel_frontend()
            self.changed()
            return
        if self.runtime is not None:
            def released(error):
                if error:
                    self.closing = False
                    self.cancel_frontend()
                    self.status = '推理环境未能退出，请重试关闭：' + error
                    self.changed()
            self._retire_runtime(released)
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
        self.emit('closed', {})
        QTimer.singleShot(0, QCoreApplication.instance().quit)

    def _disconnect(self):
        # The desktop may crash during capture. Stop and save through the normal
        # path; never tear down a running Session or writer to meet a UI timeout.
        if self.connection_lost:
            return
        self.connection_lost = True
        self.closing = True
        self.reader.cancel()
        self.stop()
        self.cancel_preparation()
        self.cancel_model_check()
        self.cancel_migration()
        self._save()
        QTimer.singleShot(0, self._continue_close)

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
    diag.start_logging('desktop-electron')
    diag.install_exception_hooks()
    from .process_platform import hold_installation_mutex
    hold_installation_mutex(installed=packaged())
    app = QCoreApplication([])
    from .frontend_switch import context
    saved = context()
    prefs = (QSettings(str(args.preferences), QSettings.Format.IniFormat) if args.preferences else
             QSettings(saved['preferences'], QSettings.Format(saved.get('preferences_format', 1))) if saved.get('preferences') else None)
    service = DesktopService(library_root=args.library or saved.get('library'), prefs=prefs,
                             no_audio=args.no_audio or saved.get('no_audio', False))
    if args.persist_library:
        if not args.library:
            raise ValueError('恢复保存位置需要明确选择目录。')
        previous_root = service.prefs.value('library_directory')
        service.prefs.setValue('library_directory', str(service.library.root))
        service.prefs.sync()
        if service.prefs.status() != QSettings.Status.NoError:
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
        diag.close_logging()


if __name__ == '__main__':
    raise SystemExit(main())
