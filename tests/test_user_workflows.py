"""Shared first-use, feedback, playback and recording lifecycle acceptance."""
import base64

import pytest
from test_beta_features import run_ui

from linguaflow.core import Caption
from linguaflow.playback import PlaybackIndex
from linguaflow.update_config import bundle_version, update_identity


def test_playback_boundaries_silence_and_order():
    index = PlaybackIndex([Caption(2, 8, 10, 'second', 'en'), Caption(1, 1, 4, 'first', 'en')])
    assert [index.at(t) for t in (0, 1, 3.9, 4, 7, 8, 10)] == [None, 1, 1, None, None, 2, None]


@pytest.mark.parametrize('target', ['macos-arm64', 'windows-x64'])
def test_update_identity_platform_channel_and_trust(target):
    config = {'feed_base': 'https://example.org/updates',
              'targets': {target: {'public_key': base64.b64encode(bytes(32)).decode()}}}
    assert update_identity(config, target, '0.7.0')['feed_url'] == f'https://example.org/updates/{target}/stable.xml'
    assert update_identity(config, target, '0.8.0-beta.2')['channel'] == 'beta'
    assert bundle_version('0.8.0-beta.2') == '0.8.0b2'
    config['targets'][target]['public_key'] = ''
    with pytest.raises(ValueError, match='公钥'):
        update_identity(config, target, '0.7.0')


def test_repeated_update_checks_do_not_interrupt_download_or_clear_install_gate(tmp_path):
    run_ui('''
from types import SimpleNamespace
calls=[]
updater=w.native_updater
updater.installed=True
updater.adapter=SimpleNamespace(check=lambda manual:calls.append(manual),close=lambda:None)
assert updater.check() and calls==[True]
assert not updater.check() and calls==[True]
updater._observe({'stage':'latest'})
updater.pending=True;updater.ready.set()
assert not updater.check() and updater.ready.is_set()
updater.pending=False;updater.ready.clear();updater.installed=False
w.close()
''',tmp_path)


def test_feedback_never_moves_workspace_and_errors_survive_success_and_navigation(tmp_path):
    run_ui('''
w.show(); settle_geometry(w)
center = w.notifications
assert w.centralWidget().layout().indexOf(center) == -1
assert w.pages.geometry().bottom() >= w.centralWidget().height()-2
before = (w.scroll.geometry(), w.control_island.geometry(), w.size())
center.post('save', '录音保存失败。', kind='error', action=lambda: None, action_text='重试')
center.post('download', '正在下载模型', kind='progress', progress=37)
center.post('selection', '模型选择已保存。', kind='success')
settle_geometry(w)
assert center.current_key == 'save'
assert before == (w.scroll.geometry(), w.control_island.geometry(), w.size())
w.open_settings('常规'); app.processEvents()
assert center.isVisibleTo(w) and center.current_key == 'save'
center.clear('save')
assert center.current_key == 'download' and center.progress.value() == 37
assert '37%' in center.message.text()
center.post('download', '正在下载模型', kind='progress', progress=None)
assert center.progress.minimum() == center.progress.maximum() == 0
center.clear('download')
center.clear('selection')
assert center.isHidden()
assert before == (w.scroll.geometry(), w.control_island.geometry(), w.size())
center.post('old','旧消息',kind='info')
center.post('new','需要处理',kind='attention')
assert center.current_key=='new'
w.leave_settings(); w.close()
''', tmp_path)


