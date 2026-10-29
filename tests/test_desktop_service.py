"""The Electron boundary must preserve the existing durable recording contracts."""
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from threading import Event

import pytest

from linguaflow.audio import Device
from linguaflow.core import Caption
from linguaflow.desktop_service import DesktopService
from linguaflow.events import Dispatcher as QCoreApplication
from linguaflow.events import Owner as QObject
from linguaflow.events import Signal
from linguaflow.library_access import acquire_recording_lock
from linguaflow.settings_store import SettingsStore as QSettings


@pytest.fixture
def desktop(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    service = DesktopService(library_root=tmp_path / '中文 录音',
                             prefs=QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat), no_audio=True)
    yield service
    service.model_refresh.stop()
    service.cancel_model_check()
    deadline = time.monotonic() + 5
    while service.saver.busy or service.exporter.busy or service.migration.busy or service.tasks or service.reader.busy or service.asset_check or service.shutdown.release_job:
        app.process()
        assert time.monotonic() < deadline
        time.sleep(.005)
    service.shutdown.timer.stop()
    service.clock.stop()
    service.autosave.stop()
    if service.recording_lock:
        service.recording_lock.unlock()
    service.deleteLater()
    app.process()


def drain(service):
    deadline = time.monotonic() + 5
    while service.saver.busy or service.exporter.busy or service.migration.busy or service.tasks or service.reader.busy or service.shutdown.release_job:
        QCoreApplication.instance().process()
        assert time.monotonic() < deadline
        time.sleep(.005)


@pytest.mark.p2
def test_sidebar_width_is_validated_and_persisted_without_changing_model_settings(desktop):
    original = dict(desktop.values)
    assert desktop.bootstrap()['layout']['sidebar_width'] is None
    assert desktop.set_sidebar_width(320) == 320
    assert desktop.bootstrap()['layout']['sidebar_width'] == 320
    assert desktop.prefs.value('electron_sidebar_width', type=int) == 320
    for invalid in (True, None, '320', 179, 421):
        with pytest.raises(ValueError, match='宽度'):
            desktop.set_sidebar_width(invalid)
    assert desktop.values == original


@pytest.mark.p0
def test_reveal_path_accepts_only_library_identifiers_without_switching_recording(desktop):
    desktop._create_recording(name='当前录音')
    current = desktop.item
    folder = desktop.library.folder('另一个文件夹')
    other = desktop.library.create(folder['id'], {}, '另一个录音')
    assert desktop.recording_path(other['id']) == str(desktop.library.directory(other['id']))
    assert desktop.recording_path(folder['id']) == str(desktop.library.directory(folder['id']))
    for invalid in ('../outside', str(desktop.library.root.parent), 'missing'):
        with pytest.raises(ValueError):
            desktop.recording_path(invalid)
    assert desktop.item == current


@pytest.mark.p1
@pytest.mark.parametrize('previous,available', [(None, True), (('missing', False), True), (('missing', False), False)])
def test_source_refresh_selects_only_first_use_and_reports_current_selection(desktop, monkeypatch, previous, available):
    desktop.device = previous
    monkeypatch.setattr(desktop, '_audio_allowed', lambda: None)
    monkeypatch.setattr('linguaflow.audio.discover_devices', lambda: [Device('fixture', '隔离输入', False)] if available else [])
    replies = []
    desktop.output.connect(replies.append)
    desktop.refresh_devices()
    assert desktop.bootstrap()['audio_refreshing']
    drain(desktop)
    assert not desktop.bootstrap()['audio_refreshing']
    assert desktop.device == (('fixture', False) if previous is None and available else previous)
    assert any(row.get('event') == 'device' and row['data'] == desktop.device for row in replies)


@pytest.mark.p1
def test_desktop_course_partial_views_keep_reopen_context(desktop):
    events = []
    desktop.output.connect(events.append)
    desktop._knowledge_event({'type': 'view', 'course': {'id': 'course', 'terms': [{'canonical': 'Context'}]},
                              'blocks': [{'id': 'page-1'}], 'busy': False})
    desktop._knowledge_event({'type': 'view', 'busy': True, 'notes': []})
    value = events[-1]['data']
    assert value['course']['terms'][0]['canonical'] == 'Context'
    assert value['blocks'][0]['id'] == 'page-1' and value['busy']


