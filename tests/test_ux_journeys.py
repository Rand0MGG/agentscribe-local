"""Real desktop navigation, responsive reads and theme/path regressions, without audio."""
from test_beta_features import run_ui


def test_library_click_keeps_event_loop_responsive_and_failed_load_keeps_view(tmp_path):
    run_ui('''
from threading import Event
from unittest.mock import patch
from PySide6.QtCore import QTimer
from linguaflow.library import Library
from linguaflow.core import Caption
w.new_recording(name='原录音',check_models=False)
w.on_caption(Caption(1,0,1,'Original words.','en'));assert w.persist_session('complete')
first=w.current_item['id']
other=w.library.create(w.folder_id,{},'待载入');w.refresh_library()
entered,release,tick=Event(),Event(),[]
original=Library.load
def held(library,item):
    entered.set()
    assert release.wait(5)
    raise ValueError('文件损坏，请恢复备份。')
with patch.object(Library,'load',held):
    try:
        w.library_tree.itemClicked.emit(w.library_rows[other['id']],0)
        wait(entered.is_set)
        QTimer.singleShot(0,lambda:tick.append(True));wait(lambda:bool(tick))
        assert w.library_reader.busy and w.current_item['id']==first
        assert not w.new_recording(check_models=False)
    finally:release.set()
    wait(lambda:not w.library_reader.busy)
assert w.current_item['id']==first and w.captions[1].source=='Original words.'
assert '文件损坏' in w.notifications.notices['operation'].text
w.library_tree.itemClicked.emit(w.library_rows[other['id']],0)
wait(lambda:not w.library_reader.busy)
assert w.current_item['id']==other['id']
w.rescan_library();wait(lambda:not w.library_reader.busy)
assert w.current_item['id']==other['id']
w.close()
''',tmp_path)


def test_close_during_library_read_waits_without_applying_late_result(tmp_path):
    run_ui('''
from threading import Event
from unittest.mock import patch
from linguaflow.library import Library
w.new_recording(name='旧视图',check_models=False);assert w.persist_session()
first=w.current_item['id']
other=w.library.create(w.folder_id,{},'迟到结果');w.refresh_library()
entered,release=Event(),Event()
original=Library.load
def held(library,item):
    entered.set();assert release.wait(5)
    return original(library,item)
w.show()
with patch.object(Library,'load',held):
    try:
        w.library_tree.itemClicked.emit(w.library_rows[other['id']],0);wait(entered.is_set)
        assert not w.close() and w.library_reader.busy
    finally:release.set()
    wait(lambda:not w.library_reader.busy)
wait(lambda:not w.isVisible())
assert w.current_item['id']==first
''',tmp_path)


def test_course_theme_and_long_path_actions_at_minimum_window(tmp_path):
    run_ui('''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QPushButton,QScrollArea
from linguaflow.knowledge.panel import KnowledgePanel
from linguaflow.ui_theme import theme_colors
p=KnowledgePanel(w.knowledge_client,lambda:None,lambda:True,w)
p.show()
for mode in ('light','dark'):
    w.appearance.setCurrentIndex(w.appearance.findData(mode));w.apply_appearance();settle_geometry(p)
    assert p.palette().color(QPalette.ColorRole.Window).name()==theme_colors(mode)['surface']
    assert p.material_text.palette().color(QPalette.ColorRole.Text).name()==theme_colors(mode)['text']
p.close()
w.resize(640,480);w.open_settings('常规')
path='E:/University/Courses/2026/'+('LongCourseNameWithoutSpaces'*6)+'/录音'
w.settings_workspace.set_storage_root(path);settle_geometry(w)
area=w.settings_workspace.pages.currentWidget();viewport=area.viewport()
for button in area.findChildren(QPushButton):
    if button.text() in ('打开','更改…','查看最近删除'):
        left=button.mapTo(viewport,QPoint(0,0)).x()
        assert 0<=left and left+button.width()<=viewport.width(),(button.text(),left,button.width(),viewport.width())
assert w.settings_workspace.storage_path.text()==path
w.close()
''',tmp_path)


def test_material_page_starts_at_top_and_resize_preserves_reading_position(tmp_path):
    run_ui('''
from PySide6.QtGui import QImage
from linguaflow.knowledge.panel import KnowledgePanel
image=QImage(1200,1500,QImage.Format.Format_RGB32);image.fill(0xffffffff)
source=Path(os.environ['AGENTSCRIBE_LIBRARY'])/'page.png';assert image.save(str(source))
p=KnowledgePanel(w.knowledge_client,lambda:None,lambda:True,w)
p.receive({'type':'view','manifest':{'notes_cloud':False,'asr_context':{}},
 'course':{'id':'a','documents':[],'terms':[]},'blocks':[
 {'id':str(i),'document_id':'d','page':i+1,'title':'Page','text':'Original evidence',
  'version':'v1','evidence_type':'native','preview_image_path':str(source)} for i in range(2)],
 'sources':{},'notes':[],'pending':[],'event_seq':0,'notes_version':0,'reading_coverage':{},'busy':False})
p.show();p.resize(640,540);settle_geometry(p)
bar=p.material_text.verticalScrollBar()
assert bar.maximum()>100
assert bar.value()==0,('initial page scroll',bar.value())
bar.setValue(100);p.resize(860,680);settle_geometry(p)
assert bar.value()==100,('resize lost reading position',bar.value())
p.pages.setCurrentIndex(1);settle_geometry(p)
assert bar.value()==0,('new page scroll',bar.value())
p.close();w.close()
''',tmp_path)