def test_feedback_popup_sizes_aligns_and_expires_without_progress_reopening(tmp_path):
    run_ui('''
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtTest import QTest
import linguaflow.notifications as notifications
w.show(); settle_geometry(w)
center=w.notifications
clock=[100.]
with patch.object(notifications,'time',SimpleNamespace(monotonic=lambda:clock[0])):
    center.post('short','已保存',kind='success'); app.processEvents()
    assert center.isWindow() and center.isVisible()
    assert center.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    pixels=center.grab().toImage()
    assert pixels.pixelColor(0,0).alpha()==0
    assert pixels.pixelColor(pixels.width()//2,pixels.height()//2).alpha()==255
    small=center.width()
    center.clear('short')
    center.post('download','下载模型',kind='progress',progress=9); app.processEvents()
    width=center.width()
    center.post('download','下载模型',kind='progress',progress=100); app.processEvents()
    assert center.width()==width
    clock[0]+=6; QTest.qWait(550)
    assert center.isHidden()
    center.post('download','下载模型',kind='progress',progress=99)
    assert center.isHidden() and 'download' in center.notices
    center.post('error','保存失败，录音仍然保留。请检查所选文件夹是否可写，再重试保存。'*3,
                kind='error',action=lambda:None,action_text='重试')
    for width,height in ((1280,840),(640,480)):
        w.resize(width,height); settle_geometry(w)
        anchor=center.anchor
        right=anchor.mapToGlobal(anchor.rect().topRight()).x()+1-16
        assert center.x()+center.width()==right
        assert small<center.width()<=anchor.width()-32
        assert center.height()>44
        assert w.pages.geometry().bottom()>=w.centralWidget().height()-2
    clock[0]+=9; QTest.qWait(550)
    assert center.isHidden() and center.notices['error'].action is not None
    center.post('success','新的任务已完成',kind='success')
    assert center.current_key=='success' and center.isVisible()
    center.dismiss.click(); assert center.isHidden()
w.close()
''',tmp_path)


def test_download_cancel_remains_available_after_popup_expires(tmp_path):
    run_ui('''
from types import SimpleNamespace
import linguaflow.notifications as feedback
w.show();settle_geometry(w)
manager=w.model_manager
cancelled=[]
manager.worker=SimpleNamespace(cancel=lambda:cancelled.append(True))
manager.cancel_button.setEnabled(True);manager.cancel_button.show()
w.on_preparation_changed(True)
w.on_download_progress({'completed':1,'total':100,'unit':'B'})
w.notifications.notices['preparation'].expires=feedback.time.monotonic()-1
w.on_download_progress({'completed':2,'total':100,'unit':'B'})
assert w.notifications.isHidden()
before=w.pages.geometry()
w.open_settings('模型管理');settle_geometry(w)
assert manager.download_card.isVisible() and manager.cancel_button.isVisible()
manager.cancel_button.click();assert cancelled==[True]
w.leave_settings();settle_geometry(w);assert not manager.download_card.isVisible()
assert w.pages.geometry()==before
manager.worker=None
w.on_preparation_changed(False)
w.open_settings('模型管理');app.processEvents()
assert manager.download_card.isHidden()
w.close()
''',tmp_path)


def test_normal_status_and_attention_preserve_unresolved_operation_error(tmp_path):
    run_ui('''
w.show();settle_geometry(w)
w.show_warning('保存失败','原始错误详情')
center=w.notifications
center.notices['operation'].expires=time.monotonic()-1
w.status.setText('普通状态消息')
center.post('operation','请先选择录音',kind='attention')
assert center.notices['operation'].kind=='error'
assert center.notices['operation'].details=='原始错误详情'
assert center.notices['status'].text=='普通状态消息'
center.clear('operation')
center.post('operation','操作完成',kind='success')
assert center.notices['operation'].kind=='success'
w.close()
''',tmp_path)


def test_startup_guidance_checks_models_before_opening_and_ignores_old_completion(tmp_path):
    run_ui('''
checks=[]
w.check_model_assets=lambda:checks.append(True)
w.show(); app.processEvents()
w.show_first_run()
assert checks and w.first_run is None and w.startup_model_guidance_pending
w.on_model_assets_checked(w.asset_check_generation, [])
assert not w.startup_model_guidance_pending and w.first_run is None
# Reopening without completing a historical wizard is quiet when models exist.
w.close();w=window();w.show();w.check_model_assets=lambda:None
w.show_first_run()
w.on_model_assets_checked(w.asset_check_generation, ['运行环境：mlx','字幕分句组件'])
assert w.first_run is None
w.missing_model_assets=('本地模型检查未完成，可在模型管理中重新检查',)
w.show_first_run(); assert w.first_run is None
# Deleting a model must still show guidance even if an old wizard was completed.
w.prefs.setValue('first_run_completed',True)
w.missing_model_assets=('识别模型：fixture',)
w.show_first_run();d=w.first_run
assert d.isVisible() and not d.finish.isEnabled()
d.reject()
w.on_model_assets_checked(w.asset_check_generation, [])
assert d.finish.isEnabled()
w.show_first_run(); assert d.isHidden()
# A late missing-file refresh after dismissal does not reopen the dialog.
w.on_model_assets_checked(w.asset_check_generation, ['识别模型：fixture'])
assert d.isHidden()
w.show_first_run(); assert d.isVisible()
w.on_model_assets_checked(w.asset_check_generation, [])
d.finish.click();app.processEvents();assert d.isHidden()
w.close()
''', tmp_path)


