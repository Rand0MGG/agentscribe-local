"""Keep an owned native child alive only while its parent's stdin pipe is open."""
import signal
import subprocess
import sys
from threading import Event

from .process_platform import parent_disconnected, spawn_options, stop_tree


def main():
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    parent_pipe = sys.stdin.fileno()
    child = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                             **spawn_options())
    try:
        # Poll the raw pipe in the main thread so shutdown never leaves a
        # daemon reader holding Python's buffered stdin lock.
        while child.poll() is None and not stopped.wait(.1):
            if parent_disconnected(parent_pipe):
                stopped.set()
    finally:
        if child.poll() is None:
            stop_tree(child)
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                stop_tree(child, force=True)
                child.wait(timeout=5)
    return 0 if stopped.is_set() else child.returncode


if __name__ == '__main__':
    sys.exit(main())
