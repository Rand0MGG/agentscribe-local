"""First-run routing, download ownership, and readable caption/popup boundaries."""
from test_beta_features import run_ui


def test_first_run_download_routes_directly_to_models_without_creating_recording(tmp_path):
    run_ui(r'''
module.Window.start_background_check=lambda *args,**kwargs:None
w.show();w.missing_model_assets=('识别模型：fixture',)
w.show_first_run()
assert w.first_run.isVisible()
assert w.first_run.storage.text()==str(w.library.root)
calls=[]
w.prepare_recommended_models=lambda **kwargs:calls.append((w.pages.currentIndex(),w.settings_workspace.pages.currentIndex(),kwargs))
w.first_run.download.click()
assert not w.first_run.isVisible()
assert calls and calls[0][0]==1 and calls[0][1]==w.settings_workspace.mapping['模型管理']
assert not w.library.index['sessions'] and w.current_item is None
w.close()
''',tmp_path)


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


def test_folder_selection_and_reset_reuse_setup_instead_of_old_placeholder(tmp_path):
    run_ui(r'''
module.Window.start_background_check=lambda *args,**kwargs:None
w.show();settle_geometry(w)
assert w.empty.details.isVisibleTo(w) and '音频来源' in w.empty.text()
folder=w.library.folder('课程文件夹');w.refresh_library()
w.open_library_item(w.library_rows[folder['id']],0);settle_geometry(w)
assert w.current_item is None and w.folder_id==folder['id']
assert w.empty.details.isVisibleTo(w) and '保存文件夹：课程文件夹' in w.empty.text()
assert not w.library.index['sessions']
w.reset_recording_view();settle_geometry(w)
assert w.empty.details.isVisibleTo(w) and '音频来源' in w.empty.text()
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    w.grab().save(str(output/'ready-workspace.png'))
w.close()
''',tmp_path)


def test_only_top_fades_but_island_zone_is_excluded_from_following(tmp_path):
    run_ui(r'''
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QColor
from linguaflow.caption_view import CaptionScrollArea
area=CaptionScrollArea();area.resize(600,500)
body=QWidget();body.setStyleSheet('background: #ff00ff');body.setMinimumHeight(2000)
area.setWidget(body);area.show();settle_geometry(area)
area.set_overlay_height(60)
area.verticalScrollBar().setValue(200);settle_geometry(area)
picture=area.viewport().grab();pixels=picture.toImage();scale=picture.devicePixelRatioF()
def pixel(y):return pixels.pixelColor(round(20*scale),round(y*scale))
assert pixel(area.viewport().height()-4)==QColor('#ff00ff')
assert pixel(1)!=QColor('#ff00ff')
area.set_playback(True);area._set_following(False)
top=area.verticalScrollBar().value()
card=QWidget(body);card.setGeometry(40,top+area.viewport().height()-35,180,25);card.show()
area.follow_playback(card)
assert area.latest_button.isVisible() and area.latest_button.direction==1
card.move(40,top+100);area.follow_playback(card)
assert not area.latest_button.isVisible()
area.close();w.close()
''',tmp_path)