def test_guidance_requires_only_enabled_models_and_preserves_translation_choice(tmp_path):
    run_ui('''
w.check_model_assets=lambda:None
w.show();app.processEvents()
w.translate.setChecked(False)
w.missing_model_assets=('翻译模型：fixture',)
w.show_first_run();assert w.first_run is None
w.model_manager.qwen_model.setCurrentText('')
w.model_manager.whisper_widgets[0].setCurrentText('')
w.missing_model_assets=()
w.show_first_run();d=w.first_run
assert d is not None and d.isVisible()
assert 'HY-MT2' not in d.models.text()
assert d.download.text()=='下载并使用推荐识别模型'
prepared=[]
w.prepare_recommended_models=lambda **kwargs:prepared.append(kwargs)
d.download.click()
assert prepared==[{'only':'asr'}] and not w.translate.isChecked()
assert d.isHidden()
w.translate.setChecked(True)
w.model_manager.llama_model.setCurrentText('')
w.model_manager.translation_model.setCurrentText('')
w.show_first_run();assert d.isVisible() and 'HY-MT2' in d.models.text()
d.reject()
# An explicit recording action owns its own prompt; no duplicate startup wizard.
w.first_run=None;w.missing_model_assets=None
w.show_first_run();w.model_action='start';w.prompt_missing_models=lambda:prepared.append('prompt')
w.on_model_assets_checked(w.asset_check_generation,['识别模型：fixture'])
assert w.first_run is None and prepared[-1]=='prompt'
w.close()
''',tmp_path)


def test_playback_highlight_manual_interrupt_return_and_seek(tmp_path):
    run_ui('''
from linguaflow.core import Caption
from linguaflow.playback import PlaybackIndex
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QWheelEvent
w.show(); w.reduce_motion.setChecked(True)
for i in range(20):
    w.on_caption(Caption(i, i*10, i*10+8, 'Recorded content. '*30, 'en','译文。'*10))
settle_geometry(w)
w.playback_index=PlaybackIndex(w.captions.values())
w.scroll.set_playback(True)
w.playback_position(152000)
assert w.cards[15].property('playing') and not w.cards[1].property('playing')
wheel=QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(),QPoint(0,120),
    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
app.sendEvent(w.scroll.viewport(),wheel); app.processEvents()
position=w.scroll.verticalScrollBar().value()
assert not w.scroll.following
w.playback_position(182000); app.processEvents()
assert w.cards[18].property('playing') and not w.cards[15].property('playing')
assert w.scroll.verticalScrollBar().value()==position
assert w.scroll.latest_button.isVisible()
w.scroll.latest_button.click(); app.processEvents()
assert w.scroll.following
w.seek_playback(2000)
assert w.cards[0].property('playing') and not w.cards[18].property('playing')
w.release_playback()
assert not w.scroll.playback_mode and not any(c.property('playing') for c in w.cards.values())
w.session_dirty=False; w.close()
''', tmp_path)


def test_close_waits_for_active_session_and_failed_save_retains_recording(tmp_path):
    run_ui('''
from linguaflow.core import Caption
from linguaflow.recording_state import RecordingState
from types import SimpleNamespace
assert w.new_recording(name='关闭不删除', check_models=False)
w.on_caption(Caption(1,0,1,'keep text','en','译文'))
identifier=w.current_item['id']
stopped=[]
w.session=SimpleNamespace(stop=lambda:stopped.append(True))
w.set_recording_state(RecordingState.LISTENING)
w.close_recording()
assert stopped and w.current_item['id']==identifier
w.session=None; w.set_recording_state(RecordingState.IDLE)
original=w.library.save
w.library.save=lambda *args: (_ for _ in ()).throw(OSError('disk full'))
w.continue_deferred_operations()
assert w.current_item and w.session_dirty and w.notifications.notices['save'].kind=='error'
w.library.save=original
w.retry_save(); wait(lambda:not w.recording_saver.busy)
w.continue_deferred_operations()
assert w.current_item is None
assert identifier in w.library.paths
assert w.library.load(next(i for i in w.library.index['sessions'] if i['id']==identifier))[1][0].source=='keep text'
w.close()
''', tmp_path)


