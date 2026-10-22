"""Real renderer helper exit and cancellation, without Qt or native audio."""
import asyncio
import sys

import pytest

from linguaflow.knowledge.rendering import run_renderer


@pytest.mark.p0
@pytest.mark.parametrize('exit_code', [0, 7])
def test_renderer_exit_reports_status_without_document_content(tmp_path, caplog, exit_code):
    helper = tmp_path / 'helper.py'
    helper.write_text("import sys\nprint('private document text', file=sys.stderr)\n"
                      f"raise SystemExit({exit_code})\n", encoding='utf-8')
    if exit_code:
        with pytest.raises(RuntimeError, match='原件与已保存内容保留'):
            asyncio.run(run_renderer([sys.executable, helper]))
        assert 'renderer exited with code 7' in caplog.text
    else:
        asyncio.run(run_renderer([sys.executable, helper]))
        assert not caplog.records
    assert 'private document text' not in caplog.text
    assert str(helper) not in caplog.text


@pytest.mark.p2
def test_renderer_cancellation_waits_for_real_helper_exit(tmp_path):
    helper = tmp_path / 'helper.py'
    started, stopped = tmp_path / 'started', tmp_path / 'stopped'
    helper.write_text('import sys\nfrom pathlib import Path\n'
                      'Path(sys.argv[1]).write_text("started")\n'
                      'sys.stdin.buffer.read()\n'
                      'Path(sys.argv[2]).write_text("stdin closed")\n', encoding='utf-8')

    async def scenario():
        task = asyncio.create_task(run_renderer([sys.executable, helper, started, stopped]))

        async def ready():
            while not started.exists():
                if task.done():
                    await task
                    raise AssertionError('Helper exited before it was ready')
                await asyncio.sleep(.01)

        try:
            await asyncio.wait_for(ready(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stopped.read_text() == 'stdin closed'
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
