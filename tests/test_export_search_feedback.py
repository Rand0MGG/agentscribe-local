"""Export progress and searchable pagination keep completion boundaries visible."""
from test_beta_features import run_ui


def test_export_and_backup_feedback_tracks_queue_failure_and_cancel(tmp_path):
    run_ui(r'''
from threading import Event
from unittest.mock import patch
from linguaflow.core import Caption
import linguaflow.recording_export as exports
w.new_recording(name='Feedback', check_models=False)
w.on_caption(Caption(1,0,1,'Final words','en'))
entered, release = Event(), Event()
def held(*args):
    entered.set()
    assert release.wait(10)
def fail(*args):
    assert 'export' in w.notifications.notices
    raise OSError('controlled failure')
target = str(path.parent/'out.txt')
with patch.object(module.QFileDialog, 'getSaveFileName', return_value=('', '')):
    w.export(); w.backup_recording_text()
assert 'export' not in w.notifications.notices
with patch.object(module.QFileDialog, 'getSaveFileName', return_value=(target, '')), \
     patch.object(exports, 'write_export', side_effect=held), \
     patch.object(exports, 'write_recovery', side_effect=fail):
    try:
        w.export()
        wait(entered.is_set)
        notice = w.notifications.notices['export']
        assert notice.kind == 'progress' and notice.expires == float('inf')
        w.notifications.current_key = 'export'
        w.notifications._dismiss()
        expiry = notice.expires
        w.backup_recording_text()
        assert w.notifications.notices['export'].expires == expiry
        assert len(w.export_saver.pending) == 1
    finally:
        release.set()
    wait(lambda:not w.export_saver.busy)
assert 'export' not in w.notifications.notices
assert 'controlled failure' in w.notifications.notices['operation'].text
with patch.object(module.QFileDialog, 'getSaveFileName', return_value=(target, '')):
    w.backup_recording_text()
    assert w.notifications.notices['export'].expires == float('inf')
    wait(lambda:not w.export_saver.busy)
assert 'export' not in w.notifications.notices
assert '原录音的保存状态未改变' in w.notifications.notices['recovery'].text
w.close()
''', tmp_path)


def test_search_pagination_empty_and_query_reset(tmp_path):
    run_ui(r'''
from linguaflow.core import Caption
from linguaflow.recording_search import RecordingSearchDialog
captions = [Caption(i,i,i+1,'common '+str(i),'en','翻译') for i in range(205)]
d = RecordingSearchDialog(captions, w)
assert d.results.count() == 100 and '205' in d.summary.text()
assert not d.previous.isEnabled() and d.next.isEnabled()
d.next.click(); assert d.results.item(0).data(Qt.ItemDataRole.UserRole) == 100
d.next.click(); assert d.results.count() == 5 and not d.next.isEnabled()
d.previous.click(); assert d.results.count() == 100
d.query.setText('common 204'); d.search()
assert d.page == 0 and d.results.count() == 1
located=[]; d.located.connect(located.append)
d.choose(); assert located == [204]
d.query.setText('absent'); d.search()
assert '没有匹配' in d.summary.text() and not d.locate.isEnabled()
assert not d.previous.isEnabled() and not d.next.isEnabled()
empty = RecordingSearchDialog([],w)
assert '还没有字幕' in empty.summary.text()
empty.close(); d.close(); w.close()
''', tmp_path)
