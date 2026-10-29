"""Startup recovery, shared by both native updaters.

The watcher uses a retained stdlib-only interpreter outside the replaced app.
Normal download/install remains Sparkle's responsibility. A native primitive
restores the whole previous app only after the owned failed startup has exited.
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp-' + uuid4().hex)
    with temporary.open('x', encoding='utf-8') as output:
        json.dump(value, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def inventory(root):
    files, links = {}, {}
    if root.is_symlink() or not root.is_dir():
        raise ValueError('保留的应用目录无效。')
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('应用包含外部链接。')
            links[name] = os.readlink(path)
        elif path.is_file():
            files[name] = checksum(path)
    return files, links


class NativeRecovery:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.library.ASProcessStamp.argtypes = [ctypes.c_ulong]
        self.library.ASProcessStamp.restype = ctypes.c_uint64
        self.library.ASStopStartup.argtypes = [ctypes.c_ulong, ctypes.c_uint64]
        self.library.ASStopStartup.restype = ctypes.c_int
        self.library.ASRecoverySwap.argtypes = [ctypes.c_char_p] * 3
        self.library.ASRecoverySwap.restype = ctypes.c_int

    def stamp(self, pid):
        return self.library.ASProcessStamp(pid)

    def stop(self, pid, stamp):
        return bool(self.library.ASStopStartup(pid, stamp))

    def restore(self, installed, backup, failed):
        return bool(self.library.ASRecoverySwap(*(str(path).encode('utf-8') for path in (installed, backup, failed))))


def read_state(directory):
    state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    token = state['token']
    installed, backup, failed = (Path(state[key]) for key in ('installed', 'backup', 'failed'))
    if (token != directory.name or len(token) != 32 or any(c not in '0123456789abcdef' for c in token)
            or not installed.is_absolute() or installed.is_symlink() or installed.parent == installed
            or backup != installed.parent / ('.AgentScribe-previous-' + token)
            or failed != installed.parent / ('.AgentScribe-failed-' + token)):
        raise ValueError('更新恢复记录无效，未修改应用。')
    native = directory / ('recovery.dll' if os.name == 'nt' else 'recovery.dylib')
    if native.is_symlink() or checksum(native) != state['native_sha256']:
        raise ValueError('更新恢复组件校验失败，未修改应用。')
    return state, native


def clear_pending(directory):
    pending = directory.parent / 'pending.json'
    try:
        if json.loads(pending.read_text())['token'] == directory.name:
            pending.unlink()
    except FileNotFoundError:
        pass


def retire_older_backups(updates, installed, current):
    """Keep the newest verified previous app; retain failures/manual evidence."""
    for directory in updates.iterdir():
        if directory == current or not directory.is_dir() or directory.is_symlink():
            continue
        try:
            state, _ = read_state(directory)
            backup = Path(state['backup'])
            if (Path(state['installed']) == installed and state['status'] in ('healthy', 'cancelled')
                    and backup.is_dir() and inventory(backup) == (state['files'], state['links'])):
                shutil.rmtree(backup)
                state['status'] = 'retired'
                write_json(directory / 'state.json', state)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Changed or failed packages are never removed automatically.


class UpdateRecovery:
    """Called in the shared shutdown thread; errors prevent installation."""
    def __init__(self, resources, target, version):
        self.resources, self.target, self.version = Path(resources), target, version
        self.directory = None
        self.process = None
        self.owned_backup = None

    def prepare(self):
        try:
            self._prepare()
        except Exception:
            self.cancel()
            if self.directory:
                clear_pending(self.directory)
            if self.owned_backup and not (self.directory / 'state.json').exists():
                shutil.rmtree(self.owned_backup, ignore_errors=True)
            raise

    def _prepare(self):
        from .runtime_base import prepare_base
        from .runtime_paths import user_data_root
        installed = (self.resources.parent.parent if self.target == 'macos-arm64' else self.resources).resolve()
        updates = user_data_root() / 'updates'
        updates.mkdir(parents=True, exist_ok=True, mode=0o700)
        pending = updates / 'pending.json'
        if pending.exists():
            raise ValueError('上一次更新尚未结束，请先完成恢复后再更新。')
        token = uuid4().hex
        directory = updates / token
        directory.mkdir(mode=0o700)
        self.directory = directory
        backup = installed.parent / ('.AgentScribe-previous-' + token)
        failed = installed.parent / ('.AgentScribe-failed-' + token)
        if not os.access(installed.parent, os.W_OK):
            raise PermissionError('应用所在目录不可写，请将应用安装到可写位置后再更新。')
        binary = (self.resources.parent / 'Frameworks/AgentScribeRecovery.dylib' if os.name != 'nt'
                  else self.resources / 'AgentScribeRecovery.dll')
        native = directory / ('recovery.dll' if os.name == 'nt' else 'recovery.dylib')
        shutil.copy2(binary, native)
        implementation = NativeRecovery(native)
        stamp = implementation.stamp(os.getpid())
        if not stamp:
            raise RuntimeError('无法确认当前应用进程，更新未开始。')
        # Keep only a complete base interpreter, not all desktop dependencies.
        source = (self.resources / 'python').resolve()
        executable = source / ('python.exe' if os.name == 'nt' else 'bin/python3')
        interpreter, _ = prepare_base(source, updates / 'python', executable)
        required = sum(path.stat().st_size for path in installed.rglob('*')
                       if path.is_file() and not path.is_symlink())
        if shutil.disk_usage(installed.parent).free < required + 64 * 1024**2:
            raise OSError('磁盘空间不足以保留旧版，更新未开始。')
        # A unique name is claimed before copying; never remove a preexisting
        # directory if this preparation fails.
        backup.mkdir()
        self.owned_backup = backup
        shutil.copytree(installed, backup, symlinks=True, dirs_exist_ok=True)
        # Compare the complete regular-file inventory; symlinks must preserve
        # their target and stay inside this application bundle.
        files, links = inventory(installed)
        if inventory(backup) != (files, links):
            raise ValueError('旧版保留校验失败，更新未开始。')
        write_json(directory / 'state.json', dict(token=token, installed=str(installed), backup=str(backup),
                   failed=str(failed), target=self.target, previous_version=self.version, status='prepared',
                   old_pid=os.getpid(), old_stamp=stamp, files=files, links=links, native_sha256=checksum(native)))
        retire_older_backups(updates, installed, directory)
        shutil.copy2(__file__, directory / 'watcher.py')
        write_json(pending, {'token': token})
        # Windows close-on-exec and its own process group keep the watcher
        # independent of runtime worker ownership. It never accesses audio.
        environment = {**os.environ, 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        for key in ('PYTHONHOME', 'PYTHONPATH', 'AGENTSCRIBE_PACKAGED', 'AGENTSCRIBE_RESOURCES'):
            environment.pop(key, None)
        options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        with (directory / 'watcher.log').open('ab') as output:
            self.process = subprocess.Popen([str(interpreter), '-I', str(directory / 'watcher.py'),
                                           '--watch', str(directory)], env=environment,
                                           stdin=subprocess.DEVNULL, stdout=output, stderr=output, **options)
        deadline = time.monotonic() + 10
        while not (directory / 'watching').is_file():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('独立更新恢复进程未启动，安装未开始。')
            time.sleep(.05)

    def cancel(self):
        if self.directory and (self.directory / 'state.json').is_file():
            (self.directory / 'cancelled').touch()


def startup():
    """Register before importing Qt; retained watcher can identify a crash."""
    from . import __version__
    from .runtime_paths import packaged, resource_root, user_data_root
    if not packaged():
        return
    updates = user_data_root() / 'updates'
    try:
        token = json.loads((updates / 'pending.json').read_text())['token']
        if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError('更新启动标识无效。')
        directory = updates / token
        state, native = read_state(directory)
        resources = resource_root().resolve()
        actual = resources.parent.parent if state['target'] == 'macos-arm64' else resources
        if actual != Path(state['installed']):
            return
        stamp = NativeRecovery(native).stamp(os.getpid())
        name = 'unchanged.json' if __version__ == state['previous_version'] else 'startup.json'
        write_json(directory / name, {'pid': os.getpid(), 'stamp': stamp, 'version': __version__})
        if name == 'unchanged.json':
            return  # Never restore underneath a relaunched, usable old app.
        os.environ['AGENTSCRIBE_STARTUP_TICKET'] = str(directory)
    except (OSError, ValueError, KeyError, TypeError):
        return


def register_desktop_child(pid):
    """Retain Electron ownership before allowing a failed startup to be restored."""
    ticket = os.environ.get('AGENTSCRIBE_STARTUP_TICKET')
    if not ticket:
        return
    directory = Path(ticket)
    _, native = read_state(directory)
    record = json.loads((directory / 'startup.json').read_text())
    if record['pid'] != os.getpid():
        raise ValueError('更新启动进程不一致。')
    stamp = NativeRecovery(native).stamp(pid)
    if not stamp:
        raise ValueError('无法确认桌面启动进程。')
    write_json(directory / 'desktop.json', {'owner': record, 'pid': pid, 'stamp': stamp})


def mark_startup_healthy():
    """The desktop has shown successfully, before model/environment preparation."""
    ticket = os.environ.pop('AGENTSCRIBE_STARTUP_TICKET', '')
    if ticket:
        directory = Path(ticket)
        read_state(directory)
        record = json.loads((directory / 'startup.json').read_text())
        if record['pid'] != os.getpid():
            raise ValueError('更新启动进程不一致。')
        write_json(directory / 'healthy.json', record)
        return True
    return False


def take_recovery_notice():
    from . import __version__
    from .runtime_paths import packaged, user_data_root
    if not packaged():
        return None
    notice = user_data_root() / 'updates/notice.json'
    try:
        value = json.loads(notice.read_text())
        state, _ = read_state(notice.parent / value['token'])
        if state['status'] == 'restored' and value['version'] == __version__:
            notice.unlink()
            return {'stage': 'error', 'text': '新版启动未完成，已恢复上一版本。录音与模型保留。',
                    'details': '未能启动的候选包保留在：' + state['failed']}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def watch(directory, *, startup_timeout=90, exit_timeout=900, relaunch=True):
    state, native = read_state(directory)
    implementation = NativeRecovery(native)
    (directory / 'watching').touch()
    started = time.monotonic()
    while implementation.stamp(state['old_pid']) == state['old_stamp']:
        if (directory / 'cancelled').exists() or time.monotonic()-started >= exit_timeout:
            state['status'] = 'cancelled'
            write_json(directory / 'state.json', state)
            clear_pending(directory)
            return 'cancelled'
        time.sleep(.25)
    deadline = time.monotonic() + startup_timeout
    startup_record = None
    while time.monotonic() < deadline:
        if (directory / 'cancelled').exists() or (directory / 'unchanged.json').exists():
            state['status'] = 'cancelled'
            write_json(directory / 'state.json', state)
            clear_pending(directory)
            return 'cancelled'
        try:
            record = json.loads((directory / 'startup.json').read_text())
            if record.get('stamp') and record.get('version') != state['previous_version']:
                startup_record = record
                if json.loads((directory / 'healthy.json').read_text()) == record:
                    state['status'] = 'healthy'
                    write_json(directory / 'state.json', state)
                    clear_pending(directory)
                    return 'healthy'
        except FileNotFoundError:
            pass
        if startup_record and implementation.stamp(startup_record['pid']) != startup_record['stamp']:
            break
        time.sleep(.25)
    if startup_record is None:
        # We cannot establish ownership/liveness of a process that failed even
        # before Python bootstrap. Keep both packages for manual recovery.
        state['status'] = 'manual-recovery'
        write_json(directory / 'state.json', state)
        clear_pending(directory)
        return 'manual-recovery'
    if startup_record and implementation.stamp(startup_record['pid']) == startup_record['stamp']:
        if not implementation.stop(startup_record['pid'], startup_record['stamp']):
            raise RuntimeError('无法停止本次未成功启动的进程；旧版保留，未恢复应用。')
        deadline = time.monotonic() + 10
        while implementation.stamp(startup_record['pid']) == startup_record['stamp'] and time.monotonic() < deadline:
            time.sleep(.1)
        if implementation.stamp(startup_record['pid']) == startup_record['stamp']:
            raise RuntimeError('本次启动进程尚未退出，旧版保留，未恢复应用。')
    # A secondary desktop may still hold executable files after its launcher
    # failed. Never restore underneath it; retain both packages if it cannot exit.
    desktop_file = directory / 'desktop.json'
    if desktop_file.exists():
        desktop = json.loads(desktop_file.read_text())
        if desktop.get('owner') != startup_record:
            raise ValueError('桌面进程归属不一致，未自动恢复应用。')
        deadline = time.monotonic() + 10
        while implementation.stamp(desktop['pid']) == desktop['stamp'] and time.monotonic() < deadline:
            time.sleep(.1)
        if implementation.stamp(desktop['pid']) == desktop['stamp']:
            state['status'] = 'manual-recovery'
            write_json(directory / 'state.json', state)
            clear_pending(directory)
            return 'manual-recovery'
    installed, backup, failed = (Path(state[key]) for key in ('installed', 'backup', 'failed'))
    if inventory(backup) != (state['files'], state['links']) or failed.exists():
        raise ValueError('旧版保留文件已变化，未自动恢复；候选版与数据仍保留。')
    if not implementation.restore(installed, backup, failed):
        raise OSError('应用恢复失败；旧版保留，可重试，用户数据未修改。')
    state['status'] = 'restored'
    write_json(directory / 'state.json', state)
    write_json(directory.parent / 'notice.json', {'token': directory.name, 'version': state['previous_version']})
    clear_pending(directory)
    if relaunch:
        command = [str(installed / 'AgentScribe.exe')] if os.name == 'nt' else ['open', '-n', str(installed)]
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 'restored'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(watch(args.watch), flush=True)
    except Exception as error:
        print('update recovery failed: ' + str(error), flush=True)
        sys.exit(1)
