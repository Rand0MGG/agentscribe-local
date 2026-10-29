"""Migration regressions through actual services; isolated data, no native audio."""
import time
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication

from linguaflow.core import Caption
from linguaflow.knowledge.client import KnowledgeClient
from linguaflow.knowledge.lifecycle import cancel_task
from linguaflow.knowledge.session import read_manifest, write_manifest
from linguaflow.recording_state import RecordingState
from linguaflow.recording_workflow import completion_state
from linguaflow.update_workflow import UpdateActivity
from tests.test_desktop_service import desktop as desktop
from tests.test_desktop_service import drain

pytestmark = pytest.mark.p1


@pytest.mark.parametrize('enabled,consent,expected', [(True, True, 1), (True, False, 0), (False, True, 0)])
def test_saved_consent_attaches_without_opening_course_window(desktop, monkeypatch, enabled, consent, expected):
    desktop._create_recording(name='自动连接')
    manifest = read_manifest(desktop.library, desktop.item['id'])
    manifest['notes_cloud'] = consent
    write_manifest(desktop.library, manifest)
    desktop.values['beta_features'] = enabled
    desktop.knowledge = KnowledgeClient(desktop)
    opened = Mock()
    monkeypatch.setattr(desktop.knowledge, 'open', opened)
    desktop.open_recording(desktop.item['id'])
    assert opened.call_count == expected


def test_cancel_import_uses_owned_cleanup_not_queued_command(desktop, monkeypatch):
    desktop._create_recording(name='取消导入')
    desktop.values['beta_features'] = True
    client = desktop.knowledge = KnowledgeClient(desktop)
    client.identifier = desktop.item['id']
    client.process = SimpleNamespace(poll=lambda: None)
    client.operation = 'import'
    closed, sent = Mock(return_value=True), Mock()
    monkeypatch.setattr(client, 'close', closed)
    monkeypatch.setattr(client, 'send', sent)
    assert desktop.knowledge_command('cancel')
    closed.assert_called_once()
    sent.assert_not_called()
    assert client.disconnected
    client.process = None


def test_cancel_cleanup_failure_is_not_success():
    client = SimpleNamespace(close=lambda: False, send=Mock(), report_disconnected=Mock())
    with pytest.raises(ValueError, match='仍在退出'):
        cancel_task(client, 'import')
    client.report_disconnected.assert_not_called()


@pytest.mark.parametrize('failure,audio,caption,expected', [
    ('', False, False, 'draft'), ('failed', False, False, 'incomplete'),
    ('', True, False, 'complete'), ('', False, True, 'complete')])
def test_final_save_classification(desktop, failure, audio, caption, expected):
    desktop._create_recording(name='录音收尾')
    desktop.library.begin(desktop.item, {})
    if audio:
        with wave.open(str(desktop.library.directory(desktop.item['id']) / '录音.wav'), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(8))
    if caption:
        desktop.captions[1] = Caption(1, 0, 1, 'saved', 'en', final=True)
    desktop.failure, desktop.translating = failure, False
    session = desktop.session = SimpleNamespace(isRunning=lambda: False, deleteLater=lambda: None)
    desktop._finished(session)
    drain(desktop)
    assert desktop.item['state'] == expected
    assert not desktop.dirty and not desktop.save_error
    assert desktop.library.load(desktop.item)[0]['session']['state'] == expected


def test_final_translation_errors_are_shared(desktop):
    desktop._create_recording(name='未定稿翻译')
    rows = [Caption(1, 0, 1, 'original', 'en', 'initial', final=True, translation_phase='initial')]
    assert completion_state(desktop.library, desktop.item, rows, translating=True, failure='') == ('incomplete', True)


def test_locate_checks_owner_and_generation_before_seeking(desktop):
    desktop._create_recording(name='定位')
    desktop.captions[5] = Caption(5, 10, 12, 'find', 'en', final=True)
    seek = Mock()
    desktop.player = SimpleNamespace(seek=seek)
    params = dict(identifier=desktop.item['id'], generation=desktop.generation, caption_id=5)
    result = desktop.locate(**params)
    seek.assert_called_once_with(10000, play=False)
    assert result['identifier'] == 5
    for changed in ({'identifier': 'old'}, {'generation': desktop.generation - 1}, {'caption_id': 6}):
        with pytest.raises(ValueError):
            desktop.locate(**{**params, **changed})
    assert seek.call_count == 1
    desktop.state = RecordingState.LISTENING
    assert desktop.locate(**params)['identifier'] == 5
    assert seek.call_count == 1
    with pytest.raises(ValueError, match='录音结束'):
        desktop.locate(identifier=desktop.item['id'], generation=desktop.generation, seconds=10)
    desktop.state = RecordingState.IDLE
    desktop.player = None