@pytest.mark.p1
def test_desktop_model_check_cancel_failure_and_stale_result_keep_known_assets(desktop, monkeypatch):
    class Check(QObject):
        result = Signal(object)
        completed = Signal()
        failure_reason = '检查进程异常结束'

        def __init__(self, module, arguments, parent):
            super().__init__(parent)
            self.killed = False

        def begin(self):
            pass

        def kill(self):
            self.killed = True

    monkeypatch.setattr('linguaflow.ui_checks.BackgroundCheck', Check)
    events = []
    desktop.output.connect(events.append)
    desktop.check_models()
    check = desktop.asset_check
    check.result.emit([])
    check.completed.emit()
    assert desktop.missing_assets == []
    desktop.check_models()
    check = desktop.asset_check
    desktop.cancel_model_check()
    assert check.killed and desktop.asset_check is check  # Wait for actual exit.
    check.result.emit(['识别模型：迟到的缺失结果'])
    check.completed.emit()
    assert desktop.missing_assets == [] and desktop.asset_check is None
    desktop.check_models()
    check = desktop.asset_check
    check.result.emit(None)
    check.completed.emit()
    assert desktop.missing_assets == []
    assert any('检查未完成' in row.get('data', {}).get('error', '') for row in events if isinstance(row.get('data'), dict))
    desktop.check_models()
    check = desktop.asset_check
    desktop.set_settings({'translate': not desktop.values['translate']})
    check.result.emit(['翻译模型：旧设置'])
    check.completed.emit()
    assert desktop.missing_assets == []


@pytest.mark.p1
def test_desktop_course_commands_reject_stale_recording(desktop):
    from types import SimpleNamespace
    desktop.values['beta_features'] = True
    desktop.knowledge = SimpleNamespace(connected=True, identifier='old')
    try:
        with pytest.raises(ValueError, match='当前录音已变化'):
            desktop.knowledge_command('permission', {'materials': True, 'notes': True})
    finally:
        desktop.knowledge = None


@pytest.mark.p1
def test_desktop_catalog_download_and_retry_freeze_selection_without_applying(desktop, monkeypatch):
    original = dict(desktop.values)
    commands = []
    monkeypatch.setattr(desktop, '_start_preparation', lambda command, kind: commands.append((list(command), kind)))
    snapshot = {**desktop._selection(), 'backend': 'wlk-whisper', 'asr_model': 'tiny'}
    desktop.prepare(only='asr', selection=snapshot)
    assert desktop.values == original
    command = commands[-1][0]
    assert json.loads(command[command.index('--selection') + 1]) == snapshot
    snapshot['asr_model'] = 'large-v3'
    desktop.set_settings({'asr': 'base'})
    desktop.preparation_recovery = '重试'
    desktop.retry_preparation()
    assert commands[-1] == commands[0]
    with pytest.raises(ValueError, match='当前平台'):
        desktop.prepare(selection={**desktop._selection(), 'translation_device': 'unsupported'})
    assert len(commands) == 2


@pytest.mark.p1
def test_desktop_pending_workspace_does_not_create_empty_recordings(desktop):
    for name in ('草稿一', '草稿二'):
        desktop.new_recording(name=name)
        desktop.rename(None, name + ' 编辑')
        assert desktop.item is None and desktop.snapshot()['draft']['name'] == name + ' 编辑'
        assert desktop.library.index['sessions'] == []
        assert not list(desktop.library.root.rglob('session.json'))
    desktop.set_settings({'source': '简体中文', 'target': '简体中文', 'translate': True})
    assert desktop.values['translate'] is False
    desktop.set_settings({'source': 'English'})
    assert desktop.values['translate'] is False
    desktop.prefs.setValue('overlay_font_size', 31)
    assert desktop.overlay_preferences()['font'] == 31
    desktop.set_overlay_preferences(opacity=0)
    assert desktop.overlay_preferences()['opacity'] == 0


