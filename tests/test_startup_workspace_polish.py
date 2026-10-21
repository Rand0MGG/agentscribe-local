"""First-run routing, download ownership, and readable caption/popup boundaries."""
from ui_support import run_ui


def test_model_download_card_is_local_and_dismissal_does_not_cancel_or_reopen(tmp_path):
    run_ui(r'''
from threading import Event
module.Window.start_background_check=lambda *args,**kwargs:None
w.settings_workspace.model_browser.start_check=None
w.show();w.open_settings('模型管理');settle_geometry(w)
m=w.model_manager
release=Event()
m.prepare(lambda:release.wait(20) and '准备完成')
owned=m.worker
assert owned is not None and owned.isRunning()
settle_geometry(w)
assert m.download_card.isVisibleTo(w)
assert w.notifications.current_key!='preparation'
output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']) if os.environ.get('AGENTSCRIBE_SCREENSHOTS') else None
if output:
    output.mkdir(parents=True,exist_ok=True);w.grab().save(str(output/'model-download-card.png'))
w.open_settings('常规');settle_geometry(w)
w.on_download_progress({'unit':'B','completed':10,'total':100})
assert not m.download_card.isVisibleTo(w)
assert w.notifications.current_key=='preparation' and w.notifications.isVisible()
assert w.notifications.notices['preparation'].expires==float('inf')
if output:
    w.grab().save(str(output/'other-settings.png'))
    w.notifications.grab().save(str(output/'download-popup.png'))
w.notifications.dismiss.click()
expires=w.notifications.notices['preparation'].expires
for category in w.settings_workspace.categories:
    w.open_settings(category);settle_geometry(w)
    for unit in ('stage','B'):
        w.on_download_progress({'unit':unit,'completed':20,'total':100})
        w.on_preparation_message('切换下载文件与准备阶段')
    assert m.download_card.isVisibleTo(w)==(category=='模型管理')
    assert w.notifications.notices['preparation'].expires==expires
    assert w.notifications.current_key!='preparation'
    assert m.worker is owned and owned.isRunning() and not owned.cancelled
w.leave_settings();settle_geometry(w)
assert not m.download_card.isVisibleTo(w) and w.notifications.current_key!='preparation'
release.set();wait(lambda:m.worker is None)
# A new task gets one fresh notification; the previous dismissal does not cancel it.
release.clear();m.prepare(lambda:release.wait(20) and '准备完成')
w.on_download_progress({'unit':'B','completed':1,'total':10})
assert w.notifications.current_key=='preparation'
release.set();wait(lambda:m.worker is None)
w.close()
''',tmp_path)
