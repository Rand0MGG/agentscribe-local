"""Narrow workspace navigation retains recording identity and expanded width."""
import pytest
from ui_support import run_ui


@pytest.mark.p2
def test_expanding_sidebar_restores_current_recording_selection(tmp_path):
    run_ui('''
from linguaflow.core import Caption
w.sidebar_in_split_layout=lambda:False
w.resize(1100,700);w.show();w.reduce_motion.setChecked(True)
assert w.new_recording(name='保留选中录音',check_models=False)
w.on_caption(Caption(1,0,2,'Keep selection','en',final=True))
assert w.persist_session('complete')
identifier=w.current_item['id']
w.refresh_library()
assert w.library_tree.currentItem().data(0,Qt.ItemDataRole.UserRole)==('session',identifier)
w.sidebar_toggle.click();w.sidebar_toggle.click()
assert w.library_tree.currentItem().data(0,Qt.ItemDataRole.UserRole)==('session',identifier)
assert w.current_item['id']==identifier
w.sidebar_toggle.click()
folder=w.library.folder('显式选中的文件夹')
w.refresh_library()
w.load_library_item(w.library_rows[folder['id']],0)
w.sidebar_toggle.click()
assert w.current_item is None
assert w.library_tree.currentItem().data(0,Qt.ItemDataRole.UserRole)==('folder',folder['id'])
w.close()
''',tmp_path)


@pytest.mark.p2
def test_compact_sidebar_keeps_full_icon_width_with_many_folders(tmp_path):
    run_ui('''
from PySide6.QtTest import QTest
w.sidebar_in_split_layout=lambda:False
for index in range(30):w.library.folder('目录 %02d'%index)
w.refresh_library();w.resize(700,480);w.show();w.reduce_motion.setChecked(True)
w.sidebar_toggle.click();app.processEvents()
assert w.library_tree.viewport().width()==36
QTest.keyClick(w.library_tree,Qt.Key.Key_End)
app.processEvents()
last=w.library_tree.topLevelItem(w.library_tree.topLevelItemCount()-1)
assert w.library_tree.currentItem() is last
assert w.library_tree.visualItemRect(last).intersects(w.library_tree.viewport().rect())
w.close()
''',tmp_path)


