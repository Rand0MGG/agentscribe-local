"""Run the real Electron audio adapter against inert media devices in Node."""
import faulthandler
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

from linguaflow.events import Dispatcher


def install():
    original_exec = Dispatcher.exec
    def run(dispatcher):
        service = sys._getframe(1).f_locals.get('service')
        adapter = None
        if service is not None and type(service).__name__ == 'DesktopService':
            from linguaflow.frontend_switch import command_for
            root = Path(__file__).resolve().parents[1]
            adapter = subprocess.Popen([command_for('electron')[0], str(root/'desktop/scripts/fake-audio.cjs'),
                os.environ['AGENTSCRIBE_INTERACTION_FIXTURE']], env={**os.environ,'ELECTRON_RUN_AS_NODE':'1'},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            def read():
                for line in adapter.stdout:
                    value = json.loads(line)
                    dispatcher.call(lambda value=value: service.player.receive(**value) if service.player else None)
            reader = Thread(target=read, daemon=True)
            reader.start()
            original_player, original_emit = service._player, service.emit
            original_bootstrap = service.routes['bootstrap']
            def emit(event, data):
                if event == 'audio-command':
                    adapter.stdin.write(json.dumps(data)+'\n')
                    adapter.stdin.flush()
                else:
                    original_emit(event, data)
            def player():
                no_audio = service.no_audio
                service.no_audio = False
                # A blocked first load otherwise leaves CI with only a UI timeout.
                faulthandler.dump_traceback_later(5)
                try:
                    return original_player()
                finally:
                    faulthandler.cancel_dump_traceback_later()
                    service.no_audio = no_audio
            def bootstrap():
                value = original_bootstrap()
                value['no_audio'] = False
                value['devices'] = [dict(id=1,loopback=False,name='隔离输入'),dict(id=2,loopback=True,name='隔离系统音频')]
                return value
            service.emit, service._player = emit, player
            service.routes['bootstrap'] = bootstrap
        try:
            return original_exec(dispatcher)
        finally:
            if adapter:
                adapter.stdin.close()
                adapter.wait(timeout=5)
                reader.join(timeout=5)
                adapter.stdout.close()
    Dispatcher.exec = run
    from linguaflow import updates
    class Response:
        def __enter__(self):
            time.sleep(3)
            return self
        def __exit__(self, *_):
            pass
        def read(self, size):
            return b'[]'
    updates.urllib.request.urlopen = lambda *args, **kwargs: Response()
