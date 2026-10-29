"""Owned backend events, timers and workers using only the Python standard library.

All callbacks run on the dispatcher's owner thread. Worker results are queued;
shutdown waits retain ownership until the actual worker exits. No UI toolkit is
imported here. A native host can supply a pump (Cocoa for Sparkle on macOS).
"""
import heapq
import itertools
import sys
import threading
import time
from enum import IntEnum


class Connection(IntEnum):
    Auto = 0
    Queued = 1


class Dispatcher:
    _current = None

    def __init__(self, *_):
        self.owner = threading.get_ident()
        self.condition = threading.Condition()
        self.pending = []
        self.sequence = itertools.count()
        self.stopped = False
        self.native_pump = None
        self._pumping = False
        Dispatcher._current = self

    @classmethod
    def instance(cls):
        if cls._current is None:
            cls._current = cls()
        return cls._current

    def call(self, callback, delay=0):
        with self.condition:
            heapq.heappush(self.pending, (time.monotonic() + max(0, delay), next(self.sequence), callback))
            self.condition.notify()

    def process(self, wait=0):
        if threading.get_ident() != self.owner:
            raise RuntimeError('Backend events must run on their owner thread')
        deadline = time.monotonic() + wait
        while True:
            with self.condition:
                now = time.monotonic()
                if self.pending and self.pending[0][0] <= now:
                    callback = heapq.heappop(self.pending)[2]
                else:
                    if now >= deadline or self.stopped:
                        return
                    delay = min(deadline - now, max(0, self.pending[0][0] - now) if self.pending else wait)
                    self.condition.wait(delay)
                    continue
            try:
                callback()
            except Exception:
                sys.excepthook(*sys.exc_info())
            self.pump_native()

    def pump_native(self):
        if self.native_pump and not self._pumping:
            self._pumping = True
            try:
                self.native_pump()
            finally:
                self._pumping = False

    def exec(self):
        self.stopped = False
        while not self.stopped:
            self.process(.01 if self.native_pump else .05)
            self.pump_native()
        return 0

    def quit(self):
        self.stopped = True
        with self.condition:
            self.condition.notify_all()


class BoundSignal:
    def __init__(self, owner):
        self.owner = owner
        self.listeners = []

    def connect(self, callback, connection=Connection.Auto):
        if hasattr(callback, 'emit'):
            callback = callback.emit
        self.listeners.append((callback, connection))

    def disconnect(self, callback=None):
        if hasattr(callback, 'emit'):
            callback = callback.emit
        self.listeners[:] = [(fn, mode) for fn, mode in self.listeners if callback is not None and fn != callback]

    def emit(self, *args):
        dispatcher = self.owner.dispatcher
        for callback, mode in tuple(self.listeners):
            def deliver(callback=callback):
                receiver = getattr(callback, "__self__", None)
                if not self.owner.disposed and not getattr(receiver, "disposed", False):
                    callback(*args)
            if mode == Connection.Queued or threading.get_ident() != dispatcher.owner:
                dispatcher.call(deliver)
            else:
                deliver()

    __call__ = emit


class Signal:
    def __init__(self, *_):
        pass

    def __set_name__(self, owner, name):
        self.name = '_signal_' + name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        if self.name not in instance.__dict__:
            instance.__dict__[self.name] = BoundSignal(instance)
        return instance.__dict__[self.name]


class Owner:
    def __init__(self, parent=None):
        self.dispatcher = getattr(parent, 'dispatcher', None) or Dispatcher.instance()
        self.disposed = False
        self.children = []
        self.parent = parent if isinstance(parent, Owner) else None
        if isinstance(parent, Owner):
            parent.children.append(self)

    def deleteLater(self):
        self.dispatcher.call(self.dispose)

    def dispose(self):
        self.disposed = True
        for child in tuple(self.children):
            child.dispose()
        self.children.clear()
        if self.parent is not None:
            self.parent.children.remove(self)
            self.parent = None
        for value in self.__dict__.values():
            if isinstance(value, BoundSignal):
                value.disconnect()


class Timer(Owner):
    timeout = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.interval = 0
        self.single = False
        self.active = False
        self.generation = 0

    def setInterval(self, milliseconds):
        self.interval = milliseconds

    def setSingleShot(self, single):
        self.single = single

    def isActive(self):
        return self.active

    def start(self, milliseconds=None):
        if milliseconds is not None:
            self.interval = milliseconds
        self.stop()
        self.active = True
        generation = self.generation

        def fire():
            if self.disposed or not self.active or generation != self.generation:
                return
            if self.single:
                self.active = False
            self.timeout.emit()
            if self.active and generation == self.generation:
                self.dispatcher.call(fire, max(.001, self.interval / 1000))
        self.dispatcher.call(fire, self.interval / 1000)

    def stop(self):
        self.active = False
        self.generation += 1

    def dispose(self):
        self.stop()
        super().dispose()

    @staticmethod
    def singleShot(milliseconds, callback):
        Dispatcher.instance().call(callback, milliseconds / 1000)


class Worker(Owner):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def start(self):
        if self.isRunning():
            raise RuntimeError('Worker is already running')
        def run():
            try:
                self.run()
            finally:
                self.finished.emit()
        self._worker = threading.Thread(target=run, name=type(self).__name__)
        self._worker.start()

    def run(self):
        raise NotImplementedError

    def isRunning(self):
        return self._worker is not None and self._worker.is_alive()

    def wait(self, milliseconds=None):
        if self._worker is not None and self._worker.ident is not None:
            self._worker.join(None if milliseconds is None else milliseconds / 1000)
        return not self.isRunning()

    def dispose(self):
        if self.isRunning():
            raise RuntimeError('Cannot release a running worker')
        super().dispose()


class WaitLoop:
    """Bounded callers supply their own timer; keep processing owned results."""
    def __init__(self):
        self.stopped = False

    def quit(self):
        self.stopped = True

    def exec(self):
        dispatcher = Dispatcher.instance()
        while not self.stopped and not dispatcher.stopped:
            dispatcher.process(.01)
            dispatcher.pump_native()
