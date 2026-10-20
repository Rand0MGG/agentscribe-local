"""Bounded, process-local support records. Never attach user content or locals."""
import atexit
import inspect
import json
import logging
import math
import os
import platform
import queue
import re
import sys
import threading
import time
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
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
_writer = None
_lifecycle_lock = threading.RLock()
_throttled = {}
_dropped = 0
_role = None
_operation = ContextVar('support_operation', default=None)


def _report_error(message):
    global _error
    first = not _error
    _error = message
    if first and sys.stderr:
        try:
            sys.stderr.write(message + '\n')
        except Exception:
            pass  # An unavailable console must not turn logging into a business failure.


def log_directory():
    return Path(os.environ['AGENTSCRIBE_LOG_DIR']) if os.environ.get('AGENTSCRIBE_LOG_DIR') else user_data_root() / 'logs'


def log_error():
    return _error


class SupportHandler(RotatingFileHandler):
    def handleError(self, record):
        _report_error('诊断日志写入失败，请检查日志目录权限和剩余空间。')


class _Writer(threading.Thread):
    """Bounded metadata queue; slow storage never runs on capture or Qt threads."""

    def __init__(self, handler):
        super().__init__(name='support-log-writer', daemon=True)
        self.handler = handler
        self.pending = queue.Queue(maxsize=1024)
        self.stopping = threading.Event()

    def run(self):
        try:
            while not self.stopping.is_set() or not self.pending.empty():
                row = self.pending.get()
                try:
                    if row is None:
                        break
                    elif isinstance(row, threading.Event):
                        row.set()
                    else:
                        self.handler.handle(logging.LogRecord(
                            _logger.name, logging.INFO, '', 0, row, (), None))
                except Exception:
                    _report_error('诊断日志写入失败，请检查日志目录权限和剩余空间。')
                finally:
                    self.pending.task_done()
        finally:
            try:
                self.handler.close()
            except Exception:
                _report_error('诊断日志关闭失败，部分记录可能未写入。')


def _clean_logs(root):
    """Only expired/over-budget inactive application logs; never delete a live writer."""
    try:
        import psutil
    except ImportError:
        # Model runtimes need not install desktop telemetry dependencies. The
        # desktop performs directory cleanup; missing probes never disable logs.
        return
    cutoff = time.time() - 14 * 86400
    owned = []
    pattern = re.compile(r'support-[a-z-]+-\d{8}T\d{6}-(\d+)-[a-f0-9]{8}\.jsonl(?:\.\d+)?$')
    for path in root.glob('support-*.jsonl*'):
        match = pattern.fullmatch(path.name)
        if not match or path.is_symlink():
            continue
        try:
            stat = path.stat()
            if path.is_file():
                owned.append((stat.st_mtime, stat.st_size, path, int(match[1])))
        except OSError:
            continue
    total = sum(item[1] for item in owned)
    for modified, size, path, pid in sorted(owned):
        if modified >= cutoff and total <= 128 * 1024 * 1024:
            continue
        if psutil.pid_exists(pid):
            continue
        try:
            path.unlink()
            total -= size
        except OSError:
            continue  # Another process or OS file protection may own this file.


def start_logging(role, directory=None, *, max_bytes=8 * 1024 * 1024, backups=3):
    """One file per process launch; never rotate a different live process's file."""
    global _handler, _error, _writer, _role, _dropped
    with _lifecycle_lock:
        if _handler is not None:
            return Path(_handler.baseFilename)
        try:
            root = Path(directory) if directory is not None else log_directory()
            root.mkdir(parents=True, exist_ok=True)
            _clean_logs(root)
            name = f'support-{role}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{os.getpid()}-{uuid4().hex[:8]}.jsonl'
            _handler = SupportHandler(root / name, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
            _handler.setFormatter(logging.Formatter('%(message)s'))
            _writer = _Writer(_handler)
            _writer.start()
            _role = role
            _dropped = 0
            _throttled.clear()
            os.environ['AGENTSCRIBE_LOG_DIR'] = str(root)
            _error = ''
            event('process_start', version=__version__, python=platform.python_version(),
                  system=platform.system(), release=platform.release(), machine=platform.machine())
            return root / name
        except Exception:
            if _handler is not None and (_writer is None or not _writer.is_alive()):
                _handler.close()
                _handler = None
                _writer = None
            _report_error('诊断日志无法创建，请检查日志目录权限和剩余空间。')
            return None


def set_session(identifier):
    global _session
    _session = identifier


def clear_session(identifier):
    global _session
    if _session == identifier:
        _session = None


def set_sink(callback):
    global _sink
    _sink = callback


def action(name, callback):
    """Instrument explicit UI commands; handled is not an asynchronous success receipt."""
    parameters = tuple(inspect.signature(callback).parameters.values())
    positional = None if any(p.kind == p.VAR_POSITIONAL for p in parameters) else sum(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in parameters)
    @wraps(callback)
    def invoke(*args, **kwargs):
        identifier = uuid4().hex[:16]
        token = _operation.set(identifier)
        started = time.monotonic()
        event('ui_action', action=name)
        try:
            # Match Qt's normal omission of the clicked/triggered checked argument.
            result = callback(*(args if positional is None else args[:positional]), **kwargs)
            event('ui_dispatch', action=name, outcome='rejected' if result is False else 'handled',
                  elapsed_seconds=time.monotonic() - started)
            return result
        except Exception as exc:
            exception('ui_action_exception', exc)
            raise
        finally:
            _operation.reset(token)
    return invoke


def _metadata(value, depth=0):
    if depth > 6:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:512]
    if isinstance(value, dict):
        return {str(k)[:64]: _metadata(v, depth + 1) for k, v in list(value.items())[:48]}
    if isinstance(value, (list, tuple)):
        return [_metadata(v, depth + 1) for v in value[:32]]
    return None  # Never call repr() on arbitrary objects containing user data.


