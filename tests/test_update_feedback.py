"""Native check completion, explicit feedback, and cancelled request isolation."""
from ui_support import run_ui


def test_background_failure_finishes_and_manual_retry_ignores_old_callbacks(tmp_path):
    run_ui('''
from types import SimpleNamespace
u=w.native_updater;u.installed=True;calls=[];seen=[]
u.adapter=SimpleNamespace(check=lambda manual:calls.append(manual),cancel=lambda:None,close=lambda:None)
u.event.connect(seen.append)
assert u.check(manual=False) and calls==[False] and not seen
old=u.generation
u.relay({'stage':'error','text':'fixture 404','request':old})
u.relay({'stage':'cycle-finished','text':'','request':old})
wait(lambda:not u.active)
assert not seen and w.notifications.current_key!='update'
w.check_software_updates()
assert calls==[False,True] and u.generation>old and u.active
assert w.notifications.current_key=='update'
assert w.notifications.notices['update'].expires==float('inf')
u.relay({'stage':'cycle-finished','text':'','request':old})
u.relay({'stage':'error','text':'stale failure','request':old})
app.processEvents()
assert u.active and seen[-1]['text']=='正在检查更新'
u.relay({'stage':'error','text':'无法获取更新订阅，请重试。','request':u.generation})
wait(lambda:not u.active)
assert w.notifications.notices['update'].kind=='error'
assert w.notifications.notices['update'].expires==float('inf')
assert '无法获取更新订阅' in w.model_manager.version_label.text()
u.installed=False;w.close()
''', tmp_path)


def test_manual_click_promotes_active_background_check_without_duplicate_request(tmp_path):
    run_ui('''
from types import SimpleNamespace
w.show();settle_geometry(w)
u=w.native_updater;u.installed=True;calls=[]
u.adapter=SimpleNamespace(check=lambda manual:calls.append(manual),close=lambda:None)
assert u.check(manual=False)
w.ui_update_button.click()
assert calls==[False] and u.manual
assert w.notifications.current_key=='update'
assert w.ui_update_button.text()=='正在检查…'
u.relay({'stage':'latest','text':'当前已是最新版本。','request':u.generation})
wait(lambda:not u.active)
assert '当前已是最新版本' in w.notifications.notices['update'].text
assert '当前已是最新版本' in w.model_manager.version_label.text()
assert w.ui_update_button.text()=='检查更新'
u.installed=False;w.close()
''', tmp_path)


def test_cancelled_update_cannot_reappear_or_install_and_new_check_has_feedback(tmp_path):
    run_ui('''
from types import SimpleNamespace
u=w.native_updater;u.installed=True;calls=[]
u.adapter=SimpleNamespace(check=lambda manual:calls.append(manual),cancel=lambda:None,close=lambda:None)
assert u.check()
old=u.generation;u.cancel()
for stage in ('available','ready','error'):
    u.relay({'stage':stage,'text':'late '+stage,'request':old})
app.processEvents()
assert not u.pending and not u.ready.is_set()
assert w.notifications.notices['update'].text=='更新已取消，当前版本保留。'
w.check_software_updates()
assert u.generation>old and calls==[True,True]
assert w.notifications.notices['update'].text=='正在检查更新'
u.relay({'stage':'latest','text':'当前已是最新版本。','request':u.generation})
wait(lambda:not u.active)
u.installed=False;w.close()
''', tmp_path)


def test_native_busy_rejection_is_visible_and_does_not_latch_check(tmp_path):
    run_ui('''
from types import SimpleNamespace
u=w.native_updater;u.installed=True
u.adapter=SimpleNamespace(check=lambda manual:False,close=lambda:None)
w.check_software_updates()
assert not u.active and w.notifications.current_key=='update'
assert '上次更新检查正在结束' in w.notifications.notices['update'].text
u.installed=False;w.close()
''', tmp_path)
