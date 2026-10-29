"""Source injected into an isolated installed-version update probe.

Old packages use their own Qt host; Qt-free versions exercise their actual backend
and native updater without pretending this is an Electron window acceptance test.
"""
HOST_IMPORTS = '''
import importlib.util
if importlib.util.find_spec('linguaflow.events') is None:
    from PySide6.QtCore import QSettings,QTimer
    from PySide6.QtWidgets import QApplication
    from linguaflow.app import Window
else:
    from linguaflow.events import Dispatcher, Timer as QTimer
    from linguaflow.settings_store import SettingsStore as QSettings
    from linguaflow.desktop_service import DesktopService
    class QApplication(Dispatcher):
        def __init__(self,*args):
            super().__init__(*args)
            if sys.platform == 'darwin':
                from linguaflow.native_dispatch import cocoa_pump
                self.native_pump=cocoa_pump()
    class Window(DesktopService):
        def __init__(self,*,discover,prefs,library_root):
            super().__init__(prefs=prefs,library_root=library_root,no_audio=True)
        def show(self):
            pass
        def set_recording_state(self,value):
            self.state=value
            self.changed()
        def try_install_update(self):
            self.update_workflow.try_install()
        def check_software_updates(self):
            self.check_updates()
'''
