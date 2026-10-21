"""Real desktop navigation, responsive reads and theme/path regressions, without audio."""
from ui_support import run_ui


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
