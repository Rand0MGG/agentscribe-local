"""Keep an owned native child alive only while its parent's stdin pipe is open."""
import signal
import subprocess
import sys
from threading import Event

from .process_platform import parent_disconnected, spawn_options


def main():
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    parent_pipe = sys.stdin.fileno()
    child = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                             **({"creationflags": spawn_options()["creationflags"]} if sys.platform == "win32" else {}))
    try:
        # Poll the raw pipe in the main thread so shutdown never leaves a
        # daemon reader holding Python's buffered stdin lock.
        while child.poll() is None and not stopped.wait(.1):
            if parent_disconnected(parent_pipe):
                stopped.set()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return 0 if stopped.is_set() else child.returncode


if __name__ == '__main__':
    sys.exit(main())
