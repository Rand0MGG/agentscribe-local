"""Platform operations for a parent-owned local inference process."""
import os
import select
import signal
import subprocess
import sys


def spawn_options():
    return ({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32'
            else {'start_new_session': True})


def stop_tree(process, force=False):
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass


def parent_disconnected(fd):
    if sys.platform == 'win32':
        # Windows select() accepts sockets only; stdin here is an anonymous pipe.
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        peek = kernel.PeekNamedPipe
        peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                         wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        peek.restype = wintypes.BOOL
        available = wintypes.DWORD()
        if not peek(msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error in (109, 232, 233):
                return True
            raise ctypes.WinError(error)
        readable = available.value > 0
    else:
        readable = bool(select.select([fd], [], [], 0)[0])
    return readable and not os.read(fd, 4096)
