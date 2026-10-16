"""Preparation failures identify the failing step without opening a details pane."""
from test_beta_features import run_ui


def test_failed_preparation_shows_stage_and_reason_and_success_clears_error(tmp_path):
    run_ui('''
w.show();settle_geometry(w)
manager=w.model_manager
import sys
raw='ConnectionError: cannot connect to download host'
script="from linguaflow.download_progress import report; report('准备字幕分句组件', unit='stage'); raise ConnectionError('cannot connect to download host')"
manager.prepare(lambda:manager.run_preparation([sys.executable,'-c',script]),affects_runtime=False)
wait(lambda:manager.worker is None)
notice=w.notifications.notices['preparation']
assert notice.kind=='error'
assert '字幕分句组件' in notice.text and '网络' in notice.text
assert '已下载' in notice.text and '保留' in notice.text
assert raw in w.diagnostics.toPlainText() and w.diagnostics.isHidden()
manager.prepare(lambda:'模型文件已检查完整：/tmp/失败案例',affects_runtime=False)
wait(lambda:manager.worker is None)
assert w.notifications.notices['preparation'].kind=='success'
w.close()
''',tmp_path)


def test_cancelled_preparation_is_not_reported_as_failure(tmp_path):
    run_ui('''
manager=w.model_manager
def cancel():
    manager.worker.cancel()
    raise RuntimeError('准备已取消；已有文件保留。')
manager.prepare(cancel,affects_runtime=False)
wait(lambda:manager.worker is None)
notice=w.notifications.notices['preparation']
assert notice.kind=='success' and '取消' in notice.text
w.close()
''',tmp_path)


def test_failed_model_check_does_not_claim_missing_models_or_start_recording(tmp_path):
    run_ui('''
callbacks=[]
w.start_background_check=lambda module,callback,*args:callbacks.append(callback)
w.missing_model_assets=()
w.model_action='start'
w.check_model_assets()
old=callbacks[-1]
old(None)
assert w.missing_model_assets==() and w.model_action is None
assert w.model_prompt is None and w.session is None
assert w.notifications.notices['model-check'].kind=='error'
assert '检查' in w.model_manager.status.text()
w.check_model_assets()
current=callbacks[-1]
old(['识别模型：stale'])
assert w.missing_model_assets==()
current([])
assert 'model-check' not in w.notifications.notices
assert w.model_prompt is None and w.session is None
w.close()
''',tmp_path)


def test_changing_next_session_settings_cannot_replace_preparation_failure(tmp_path):
    run_ui('''
from threading import Event
release=Event();manager=w.model_manager
def fail():
    assert release.wait(2)
    raise RuntimeError('fixture preparation error')
manager.prepare(fail,affects_runtime=False)
manager.worker.result.connect(lambda *_:manager.update_translation_engine(),Qt.ConnectionType.QueuedConnection)
release.set()
wait(lambda:manager.worker is None)
assert w.notifications.notices['preparation'].kind=='error'
assert 'fixture preparation error' in manager.status.text()
w.close()
''',tmp_path)


def test_successful_asset_recheck_does_not_replace_preparation_failure(tmp_path):
    run_ui('''
w.notifications.post('model-check','上次检查未完成',kind='error')
w.model_manager.status.setText('准备未完成：翻译组件；fixture failure')
w.on_model_assets_checked(w.asset_check_generation,[])
assert 'model-check' not in w.notifications.notices
assert w.model_manager.status.text()=='准备未完成：翻译组件；fixture failure'
w.close()
''',tmp_path)


def test_failed_recheck_revalidates_old_missing_result_before_download_guidance(tmp_path):
    run_ui('''
callbacks=[]
w.start_background_check=lambda module,callback,*args:callbacks.append(callback)
w.missing_model_assets=('识别模型：previous result',)
w.check_model_assets();callbacks[-1](None)
count=len(callbacks)
w.show_first_run()
assert w.first_run is None and len(callbacks)==count+1
callbacks[-1]([])
assert w.first_run is None and w.model_prompt is None
w.close()
''',tmp_path)
