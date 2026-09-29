from threading import Event, Thread

from linguaflow.capture_control import CaptureControl


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
