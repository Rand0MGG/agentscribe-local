import json
from types import SimpleNamespace

import pytest

from linguaflow import download_progress


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
