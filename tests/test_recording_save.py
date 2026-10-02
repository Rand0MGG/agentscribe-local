"""Real disk writes with delayed/failing workers, without audio device access."""
from dataclasses import replace
from threading import Event, get_ident

from PySide6.QtCore import QCoreApplication, QTimer

from linguaflow.core import Caption
from linguaflow.library import Library
from linguaflow.recording_save import RecordingSaver


def test_serial_save_coalesces_revisions_freezes_input_and_keeps_qt_responsive(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    library = Library(tmp_path)
    item = library.create('inbox', {})
    saver = RecordingSaver()
    release, calls, results, ticks = Event(), [], [], []
    main_thread = get_ident()

    def write(item, captions, state):
        assert get_ident() != main_thread
        if not calls:
            assert release.wait(3)
        calls.append((captions[0].source, state))
        library.save(item, captions, state)

    def completed(snapshot, state, error):
        assert get_ident() == main_thread
        results.append((snapshot.revision, state, error))

    saver.completed.connect(completed)
    first = Caption(1, 0, 1, 'first', 'en')
    token = (1, item['id'])
    saver.submit(write, token, 1, item, [first])
    saver.submit(write, token, 2, item, [replace(first, source='superseded')])
    last = replace(first, source='latest', revision=3)
    saver.submit(write, token, 3, item, [last], 'complete')
    saver.submit(write, token, 3, item, [last])  # Automatic save cannot erase completion state.
    saver.submit(write, token, 2, item, [replace(first, source='late old request')])
    last.source = 'mutated after submit'
    QTimer.singleShot(10, lambda: ticks.append(True))
    QTimer.singleShot(20, release.set)
    try:
        assert saver.flush(3000)
    finally:
        release.set()
        saver.flush(3000)
    app.processEvents()
    assert ticks and calls == [('first', None), ('latest', 'complete')]
    assert results == [(1, 'draft', ''), (3, 'complete', '')]
    data, captions = library.load(item)
    assert data['session']['state'] == 'complete' and captions[0].source == 'latest'
    assert item['state'] == 'draft'  # Only the UI result handler updates its live item.


def test_save_failure_reports_error_retains_original_and_allows_explicit_retry(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    library = Library(tmp_path)
    item = library.create('inbox', {})
    first = Caption(1, 0, 1, 'saved', 'en')
    library.save(item, [first])
    saver, results = RecordingSaver(), []
    saver.completed.connect(lambda *values: results.append(values))

    def fail(*args):
        raise OSError('disk unavailable')

    saver.submit(fail, (1, item['id']), 2, item, [replace(first, source='new')])
    assert saver.flush(3000)
    assert 'disk unavailable' in results[-1][2]
    assert library.load(item)[1][0].source == 'saved'
    saver.submit(library.save, (1, item['id']), 2, item, [replace(first, source='new')], 'complete')
    assert saver.flush(3000) and not results[-1][2]
    assert library.load(item)[1][0].source == 'new'
    app.processEvents()


def test_timeout_retains_job_and_ignores_older_revision_of_active_save(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    saver, release, results = RecordingSaver(), Event(), []
    saver.completed.connect(lambda *values: results.append(values))

    def write(item, captions, state):
        assert release.wait(3)
        item['state'] = state

    item = {'id': 'one', 'state': 'recording'}
    saver.submit(write, (1, 'one'), 3, item, [Caption(1, 0, 1, 'new', 'en')], 'complete')
    saver.submit(write, (1, 'one'), 2, item, [Caption(1, 0, 1, 'old', 'en')])
    try:
        assert not saver.flush(20)
        assert saver.busy and not saver.waiting
    finally:
        release.set()
        assert saver.flush(3000)
    app.processEvents()
    assert len(results) == 1 and results[0][0].revision == 3
