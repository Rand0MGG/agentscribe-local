"""Coordinate capture segments without holding a device open while paused."""
from threading import Condition, Event


class CaptureControl:
    def __init__(self):
        self.condition = Condition()
        self.paused = False
        self.stopped = False
        self.segment = None
        self.waiting = False

    def pause(self):
        with self.condition:
            if self.stopped or self.paused:
                return False
            self.paused = True
            if self.segment is not None:
                self.segment.set()
            return True

    def resume(self):
        with self.condition:
            if self.stopped or not self.paused or not self.waiting:
                return False
            self.paused = False
            self.condition.notify_all()
            return True

    def stop(self):
        with self.condition:
            self.stopped = True
            if self.segment is not None:
                self.segment.set()
            self.condition.notify_all()

    def restart(self):
        """Release the current source before opening its replacement."""
        with self.condition:
            if self.stopped:
                return False
            if self.segment is not None:
                self.segment.set()
            return True

    def next_segment(self, on_pause, on_resume):
        with self.condition:
            if self.stopped:
                return None
            if not self.paused:
                # Do not leave a gap where pause can precede wait registration.
                self.segment = Event()
                return self.segment
            # The capture function has returned and released its device.
            self.waiting = True
        # Callbacks can flush the journal; never hold the UI control lock over IO.
        on_pause()
        with self.condition:
            while self.paused and not self.stopped:
                self.condition.wait()
            self.waiting = False
            if self.stopped:
                return None
            self.segment = Event()
            segment = self.segment
        on_resume()
        return segment

    def accept(self, write, segment=None):
        with self.condition:
            accepted = (not self.paused and not self.stopped
                        and (segment is None or (segment is self.segment and not segment.is_set())))
        # Capture delivers blocks serially. An admitted block finishes before the
        # capture function returns; pause/stop reject later blocks without waiting for IO.
        if accepted:
            write()
        return accepted