def test_update_never_stops_recording_and_release_is_background_and_fenced(tmp_path):
    run_ui('''
from threading import Event
from types import SimpleNamespace
from linguaflow.recording_state import RecordingState
stopped=[]; released=Event(); installed=[]
w.session=SimpleNamespace(stop=lambda:stopped.append(True))
w.set_recording_state(RecordingState.LISTENING)
w.native_updater.adapter=SimpleNamespace(install=lambda:installed.append(True),close=lambda:None)
w.native_updater.pending=True
w.try_install_update()
assert not stopped and not installed and not w.update_fenced
w.session=None; w.set_recording_state(RecordingState.IDLE)
# Finish owned local checks before requesting process release.
wait(lambda:not w.background_checks)
class Runtime:
    closed=False
    def close(self,wait=True):
        assert wait
        released.wait(5)
        self.closed=True
w.runtime=Runtime()
w.try_install_update()
assert w.update_fenced and not installed
# GUI navigation/events remain possible while runtime release waits.
w.open_settings('常规'); app.processEvents()
w.start(models_checked=True); assert w.session is None
released.set(); wait(lambda:bool(installed))
assert w.native_updater.ready.is_set()
w.native_updater.installing=False; w.runtime=None; w.close()
''', tmp_path)


@pytest.mark.parametrize('final_state', ['complete', 'incomplete'])
def test_library_operation_retries_failed_final_state(tmp_path, final_state):
    run_ui('''
from linguaflow.core import Caption
w.show();settle_geometry(w)
assert w.new_recording(name='保存恢复',check_models=False)
w.library.begin(w.current_item,{})
w.on_caption(Caption(1,0,1,'keep caption','en',final=True))
original_save=w.library.save
failed=[]
def save(item,captions,state=None):
    if state==FINAL_STATE and not failed:
        failed.append(True)
        raise OSError('transient disk failure')
    return original_save(item,captions,state)
w.library.save=save
assert not w.persist_session(FINAL_STATE)
assert w.save_target_state==FINAL_STATE and w.session_dirty
assert w.can_edit_library()
observed=(w.current_item['state'],w.save_target_state,w.session_dirty,
          w.library.load(w.current_item)[0]['session']['state'])
captions=w.library.load(w.current_item)[1]
w.close();wait(lambda:not w.isVisible())
assert observed==(FINAL_STATE,None,False,FINAL_STATE),observed
assert captions[0].source=='keep caption'
'''.replace('FINAL_STATE', repr(final_state)), tmp_path)


@pytest.mark.parametrize('event', ['cancel', 'cancelled', 'error'])
def test_update_abandonment_waits_for_runtime_shutdown_and_recovers(tmp_path, event):
    run_ui('''
from linguaflow.runtime_preparation import RuntimePreparation
w.show();settle_geometry(w)
wait(lambda:not w.background_checks)
runtime=RuntimePreparation()
w.runtime=runtime
w.native_updater.installed=True
observations=[]
try:
    with runtime.lock:
        w.try_install_update()
        observations.append(w.update_fenced and w.native_updater.shutdown_job is not None)
        if EVENT=='cancel':
            w.native_updater.cancel()
        else:
            w.native_updater.event.emit({'stage':EVENT,'text':'fixture update abandoned'})
        observations.append(w.update_fenced and w.model_manager.update_fenced)
        observations.append(not w.start_button.isEnabled())
        w.native_updater.confirm_install()
        observations.append(not w.native_updater.pending)
        observations.append(not w.native_updater.check())
finally:
    wait(lambda:w.native_updater.shutdown_job is None)
new_runtime=w.runtime
observations.append(new_runtime is not runtime and not new_runtime.closed)
observations.append(not w.update_fenced and not w.model_manager.update_fenced)
observations.append(w.start_button.isEnabled() and w.library_tree.isEnabled())
observations.append(not w.native_updater.ready.is_set() and not w.native_updater.installing)
# A native shutdown request queued before cancellation must not revive it.
w.native_updater.request_install.emit();app.processEvents()
observations.append(not w.native_updater.pending and not w.update_fenced)
w.native_updater.installed=False
w.close();wait(lambda:not w.isVisible())
assert all(observations),observations
'''.replace('EVENT', repr(event)), tmp_path)


