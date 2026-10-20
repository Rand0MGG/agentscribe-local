"""Owned preparation task: subprocess supervision, progress and cancellation."""
import json
import re
import subprocess
from collections import deque
from threading import Event, Thread
from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from . import diagnostic_log as diag
from .download_progress import PREFIX
from .process_platform import spawn_options, stop_tree
from .runtime_paths import installation_command, python_environment, resource_root


def preparation_error_message(text):
    """Keep a bounded step/reason in the UI; the caller retains the raw diagnostic."""
    lines = [line.strip() for line in text.removeprefix('未完成：').splitlines() if line.strip()]
    stage = lines[0] if len(lines) > 1 else '准备模型与组件'
    reason = lines[-1] if lines else '准备任务未正常结束'
    for line in reversed(lines):
        if re.match(r'[\w.]+(?:Error|Exception):', line):
            reason = line
            break
    lowered = reason.lower()
    if any(word in lowered for word in ('connectionerror', 'connecterror', 'readtimeout', 'connecttimeout',
                                       'nameresolutionerror', 'cannot connect', 'connection refused')):
        reason = '网络连接失败或超时，请检查网络后重试。'
    elif 'no space left' in lowered:
        reason = '磁盘空间不足，请释放空间后重试。'
    elif 'permissionerror' in lowered or 'permission denied' in lowered:
        reason = '没有写入权限，请检查模型保存目录的权限。'
    else:
        reason = re.sub(r'^[\w.]+(?:Error|Exception):\s*', '', reason)
    return f'准备未完成：{stage[:40]}；{reason[:120]} 已下载文件保留，可重新检查。'


class Preparation(QThread):
    result = Signal(str)
    download = Signal(dict)

    def __init__(self, action, parent, *, affects_runtime=True, beta_only=False):
        super().__init__(parent)
        self.action = action
        self.affects_runtime = affects_runtime
        self.beta_only = beta_only
        self.process = None
        self.cancelled = False
        self.stage = '准备本地模型与组件'
        self.log_task = uuid4().hex

    def cancel(self):
        if not self.cancelled:
            diag.event('preparation_cancel_requested', task_id=self.log_task)
        self.cancelled = True

    def run(self):
        outcome = 'success'
        diag.event('preparation_started', task_id=self.log_task, affects_runtime=self.affects_runtime,
                   beta_only=self.beta_only)
        try:
            result = self.action()
            self.result.emit('准备已取消；已完成文件保留。' if self.cancelled else result)
        except Exception as exc:
            outcome = 'failed'
            if not self.cancelled:
                diag.exception('preparation_exception', exc, task_id=self.log_task)
            self.result.emit('准备已取消；已完成文件保留。' if self.cancelled else
                             f"未完成：{self.stage}\n{exc}")
        finally:
            diag.event('preparation_finished', task_id=self.log_task,
                       outcome='cancelled' if self.cancelled else outcome)

    def run_command(self, command, *, show_progress=True):
        if self.cancelled:
            raise RuntimeError('准备已取消。')
        tail = deque(maxlen=20)
        if show_progress:
            self.download.emit(dict(label='准备组件', unit='stage'))
        # The supervisor owns descendants even when the desktop exits unexpectedly.
        command = installation_command('linguaflow.managed_process', *command)
        with subprocess.Popen(command, cwd=resource_root(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              env=python_environment(),
                              **spawn_options()) as process:
            self.process = process
            finished = Event()
            def watch():
                while not finished.wait(.05):
                    if self.cancelled:
                        process.stdin.close()  # EOF lets the supervisor reap its tree.
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            stop_tree(process, force=True)
                        return
            watcher = Thread(target=watch, daemon=True)
            watcher.start()
            try:
                for line in process.stdout:
                    if line.strip():
                        if line.startswith(PREFIX):
                            try:
                                event = json.loads(line[len(PREFIX):])
                                if isinstance(event, dict):
                                    if event.get('unit') == 'stage' and event.get('label'):
                                        self.stage = str(event['label'])
                                    self.download.emit(event)
                                    continue
                            except ValueError:
                                pass
                        tail.append(line.strip())
                code = process.wait(timeout=10)
                if self.cancelled:
                    raise RuntimeError('准备已取消；已有文件保留，可稍后继续。')
                if code:
                    raise RuntimeError("\n".join(tail)[-1500:] or f'准备进程异常结束（退出码 {code}）')
            finally:
                finished.set()
                watcher.join(timeout=10)
                self.process = None
        return tail[-1] if tail else "准备完成"