@pytest.mark.p1
def test_desktop_library_save_revision_search_export_reopen(desktop, tmp_path):
    service = desktop
    events = []
    service.output.connect(events.append)
    service._create_recording(name='中文 课堂')
    identifier = service.item['id']
    row = Caption(1, 0, 4, 'Context matters.', 'en', '上下文很重要。')
    service._caption(row)
    service._caption(replace(row, revision=2, source='Context really matters.'))
    service._caption(row)  # Older source revision cannot replace the current text.
    service._save('complete')
    drain(service)
    assert not service.dirty and not service.save_error
    assert service.search('上下文')['rows'][0]['source'] == 'Context really matters.'
    service.export(str(tmp_path / '导出.md'), 'md')
    drain(service)
    assert any(row.get('event') == 'notice' and row['data'].get('text') == '导出完成' for row in events)
    assert 'Context really matters' in (tmp_path / '导出.md').read_text('utf-8-sig')
    service._create_recording(name='第二节')
    service.open_recording(identifier)
    assert service.page()['rows'][0]['revision'] == 2
    assert service.item['name'] == '中文 课堂'
    token = service.trash(identifier)
    assert service.item is None
    service.restore(token)
    service.open_recording(identifier)
    assert service.page()['rows'][0]['translation'] == '上下文很重要。'


@pytest.mark.p0
def test_desktop_failed_save_blocks_navigation_and_close_until_retry(desktop, monkeypatch):
    service = desktop
    service._create_recording(name='不能丢失的文字')
    identifier = service.item['id']
    service.recording_lock = acquire_recording_lock(service.library.directory(identifier))
    service._caption(Caption(1, 0, 1, 'Keep this text', 'en'))
    original = service.library.save
    def fail(*_args):
        raise OSError('disk full')
    monkeypatch.setattr(service.library, 'save', fail)
    service._save('incomplete')
    drain(service)
    assert service.save_error and service.dirty and service.recording_lock
    for operation in (service.new_recording, lambda: service.trash(identifier), service.close):
        with pytest.raises(ValueError):
            operation()
    assert service.captions[1].source == 'Keep this text'
    monkeypatch.setattr(service.library, 'save', original)
    service.retry_save()
    drain(service)
    assert not service.dirty and not service.save_error and service.recording_lock is None
    assert service.library.load(service.item)[0]['session']['state'] == 'incomplete'


@pytest.mark.p0
def test_desktop_bad_document_lock_and_export_cannot_destroy_original(desktop):
    service = desktop
    service._create_recording(name='原件')
    original = service.item.copy()
    folder = service.library.directory(original['id'])
    before = (folder / 'session.json').read_bytes()
    with pytest.raises(ValueError, match='录音库之外'):
        service.export(str(folder / 'session.json'))
    assert (folder / 'session.json').read_bytes() == before
    lock = acquire_recording_lock(folder)
    try:
        with pytest.raises(ValueError, match='另一个窗口'):
            service.trash(original['id'])
    finally:
        lock.unlock()
    bad = service.library.create(original['folder'], {}, '损坏的录音')
    (service.library.directory(bad['id']) / 'session.json').write_text('{}')
    with pytest.raises(ValueError):
        service.open_recording(bad['id'])
    assert service.item['id'] == original['id']
    assert (folder / 'session.json').read_bytes() == before


@pytest.mark.p0
def test_desktop_protocol_rejects_unknown_commands_and_native_audio(desktop):
    replies = []
    desktop.output.connect(replies.append)
    for method in ('__dict__', 'closeEvent', 'audio.refresh', 'recording.start', 'playback.toggle'):
        desktop.dispatch({'version': 1, 'id': 1, 'method': method, 'params': {}})
        assert 'error' in replies[-1]
    assert not desktop.devices and desktop.player is None and desktop.session is None
    desktop.dispatch({'version': 2, 'id': 2, 'method': 'bootstrap'})
    assert 'error' in replies[-1]
    desktop.dispatch({'version': 1, 'id': 3, 'method': 'bootstrap'})
    assert replies[-1]['result']['no_audio']


