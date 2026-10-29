"""Confirm the selected desktop is ready in the original native launch process."""
import json
import os
import socket
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
    with tempfile.TemporaryDirectory(prefix='agentscribe-desktop-') as temporary, socket.socket() as listener:
        ready = Path(temporary) / 'ready.json'
        token = uuid4().hex
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.setblocking(False)
        environment = dict(env, AGENTSCRIBE_DESKTOP_READY=str(ready), AGENTSCRIBE_DESKTOP_READY_TOKEN=token,
                           AGENTSCRIBE_DESKTOP_LIFETIME=f'{listener.getsockname()[1]}:{token}')
        environment.pop('AGENTSCRIBE_STARTUP_TICKET', None)
        # Electron's Windows GUI process exposes an already-ended stdin even
        # when Python retains the pipe. A private loopback connection has the
        # same owner-death semantics on both platforms, without PID polling.
        with subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL) as child:
            channel = pending = None
            received = bytearray()
            expected = (token + '\n').encode('ascii')
            pending_since = 0.
            confirmed = False
            try:
                register_desktop_child(child.pid)
                while child.poll() is None:
                    if channel is None:
                        if pending is None:
                            try:
                                pending, _ = listener.accept()
                                pending.setblocking(False)
                                received.clear()
                                pending_since = time.monotonic()
                            except BlockingIOError:
                                pass
                        if pending is not None:
                            try:
                                fragment = pending.recv(len(expected) + 1)
                            except BlockingIOError:
                                fragment = None
                            except ConnectionError:
                                fragment = b''
                            if fragment:
                                received.extend(fragment)
                                if received == expected:
                                    channel, pending = pending, None
                                    listener.close()
                            if pending is not None and (fragment == b'' or not expected.startswith(received)
                                                       or time.monotonic() - pending_since > 2):
                                pending.close()
                                pending = None
                    if channel is not None and not confirmed and ready.is_file():
                        value = json.loads(ready.read_text(encoding='utf-8'))
                        if value != {'token': token, 'parent': child.pid}:
                            raise ValueError('桌面启动确认不属于当前应用。')
                        mark_startup_healthy()
                        confirmed = True
                    time.sleep(.05)
                return child.returncode
            finally:
                # Close before Popen waits, so startup errors also request the
                # desktop's ordinary save/close flow rather than hanging here.
                listener.close()
                if pending is not None:
                    pending.close()
                if channel is not None:
                    channel.close()
