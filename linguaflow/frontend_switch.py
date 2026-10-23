"""Explicit desktop handoff; the next UI starts only after the old owner exits."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from .process_platform import spawn_options
from .runtime_paths import knowledge_python, packaged, python_environment, resource_root

CONTEXT_ENV = 'AGENTSCRIBE_FRONTEND_CONTEXT'


def command_for(frontend):
    root = resource_root()
    if frontend == 'qt':
        command = ([str(root.parent / 'MacOS/AgentScribe' if sys.platform == 'darwin' else root / 'AgentScribe.exe'), '--frontend', 'qt']
                   if packaged() else [str(knowledge_python()), '-m', 'linguaflow', '--frontend', 'qt'])
    elif frontend == 'electron':
        suffix = ('Electron.app/Contents/MacOS/Electron' if sys.platform == 'darwin'
                  else 'electron.exe' if sys.platform == 'win32' else 'electron')
        bundled = root / 'desktop/runtime' / suffix
        executable = bundled if bundled.is_file() else root / 'desktop/node_modules/electron/dist' / suffix
        if not executable.is_file() or not (root / 'desktop/dist/index.html').is_file():
            raise ValueError('Electron 界面尚未准备，请先安装 desktop 依赖并完成构建。当前界面保留。')
        command = [str(executable), str(root / 'desktop')]
    else:
        raise ValueError('不支持的界面。')
    if not Path(command[0]).is_file():
        raise ValueError('目标界面缺少启动组件，当前界面保留。')
    return command


def context():
    filename = os.environ.get(CONTEXT_ENV)
    if not filename:
        return {}
    value = json.loads(Path(filename).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('界面切换记录无效，未修改录音。')
    return value


def prepare(frontend, *, library, prefs, recording=None, draft=None, no_audio=False, owner_pid=None, geometry=None, purpose=None):
    command_for(frontend)  # Fail before closing any window.
    owner_pid = owner_pid or os.getpid()
    if owner_pid not in (os.getpid(), os.getppid()):
        raise ValueError('界面进程归属无效。')
    directory = Path(tempfile.mkdtemp(prefix='agentscribe-frontend-'))
    path = directory / 'context.json'
    owners = [{'pid': pid, 'created': psutil.Process(pid).create_time()} for pid in {owner_pid, os.getpid()}]
    prefs.sync()
    if prefs.status() != type(prefs.status()).NoError:
        raise OSError('设置未能保存，请检查配置文件权限后重试。')
    value = dict(version=1, target=frontend, previous='qt' if frontend == 'electron' else 'electron',
                 library=str(library.root), preferences=prefs.fileName(), preferences_format=prefs.format().value,
                 recording=recording, draft=draft, no_audio=bool(no_audio), geometry=geometry, owners=owners, purpose=purpose)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    path.chmod(0o600)
    return path


def launch(path):
    """Only called after all save/close guards succeed; never terminates a UI."""
    env = python_environment()
    env.pop(CONTEXT_ENV, None)
    output = Path(path).with_name('handoff.log').open('ab')
    try:
        process = subprocess.Popen([str(knowledge_python()), '-m', 'linguaflow.frontend_switch', str(path)],
                                   cwd=resource_root(), env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32'
                                      else {'start_new_session': True}))
    finally:
        output.close()
    return process


def ready(frontend, prefs):
    filename = os.environ.get(CONTEXT_ENV)
    if filename:
        Path(filename).with_name('ready-' + frontend).write_text('ready', encoding='ascii')
    prefs.setValue('desktop_frontend', frontend)
    prefs.sync()


def handoff(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    for owner in value['owners']:
        try:
            process = psutil.Process(owner['pid'])
            if abs(process.create_time() - owner['created']) < .001:
                process.wait()  # No timeout kill: an old owner may still be saving.
        except psutil.NoSuchProcess:
            pass
    environment = python_environment()
    environment[CONTEXT_ENV] = str(path)
    environment['AGENTSCRIBE_DESKTOP_PYTHON'] = str(knowledge_python())
    for key in ('AGENTSCRIBE_FRONTEND_RECOVERY', 'AGENTSCRIBE_DESKTOP_LIBRARY', 'AGENTSCRIBE_DESKTOP_PREFERENCES'):
        environment.pop(key, None)
    output = path.with_name('handoff.log').open('ab')
    try:
        for frontend in (value['target'], value['previous']):
            marker = path.with_name('ready-' + frontend)
            marker.unlink(missing_ok=True)
            try:
                child = subprocess.Popen(command_for(frontend), cwd=resource_root(), env=environment,
                                         stdin=subprocess.DEVNULL, stdout=output, stderr=output, **spawn_options())
                while child.poll() is None:
                    if marker.exists():
                        return 0
                    time.sleep(.05)
                if marker.exists():
                    return child.returncode
                message = f'{frontend} 界面未完成启动（退出码 {child.returncode}），恢复原界面。'
            except (OSError, ValueError) as exc:
                message = f'界面启动失败，恢复原界面：{exc}'
            print(message, flush=True)
            environment['AGENTSCRIBE_FRONTEND_RECOVERY'] = message
        return 1
    finally:
        output.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('context', type=Path)
    raise SystemExit(handoff(parser.parse_args().context))
