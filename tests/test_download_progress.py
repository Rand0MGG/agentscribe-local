import io
import json
from types import SimpleNamespace

import pytest

from linguaflow import download_progress


@pytest.mark.parametrize('length', ['7', None])
def test_http_progress_reports_bytes_without_inventing_a_total(capsys, length):
    response = io.BytesIO(b'content')
    response.headers = {'Content-Length': length} if length else {}
    output = io.BytesIO()
    download_progress.copy_download(response, output, 'weights')
    events = [json.loads(line.removeprefix(download_progress.PREFIX))
              for line in capsys.readouterr().out.splitlines()]
    assert output.getvalue() == b'content'
    assert events[0]['completed'] == 0
    assert events[-1]['completed'] == 7
    assert events[-1]['total'] == (7 if length else None)
    assert events[-1]['rate'] > 0


def test_hub_progress_preserves_resume_offset_and_restores_adapter_after_failure(monkeypatch, capsys):
    class Original:
        def __init__(self, **kwargs):
            self.n, self.total, self.unit, self.desc = 6, 10, 'B', 'resumed weights'
            self.format_dict = {'rate': 2}

    module = SimpleNamespace(tqdm=Original)
    monkeypatch.setattr(download_progress.importlib, 'import_module', lambda _: module)
    with pytest.raises(RuntimeError):
        with download_progress.hub_progress() as adapter:
            adapter().display()
            assert module.tqdm is adapter
            raise RuntimeError('cancelled')
    event = json.loads(capsys.readouterr().out.strip().removeprefix(download_progress.PREFIX))
    assert event['completed'] == 6 and event['total'] == 10 and event['rate'] == 2
    assert module.tqdm is Original


def test_semantic_downloads_use_progress_but_local_checks_remain_offline(monkeypatch, tmp_path):
    import sys
    from contextlib import nullcontext

    from linguaflow import semantic_model
    (tmp_path / 'model_optimized.onnx').write_bytes(b'fixture')
    calls, bar = [], object()
    def snapshot(repo, **kwargs):
        calls.append(kwargs)
        return str(tmp_path)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setattr(download_progress, 'hub_progress', lambda: nullcontext(bar))
    semantic_model.paths(prepare=True)
    assert all(call['tqdm_class'] is bar and not call['local_files_only'] for call in calls)
    calls.clear()
    semantic_model.paths()
    assert all(call['local_files_only'] and 'tqdm_class' not in call for call in calls)


def test_hub_byte_callbacks_report_below_adaptive_terminal_refresh(capsys):
    import importlib
    from unittest.mock import patch
    module = importlib.import_module('huggingface_hub.utils.tqdm')
    original = module.tqdm
    with download_progress.hub_progress() as bar_type:
        with patch.object(download_progress.time, 'monotonic', side_effect=range(100, 1000)):
            with bar_type(total=1000, unit='B', desc='large weights', miniters=10**9) as bar:
                bar.update(10)
                bar.update(20)
    events = [json.loads(line.removeprefix(download_progress.PREFIX))
              for line in capsys.readouterr().out.splitlines()]
    assert any(event['completed'] == 10 for event in events)
    assert any(event['completed'] == 30 for event in events)
    assert module.tqdm is original