@pytest.mark.p2
def test_sidebar_compacts_and_restores_without_losing_navigation(tmp_path):
    run_ui('''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from linguaflow.core import Caption
w.resize(1100,700);w.show()
wait(lambda:not w.sidebar_compact)
app.processEvents()
assert w.folder_button.y()-w.sidebar_toggle.y()-w.sidebar_toggle.height()==8
for button in (w.new_button,w.sidebar_toggle,w.folder_button,w.deleted_button,w.ui_update_button,w.settings_button):
    assert button.height()==36 and button.minimumHeight()==button.maximumHeight()==36
tiled=False
w.sidebar_in_split_layout=lambda:tiled
w.new_recording(name='侧栏图标测试',check_models=False)
item=w.current_item
w.on_caption(Caption(1,0,1,'Keep this caption.','en',final=True))
assert w.persist_session('complete')
w.recording_splitter.setSizes([310,750])
app.processEvents()
expanded=w.recording_sidebar.width()
before=w.captions[1].source
for attempt in range(3):
    w.resize(700,650)
    app.processEvents()
    assert not w.sidebar_compact, 'A narrow floating window must retain the manual mode'
    expanded=w.recording_sidebar.width()
    tiled=True;w.update_sidebar_mode()
    wait(lambda:w.sidebar_compact and w.recording_sidebar.width()==w.title_bar.height())
    assert w.workspace_frame.width()>550
    assert w.brand.isHidden() and w.folders_label.isHidden()
    assert w.folder_button.y()-w.sidebar_toggle.y()-w.sidebar_toggle.height()==4
    assert abs(w.folder_button.geometry().center().x()-w.recording_sidebar.width()/2)<=1
    if attempt==0 and os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
        output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
        w.grab().save(str(output/'qt-sidebar-compact-light.png'))
        w.appearance.setCurrentIndex(1);app.processEvents()
        w.grab().save(str(output/'qt-sidebar-compact-dark.png'))
        w.appearance.setCurrentIndex(0)
    for button in (w.new_button,w.sidebar_toggle,w.deleted_button,w.ui_update_button,w.settings_button):
        assert button.width()==button.height()==36
        assert button.property('iconOnly') and not button.icon().isNull()
        assert button.toolTip()==button.text() and button.accessibleName()==button.text()
    row=w.library_rows[item['id']]
    assert not row.parent().isExpanded()
    assert w.library_tree.visualItemRect(row).isEmpty()
    assert w.current_item['id']==item['id'] and w.captions[1].source==before
    assert w.sidebar_toggle.geometry().top()>w.new_button.geometry().bottom()
    if attempt==1:
        parent=row
        while parent.parent():parent=parent.parent()
        folder_id=parent.data(0,Qt.ItemDataRole.UserRole)[1]
        QTest.mouseClick(w.library_tree.viewport(),Qt.MouseButton.LeftButton,pos=w.library_tree.visualItemRect(parent).center())
        parent=w.library_rows[folder_id]
        QTest.mouseDClick(w.library_tree.viewport(),Qt.MouseButton.LeftButton,pos=w.library_tree.visualItemRect(parent).center())
        QTest.keyClick(w.library_tree,Qt.Key.Key_Right)
        app.processEvents()
        assert w.sidebar_compact and not w.library_tree.topLevelItem(0).isExpanded()
    w.sidebar_toggle.click()
    wait(lambda:not w.sidebar_compact and w.sidebar_motion.state()==w.sidebar_motion.State.Stopped)
    assert abs(w.recording_sidebar.width()-expanded)<=1,(attempt,w.recording_sidebar.width(),expanded,w.sidebar_expanded_width)
    assert w.folder_button.y()-w.sidebar_toggle.y()-w.sidebar_toggle.height()==8
    assert w.library_rows[item['id']].parent().isExpanded()
    row=w.library_rows[item['id']]
    w.library_tree.scrollToItem(row);app.processEvents()
    rect=w.library_tree.visualItemRect(row)
    assert rect.width()<=w.library_tree.viewport().width()
    QTest.mouseClick(w.library_tree.viewport(),Qt.MouseButton.LeftButton,pos=rect.center())
    wait(lambda:not w.library_reader.busy)
    assert w.current_item['id']==item['id'] and w.captions[1].source==before
    assert w.library_tree.currentItem().text(0)=='侧栏图标测试'
    assert '侧栏图标测试' in w.library_rows[item['id']].toolTip(0)
    w.sidebar_toggle.click()
    wait(lambda:w.sidebar_compact and w.recording_sidebar.width()==w.title_bar.height())
    w.resize(820,650);app.processEvents()
    assert w.sidebar_compact
    w.open_settings();w.leave_settings();app.processEvents()
    assert w.sidebar_compact
    tiled=False
    w.resize(1100,700)
    app.processEvents()
    assert w.sidebar_compact, 'Leaving split view must not override the user mode'
    w.sidebar_toggle.click()
    wait(lambda:not w.sidebar_compact and w.sidebar_motion.state()==w.sidebar_motion.State.Stopped
         and abs(w.recording_sidebar.width()-expanded)<=1)
    assert not w.new_button.property('iconOnly') and not w.brand.isHidden()
    assert w.current_item['id']==item['id']
    if attempt==0 and os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
        w.grab().save(str(output/'qt-sidebar-expanded.png'))
w.close()
''',tmp_path)


@pytest.mark.p2
def test_recording_states_do_not_override_manual_sidebar(tmp_path):
    run_ui('''
from linguaflow.recording_state import RecordingState
w.sidebar_in_split_layout=lambda:False
w.resize(700,650);w.show();app.processEvents()
assert not w.sidebar_compact
for compact in (False,True,False):
    if w.sidebar_compact!=compact:w.sidebar_toggle.click()
    for state in RecordingState:
        w.set_recording_state(state);app.processEvents()
        assert w.sidebar_compact==compact
w.set_recording_state(RecordingState.IDLE)
w.close()
''',tmp_path)


@pytest.mark.p3
def test_compact_folder_tooltip_and_settings_navigation_motion(tmp_path):
    run_ui('''
from PySide6.QtCore import QEvent
from PySide6.QtGui import QHelpEvent
from linguaflow.ui_tooltips import install_tooltips
w.sidebar_in_split_layout=lambda:False
w.resize(1100,700);w.show();app.processEvents()
w.reduce_motion.setChecked(False)
w.sidebar_toggle.click()
wait(lambda:w.sidebar_compact and w.recording_sidebar.width()==36)
row=w.library_tree.topLevelItem(0)
position=w.library_tree.visualItemRect(row).center()
viewport=w.library_tree.viewport()
app.sendEvent(viewport,QHelpEvent(QEvent.Type.ToolTip,position,viewport.mapToGlobal(position)))
tooltip=install_tooltips(app)
assert tooltip.bubble.isVisible() and tooltip.bubble.label.text()==row.text(0)
app.sendEvent(viewport,QEvent(QEvent.Type.Leave))
assert not tooltip.bubble.isVisible()
samples=[]
w.settings_sidebar_motion.valueChanged.connect(lambda value:samples.append(round(value)))
w.open_settings()
wait(lambda:len(set(samples))>=3)
assert 36<w.settings_workspace.sidebar.width()<250
assert w.pages.currentIndex()==1 and w.sidebar_compact
w.leave_settings()
assert w.settings_sidebar_motion.state()==w.settings_sidebar_motion.State.Stopped
wait(lambda:w.recording_sidebar.width()==36)
w.open_settings()
wait(lambda:w.settings_workspace.sidebar.width()>36)
w.reduce_motion.setChecked(True)
assert w.settings_workspace.sidebar.width()==250
assert w.settings_sidebar_motion.state()==w.settings_sidebar_motion.State.Stopped
w.leave_settings()
assert w.sidebar_compact and w.recording_sidebar.width()==36
w.open_settings()
assert w.settings_workspace.sidebar.width()==250
assert w.settings_sidebar_motion.state()==w.settings_sidebar_motion.State.Stopped
if os.environ.get('AGENTSCRIBE_SCREENSHOTS'):
    output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']);output.mkdir(parents=True,exist_ok=True)
    w.grab().save(str(output/'qt-settings-light.png'))
w.leave_settings();w.close()
''',tmp_path)