def test_text_location_does_not_create_audio_player(desktop):
    desktop._create_recording(name='只定位文字')
    desktop.captions[1] = Caption(1, 7, 8, 'find', 'en', final=True)
    desktop.locate(identifier=desktop.item['id'], generation=desktop.generation, caption_id=1)
    assert desktop.player is None and desktop.located_position == 7000
    desktop._select(None)
    assert desktop.located_position is None


def test_document_preparation_does_not_block_capture(desktop, monkeypatch):
    desktop.values['beta_features'] = True
    desktop.state = RecordingState.LISTENING
    launched = Mock()
    monkeypatch.setattr(desktop, '_start_preparation', launched)
    desktop.prepare(kind='documents')
    assert launched.call_args.args[1] == 'documents'
    with pytest.raises(ValueError, match='聆听'):
        desktop.prepare(kind='runtime')
    desktop.state = RecordingState.IDLE
    desktop.preparation = SimpleNamespace(affects_runtime=False, cancelled=False)
    assert not desktop.snapshot()['preparation_blocks_recording']
    desktop.preparation.affects_runtime = True
    assert desktop.snapshot()['preparation_blocks_recording']
    desktop.preparation = None


@pytest.mark.parametrize('gate', list(UpdateActivity.__dataclass_fields__))
def test_each_update_gate_prevents_release(desktop, monkeypatch, gate):
    release = Mock()
    monkeypatch.setattr(desktop.native_updater, 'release_runtime', release)
    desktop.update_workflow.activity = lambda: UpdateActivity(**{gate: True})
    desktop.update_workflow.try_install()
    release.assert_not_called()
    assert desktop.native_updater.pending and not desktop.update_fenced
    desktop.update_workflow.cancel_wait()
    assert not desktop.native_updater.pending


def test_update_checks_work_while_recording_and_never_handoff(desktop, monkeypatch):
    desktop.native_updater.installed = True
    checked = Mock(return_value=True)
    monkeypatch.setattr(desktop.native_updater, 'check', checked)
    desktop.state = RecordingState.LISTENING
    assert desktop.check_updates()
    checked.assert_called_once_with(manual=True)
    assert desktop.frontend_handoff is None and not desktop.closing
    desktop.state = RecordingState.IDLE


def test_update_release_cancel_keeps_fence_until_owned_thread_finishes(desktop, monkeypatch):
    from threading import Event
    released = Event()
    class Runtime:
        closed = False
        def close(self, wait=True):
            assert released.wait(5)
            self.closed = True
    desktop.runtime = Runtime()
    desktop.update_workflow.try_install()
    assert desktop.update_fenced
    desktop.update_action('cancel')
    assert desktop.update_fenced
    released.set()
    deadline = time.monotonic() + 5
    while desktop.native_updater.shutdown_job:
        QCoreApplication.instance().processEvents()
        assert time.monotonic() < deadline
        time.sleep(.005)
    assert not desktop.update_fenced and desktop.runtime is None
    assert not desktop.native_updater.ready.is_set()


def test_update_rechecks_edits_after_runtime_release(desktop, monkeypatch):
    install = Mock()
    monkeypatch.setattr(desktop.native_updater, 'install', install)
    desktop.native_updater.pending = True
    desktop.update_workflow.fenced = desktop.update_fenced = True
    desktop.unsaved_edits = True
    desktop.update_workflow.released('')
    desktop.update_workflow.try_install()
    install.assert_not_called()
    desktop.unsaved_edits = False
    desktop.update_workflow.try_install()
    install.assert_called_once()
    desktop.native_updater.pending = False
    desktop.update_workflow.resume()


def test_reference_location_returns_matching_caption(desktop):
    desktop._create_recording(name='引用定位')
    desktop.captions[1] = Caption(1, 7, 9, 'reference', 'en', final=True)
    result = desktop.locate(identifier=desktop.item['id'], generation=desktop.generation, seconds=8)
    assert result['identifier'] == 1 and desktop.located_position == 8000


def test_cancelled_update_rejects_late_download_and_install(desktop):
    updater = desktop.native_updater
    updater.adapter = SimpleNamespace(cancel=Mock(), download=Mock(), install=Mock())
    updater.last_event = {'stage': 'available'}
    updater.cancel()
    assert not updater.download()
    updater.last_event = {'stage': 'ready'}
    assert not updater.confirm_install()
    updater.adapter.download.assert_not_called()
    updater.adapter.install.assert_not_called()
    updater.adapter = None


def test_cancel_wait_requires_new_install_confirmation(desktop, monkeypatch):
    install = Mock()
    monkeypatch.setattr(desktop.native_updater, 'install', install)
    desktop.native_updater.pending = True
    desktop.native_updater.last_event = {'stage': 'waiting'}
    desktop.update_workflow.cancel_wait()
    assert not desktop.native_updater.pending
    assert desktop.native_updater.last_event['stage'] == 'ready'
    desktop._clock()
    install.assert_not_called()
