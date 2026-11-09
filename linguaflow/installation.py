"""Shared owned commands, preparation locks and atomic component publication."""
import json
import os
import subprocess
from contextlib import contextmanager
from uuid import uuid4

from .os_lock import exclusive_lock
from .process_platform import spawn_options, stop_tree
from .runtime_paths import installation_command, python_environment, resource_root


def run_command(command, *, env=None, cwd=None, timeout=1800):
    """Bounded command with descendant ownership, including CLI interruption."""
    supervisor = installation_command('linguaflow.managed_process', *command)
    with subprocess.Popen(supervisor, stdin=subprocess.PIPE, env=env or python_environment(),
                          cwd=cwd or resource_root(), **spawn_options()) as process:
        try:
            code = process.wait(timeout=timeout)
            if code:
                raise subprocess.CalledProcessError(code, command)
        finally:
            process.stdin.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    stop_tree(process, force=True)
                    process.wait(timeout=5)


@contextmanager
def preparation_lock(directory):
    """OS releases the lock even if a cancelled preparation is forcibly killed."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'prepare.lock').open('a+b') as handle:
        lock = exclusive_lock(handle)
        try:
            lock.__enter__()
        except OSError as exc:
            raise RuntimeError('已有准备任务正在运行，请等待完成或取消后重试。') from exc
        try:
            yield
        finally:
            lock.__exit__(None, None, None)


def publish(pointer, value):
    """Only a successfully verified environment becomes visible to sessions."""
    temporary = pointer.with_name(pointer.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(pointer)
    finally:
        temporary.unlink(missing_ok=True)
