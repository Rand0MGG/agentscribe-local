"""Bounded, process-local support records. Never attach user content or locals."""
import atexit
import json
import logging
import math
import os
import platform
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from . import __version__
from .runtime_paths import user_data_root

_logger = logging.getLogger('agentscribe.support')
_logger.propagate = False
_logger.addHandler(logging.NullHandler())
_logger.setLevel(logging.INFO)
_handler = None
_session = None
_error = ''
_sink = None
_hooks_installed = False


def log_directory():
    return Path(os.environ['AGENTSCRIBE_LOG_DIR']) if os.environ.get('AGENTSCRIBE_LOG_DIR') else user_data_root() / 'logs'


def log_error():
    return _error


class SupportHandler(RotatingFileHandler):
    def handleError(self, record):
        global _error
        first = not _error
        _error = '诊断日志写入失败，请检查日志目录权限和剩余空间。'
        if first and sys.stderr:
            sys.stderr.write(_error + '\n')


def start_logging(role, directory=None, *, max_bytes=2 * 1024 * 1024, backups=2):
    """One file per process launch; never rotate a different live process's file."""
    global _handler, _error
    if _handler is not None:
        return Path(_handler.baseFilename)
    root = Path(directory) if directory is not None else log_directory()
    try:
        root.mkdir(parents=True, exist_ok=True)
        # Remove only this logger's stale files, not recordings or other logs.
        cutoff = time.time() - 14 * 86400
        for old in root.glob('support-*.jsonl*'):
            try:
                if not old.is_symlink() and old.is_file() and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                continue  # Rotation by another process must not disable new logs.
        name = f'support-{role}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{os.getpid()}-{uuid4().hex[:8]}.jsonl'
        _handler = SupportHandler(root / name, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
        _handler.setFormatter(logging.Formatter('%(message)s'))
        _logger.addHandler(_handler)
        os.environ['AGENTSCRIBE_LOG_DIR'] = str(root)
        _error = ''
        event('process_start', role=role, version=__version__, python=platform.python_version(),
              system=platform.system(), release=platform.release(), machine=platform.machine())
        return root / name
    except OSError:
        _error = '诊断日志无法创建，请检查日志目录权限和剩余空间。'
        if sys.stderr:
            sys.stderr.write(_error + '\n')
        return None


def set_session(identifier):
    global _session
    _session = identifier


def set_sink(callback):
    global _sink
    _sink = callback


def event(name, **fields):
    """Call sites provide only explicit operational metadata, never raw payloads."""
    if _sink is not None and name == 'asr_decode_end':
        _sink(dict(type='asr_timing', **fields))
    if _handler is None:
        return
    row = dict(schema=1, utc=datetime.now(timezone.utc).isoformat(), monotonic=time.monotonic(),
               pid=os.getpid(), thread=threading.current_thread().name, session=_session, event=name)
    row.update({k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in fields.items()})
    _logger.info(json.dumps(row, ensure_ascii=False, allow_nan=False))


def exception(name, exc):
    # Exception strings, source lines and locals may contain transcripts, URLs,
    # credentials or filenames. Preserve types, errno and executable locations.
    chain = []
    seen = set()
    while exc is not None and id(exc) not in seen and len(chain) < 8:
        seen.add(id(exc))
        message = str(exc).lower()
        categories = [code for code, terms in {
            'out_of_memory': ('out of memory', 'not enough memory'),
            'disk_full': ('no space left', 'disk full', '磁盘空间不足'),
            'permission': ('permission denied', 'access is denied', '拒绝访问'),
            'timeout': ('timed out', 'timeout', '超时'),
            'cuda': ('cuda', 'cudnn', 'cublas'),
            'missing_resource': ('no such file', 'not found', '找不到'),
        }.items() if any(term in message for term in terms)]
        chain.append(dict(type=type(exc).__name__, errno=getattr(exc, 'errno', None),
                          winerror=getattr(exc, 'winerror', None), categories=categories,
                          frames=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                  for f in traceback.extract_tb(exc.__traceback__)[-32:]]))
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    event(name, exceptions=chain)


def install_exception_hooks():
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    previous = sys.excepthook
    def uncaught(kind, value, tb):
        exception('uncaught_exception', value)
        previous(kind, value, tb)
    sys.excepthook = uncaught
    previous_thread = threading.excepthook
    def thread_error(args):
        exception('uncaught_thread_exception', args.exc_value)
        previous_thread(args)
    threading.excepthook = thread_error


def close_logging():
    global _handler
    if _handler is not None:
        event('process_log_close')
        _logger.removeHandler(_handler)
        _handler.close()
        _handler = None


atexit.register(close_logging)
