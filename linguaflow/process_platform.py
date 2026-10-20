"""Platform operations for a parent-owned local inference process."""
import errno
import os
import select
import signal
import subprocess
import sys

_installation_mutex = None
_WORKER_JOB = 'AGENTSCRIBE_WORKER_JOB'


def _job_api():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
        'OpenJobObjectW': ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
        'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        'GetCurrentProcess': ([], wintypes.HANDLE),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


class WindowsWorkerJob:
    """Parent-held lifetime for the worker and descendants, even after its crash."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        from uuid import uuid4

        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('minimum_working_set', ctypes.c_size_t),
                        ('maximum_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io_counters', ctypes.c_uint64 * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.name = 'Local\\AgentScribe.Worker.' + uuid4().hex
        self.kernel = _job_api()
        self.handle = self.kernel.CreateJobObjectW(None, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def environment(self, environment):
        return {**environment, _WORKER_JOB: self.name}

    def close(self):
        if self.handle is not None:
            import ctypes
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


def worker_entry():
    """Join ownership before importing model code or spawning any descendants."""
    import runpy
    name = os.environ.pop(_WORKER_JOB, None)
    if sys.platform == 'win32':
        import ctypes
        if not name:
            raise RuntimeError('推理进程缺少资源归属，未启动模型。')
        kernel = _job_api()
        job = kernel.OpenJobObjectW(1, False, name)  # JOB_OBJECT_ASSIGN_PROCESS
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            # Only the desktop retains a handle, so its crash also reaps the tree.
            kernel.CloseHandle(job)
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    if target.endswith('.py'):
        runpy.run_path(target, run_name='__main__')
    else:
        runpy.run_module(target, run_name='__main__')


def hold_installation_mutex(*, installed):
    """Keep Inno from replacing a running installed app, until process exit.

    The OS releases this handle after all Python cleanup threads have ended.
    Source/worker processes do not acquire it. It is not a single-instance lock.
    """
    global _installation_mutex
    if os.name != 'nt' or not installed or _installation_mutex is not None:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    _installation_mutex = kernel.CreateMutexW(None, False, 'AgentScribe.InstallationActive')
    if not _installation_mutex:
        raise ctypes.WinError(ctypes.get_last_error())


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
        except PermissionError as exc:
            # Darwin filters zombies from killpg and can return EPERM when a
            # concurrent cancellation has already killed the last group member.
            # Reap our child to confirm that case; live permission failures
            # still propagate. Signal the group first so surviving descendants
            # are not skipped just because their parent has exited.
            if sys.platform != 'darwin':
                raise
            if process.poll() is None:
                # The kernel can exclude an exiting group before waitpid can
                # reap its last child. Confirm completion without retrying a
                # signal or hiding a permission failure for a live process.
                try:
                    process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    raise exc


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


if __name__ == '__main__':
    worker_entry()