@pytest.mark.p1
@pytest.mark.parametrize('outcome', ['success', 'failure', 'closing'])
def test_slow_device_refresh_keeps_protocol_responsive_and_preserves_results(desktop, monkeypatch, outcome):
    entered, release = Event(), Event()
    calls = []
    old = [dict(id='old', name='Previous source', loopback=False)]
    desktop.devices = old
    def discover():
        calls.append(True)
        entered.set()
        assert release.wait(2), 'device discovery blocked the protocol thread'
        if outcome == 'failure':
            raise RuntimeError('Device discovery failed; refresh again.')
        return [Device('new', 'New source', False)]
    # Only the synthetic discovery is permitted; the native-audio guard remains.
    monkeypatch.setattr(desktop, '_audio_allowed', lambda: None)
    monkeypatch.setattr('linguaflow.audio.discover_devices', discover)
    replies = []
    desktop.output.connect(replies.append)
    try:
        desktop.dispatch({'version': 1, 'id': 81, 'method': 'audio.refresh'})
        assert entered.wait(1)
        assert next(value for value in replies if value.get('id') == 81).get('error') is None
        desktop.dispatch({'version': 1, 'id': 82, 'method': 'bootstrap'})
        assert next(value for value in replies if value.get('id') == 82)['result']['devices'] == old
        desktop.refresh_devices()
        assert len(calls) == 1
        if outcome == 'closing':
            desktop.closing = True
            monkeypatch.setattr(desktop, '_continue_close', lambda: None)
    finally:
        release.set()
        drain(desktop)
    for value in replies:
        json.dumps(value, ensure_ascii=False)
    if outcome == 'success':
        assert desktop.devices == [dict(id='new', name='New source', loopback=False)]
        assert any(value.get('event') == 'devices' and value['data'] == desktop.devices for value in replies)
    else:
        assert desktop.devices == old
        assert not any(value.get('event') == 'devices' for value in replies)
        if outcome == 'failure':
            assert any(value.get('event') == 'notice' and value['data'].get('error') for value in replies)


@pytest.mark.p0
def test_desktop_slow_open_keeps_commands_responsive_and_cancel_preserves_view(desktop, monkeypatch):
    service = desktop
    service._create_recording(name='保留当前视图')
    original = service.item
    other = service.library.create(original['folder'], {}, '缓慢读取')
    entered, release = Event(), Event()
    load = type(service.library).load
    def slow_load(library, item):
        entered.set()
        assert release.wait(3)
        return load(library, item)
    monkeypatch.setattr(type(service.library), 'load', slow_load)
    replies = []
    service.output.connect(replies.append)
    try:
        service.dispatch({'version': 1, 'id': 41, 'method': 'recording.open', 'params': {'identifier': other['id']}})
        assert entered.wait(1)
        assert not any(row.get('id') == 41 for row in replies)
        service.dispatch({'version': 1, 'id': 42, 'method': 'bootstrap'})
        assert replies[-1]['id'] == 42 and replies[-1]['result']['state']['item'] == original
        with pytest.raises(ValueError, match='正在读取'):
            service._create_recording()
        service.reader.cancel()
    finally:
        release.set()
        drain(service)
    assert service.item == original
    assert any(row.get('id') == 41 and 'error' in row for row in replies)


@pytest.mark.p0
def test_desktop_active_rename_keeps_writer_path_until_final_save(desktop):
    service = desktop
    service._create_recording(name='录音中')
    previous = service.library.directory(service.item['id'])
    service.recording_lock = acquire_recording_lock(previous)
    service.session = object()  # Only the lifecycle ownership boundary is simulated.
    try:
        service.rename(service.item['id'], '中文 新名称')
        assert service.library.directory(service.item['id']) == previous
        assert service.library.load(service.item)[0]['session']['pending_name'] == '中文 新名称'
        service._caption(Caption(1, 0, 1, 'Still captured', 'en'))
        service._save('complete')
        drain(service)
    finally:
        service.session = None
    service._release_lock()
    assert service.recording_lock is None
    assert service.library.directory(service.item['id']).name == '中文 新名称'
    assert service.library.load(service.item)[1][0].source == 'Still captured'


@pytest.mark.p1
def test_saved_transcript_opens_complete_from_beginning_and_keeps_live_window_bounded(desktop):
    rows = [Caption(i, i * 2, i * 2 + 2, f'Sentence {i}', 'en', final=True) for i in range(650)]
    desktop._select(None, rows)
    for params in ({}, {'locate': 425}, {'seconds': 850}, {'start': 200}):
        page = desktop.page(**params)
        assert page['start'] == 0
        assert [row['id'] for row in page['rows']] == list(range(650))
    assert len(desktop.bootstrap()['captions']['rows']) == 650
    from linguaflow.recording_state import RecordingState
    desktop.state = RecordingState.LISTENING
    try:
        assert desktop.page()['start'] == 450
        assert len(desktop.page()['rows']) == 200
    finally:
        desktop.state = RecordingState.IDLE


