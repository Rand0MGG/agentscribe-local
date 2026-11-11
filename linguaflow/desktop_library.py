"""DesktopLibrary commands on the single DesktopService owner; no separate business state."""
from dataclasses import asdict
from pathlib import Path

from .library import default_recording_name
from .library_access import check_library_access
from .source_preview import preview_captions
from .transcript import Transcript


class DesktopLibrary:
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
        from .storage_io import Directory, identity
        with Directory(target.parent) as directory:
            parent_identity = identity(directory.info)
        if not self.exporter.busy:
            self.export_errors = []
        self.export_sequence += 1
        item = {'recording_token': (self.generation, self.item['id']), 'path': str(target), 'format': format, 'name': self.item['name'], 'recovery': recovery,
                'state': 'recovery' if recovery else 'export', 'parent_identity': parent_identity}
        self.exporter.submit(write_recovery if recovery else write_export,
                             (-self.export_sequence, str(target)), self.revision, item,
                             preview_captions(self.captions, self.preview))
        self.emit('notice', {'key': 'export', 'text': '正在导出…', 'busy': True})

    def _exported(self, snapshot, _state, error):
        if not error and snapshot.item.get('recovery'):
            from .recording_export import ExportReceipt
            if isinstance(snapshot.result, ExportReceipt):
                self.recovery_receipt = (snapshot, snapshot.result)
            else:
                error = '未取得有效备份回执，请重新备份。'
        if error:
            self._export_failed(snapshot, error)
        else:
            self.changed()

    def _export_failed(self, snapshot, error):
        if self.recovery_receipt and self.recovery_receipt[0].token == snapshot.token:
            self.recovery_receipt = None
        self.export_errors.append(f"{Path(snapshot.item['path']).name}：{error}")
        self.changed()

    def _exports_finished(self):
        self.emit('notice', {'key': 'export', 'text': '导出失败：' + '；'.join(self.export_errors)
                            if self.export_errors else '导出完成', 'error': bool(self.export_errors)})

    def _recovery_ready(self):
        receipt = self.recovery_receipt
        return bool(receipt and self.item and not self.session and not self.saver.busy and not self.exporter.busy and self.dirty
                    and self.save_error and receipt[0].item.get('recording_token') == (self.generation, self.item['id'])
                    and receipt[0].revision == self.revision)

    def close_recovered(self):
        if not self._recovery_ready():
            raise ValueError('录音内容已变化，请先停止并重新备份全部文字。')
        from .recording_export import check_export
        snapshot, receipt = self.recovery_receipt
        check_export(snapshot.item['path'], receipt)
        if not self.recording.release_lock(recovered=True):
            raise ValueError('录音仍在处理，请等待完成后重试关闭。')
        self.autosave.stop()
        self._select(None)
        self.refresh()

    def recording_path(self, identifier=None):
        if identifier is not None:
            item = self._find(identifier)
            return str(self.library.directory(item['id']))
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
