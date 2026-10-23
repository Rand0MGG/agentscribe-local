"""Offline execution boundary for native Electron probes, installed only in their sitecustomize.

Never replace the renderer bridge, Service.request, DesktopService dispatch or validators.
Real Preparation/BackgroundCheck processes execute this small local workload instead of
installing dependencies or downloading model weights. All other commands use production code.
"""
import json
import os
import sys
import time
from pathlib import Path


def install():
    from linguaflow import runtime_paths
    original = runtime_paths.installation_command

    def command(module, *arguments):
        if module in ('linguaflow.recommended_prepare', 'linguaflow.runtime_install', 'linguaflow.document_install'):
            return [sys.executable, '-u', str(Path(__file__).resolve()), module, *arguments]
        return original(module, *arguments)

    runtime_paths.installation_command = command
    # Slow only the first explicit write, retaining the real serializer and filesystem.
    from linguaflow import recording_export
    writer = recording_export.write_export

    def write(item, captions, state=None):
        root = Path(os.environ['AGENTSCRIBE_CHAIN_FIXTURE'])
        if (root / 'hold-export').exists():
            (root / 'export-started').touch()
            deadline = time.monotonic() + 15
            while (root / 'hold-export').exists() and time.monotonic() < deadline:
                time.sleep(.02)
        return writer(item, captions, state)

    recording_export.write_export = write
    # Isolate cloud execution only. KnowledgeClient, worker IPC, permissions, jobs,
    # recording identity, persistence and stale-result rejection remain real.
    from linguaflow.knowledge import api, harness
    class NoProviderSDK:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in {'langchain_core', 'langchain_deepseek', 'deepagents', 'keyring'}:
                raise RuntimeError('Offline desktop probe must not import provider SDKs: ' + fullname)

    sys.meta_path.insert(0, NoProviderSDK())

    def initialize(self, *args, notify=lambda value: None, before_request=None, **kwargs):
        # Model execution is offline even in the minimal .[dev] CI environment.
        self.http = None
        self.budget = api.RequestBudget(notify)
        self.before_request = before_request

    async def answer(service, job, **kwargs):
        if service.before_request:
            service.before_request()
        service.budget.reserve('fixture', [job.question])
        service.budget.finish('fixture', {'total_tokens': 12})
        return {'answer': '本地测试回答：' + job.question, 'refs': []}

    api.DeepSeekService.__init__ = initialize
    harness.run_agent = answer


def main():
    from linguaflow.download_progress import report
    root = Path(os.environ['AGENTSCRIBE_CHAIN_FIXTURE'])
    args = sys.argv[1:]
    with (root / 'commands.jsonl').open('a', encoding='utf-8') as file:
        file.write(json.dumps(args) + '\n')
    if '--check' in args:
        print(json.dumps([] if (root / 'prepared').exists() else ['翻译模型：离线测试资源尚未准备']))
        return
    mode = (root / 'prepare-mode').read_text().strip() if (root / 'prepare-mode').exists() else 'success'
    for index in range(5 if mode != 'hold' else 1200):
        report('离线测试资源', index * 1024, 5 * 1024, rate=2048)
        time.sleep(.1)
    if mode == 'fail':
        raise RuntimeError('测试下载失败，原文件保留')
    (root / 'prepared').touch()
    print('准备完成')


if __name__ == '__main__':
    main()