@pytest.mark.p2
@pytest.mark.parametrize('bounds,expected', [
    ((0,24,720,876),True), ((720,24,720,876),True),
    ((0,24,960,876),True), ((1440,24,720,876),False),
    ((0,24,1440,876),False), ((0,24,700,650),False),
    ((100,100,700,650),False), ((100,24,720,876),False),
    ((-1440,24,720,876),True), ((-720,24,720,876),True),
])
def test_split_layout_requires_full_height_edge_tile(bounds, expected):
    from PySide6.QtCore import QRect

    from linguaflow.window_chrome import is_split_layout
    area=QRect(-1440 if bounds[0]<0 else 0,24,1440,876)
    assert is_split_layout(QRect(*bounds),area) is expected


@pytest.mark.p3
def test_sidebar_animation_reverses_and_respects_reduced_motion(tmp_path):
    run_ui('''
w.resize(1100,700);w.show();wait(lambda:w.recording_sidebar.width()>=180)
w.reduce_motion.setChecked(False)
wide=w.recording_sidebar.width();motion=w.sidebar_motion
w.sidebar_toggle.click()
# Drive intermediate frames synchronously: a busy event loop may legitimately
# deliver the final frame before a polling wait observes an intermediate width.
assert motion.state()==motion.State.Running
motion.setCurrentTime(motion.duration()//3)
first=w.recording_sidebar.width()
motion.setCurrentTime(2*motion.duration()//3)
middle=w.recording_sidebar.width()
assert w.title_bar.height()<middle<first<wide
w.sidebar_toggle.click()
assert motion.state()==motion.State.Running
assert w.recording_sidebar.width()==middle
motion.setCurrentTime(motion.duration()//3)
assert middle<w.recording_sidebar.width()<wide
wait(lambda:not w.sidebar_compact and w.recording_sidebar.width()==wide and motion.state()==motion.State.Stopped)
w.sidebar_toggle.click()
wait(lambda:w.recording_sidebar.width()==w.title_bar.height() and motion.state()==motion.State.Stopped)
w.sidebar_toggle.click()
wait(lambda:w.recording_sidebar.width()==wide and motion.state()==motion.State.Stopped)
w.sidebar_toggle.click();motion.setCurrentTime(motion.duration()//3)
assert w.title_bar.height()<w.recording_sidebar.width()<wide
w.reduce_motion.setChecked(True)
assert w.recording_sidebar.width()==w.title_bar.height()
assert w.sidebar_motion.state()==w.sidebar_motion.State.Stopped
w.sidebar_toggle.click()
assert w.recording_sidebar.width()==wide
w.close()
''',tmp_path)


@pytest.mark.p2
def test_cross_folder_recording_row_hit_areas_load_matching_content(tmp_path):
    run_ui('''
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from linguaflow.core import Caption
w.resize(1100,700);w.show()
items=[]
for name in ('A','B','C'):
    folder=w.library.folder('课程 '+name)
    if name=='C':folder=w.library.folder('子课程',parent=folder['id'])
    item=w.library.create(folder['id'],{},'录音 '+name)
    w.library.save(item,[Caption(1,0,2,name+' content','en',final=True)],'complete')
    items.append(item)
w.refresh_library()
for index,position in ((0,'text'),(1,'icon'),(2,'indent'),(0,'trailing'),(1,'text')):
    item=items[index];row=w.library_rows[item['id']]
    w.library_tree.scrollToItem(row);app.processEvents()
    rect=w.library_tree.visualItemRect(row)
    x={'text':80,'icon':38,'indent':8,'trailing':rect.width()-40}[position]
    QTest.mouseClick(w.library_tree.viewport(),Qt.MouseButton.LeftButton,pos=QPoint(rect.x()+x,rect.center().y()))
    wait(lambda:not w.library_reader.busy and w.current_item and w.current_item['id']==item['id'])
    assert w.captions[1].source==chr(65+index)+' content'
    assert w.folder_id==item['folder']
    assert w.library_tree.currentItem().data(0,Qt.ItemDataRole.UserRole)==('session',item['id'])
w.close()
''',tmp_path)