def test_older_auto_save_cannot_clear_pending_final_state(tmp_path):
    run_ui('''
from dataclasses import replace
from threading import Event
from linguaflow.core import Caption
w.show();settle_geometry(w)
assert w.new_recording(name='最终保存排队',check_models=False)
w.library.begin(w.current_item,{})
caption=Caption(1,0,1,'first','en',final=True)
w.on_caption(caption);w.autosave.stop()
original_save=w.library.save
initial_started,initial_release,final_started,final_release=Event(),Event(),Event(),Event()
calls=[]
def save(item,captions,state=None):
    calls.append(state)
    if len(calls)==1:
        initial_started.set();assert initial_release.wait(5)
    elif len(calls)==2:
        final_started.set();assert final_release.wait(5)
    return original_save(item,captions,state)
w.library.save=save
try:
    w.queue_session_save();wait(initial_started.is_set)
    w.queue_session_save('complete')
    initial_release.set();wait(final_started.is_set)
    observed=(w.save_target_state,w.session_dirty)
    w.on_caption(replace(caption,source='latest',revision=2));w.autosave.stop()
    w.queue_session_save()
finally:
    initial_release.set();final_release.set()
    wait(lambda:not w.recording_saver.busy)
saved=w.library.load(w.current_item)
w.close();wait(lambda:not w.isVisible())
assert observed==('complete',True),observed
assert calls==[None,'complete','complete'],calls
assert saved[0]['session']['state']=='complete' and saved[1][0].source=='latest'
''', tmp_path)


def test_search_locates_saved_source_and_translation_without_starting_playback(tmp_path):
    run_ui('''
from linguaflow.core import Caption
assert w.new_recording(name='搜索定位',check_models=False)
w.on_caption(Caption(1,0,5,'first paragraph','en','第一段'))
w.on_caption(Caption(2,10,15,'find this phrase','en','上下文'))
w.find_captions(); d=w.search_dialog
assert d.isVisible()
d.query.setText('上下文');d.search()
assert d.results.count()==1
d.locate.click();app.processEvents()
assert not d.isVisible() and w.player is None
assert not w.scroll.following
w.persist_session();w.close()
''',tmp_path)


def test_library_migration_waits_for_session_and_commits_verified_recordings(tmp_path):
    run_ui('''
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace
from linguaflow.core import Caption,Settings
from linguaflow.recording_state import RecordingState
w.prepare_playback=lambda:None
assert w.new_recording(name='迁移保存',check_models=False)
w.on_caption(Caption(1,0,3,'keep me','en','保留'))
identifier=w.current_item['id']; source=w.library.root
wav=w.library.directory(identifier)/'录音.wav';wav.write_bytes(b'fixture audio bytes'*100)
assert w.persist_session('complete')
destination=source.parent/(source.name+'-new');destination.mkdir()
module.QFileDialog.getExistingDirectory=lambda *args:str(destination)
stops=[]
w.session=SimpleNamespace(stop=lambda:stops.append(True))
w.set_recording_state(RecordingState.LISTENING)
w.choose_library()
assert not stops and not w.library_migration.busy and w.pending_library_path
assert w.library.root==source
w.session=None;w.set_recording_state(RecordingState.IDLE)
w.continue_deferred_operations()
assert w.library_migration.busy
w.open_settings('常规');app.processEvents()
wait(lambda:not w.library_migration.busy and w.library.root==destination)
assert w.library.load(w.current_item)[1][0].source=='keep me'
assert (w.library.directory(identifier)/'录音.wav').is_file() and not wav.exists()
assert w.prefs.value('library_directory')==str(destination)
assert not w.migration_locks and w.start_button.isEnabled()
w.close()
''',tmp_path)
