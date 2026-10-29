"""Shared explicit Qt/Electron entry, retaining the last successfully opened UI."""
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
    from PySide6.QtCore import QSettings
    saved = context()
    no_audio = args.no_audio or saved.get('no_audio', False) or bool(os.environ.get('AGENTSCRIBE_AUDIO_GUARD_LOG'))
    if no_audio:
        os.environ['AGENTSCRIBE_NO_AUDIO'] = '1'
    prefs = (QSettings(saved['preferences'], QSettings.Format(saved.get('preferences_format', 1)))
             if saved.get('preferences') else QSettings('LinguaFlow', 'LocalCaptions'))
    frontend = args.frontend or prefs.value('desktop_frontend', 'qt')
    if frontend == 'electron':
        try:
            command = command_for('electron')
        except ValueError as exc:
            os.environ['AGENTSCRIBE_FRONTEND_RECOVERY'] = str(exc)
        else:
            if no_audio:
                command.append('--no-audio')
            environment = python_environment()
            environment['AGENTSCRIBE_DESKTOP_PYTHON'] = str(knowledge_python())
            from .desktop_startup import run_desktop
            return run_desktop(command, cwd=resource_root(), env=environment)
    from .app import main as qt_main
    return qt_main()
