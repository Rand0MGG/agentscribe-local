"""Platform operations for a parent-owned local inference process."""
import errno
import os
import select
import signal
import subprocess
import sys


def spawn_options():
    return ({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32'
            else {'start_new_session': True})


def close_process_pipes(process):
    """Close reaped-child pipes after readers join; preserve unexpected IO failures."""
    error = None
    for name in ('stdin', 'stdout', 'stderr'):
        pipe = getattr(process, name, None)
        if pipe is None or pipe.closed:
            continue
        try:
            pipe.close()
        except Exception as exc:
            # Closing stdin flushes settings buffered before a child exited.
            # An expected broken pipe must not prevent closing output streams.
            # Windows CRT can report EINVAL instead of EPIPE when flushing an
            # anonymous pipe whose reader has already exited. A live child or
            # any other stream/error still indicates an unexpected IO failure.
            exited_windows_pipe = (sys.platform == 'win32' and isinstance(exc, OSError)
                                   and exc.errno == errno.EINVAL and process.poll() is not None)
            if name != 'stdin' or not (isinstance(exc, BrokenPipeError) or exited_windows_pipe):
                error = error or exc
    if error is not None:
        raise error


def window_session_available():
    """Check Quartz availability without registering an app or opening devices."""
    if sys.platform != 'darwin':
        return True
    import ctypes
    graphics = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    graphics.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    session = graphics.CGSessionCopyCurrentDictionary()
    if not session:
        return False
    foundation = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    foundation.CFRelease.argtypes = [ctypes.c_void_p]
    foundation.CFRelease.restype = None
    foundation.CFRelease(session)
    return True


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