@pytest.mark.p1
def test_desktop_preview_recovery_preserves_complete_saved_transcript(desktop):
    service = desktop
    service._create_recording(name='分页')
    for number in range(450):
        service._caption(Caption(number, number, number + 1, f'Line {number}', 'en'))
    service.preview = {'sequence': 1, 'keep_ids': list(range(449)), 'source': 'Latest recognized tail',
                       'start': 449, 'end': 451, 'language': 'en'}
    service._save('incomplete')
    drain(service)
    assert len(service.page()['rows']) == 450
    assert service.page(locate=5)['rows'][0]['id'] == 0
    saved = service.library.load(service.item)[1]
    assert saved[-1].source == 'Latest recognized tail' and not saved[-1].final


@pytest.mark.p0
def test_desktop_preferences_validate_before_persisting(desktop):
    original = dict(desktop.values)
    for changes in ({'beta_features': 'yes'}, {'appearance': 'other'}, {'draft_seconds': float('nan')},
                    {'source': 'unknown'}, {'unrecognized_key': True}):
        with pytest.raises(ValueError):
            desktop.set_settings(changes)
        assert desktop.values == original
    desktop.set_settings({'appearance': 'dark', 'reduce_motion': True})
    assert desktop.prefs.value('appearance') == 'dark'


@pytest.mark.p0
def test_desktop_library_migration_preserves_recording_and_preferences(desktop, tmp_path):
    service = desktop
    service._create_recording(name='迁移证据')
    service._caption(Caption(1, 0, 1, 'Preserve me', 'en'))
    service._save('complete')
    drain(service)
    identifier = service.item['id']
    previous = service.library.root
    destination = tmp_path / '新位置'
    service.migrate_library(str(destination))
    drain(service)
    assert service.library.root == destination
    assert service.prefs.value('library_directory') == str(destination)
    assert service.item['id'] == identifier
    assert service.library.load(service.item)[1][0].source == 'Preserve me'
    assert not service.migration_locks
    assert not (previous / '我的录音' / '迁移证据' / 'session.json').exists()


@pytest.mark.p0
def test_desktop_recovery_receipt_rejects_changed_backup_and_new_caption(desktop, tmp_path, monkeypatch):
    service = desktop
    service._create_recording(name='失败后的备份')
    service._caption(Caption(1, 0, 1, 'Original draft', 'en', final=False))
    monkeypatch.setattr(service.library, 'save', lambda *_: (_ for _ in ()).throw(OSError('full')))
    service._save('incomplete')
    drain(service)
    backup = tmp_path / 'recovery.txt'
    service.export(str(backup), recovery=True)
    drain(service)
    assert service.snapshot()['recovery_ready']
    backup.write_text('external edit')
    with pytest.raises(ValueError, match='备份已被修改'):
        service.close_recovered()
    service.export(str(backup), recovery=True)
    drain(service)
    service._caption(Caption(2, 1, 2, 'New draft', 'en', final=False))
    with pytest.raises(ValueError, match='内容已变化'):
        service.close_recovered()
    service.export(str(backup), recovery=True)
    drain(service)
    service.close_recovered()
    assert service.item is None and not service.dirty
    assert 'Original draft' in backup.read_text('utf-8-sig')
    assert 'New draft' in backup.read_text('utf-8-sig')


@pytest.mark.p1
def test_capture_feedback_distinguishes_audio_and_model_lifecycle(desktop):
    from types import SimpleNamespace

    from linguaflow.recording_state import RecordingState
    ready = Event()
    desktop.session = SimpleNamespace(model_ready=ready)
    try:
        desktop.state = RecordingState.STARTING
        starting = desktop.snapshot()['capture']
        assert starting == {'label': '正在启动…', 'volume_label': '准备收音', 'waiting': '正在连接音频来源…', 'model_loading': True}
        desktop._source_changed(0)
        capturing = desktop.snapshot()['capture']
        assert capturing['label'] == '录音中' and capturing['waiting'] == '录音已开始'
        assert capturing['volume_label'] == '输入音量' and capturing['model_loading']
        desktop.pending_source_revision = 2
        replies = []
        desktop.output.connect(replies.append)
        desktop._source_changed(2)
        assert desktop.pending_source_revision is None
        assert replies[-1]['event'] == 'state' and replies[-1]['data']['capture']['volume_label'] == '输入音量'
        ready.set()
        desktop._ready()
        assert not desktop.snapshot()['capture']['model_loading']
        assert desktop.snapshot()['capture']['waiting'] == '正在聆听…'
        desktop._stage('音频', '输入持续为零，请检查来源 / 静音')
        assert desktop.snapshot()['capture']['waiting'].startswith('没有收到声音。')
        desktop.state = RecordingState.PAUSED
        assert desktop.snapshot()['capture']['volume_label'] == '已暂停'
        desktop.pending_source_revision = 2
        assert desktop.snapshot()['capture']['volume_label'] == '继续后切换'
        ready.clear()
        desktop.state = RecordingState.STOPPING
        assert not desktop.snapshot()['capture']['model_loading']
        assert desktop.snapshot()['capture']['volume_label'] == '收尾中'
    finally:
        desktop.session = None
        desktop.state = RecordingState.IDLE
        desktop.pending_source_revision = None


