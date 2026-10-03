"""Own one prepared inference process; desktop code never imports model libraries."""
import atexit
import json
import os
import subprocess
from collections import deque
from pathlib import Path
from threading import Event, Lock, Thread, Timer

from .runtime_paths import runtime_python


class PreparedWorker:
    timeout = 180.

    def __init__(self, python):
        self.process = None
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
            self.error = RuntimeError('运行环境准备超时，请在模型管理中检查运行环境。')
            self.close()

    def start(self, python):
        try:
            with self.lock:
                if self.closed.is_set():
                    return
                self.process = subprocess.Popen(
                    [str(python), '-u', '-m', 'linguaflow.wlk_worker', '--prepared'],
                    cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.diagnostics = Thread(target=self.read_logs, daemon=True)
            self.diagnostics.start()
            self.read_ready()
        except Exception as exc:
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
            if cancelled.is_set() or self.closed.is_set():
                raise RuntimeError('运行环境准备已取消。')
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
        self.ready.clear()
        self.error = None
        def read():
            try:
                self.read_ready()
            except Exception as exc:
                self.error = exc
            finally:
                self.ready.set()
        self.reader = Thread(target=read, daemon=True)
        self.reader.start()
        self.wait(self.closed)

    def close(self):
        self.closed.set()
        self.ready.set()
        with self.close_lock:
            with self.lock:
                process = self.process
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            self.reader.join(timeout=2)
            diagnostics = getattr(self, 'diagnostics', None)
            if diagnostics:
                diagnostics.join(timeout=2)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if not pipe.closed:
                    pipe.close()


class RuntimePreparation:
    """One exclusive lease; successful sessions release weights and retain imports."""
    idle_timeout = 30 * 60.

    def __init__(self):
        self.lock = Lock()
        self.worker = None
        self.busy = False
        self.closed = False
        self.idle_timer = None
        atexit.register(self.close)

    def prepare(self):
        with self.lock:
            if self.closed or self.worker is not None:
                return
            python = runtime_python()
            if python.is_file():
                self.worker = PreparedWorker(python)
                self.arm_idle(self.worker)

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
        self.prepare()
        with self.lock:
            if self.closed:
                raise RuntimeError('推理运行环境已关闭。')
            if self.busy:
                raise RuntimeError('推理运行环境正在处理另一会话。')
            worker = self.worker
            if worker is None:
                return None
            self.busy = True
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
        try:
            worker.wait(cancelled)
            return worker
        except BaseException:
            self.release(worker, reusable=False)
            raise

    def release(self, worker, reusable):
        try:
            if reusable and not self.closed:
                worker.settle()
            else:
                worker.close()
        except BaseException:
            worker.close()
            reusable = False
            raise
        finally:
            with self.lock:
                self.busy = False
                if not reusable or self.closed:
                    if self.worker is worker:
                        self.worker = None
                else:
                    self.arm_idle(worker)

    def close(self, wait=True):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            worker, self.worker = self.worker, None
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
        atexit.unregister(self.close)
        if worker:
            if wait:
                worker.close()
            else:
                # Non-daemon cleanup finishes even after Qt's event loop exits.
                Thread(target=worker.close).start()
