import gzip
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from linguaflow import diagnostic_archive as archive
from linguaflow import diagnostic_log as diag


def raw_path(root, index=0, pid=999999999, role='worker'):
    return root / f'support-{role}-20261030T000000-{pid}-{index:08x}.jsonl'


def pending_path(root, index=0, pid=None):
    return Path(str(raw_path(root, index, os.getpid() if pid is None else pid))
                + f'.{index:020d}-12345678.pending')


def gz_path(root, index=0, role='worker'):
    return Path(str(raw_path(root, index, role=role)) + '.gz')


@pytest.mark.p2
def test_shared_compressed_budget_removes_multiple_oldest_and_excludes_active(tmp_path):
    histories = [gz_path(tmp_path, i, role='desktop' if i % 2 else 'worker') for i in range(4)]
    for i, path in enumerate(histories):
        path.write_bytes(gzip.compress(os.urandom(256), mtime=0))
        os.utime(path, (100 + i, 100 + i))
    live = raw_path(tmp_path, 30, os.getpid())
    with live.open('wb') as stream:
        stream.truncate(8 * 1024 * 1024)
    unknown = tmp_path / 'support-unrelated.jsonl.gz'
    unknown.write_bytes(b'not ours')
    # Equal-to-budget is retained. Both roles share one budget; active 8 MiB excluded.
    budget = sum(p.stat().st_size for p in histories[-2:])
    errors = []
    assert archive.maintain(tmp_path, budget, errors.append)
    assert [p.exists() for p in histories] == [False, False, True, True]
    assert live.stat().st_size == 8 * 1024 * 1024 and unknown.read_bytes() == b'not ours'
    assert errors == []
    assert archive.maintain(tmp_path, budget, errors.append)
    assert histories[-2].exists() and histories[-1].exists()  # No 14-day expiration.


@pytest.mark.p2
def test_recovery_is_byte_exact_preserves_age_and_old_rotation_files(tmp_path):
    source = raw_path(tmp_path)
    old_rotation = Path(str(raw_path(tmp_path, 1)) + '.3')
    body = '{"session":"关联会话","caption_id":12}\n{"partial":'.encode()
    for path in (source, old_rotation):
        path.write_bytes(body)
        os.utime(path, (100, 100))
    errors = []
    assert archive.maintain(tmp_path, archive.HISTORY_BYTES, errors.append)
    for path in (source, old_rotation):
        target = Path(str(path) + '.gz')
        assert not path.exists() and gzip.decompress(target.read_bytes()) == body
        assert target.stat().st_mtime == 100  # Recovery doesn't make old logs newest.
    assert errors == []


@pytest.mark.p2
def test_sealed_live_chunks_and_budget_work_without_psutil(tmp_path, monkeypatch):
    source = pending_path(tmp_path)
    source.write_bytes(b'{"task":"preserve"}\n')
    live = raw_path(tmp_path, 1, os.getpid())
    live.write_bytes(b'active')
    monkeypatch.setitem(sys.modules, 'psutil', None)
    assert archive.maintain(tmp_path, archive.HISTORY_BYTES, pytest.fail)
    assert gzip.decompress(source.with_suffix('.gz').read_bytes()) == b'{"task":"preserve"}\n'
    assert live.read_bytes() == b'active'
    assert archive.maintain(tmp_path, 0, pytest.fail)
    assert not source.with_suffix('.gz').exists() and live.exists()


@pytest.mark.p2
@pytest.mark.parametrize('stage', ['write', 'verify', 'publish'])
def test_failed_compression_preserves_source_and_recovers(tmp_path, monkeypatch, stage):
    source = pending_path(tmp_path)
    body = b'full evidence\n' * 100
    source.write_bytes(body)
    target = source.with_suffix('.gz')
    # A prior interrupted attempt cannot be mistaken for a completed archive.
    temporary = Path(str(target) + '.tmp')
    temporary.write_bytes(b'incomplete gzip')
    errors = []
    def fail(*args, **kwargs):
        raise OSError('simulated archive failure')
    with monkeypatch.context() as patch:
        if stage == 'write':
            patch.setattr(archive.gzip, 'GzipFile', fail)
        elif stage == 'verify':
            patch.setattr(archive.gzip, 'open', fail)
        else:
            patch.setattr(archive.os, 'replace', fail)
        assert not archive.maintain(tmp_path, archive.HISTORY_BYTES, errors.append)
    assert errors and source.read_bytes() == body and not target.exists()
    assert not temporary.exists()
    assert archive.maintain(tmp_path, archive.HISTORY_BYTES, errors.append)
    assert not source.exists() and gzip.decompress(target.read_bytes()) == body


@pytest.mark.p2
def test_crash_after_archive_publication_before_unlink_is_idempotent(tmp_path):
    source = pending_path(tmp_path)
    source.write_bytes(b'evidence')
    source.with_suffix('.gz').write_bytes(gzip.compress(b'evidence'))
    assert archive.maintain(tmp_path, archive.HISTORY_BYTES, pytest.fail)
    assert not source.exists()
    assert len(list(tmp_path.glob('*.gz'))) == 1
    assert gzip.decompress(source.with_suffix('.gz').read_bytes()) == b'evidence'


