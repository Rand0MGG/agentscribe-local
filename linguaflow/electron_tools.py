"""Bounded calls to the already shipped desktop runtime; no business in the UI."""
import json
import os
import signal
import subprocess
import threading

from .frontend_switch import command_for
from .process_platform import close_process_pipes, spawn_options, stop_tree
from .runtime_paths import resource_root


def run_tool(script, argument, *, timeout=115, node=False):
    executable = command_for('electron')[0]
    environment = {**os.environ, 'AGENTSCRIBE_HELPER_OWNER_PID': str(os.getpid())}
    environment.pop('ELECTRON_RUN_AS_NODE', None)
    if node:
        environment['ELECTRON_RUN_AS_NODE'] = '1'
    process = subprocess.Popen([executable, str(resource_root() / 'desktop/electron' / script), str(argument)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, **spawn_options())
    previous_handler = None
    if os.name != 'nt' and threading.current_thread() is threading.main_thread():
        def cancelled(signum, _frame):
            raise SystemExit(128 + signum)
        previous_handler = signal.signal(signal.SIGTERM, cancelled)
    try:
        output, errors = process.communicate(timeout=timeout)
        if process.returncode:
            raise ValueError('本地渲染组件执行失败：' + errors.decode('utf-8', errors='replace')[-500:])
        return json.loads(output.decode('utf-8'))
    finally:
        # Descendants share this owned group, including a crashed browser's helpers.
        stop_tree(process, force=True)
        process.wait(timeout=5)
        close_process_pipes(process)
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
