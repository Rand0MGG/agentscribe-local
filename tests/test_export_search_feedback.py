"""Export progress and searchable pagination keep completion boundaries visible."""
import pytest
from ui_support import run_ui


@pytest.mark.p1
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
