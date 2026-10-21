"""Own one prepared inference process; desktop code never imports model libraries."""
import atexit
import json
import subprocess
from collections import deque
from threading import Event, Lock, Thread, Timer

from . import diagnostic_log as diag
from .process_platform import close_process_transport, start_worker, stop_worker
from .runtime_paths import python_environment, resource_root, runtime_python


class PreparedWorker:
    timeout = 180.

    def __init__(self, python):
        self.python = python
        self.process = None
        self.job = None
        self.error = None
        self.ready = Event()
        self.closed = Event()
        self.lock = Lock()
        self.close_lock = Lock()
        self.logs = deque(maxlen=128)
        self.log_lock = Lock()
        self.log_serial = 0
        self.reader = Thread(target=self.start, args=(python,), daemon=True)
        self.reader.start()
        Thread(target=self.watch_startup, daemon=True).start()

    def watch_startup(self):
        if not self.ready.wait(self.timeout):
            with self.lock:
                if self.closed.is_set() or self.ready.is_set():
                    return
                self.error = RuntimeError('运行环境准备超时，请在模型管理中检查运行环境。')
            self.close()

    def start(self, python):
        try:
            with self.lock:
                if self.closed.is_set():
                    return
                self.process, self.job = start_worker(
                    python, 'linguaflow.wlk_worker',
                    cwd=resource_root(), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                    env=python_environment())
            self.diagnostics = Thread(target=self.read_logs, daemon=True)
            self.diagnostics.start()
            self.read_ready()
        except Exception as exc:
            diag.exception('runtime_start_exception', exc)
            if self.error is None:
                self.error = exc
        finally:
            self.ready.set()

    def read_logs(self):
        for line in self.process.stderr:
            if line.strip():
                with self.log_lock:
                    self.log_serial += 1
                    self.logs.append((self.log_serial, line.strip()))

    def read_ready(self):
        for line in self.process.stdout:
            message = json.loads(line)
            if message['type'] == 'runtime_ready':
                return
            if message['type'] == 'error':
                raise RuntimeError(message['text'])
        raise RuntimeError('推理运行环境已退出，请在模型管理中检查运行环境。')

    def wait(self, cancelled):
        # The caller runs on Session's thread, never the Qt interface thread.
        import time
        deadline = time.monotonic() + self.timeout
        while not self.ready.wait(.05):
            if cancelled.is_set():
                raise RuntimeError('运行环境准备已取消。')
            if self.closed.is_set():
                # Watchdog cleanup must preserve its recorded failure reason.
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('运行环境准备超时，请在模型管理中检查运行环境。')
        if self.error:
            raise RuntimeError('运行环境准备失败：' + str(self.error)) from self.error
        if cancelled.is_set() or self.closed.is_set() or self.process.poll() is not None:
            raise RuntimeError('运行环境准备已取消或进程已退出。')
        self.reader.join()
        return self.process

    def recent_logs(self, after=0):
        with self.log_lock:
            return [(serial, text) for serial, text in self.logs if serial > after]

    def settle(self):
        """Wait for the post-session marker, emitted only after model cleanup."""
        def read():
            try:
                self.read_ready()
            except Exception as exc:
                self.error = exc
            finally:
                self.ready.set()
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError('推理运行环境已关闭。')
            self.ready.clear()
            self.error = None
            self.reader = Thread(target=read, daemon=True)
            self.reader.start()
        self.wait(self.closed)

    def _readers(self):
        yield self.reader
        diagnostics = getattr(self, 'diagnostics', None)
        if diagnostics:
            yield diagnostics

    def close(self):
        with self.lock:
            self.closed.set()
            self.ready.set()
        with self.close_lock:
            with self.lock:
                process = self.process
                job = self.job
            stop_worker(process, job, self._readers())
            if process is None:
                return
            close_process_transport(process, self._readers(), timeout=2,
                error='推理管道读取线程未退出；已保留资源，不能安全关闭管道。')


class RuntimePreparation:
    """One exclusive lease; successful sessions release weights and retain imports."""
    idle_timeout = 30 * 60.

    def __init__(self):
        self.lock = Lock()
        self.close_lock = Lock()
        self.worker = None
        self.busy = False
        self.closed = False
        self.idle_timer = None
        atexit.register(self.close)

    def prepare(self):
        """Prepare imports asynchronously without changing user inference devices."""
        with self.lock:
            if self.closed or self.busy:
                return
            previous = self._prepare_locked()
        if previous:
            Thread(target=previous.close).start()

    def _prepare_locked(self):
        """Return a replaced idle worker; caller cleans up outside the lock."""
        python = runtime_python()
        if (self.worker is not None and self.worker.python == python
                and self.worker.error is None and not self.worker.closed.is_set()
                and (self.worker.process is None or self.worker.process.poll() is None)):
            return None
        previous, self.worker = self.worker, None
        if self.idle_timer:
            self.idle_timer.cancel()
            self.idle_timer = None
        if python.is_file():
            self.worker = PreparedWorker(python)
            self.arm_idle(self.worker)
        return previous

    def arm_idle(self, worker):
        # Called under the pool lock. An active session always cancels this timer.
        if self.idle_timer:
            self.idle_timer.cancel()
        self.idle_timer = Timer(self.idle_timeout, self.expire, args=(worker,))
        self.idle_timer.daemon = True
        self.idle_timer.start()

    def expire(self, worker):
        with self.lock:
            if self.closed or self.busy or self.worker is not worker:
                return
            self.worker = None
            self.idle_timer = None
        worker.close()

    def acquire(self, cancelled):
        """Lease the prepared process, replacing a failed or exited worker."""
        with self.lock:
            if self.closed:
                raise RuntimeError('推理运行环境已关闭。')
            if self.busy:
                raise RuntimeError('推理运行环境正在处理另一会话。')
            previous = self._prepare_locked()
            worker = self.worker
            if worker is None:
                if previous:
                    Thread(target=previous.close).start()
                raise RuntimeError('推理运行环境未安装，请在识别模型设置中准备运行环境。')
            self.busy = True
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
        try:
            if previous:
                previous.close()
            worker.wait(cancelled)
            return worker
        except BaseException:
            self.release(worker, reusable=False)
            raise

    def release(self, worker, reusable):
        cleaned = False
        try:
            if reusable and not self.closed:
                try:
                    worker.settle()
                except BaseException:
                    reusable = False
                    worker.close()
                    cleaned = True
                    raise
            else:
                reusable = False
                worker.close()
                cleaned = True
        finally:
            with self.lock:
                self.busy = False
                if not reusable or self.closed:
                    if cleaned and self.worker is worker:
                        self.worker = None
                else:
                    self.arm_idle(worker)

    def close(self, wait=True):
        with self.lock:
            self.closed = True
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
        if wait:
            self._close_worker()
        else:
            # Non-daemon cleanup finishes even after Qt's event loop exits.
            Thread(target=self._close_worker).start()

    def _close_worker(self):
        # Serialize synchronous retries with an outstanding asynchronous close.
        with self.close_lock:
            with self.lock:
                worker = self.worker
            if worker:
                worker.close()
                with self.lock:
                    if self.worker is worker:
                        self.worker = None
            atexit.unregister(self.close)
