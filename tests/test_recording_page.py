"""One-click recording workspace, safe naming and consistent control geometry."""
from test_beta_features import run_ui


def test_new_workspace_uses_defaults_without_creating_empty_recordings(tmp_path):
    run_ui(r'''
from PySide6.QtTest import QTest
from linguaflow.core import Caption
assert w.new_recording(name='已有录音',check_models=False)
w.on_caption(Caption(1,0,2,'Existing saved text','en'))
assert w.persist_session('complete')
identifier=w.current_item['id']
path=w.library.directory(identifier)/'session.json'
before=path.read_bytes()
w.notifications.post('session','录音与字幕已保存。',kind='success')
w.show()
for _ in range(3):
    w.new_button.click()
    assert app.activeModalWidget() is None
    assert w.current_item is None and w.session is None
    assert len(w.library.index['sessions'])==1
    assert path.read_bytes()==before
    assert 'status' not in w.notifications.notices and 'session' not in w.notifications.notices
    assert not w.start_button.isHidden()
    assert '音频来源：' in w.empty.text() and '保存文件夹：' in w.empty.text() and '语言：' in w.empty.text()
assert not any(b.accessibleName()=='关闭当前录音' for b in w.findChildren(module.QPushButton))
QTest.mouseClick(w.workspace_title.label,Qt.MouseButton.LeftButton)
assert w.workspace_title.currentIndex()==1
w.workspace_title.editor.setText('第二段录音')
w.commit_recording_title(w.workspace_title.editor.text())
assert w.pending_recording_name=='第二段录音' and w.workspace_title.text()=='第二段录音'
w.rename_current()
w.workspace_title.editor.setText('取消这个名称')
QTest.keyClick(w.workspace_title.editor,Qt.Key.Key_Escape)
assert w.pending_recording_name=='第二段录音' and w.workspace_title.currentIndex()==0
folder=w.library.folder('课堂')['id']
from PySide6.QtCore import QTimer
from linguaflow.ui_components import ActionMenu
menus=[]
def select_from_menu():
    menu=app.activePopupWidget()
    if isinstance(menu,ActionMenu):
        menus.append(menu.screen().availableGeometry().contains(menu.geometry())
                     and all(menu.actionGeometry(action).height()>=34
                             and menu.rect().contains(menu.actionGeometry(action)) for action in menu.actions()))
        next(action for action in menu.actions() if action.text()=='课堂').trigger()
        menu.close()
QTimer.singleShot(30,select_from_menu)
w.quick_folder.click()
assert menus==[True]
assert w.folder_id==folder and '课堂' in w.empty.text()
assert len(w.library.index['sessions'])==1 and path.read_bytes()==before
w.device.addItem('外部输入 · 测试麦克风',('fixture',False))
assert '测试麦克风' in w.empty.text()
w.source.setCurrentIndex(1)
w.update_quick_settings()
assert w.source.currentText() in w.empty.text()
# Start creates the selected draft with the inline name. Stop before inference or audio.
assert w.new_recording(name=w.pending_recording_name,check_models=False)
assert w.current_item['name']=='第二段录音' and w.current_item['folder']==folder
assert path.read_bytes()==before
w.rename_current()
w.workspace_title.editor.setText('已改名')
w.commit_recording_title('已改名')
assert w.current_item['name']=='已改名'
assert w.library.directory(w.current_item['id']).name=='已改名'
messages=[]
w.show_warning=lambda title,message: messages.append(title)
w.rename_current()
w.commit_recording_title('../不合法')
assert messages and w.current_item['name']=='已改名' and path.read_bytes()==before
w.notifications.post('save','保存失败，原内容保留。',kind='error')
w.new_button.click()
assert w.notifications.notices['save'].kind=='error'
w.notifications.clear('save')
w.close()
''',tmp_path)