@pytest.mark.p0
def test_unrelated_files_and_symbolic_links_are_never_archived_or_deleted(tmp_path):
    outside = tmp_path / 'personal.txt'
    outside.write_bytes(b'personal')
    for path in (raw_path(tmp_path), pending_path(tmp_path, 1), gz_path(tmp_path, 2)):
        try:
            path.symlink_to(outside)
        except OSError:
            pytest.skip('Symbolic link creation is unavailable on this platform')
    assert archive.maintain(tmp_path, 0, pytest.fail)
    assert outside.read_bytes() == b'personal'
    assert all(path.is_symlink() for path in (raw_path(tmp_path), pending_path(tmp_path, 1), gz_path(tmp_path, 2)))


@pytest.mark.p2
def test_utf8_rotation_and_failed_archive_keep_writing_without_losing_records(tmp_path, monkeypatch):
    path = raw_path(tmp_path, pid=os.getpid())
    handler = diag.SupportHandler(path, max_bytes=1000, history_bytes=archive.HISTORY_BYTES)
    handler.setFormatter(logging.Formatter('%(message)s'))
    original = archive._compress
    errors = []
    monkeypatch.setattr(diag, '_report_error', errors.append)
    def failed(_path):
        raise OSError('disk full')
    monkeypatch.setattr(archive, '_compress', failed)
    records = [json.dumps({'index': i, 'session': 'same-session', 'text': '中文' * 80}, ensure_ascii=False)
               for i in range(10)]
    for row in records:
        handler.handle(logging.LogRecord('test', logging.INFO, '', 0, row, (), None))
    assert errors and path.exists()
    assert list(tmp_path.glob('*.pending'))
    assert all(p.stat().st_size <= 1000 for p in tmp_path.glob('*.pending'))
    monkeypatch.setattr(archive, '_compress', original)
    handler.finish()
    assert not path.exists() and not list(tmp_path.glob('*.pending'))
    decoded = [line for p in tmp_path.glob('*.gz') for line in gzip.decompress(p.read_bytes()).decode().splitlines()]
    assert sorted(decoded) == sorted(records)
    assert len(decoded) == len(records)


@pytest.mark.p2
@pytest.mark.parametrize('budget', [4096, 8 * 1024 * 1024])
def test_two_live_processes_share_budget_and_preserve_task_links(tmp_path, budget):
    program = '''
import sys
from pathlib import Path
from linguaflow import diagnostic_log as d
root, role, budget = sys.argv[1:]
d.start_logging(role, root, max_bytes=1800, history_bytes=int(budget))
d.set_session(role + '-session')
for i in range(40):
    d.event('linked', index=i, translation_task_id=role + '-task-' + str(i), caption_id=i,
            mapping_id='mapping-' + str(i), source_version=i, metadata='中文' * 60)
assert d.flush()
Path(root, role + '.ready').write_text('ready')
print('ready', flush=True)
sys.stdin.readline()
d.close_logging()
assert not d.log_error(), d.log_error()
'''
    processes = [subprocess.Popen([sys.executable, '-c', program, str(tmp_path), role, str(budget)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for role in ('desktop', 'worker')]
    try:
        deadline = time.monotonic() + 10
        while len(list(tmp_path.glob('*.ready'))) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert len(list(tmp_path.glob('*.ready'))) == 2
        assert len(list(tmp_path.glob('*.jsonl'))) == 2
        for process in processes:
            process.stdin.write('close\n')
            process.stdin.flush()
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            assert 'ready' in stdout
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    archives = list(tmp_path.glob('*.gz'))
    assert archives and sum(p.stat().st_size for p in archives) <= budget
    assert not list(tmp_path.glob('*.pending')) and not list(tmp_path.glob('*.tmp'))
    assert not list(tmp_path.glob('*.jsonl'))
    rows = [json.loads(line) for p in archives for line in gzip.decompress(p.read_bytes()).splitlines()]
    assert sum(r['event'] == 'process_log_close' for r in rows) == 2
    linked = [r for r in rows if r['event'] == 'linked']
    assert linked
    for row in linked:
        assert row['session'] == row['role'] + '-session'
        assert row['translation_task_id'] == row['role'] + '-task-' + str(row['caption_id'])
        assert row['caption_id'] == row['source_version'] == row['index']
    if budget > 4096:
        assert len(archives) > 4
        assert {(r['role'], r['index']) for r in linked} == {(role, i) for role in ('desktop', 'worker') for i in range(40)}


@pytest.mark.p2
def test_abrupt_process_exit_recovers_raw_tail_on_next_start(tmp_path):
    program = '''
import os, sys
from linguaflow import diagnostic_log as d
d.start_logging('worker', sys.argv[1])
d.set_session('crashed-session')
d.event('unfinished', translation_task_id='task-without-end')
assert d.flush()
os._exit(0)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path)], capture_output=True, timeout=10)
    assert result.returncode == 0
    raw, = tmp_path.glob('*.jsonl')
    original = raw.read_bytes()
    assert archive.maintain(tmp_path, archive.HISTORY_BYTES, pytest.fail)
    assert not raw.exists()
    assert gzip.decompress(Path(str(raw) + '.gz').read_bytes()) == original
    assert b'task-without-end' in original


@pytest.mark.p2
def test_failed_oldest_deletion_keeps_newer_history_and_reports(tmp_path, monkeypatch):
    old, new = gz_path(tmp_path, 0), gz_path(tmp_path, 1)
    for i, path in enumerate((old, new)):
        path.write_bytes(gzip.compress(b'evidence'))
        os.utime(path, (100 + i, 100 + i))
    original = Path.unlink
    def protected(path, *args, **kwargs):
        if path == old:
            raise PermissionError('protected file')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', protected)
    errors = []
    assert not archive.maintain(tmp_path, new.stat().st_size, errors.append)
    assert old.exists() and new.exists() and errors
