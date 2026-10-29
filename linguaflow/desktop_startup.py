"""Confirm the selected desktop is ready in the original native launch process."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4


def frontend_healthy(owner_pid=None):
    filename = os.environ.pop('AGENTSCRIBE_DESKTOP_READY', '')
    token = os.environ.pop('AGENTSCRIBE_DESKTOP_READY_TOKEN', '')
    if filename and token:
        from .update_recovery import write_json
        write_json(Path(filename), {'token': token, 'parent': os.getppid() if owner_pid is None else owner_pid})


def run_desktop(command, *, cwd, env):
    # The recovery ticket belongs to this launcher's PID. Never transfer it to
    # a child or mark healthy merely because the Electron process was spawned.
    from .process_platform import hold_installation_mutex
    from .runtime_paths import packaged
    from .update_recovery import mark_startup_healthy, register_desktop_child
    hold_installation_mutex(installed=packaged())
    with tempfile.TemporaryDirectory(prefix='agentscribe-desktop-') as temporary:
        ready = Path(temporary) / 'ready.json'
        token = uuid4().hex
        environment = dict(env, AGENTSCRIBE_DESKTOP_READY=str(ready), AGENTSCRIBE_DESKTOP_READY_TOKEN=token)
        environment.pop('AGENTSCRIBE_STARTUP_TICKET', None)
        with subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.PIPE) as child:
            register_desktop_child(child.pid)
            confirmed = False
            while child.poll() is None:
                if not confirmed and ready.is_file():
                    value = json.loads(ready.read_text(encoding='utf-8'))
                    if value != {'token': token, 'parent': child.pid}:
                        raise ValueError('桌面启动确认不属于当前应用。')
                    mark_startup_healthy()
                    confirmed = True
                time.sleep(.05)
            return child.returncode