def test_control_sizes_and_popups_survive_theme_and_window_changes(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QMargins, QPoint, Qt
from PySide6.QtTest import QTest
from linguaflow.core import Caption
from linguaflow.ui_components import ActionMenu
w.show()
w.update_titlebar_inset(QMargins(0,0,0,0))
settle_geometry(w,w.control_island)
assert w.scroll._overlay_height==w.control_island.height()+18
for mode in (0,1):
    w.appearance.setCurrentIndex(mode)
    for width,height in ((1280,840),(900,650),(640,480)):
        w.resize(width,height);w.new_button.click();settle_geometry(w)
        assert w.title_bar.height()>=36
        assert w.workspace_title.parentWidget().height()==40
        assert abs(w.brand.mapTo(w,w.brand.rect().center()).y()-w.workspace_title.mapTo(w,w.workspace_title.rect().center()).y())<=2
        assert w.folder_button.size().toTuple()==(28,28)
        assert w.play_button.size().toTuple()==(40,40)
        assert next(b for b in w.overlay.findChildren(module.QPushButton) if b.accessibleName()=='关闭悬浮字幕').size().toTuple()==(32,32)
        for button in (w.new_button,w.settings_button,w.deleted_button):
            assert button.height()==38 and button.minimumHeight()==38, (button.text(),button.size(),button.minimumSize(),button.maximumSize())
            assert button.fontMetrics().height()<=button.height()-8
        for control in (w.quick_device,w.quick_language,w.quick_folder,w.start_button):
            assert control.size().toTuple()==(40,40), (control.accessibleName(),control.size())
            assert control.accessibleName() and control.toolTip()
            assert w.control_island.rect().contains(control.rect().translated(control.mapTo(w.control_island,QPoint(0,0))))
for choice in (w.quick_device,w.source,w.target,w.appearance):
    if choice is w.quick_device:
        for i in range(15):
            choice.addItem('示例来源 '+str(i),('fixture'+str(i),False))
    choice.showPopup()
    popup=choice.view().window()
    settle_geometry(popup)
    assert popup.isVisible() and popup.screen().availableGeometry().contains(popup.geometry())
    view=choice.view()
    assert view.sizeHintForRow(0)>=34
    first=view.visualRect(view.model().index(0,0))
    assert first.height()>=34
    assert popup.rect().contains(view.rect().translated(view.mapTo(popup,QPoint(0,0))))
    choice.hidePopup()
# Every header menu action must remain fully visible, including the last row.
more=next(button for button in w.recording_actions.findChildren(module.QPushButton) if button.menu())
menu=more.menu()
menu.popup(more.mapToGlobal(QPoint(0,more.height())))
settle_geometry(menu)
assert all(menu.rect().contains(menu.actionGeometry(action)) for action in menu.actions() if action.isVisible() and not action.isSeparator())
assert menu.height()>sum(action.isVisible() for action in menu.actions())*20
menu.close()
# Mouse selection preserves the public QComboBox activation signal.
activated=[]
w.quick_device.activated.connect(activated.append)
w.quick_device.showPopup()
view=w.quick_device.view()
view.scrollToTop();app.processEvents()
QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(view.model().index(1,0)).center())
assert w.quick_device.currentIndex()==1 and not view.window().isVisible()
assert activated==[1]
for identifier in range(30):
    w.on_caption(Caption(identifier,identifier,identifier+1,'Scrollable sentence. '*5,'en'))
settle_geometry(w)
w.scroll.verticalScrollBar().setValue(100);app.processEvents()
assert w.scroll.top_fade.isVisible() and w.scroll.top_fade.height()==22
assert w.scroll.top_fade.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
assert w.scroll.latest_button.geometry().bottom()<w.control_island.geometry().top()
shadows=[w.control_island.graphicsEffect(),w.playback_volume.graphicsEffect()]
assert all(s.blurRadius()==24 and s.offset().toTuple()==(0.,4.) and s.color().alpha()==30 for s in shadows)
assert ActionMenu(w).windowFlags() & Qt.WindowType.NoDropShadowWindowHint
w.close()
''',tmp_path)


def test_start_from_new_workspace_creates_the_selected_name_and_folder(tmp_path):
    run_ui(r'''
from linguaflow.recording_state import RecordingState
w.new_button.click()
w.rename_current()
w.commit_recording_title('第一堂课')
folder=w.library.folder('课程')['id']
w.select_recording_folder(folder)
w.device.addItem('外部输入 · 课堂',('classroom',False))
w.translate.setChecked(False)
w.model_manager.backend.setCurrentIndex(0)
assert not w.library.index['sessions']
launched=[]
w.launch_session=lambda settings: launched.append(settings)
w.start(models_checked=True)
assert len(launched)==1 and launched[0].device_id=='classroom'
assert w.current_item['name']=='第一堂课' and w.current_item['folder']==folder
assert len(w.library.index['sessions'])==1
assert w.library.directory(w.current_item['id']).parent==w.library.directory(folder)
w.set_recording_state(RecordingState.IDLE)
w.release_recording_lock()
w.current_item=None
w.close()
''',tmp_path)
