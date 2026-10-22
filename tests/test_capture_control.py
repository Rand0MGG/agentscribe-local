from threading import Condition, Event, Thread, current_thread

import pytest

from linguaflow.capture_control import CaptureControl


@pytest.mark.p1
def test_pause_at_source_handoff_registers_wait_or_cancels_new_segment():
    unlocked, proceed, paused = Event(), Event(), Event()

    class Handoff:
        def __init__(self):
            self.inner = Condition()
            self.first = True

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, *args):
            result = self.inner.__exit__(*args)
            if current_thread().name == 'capture-handoff' and self.first:
                self.first = False
                unlocked.set()
                assert proceed.wait(3)
            return result

        def wait(self):
            return self.inner.wait()

        def notify_all(self):
            self.inner.notify_all()

    control = CaptureControl()
    control.next_segment(lambda: None, lambda: None)
    control.restart()
    control.condition = Handoff()
    result = []

    def capture():
        segment = control.next_segment(paused.set, lambda: None)
        # Match the session loop: a cancelled segment cannot open a source.
        if segment is not None and segment.is_set():
            segment = control.next_segment(paused.set, lambda: None)
        result.append(segment)

    thread = Thread(target=capture, name='capture-handoff')
    thread.start()
    try:
        assert unlocked.wait(2)
        assert control.pause()
        proceed.set()
        assert paused.wait(1), 'paused capture never acknowledged its wait state'
        assert control.resume()
        thread.join(2)
        assert not thread.is_alive() and result[0] is not None and not result[0].is_set()
    finally:
        proceed.set()
        control.stop()
        thread.join(3)


@pytest.mark.p1
@pytest.mark.parametrize('action', ['pause', 'stop', 'restart'])
def test_control_returns_while_admitted_write_is_blocked(action):
    control = CaptureControl()
    segment = control.next_segment(lambda: None, lambda: None)
    entered, release, returned = Event(), Event(), Event()
    results = []

    def write():
        entered.set()
        assert release.wait(3)
        results.append('written')

    writer = Thread(target=lambda: results.append(control.accept(write, segment)))
    controller = Thread(target=lambda: (getattr(control, action)(), returned.set()))
    writer.start()
    try:
        assert entered.wait(2)
        controller.start()
        assert returned.wait(1), 'UI control waited for disk IO'
        assert not control.accept(lambda: results.append('late'), segment)
        assert results == []
    finally:
        release.set()
        writer.join(3)
        if controller.ident is not None:
            controller.join(3)
    assert results == ['written', True]


@pytest.mark.p1
def test_stop_does_not_wait_for_pause_journal_callback():
    control = CaptureControl()
    control.next_segment(lambda: None, lambda: None)
    control.pause()
    entered, release, returned = Event(), Event(), Event()
    result = []

    def paused():
        entered.set()
        assert release.wait(3)

    worker = Thread(target=lambda: result.append(control.next_segment(paused, lambda: None)))
    stopper = Thread(target=lambda: (control.stop(), returned.set()))
    worker.start()
    try:
        assert entered.wait(2)
        stopper.start()
        assert returned.wait(1)
    finally:
        release.set()
        worker.join(3)
        if stopper.ident is not None:
            stopper.join(3)
    assert result == [None]


@pytest.mark.p1
def test_source_restart_rejects_old_blocks_without_pausing_or_reopening_after_stop():
    control = CaptureControl()
    old = control.next_segment(lambda: None, lambda: None)
    assert control.restart() and old.is_set()
    assert not control.paused
    assert not control.accept(lambda: None, old)
    new = control.next_segment(lambda: None, lambda: None)
    assert control.accept(lambda: None, new)
    assert not control.accept(lambda: None, old)
    control.stop()
    assert not control.restart()
    assert not control.accept(lambda: None, new)
    assert control.next_segment(lambda: None, lambda: None) is None


@pytest.mark.p1
def test_pause_excludes_late_blocks_and_waits_for_device_release_before_resume():
    control = CaptureControl()
    paused, resumed = Event(), []
    segment = control.next_segment(lambda: None, lambda: None)
    assert control.accept(lambda: None)
    assert control.pause() and segment.is_set()
    assert not control.resume()
    assert not control.accept(lambda: (_ for _ in ()).throw(AssertionError('late audio')))
    result = []
    thread = Thread(target=lambda: result.append(control.next_segment(paused.set, lambda: resumed.append(True))))
    thread.start()
    try:
        assert paused.wait(2)
        assert control.resume()
        thread.join(2)
        assert not thread.is_alive() and result[0] is not segment and resumed == [True]
        assert not result[0].is_set()
    finally:
        control.stop()
        thread.join(2)


@pytest.mark.p1
def test_stopping_paused_capture_wakes_waiter_without_reopening():
    control = CaptureControl()
    control.next_segment(lambda: None, lambda: None)
    assert control.pause()
    paused, result = Event(), []
    thread = Thread(target=lambda: result.append(control.next_segment(paused.set,
                     lambda: (_ for _ in ()).throw(AssertionError('must not resume')))))
    thread.start()
    try:
        assert paused.wait(2)
        control.stop()
        thread.join(2)
        assert result == [None]
        assert not control.resume() and not control.pause()
    finally:
        control.stop()
        thread.join(2)