@pytest.mark.p1
def test_desktop_model_ready_does_not_claim_audio_capture(desktop):
    from threading import Event
    from types import SimpleNamespace

    from linguaflow.recording_state import RecordingState
    desktop.session = SimpleNamespace(model_ready=Event())
    desktop.state = RecordingState.STARTING
    desktop._ready()
    assert desktop.state == RecordingState.STARTING
    desktop._source_changed(0)
    assert desktop.state == RecordingState.LISTENING
    desktop.state = RecordingState.STOPPING
    desktop._source_changed(1)
    assert desktop.state == RecordingState.STOPPING
    desktop.session = None
    desktop.state = RecordingState.IDLE


@pytest.mark.p1
def test_desktop_real_stdio_unicode_and_eof_shutdown(tmp_path):
    messages = [dict(version=1, id=1, method='bootstrap'),
                dict(version=1, id=2, method='recording.new', params={'name': '中文 · IPC'}),
                dict(version=1, id=3, method='app.close')]
    result = subprocess.run([sys.executable, '-u', '-m', 'linguaflow.desktop_service', '--no-audio',
                             '--library', str(tmp_path / '录音'), '--preferences', str(tmp_path / 'prefs.ini')],
                            input=''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in messages),
                            text=True, encoding='utf-8', capture_output=True, timeout=15,
                            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'AGENTSCRIBE_LOG_DIR': str(tmp_path / 'logs')})
    assert result.returncode == 0, result.stderr
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert next(row for row in frames if row.get('id') == 2)['result']['draft']['name'] == '中文 · IPC'
    assert any(row.get('event') == 'closed' for row in frames)


@pytest.mark.p2
def test_explicit_export_queue_keeps_all_paths_and_failures(desktop, tmp_path, monkeypatch):
    from linguaflow.recording_export import write_export
    desktop._create_recording(name='导出队列')
    desktop.captions[1] = Caption(1, 0, 2, 'All exports survive.', 'en', final=True)
    started, release = Event(), Event()
    calls, notices = [], []
    desktop.output.connect(lambda value: notices.append(value['data']) if value.get('event') == 'notice' else None)

    def writer(item, captions, state=None):
        calls.append(item['path'])
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        if item['path'].endswith('B.txt'):
            raise OSError('fixture disk error')
        return write_export(item, captions, state)

    monkeypatch.setattr('linguaflow.recording_export.write_export', writer)
    desktop.export(str(tmp_path / 'A.txt'), 'txt')
    assert started.wait(2)
    desktop.export(str(tmp_path / 'B.txt'), 'txt')
    desktop.export(str(tmp_path / 'C.txt'), 'txt')
    release.set()
    drain(desktop)
    assert len(calls) == 3
    assert (tmp_path / 'A.txt').exists() and (tmp_path / 'C.txt').exists()
    final = [value for value in notices if value.get('key') == 'export' and not value.get('busy')]
    assert len(final) == 1 and final[0]['error'] and 'B.txt' in final[0]['text']


@pytest.mark.p1
def test_model_selection_schedules_refresh_and_beta_cancels(desktop):
    class Task:
        beta_only = True
        affects_runtime = False
        cancelled = False

        def cancel(self):
            self.cancelled = True

    desktop.set_settings({'beta_features': True})
    task = Task()
    desktop.preparation = task
    desktop.set_settings({'beta_features': False, 'qwen_model': 'fixture/new-model'})
    assert task.cancelled and desktop.model_refresh.isActive()
    assert desktop.snapshot()['preparation_cancelling']
    desktop.preparation = None
    desktop.model_refresh.stop()


