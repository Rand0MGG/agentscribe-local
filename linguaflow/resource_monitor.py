"""Low-frequency metadata-only resource sampling, never on the Qt/audio thread."""
import csv
import io
import math
import os
import plistlib
import shutil
import subprocess
import sys
import threading
import time
from xml.parsers.expat import ExpatError

import psutil

from . import diagnostic_log as diag
from .process_platform import spawn_options


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


class ResourceSampler:
    def __init__(self, *, root_pid=None):
        self.root = psutil.Process() if root_pid is None else psutil.Process(root_pid)
        self.previous = {}
        self.previous_time = None
        self.previous_system = None
        self.gpu_command = shutil.which('nvidia-smi') if sys.platform == 'win32' else None
        self.macos_gpu = sys.platform == 'darwin'
        self.gpu_retry_at = 0.
        self.gpu_status = 'tool_unavailable' if sys.platform in ('win32', 'darwin') else 'unsupported_platform'

    def _mac_gpu(self):
        # One bounded query per sample, no sudo/powermetrics or persistent helper.
        # Only accelerator properties are returned; child/user-client trees are excluded.
        result = subprocess.run(
            ['/usr/sbin/ioreg', '-a', '-r', '-d', '1', '-c', 'IOAccelerator'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5, check=True)
        if len(result.stdout) > 1024 * 1024:
            raise ValueError('oversized GPU properties')
        try:
            entries = plistlib.loads(result.stdout)
        except (ValueError, ExpatError) as exc:
            raise ValueError('invalid GPU properties') from exc
        if not isinstance(entries, list):
            raise ValueError('invalid GPU properties')
        devices = []
        for index, entry in enumerate(entries[:32]):
            stats = entry.get('PerformanceStatistics') if isinstance(entry, dict) else None
            if not isinstance(stats, dict):
                continue
            utilization = _number(stats.get('Device Utilization %'))
            if utilization is None:
                utilization = _number(stats.get('GPU Activity(%)'))
            if utilization is not None and 0 <= utilization <= 100:
                devices.append(dict(index=index, utilization_percent=utilization))
        self.gpu_status = 'available' if devices else 'counters_unavailable'
        if not devices:
            self.gpu_retry_at = time.monotonic() + 60.
        return dict(status=self.gpu_status, scope='whole_device', source='ioreg',
                    devices=devices, app_memory_status='not_reported')

    def _gpu_query(self, query):
        result = subprocess.run(
            [self.gpu_command, query, '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=1.5, check=True, **spawn_options())
        return list(csv.reader(io.StringIO(result.stdout)))

    def gpu(self, owned_pids):
        if time.monotonic() < self.gpu_retry_at or (not self.gpu_command and not self.macos_gpu):
            return dict(status=self.gpu_status)
        try:
            if self.macos_gpu:
                return self._mac_gpu()
            devices = []
            for row in self._gpu_query('--query-gpu=index,utilization.gpu,memory.used,memory.total'):
                if len(row) != 4:
                    raise ValueError('invalid GPU columns')
                index, utilization, used, total = map(_number, row)
                if index is None:
                    raise ValueError('invalid GPU index')
                devices.append(dict(index=int(index), utilization_percent=utilization,
                                    used_bytes=None if used is None else int(used * 1024**2),
                                    total_bytes=None if total is None else int(total * 1024**2)))
            self.gpu_status = 'available' if devices else 'no_devices'
            result = dict(status=self.gpu_status, scope='whole_device', devices=devices)
            # WDDM may report N/A. An unknown per-process allocation is never zero.
            try:
                rows = self._gpu_query('--query-compute-apps=pid,used_memory')
                allocations = []
                unknown = False
                for row in rows:
                    if len(row) != 2:
                        raise ValueError('invalid GPU process columns')
                    pid, used = map(_number, row)
                    if pid is not None and int(pid) in owned_pids:
                        unknown |= used is None
                        allocations.append(dict(pid=int(pid), used_bytes=None if used is None else int(used * 1024**2)))
                result.update(app_allocations=allocations, app_memory_status='unavailable' if unknown else
                              'reported' if allocations else 'not_reported')
            except (OSError, subprocess.SubprocessError, ValueError):
                result['app_memory_status'] = 'unavailable'
            return result
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            self.gpu_status = 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'query_failed'
            self.gpu_retry_at = time.monotonic() + 60.
            return dict(status=self.gpu_status)

    def sample(self):
        now = time.monotonic()
        interval = None if self.previous_time is None else now - self.previous_time
        current = {}
        rows = []
        inaccessible = 0
        try:
            children = self.root.children(recursive=True)
        except psutil.Error:
            children = []
            inaccessible += 1
        for process in [self.root, *children]:
            try:
                with process.oneshot():
                    identity = (process.pid, process.create_time())
                    times = process.cpu_times()
                    cpu = times.user + times.system
                    rss = process.memory_info().rss
                    current[identity] = cpu
                    previous = self.previous.get(identity)
                    percent = (max(0., cpu - previous) / interval * 100.
                               if previous is not None and interval and interval > 0 else None)
                    rows.append(dict(pid=process.pid, parent_pid=process.ppid(),
                                     cpu_percent=percent, rss_bytes=rss))
            except psutil.Error:
                inaccessible += 1
        system = psutil.cpu_times()
        total = sum(system)
        idle = system.idle
        system_percent = None
        if self.previous_system is not None:
            delta = total - self.previous_system[0]
            if delta > 0:
                system_percent = max(0., min(100., (1 - (idle - self.previous_system[1]) / delta) * 100))
        memory = psutil.virtual_memory()
        self.previous, self.previous_time, self.previous_system = current, now, (total, idle)
        return dict(interval_seconds=interval, logical_cpus=os.cpu_count(),
                    system_cpu_percent=system_percent, system_ram_total_bytes=memory.total,
                    system_ram_available_bytes=memory.available, system_ram_percent=memory.percent,
                    app_cpu_percent=(sum(r['cpu_percent'] or 0 for r in rows) if interval and rows else None),
                    app_cpu_partial=any(r['cpu_percent'] is None for r in rows) or bool(inaccessible),
                    app_rss_sum_bytes=sum(r['rss_bytes'] for r in rows),
                    app_process_count=len(rows), inaccessible_process_count=inaccessible,
                    processes=rows[:32], gpu=self.gpu({r['pid'] for r in rows}))


class ResourceMonitor(threading.Thread):
    def __init__(self, *, interval=10., sampler_factory=ResourceSampler):
        super().__init__(name='support-resources', daemon=True)
        self.interval = interval
        self.sampler_factory = sampler_factory
        self.stopping = threading.Event()

    def run(self):
        sampler = None
        failed = False
        while not self.stopping.is_set():
            started = time.monotonic()
            try:
                sampler = sampler or self.sampler_factory()
                sample = sampler.sample()
                sample['sample_duration_seconds'] = time.monotonic() - started
                diag.event('resource_sample', **sample)
                if failed:
                    diag.event('resource_sampling_recovered')
                failed = False
            except Exception as exc:
                if not failed:
                    diag.exception('resource_sampling_failed', exc)
                failed = True
            if self.stopping.wait(max(.1, self.interval - (time.monotonic() - started))):
                break

    def close(self):
        self.stopping.set()
        self.join(timeout=4.)
        if self.is_alive():
            diag.event('resource_sampling_stop_timeout')
