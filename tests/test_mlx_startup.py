import asyncio
import io
import json
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import linguaflow.mlx_asr as mlx
from linguaflow.inference_startup import load_components


def controlled_process(monkeypatch, reply):
    entered, release, exited = Event(), Event(), Event()
    class Output(io.StringIO):
        def readline(self):
            entered.set()
            assert release.wait(3), 'test did not release model initialization'
            return '' if exited.is_set() else json.dumps(reply) + '\n'
    def stop():
        exited.set()
        release.set()
    process = SimpleNamespace(stdin=io.StringIO(), stdout=Output(),
                              poll=lambda: 0 if exited.is_set() else None,
                              terminate=stop, kill=stop, wait=lambda **kwargs: stop())
    monkeypatch.setattr(mlx, 'mlx_python', lambda: Path(sys.executable))
    monkeypatch.setattr(mlx.subprocess, 'Popen', lambda *args, **kwargs: process)
    return process, entered, release


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_shared_startup_owns_blocked_mlx_handshake_and_closes_it(monkeypatch, outcome):
    reply = ({'type': 'error', 'text': 'bad weights'} if outcome == 'error' else
             {'type': 'ready', 'device': 'Device(gpu, 0)', 'load_seconds': 1.})
    process, entered, release = controlled_process(monkeypatch, reply)
    clients, statuses, delivered = [], [], []

    def load(own):
        def track(client):
            clients.append(client)
            own(client)
        return mlx.MLXClient('model', 'English', statuses.append, own=track)

    async def exercise():
        async def startup():
            async with load_components(load, lambda: 'SaT') as (client, semantic):
                delivered.append((client, semantic))
        task = asyncio.create_task(startup())
        assert await asyncio.to_thread(entered.wait, 2)
        assert not task.done() and not statuses and not delivered
        assert json.loads(process.stdin.getvalue()) == {'model': 'model', 'language': 'English'}
        if outcome == 'cancel':
            task.cancel()
        else:
            release.set()
        if outcome == 'success':
            await asyncio.wait_for(task, 3)
            assert delivered == [(clients[0], 'SaT')] and len(statuses) == 1
        else:
            with pytest.raises(asyncio.CancelledError if outcome == 'cancel' else RuntimeError):
                await asyncio.wait_for(task, 3)
            assert not delivered
        assert clients[0].closed and not clients[0].exchange.is_alive()
        clients[0].close()

    asyncio.run(exercise())
    assert process.poll() is not None and process.stdin.closed and process.stdout.closed


def test_adapter_loads_once_and_closes_on_construction_failure(monkeypatch):
    calls = []
    client = SimpleNamespace(decode=lambda _: 'text', close=lambda: calls.append('close'))
    def create(*args, **kwargs):
        calls.append('load')
        return client
    monkeypatch.setattr(mlx, 'MLXClient', create)
    def fail(*args, **kwargs):
        raise RuntimeError('adapter failed')
    monkeypatch.setattr(mlx, 'QwenAccurateOnline', fail)
    with pytest.raises(RuntimeError, match='adapter failed'):
        mlx.build_mlx_online('model', 'en', .5, lambda _: None)
    assert calls == ['load', 'close']