@pytest.mark.p1
def test_runtime_release_failure_retains_owner_and_can_retry(desktop):
    class Runtime:
        calls = 0

        def close(self):
            self.calls += 1
            if self.calls == 1:
                raise OSError('owned process still alive')

    runtime = desktop.runtime = Runtime()
    results = []
    desktop._retire_runtime(results.append)
    drain(desktop)
    assert desktop.runtime is runtime and results == ['owned process still alive']
    desktop._retire_runtime(results.append)
    drain(desktop)
    assert desktop.runtime is None and results[-1] == ''


@pytest.mark.p2
def test_recording_audio_metadata_is_ready_without_player(desktop):
    import wave
    desktop._create_recording(name='WAV metadata')
    item = desktop.item
    with wave.open(str(desktop.library.directory(item['id']) / '录音.wav'), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(64000))
    desktop._select(item)
    assert desktop.snapshot()['playback'] == {'duration': 2000, 'supports_gain': True, 'volume': 100}
    assert desktop.player is None


@pytest.mark.p1
def test_finished_session_populates_playback_after_saving_and_unlocking(desktop):
    import wave
    from types import SimpleNamespace
    desktop._create_recording(name='completed audio')
    directory = desktop.library.directory(desktop.item['id'])
    with wave.open(str(directory / '录音.wav'), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(64000))
    desktop.recording_lock = acquire_recording_lock(directory)
    desktop.translating = False
    desktop.session = SimpleNamespace(isRunning=lambda: False, deleteLater=lambda: None)
    desktop._finished(desktop.session)
    drain(desktop)
    assert desktop.recording_lock is None
    assert desktop.snapshot()['playback']['duration'] == 2000
    assert desktop.player is None


@pytest.mark.p0
@pytest.mark.parametrize('failed', [False, True])
def test_worker_finished_signal_saves_recording_and_releases_stop_state(desktop, monkeypatch, failed):
    """Exercise the real worker -> workflow -> desktop completion notification."""
    import wave

    from linguaflow.recording_state import RecordingState
    from linguaflow.wlk_session import Session

    class FileSession(Session):
        def run(self):
            with wave.open(str(self.recording_path), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(64000))
            self.capture_started.set()
            self.source_changed.emit(0)
            assert self.stop_capture.wait(5)
            self.caption.emit(Caption(1, 0, 2, 'Saved final sentence.', 'en'))
            if failed:
                self.failure.emit('Fixture inference failure')

    monkeypatch.setattr('linguaflow.wlk_session.Session', FileSession)
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args[1]))
    desktop._create_recording(name='worker completion')
    item = desktop.item
    settings = replace(desktop.settings(), translate=False)
    desktop.recording.start(settings, desktop._launch_session)
    session = desktop.session
    try:
        deadline = time.monotonic() + 5
        while desktop.state != RecordingState.LISTENING:
            QCoreApplication.instance().process()
            assert not errors
            assert time.monotonic() < deadline
            time.sleep(.005)
        desktop.stop()
        assert desktop.state == RecordingState.STOPPING
        while desktop.session is not None or desktop.saver.busy or desktop.recording_lock:
            QCoreApplication.instance().process()
            assert not errors, errors
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert desktop.state == RecordingState.IDLE
        assert not desktop.dirty and not desktop.save_error
        assert item['state'] == ('incomplete' if failed else 'complete')
        assert desktop.library.load(item)[1][0].source == 'Saved final sentence.'
        assert desktop.snapshot()['playback']['duration'] == 2000
        desktop._idle()  # Finished recordings no longer block navigation/start.
    finally:
        session.stop_capture.set()
        session.wait(5000)


@pytest.mark.p1
def test_failed_runtime_shutdown_cancels_handoff_but_keeps_owner(desktop):
    class Runtime:
        def close(self):
            raise OSError('worker still owned')
    runtime = desktop.runtime = Runtime()
    desktop.frontend_handoff = {'fixture': True}
    desktop.closing = True
    desktop._continue_close()
    drain(desktop)
    assert not desktop.closing and desktop.frontend_handoff is None
    assert desktop.runtime is runtime and 'worker still owned' in desktop.status
    desktop.runtime = None


@pytest.mark.p1
def test_failed_runtime_release_cannot_start_a_new_recording(desktop):
    from types import SimpleNamespace
    desktop.runtime = SimpleNamespace(closed=True)
    desktop.no_audio = False
    try:
        with pytest.raises(ValueError, match='尚未安全释放'):
            desktop.start()
        assert desktop.item is None and desktop.session is None
    finally:
        desktop.no_audio = True
        desktop.runtime = None
