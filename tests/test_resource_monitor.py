import plistlib
import subprocess
import threading
from collections import namedtuple
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from linguaflow import resource_monitor as resources


def test_process_tree_cpu_ram_and_new_child_are_distinguished(monkeypatch):
    times = iter([10., 12., 14.])
    monkeypatch.setattr(resources.time, 'monotonic', lambda: next(times))
    system = namedtuple('CPU', 'user system idle')
    readings = iter([system(10, 10, 80), system(20, 20, 100), system(30, 30, 120)])
    monkeypatch.setattr(resources.psutil, 'cpu_times', lambda: next(readings))
    monkeypatch.setattr(resources.psutil, 'virtual_memory',
                        lambda: SimpleNamespace(total=1000, available=400, percent=60))
    class Process:
        def __init__(self, pid):
            self.pid, self.cpu = pid, 0
        def oneshot(self):
            return nullcontext()
        def create_time(self):
            return 1.
        def cpu_times(self):
            return SimpleNamespace(user=self.cpu, system=0)
        def memory_info(self):
            return SimpleNamespace(rss=100)
        def ppid(self):
            return 1
        def children(self, recursive):
            return children
    root, child = Process(1), Process(2)
    children = []
    monkeypatch.setattr(resources.psutil, 'Process', lambda: root)
    sampler = resources.ResourceSampler()
    monkeypatch.setattr(sampler, 'gpu', lambda pids: {'status': 'unavailable'})
    first = sampler.sample()
    assert first['app_cpu_percent'] is None and first['system_cpu_percent'] is None
    root.cpu = 3
    children.append(child)
    second = sampler.sample()
    assert second['app_cpu_percent'] == 150
    assert second['app_cpu_partial']
    assert second['app_rss_sum_bytes'] == 200 and second['app_process_count'] == 2
    assert second['system_cpu_percent'] == 50
    root.cpu, child.cpu = 4, 2
    third = sampler.sample()
    assert third['app_cpu_percent'] == 150 and not third['app_cpu_partial']
    assert all(set(p) == {'pid', 'parent_pid', 'cpu_percent', 'rss_bytes'} for p in third['processes'])


def test_gpu_scope_wddm_unknown_and_timeout_backoff(monkeypatch):
    sampler = resources.ResourceSampler()
    sampler.macos_gpu = False
    sampler.gpu_command = 'fixture-nvidia-smi'
    def query(command):
        if command.startswith('--query-gpu='):
            return [['0', '42', '100', '8000']]
        return [['123', 'N/A'], ['999', '500']]
    monkeypatch.setattr(sampler, '_gpu_query', query)
    result = sampler.gpu({123})
    assert result['scope'] == 'whole_device'
    assert result['devices'][0]['utilization_percent'] == 42
    assert result['app_allocations'] == [{'pid': 123, 'used_bytes': None}]
    assert result['app_memory_status'] == 'unavailable'
    calls = []
    def timeout(command):
        calls.append(command)
        raise subprocess.TimeoutExpired('fixture', 1.5)
    monkeypatch.setattr(sampler, '_gpu_query', timeout)
    assert sampler.gpu({123}) == {'status': 'timeout'}
    assert sampler.gpu({123}) == {'status': 'timeout'}
    assert len(calls) == 1


@pytest.mark.parametrize('value', ['N/A', '[Not Supported]', 'nan', 'inf', None, True])
def test_unavailable_gpu_numbers_are_not_zero(value):
    assert resources._number(value) is None


def test_monitor_recovers_and_stops_without_waiting_full_interval(monkeypatch):
    events, sampled = [], threading.Event()
    class Sampler:
        calls = 0
        def sample(self):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError('private details')
            sampled.set()
            return {'app_rss_sum_bytes': 123}
    monkeypatch.setattr(resources.diag, 'event', lambda name, **fields: events.append(name))
    monkeypatch.setattr(resources.diag, 'exception', lambda name, exc: events.append(name))
    monitor = resources.ResourceMonitor(interval=.01, sampler_factory=Sampler)
    monitor.start()
    assert sampled.wait(2)
    monitor.close()
    assert not monitor.is_alive()
    assert events.count('resource_sampling_failed') == 1
    assert events.count('resource_sampling_recovered') == 1
    assert 'resource_sample' in events


def test_mac_gpu_extracts_only_utilization_without_raw_registry_data(monkeypatch):
    sampler = resources.ResourceSampler()
    sampler.macos_gpu = True
    payload = plistlib.dumps([
        {'IORegistryEntryName': 'PRIVATE', 'PerformanceStatistics': {
            'Device Utilization %': 37, 'Renderer Utilization %': 99, 'private_field': b'PRIVATE'}},
        {'PerformanceStatistics': {'GPU Activity(%)': 0}},
        {'PerformanceStatistics': {'Device Utilization %': 101}},
        {'IORegistryEntryChildren': [{'PerformanceStatistics': {'Device Utilization %': 90}}]},
    ])
    calls = []
    def query(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=payload)
    monkeypatch.setattr(resources.subprocess, 'run', query)
    result = sampler.gpu(set())
    assert result == dict(status='available', scope='whole_device', source='ioreg',
                          devices=[dict(index=0, utilization_percent=37.), dict(index=1, utilization_percent=0.)],
                          app_memory_status='not_reported')
    assert calls[0][0] == ['/usr/sbin/ioreg', '-a', '-r', '-d', '1', '-c', 'IOAccelerator']
    assert calls[0][1]['timeout'] == 1.5 and calls[0][1]['stderr'] == subprocess.DEVNULL
    assert 'PRIVATE' not in str(result)


@pytest.mark.parametrize('payload, status', [
    (plistlib.dumps([]), 'counters_unavailable'),
    (plistlib.dumps([{'PerformanceStatistics': {'Device Utilization %': True}}]), 'counters_unavailable'),
    (plistlib.dumps({'unexpected': 'shape'}), 'query_failed'),
    (b'not a plist PRIVATE', 'query_failed'),
    (b'<?xml version="1.0"?><plist><', 'query_failed'),
    (b'x' * (1024 * 1024 + 1), 'query_failed'),
], ids=['missing', 'boolean', 'shape', 'not-plist', 'broken-xml', 'oversized'])
def test_mac_missing_invalid_counters_back_off_without_false_zero(monkeypatch, payload, status):
    sampler = resources.ResourceSampler()
    sampler.macos_gpu = True
    calls = []
    def query(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(stdout=payload)
    monkeypatch.setattr(resources.subprocess, 'run', query)
    first = sampler.gpu(set())
    assert first['status'] == status and not first.get('devices')
    assert sampler.gpu(set()) == {'status': status}
    assert len(calls) == 1


def test_mac_timeout_is_bounded_and_cpu_ram_sample_survives(monkeypatch):
    sampler = resources.ResourceSampler()
    sampler.macos_gpu = True
    calls = []
    def query(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired('ioreg', 1.5)
    monkeypatch.setattr(resources.subprocess, 'run', query)
    sample = sampler.sample()
    assert sample['gpu'] == {'status': 'timeout'}
    assert sample['app_rss_sum_bytes'] > 0
    assert sampler.sample()['gpu'] == {'status': 'timeout'}
    assert len(calls) == 1