def event(name, *, level='INFO', **fields):
    """Persist independently of optional diagnostic protocol delivery."""
    _enqueue(name, fields, level)
    if _sink is not None and name == 'asr_decode_end':
        try:
            _sink(dict(type='asr_timing', **fields))
        except Exception:
            _report_error('诊断耗时回传失败；本地记录继续保留。')


def _enqueue(name, fields, level):
    global _dropped
    writer = _writer
    if writer is None or writer.stopping.is_set():
        return
    try:
        row = dict(schema=2, utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   monotonic=round(time.monotonic(), 6), level=level,
                   pid=os.getpid(), role=_role, thread=threading.current_thread().name,
                   session=_session, operation=_operation.get(), event=name)
        row.update(_metadata(fields))
        if _dropped:
            row['dropped_events'] = _dropped
        payload = json.dumps(row, ensure_ascii=False, allow_nan=False)
        if len(payload.encode('utf-8')) > 16384:
            row = {key: row[key] for key in ('schema', 'utc', 'monotonic', 'level', 'pid', 'role', 'session', 'event')}
            row['metadata_omitted'] = True
            payload = json.dumps(row, ensure_ascii=False)
        writer.pending.put_nowait(payload)
        _dropped = 0
    except queue.Full:
        _dropped += 1
        _report_error('诊断日志写入积压，部分记录已省略；录音继续。')
    except Exception:
        _report_error('部分诊断字段无法记录；录音继续。')


def periodic(name, *, seconds=5., key=None, **fields):
    """Coalesce repetitive progress; lifecycle, actions and errors use event()."""
    if _writer is None:
        return
    now = time.monotonic()
    identity = (name, key)
    if now - _throttled.get(identity, float('-inf')) >= seconds:
        if len(_throttled) >= 256 and identity not in _throttled:
            _throttled.pop(next(iter(_throttled)))
        _throttled[identity] = now
        event(name, **fields)


def flush(timeout=2.):
    writer = _writer
    if writer is None:
        return True
    barrier = threading.Event()
    deadline = time.monotonic() + timeout
    try:
        writer.pending.put(barrier, timeout=max(0., timeout))
    except queue.Full:
        return False
    return barrier.wait(max(0., deadline - time.monotonic()))


def exception(name, exc, **fields):
    # Exception strings, source lines and locals may contain transcripts, URLs,
    # credentials or filenames. Preserve types, errno and executable locations.
    chain = []
    seen = set()
    while exc is not None and id(exc) not in seen and len(chain) < 8:
        seen.add(id(exc))
        try:
            message = str(exc).lower()
        except Exception:
            message = ''
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
    event(name, level='ERROR', exceptions=chain, **fields)


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
    global _handler, _writer
    with _lifecycle_lock:
        writer = _writer
        if writer is not None:
            event('process_log_close')
            writer.stopping.set()
            _writer = None
            _handler = None
            try:
                writer.pending.put_nowait(None)
            except queue.Full:
                pass  # A full queue keeps the writer awake until it drains.
            writer.join(timeout=2.)
            if writer.is_alive():
                _report_error('诊断日志关闭等待超时，部分尾部记录可能未写入。')


atexit.register(close_logging)
