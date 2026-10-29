"""Electron desktop entry with backward-compatible launch context."""
import argparse
import os

from .runtime_paths import knowledge_python, python_environment, resource_root


def main():
    parser = argparse.ArgumentParser(description='AgentScribe 桌面')
    parser.add_argument('--frontend', choices=('qt', 'electron'))
    parser.add_argument('--no-audio', action='store_true')
    args = parser.parse_args()
    from . import diagnostic_log as diag
    from .frontend_switch import command_for, context
    from .update_recovery import startup
    diag.start_logging('desktop-launcher')
    diag.install_exception_hooks()
    startup()
    saved = context()
    no_audio = args.no_audio or saved.get('no_audio', False) or bool(os.environ.get('AGENTSCRIBE_AUDIO_GUARD_LOG'))
    if no_audio:
        os.environ['AGENTSCRIBE_NO_AUDIO'] = '1'
    if args.frontend == 'qt':
        raise ValueError('Qt 界面已退役，请使用 Electron 界面。')
    command = command_for('electron')
    if no_audio:
        command.append('--no-audio')
    environment = python_environment()
    environment['AGENTSCRIBE_DESKTOP_PYTHON'] = str(knowledge_python())
    from .desktop_startup import run_desktop
    return run_desktop(command, cwd=resource_root(), env=environment)
