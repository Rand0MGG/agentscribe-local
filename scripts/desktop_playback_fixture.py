"""Test-only delayed media adapter; never open an audio device or use personal files.

The native probe retains renderer/IPC/validators/PlaybackController/PlaybackStream.
Only QtMultimedia's hardware boundary and the update HTTP response are isolated.
"""
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal


class Output(QObject):
    def setVolume(self, value):
        self.volume = value


class Player(QObject):
    durationChanged = Signal('qlonglong')
    positionChanged = Signal('qlonglong')
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    seekableChanged = Signal(bool)
    errorOccurred = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.offset, self.generation = 0, 0
        self.status, self.state = 'NoMedia', 'StoppedState'

    def log(self, action):
        root = os.environ.get('AGENTSCRIBE_INTERACTION_FIXTURE')
        if root:
            with (Path(root) / 'media.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(action=action, position=self.offset, status=self.status)) + '\n')

    def setAudioOutput(self, output):
        self.output = output

    def setSourceDevice(self, stream, url):
        self.generation += 1
        generation = self.generation
        self.status = 'LoadingMedia'
        self.mediaStatusChanged.emit(self.mediaStatus())
        def ready():
            if generation != self.generation:
                return
            self.status = 'LoadedMedia'
            self.durationChanged.emit(stream.duration_ms)
            self.mediaStatusChanged.emit(self.mediaStatus())
            self.seekableChanged.emit(True)
        QTimer.singleShot(350, ready)

    def setSource(self, url):
        self.generation += 1
        self.status = 'NoMedia'
        self.offset = 0

    def mediaStatus(self):
        return SimpleNamespace(name=self.status)

    def isSeekable(self):
        return self.status == 'LoadedMedia'

    def setPosition(self, value):
        if not self.isSeekable():
            self.log('ignored-seek')
            return
        self.offset = value
        self.log('seek')
        self.positionChanged.emit(value)

    def position(self):
        return self.offset

    def playbackState(self):
        return SimpleNamespace(name=self.state)

    def play(self):
        self.log('play')
        self.state = 'PlayingState'
        self.playbackStateChanged.emit(self.playbackState())

    def pause(self):
        self.state = 'PausedState'
        self.playbackStateChanged.emit(self.playbackState())

    def stop(self):
        self.state = 'StoppedState'
        self.playbackStateChanged.emit(self.playbackState())

    def errorString(self):
        return 'fixture media error'


def install():
    sys.modules['PySide6.QtMultimedia'] = SimpleNamespace(QMediaPlayer=Player, QAudioOutput=Output)
    original_exec = QCoreApplication.exec

    def run():
        # The -m entrypoint defines its class in __main__; instrument the actual
        # instance immediately before its Qt event loop processes requests.
        service = sys._getframe(1).f_locals.get('service')
        if service is not None and type(service).__name__ == 'DesktopService':
            original_player = service._player
            original_bootstrap = service.routes['bootstrap']

            def player():
                no_audio = service.no_audio
                service.no_audio = False
                try:
                    return original_player()
                finally:
                    service.no_audio = no_audio

            def bootstrap():
                value = original_bootstrap()
                value['no_audio'] = False  # Enable renderer controls for the inert adapter.
                value['devices'] = [dict(id=1, loopback=False, name='隔离输入'), dict(id=2, loopback=True, name='隔离系统音频')]
                return value

            service._player = player
            service.routes['bootstrap'] = bootstrap
        return original_exec()

    QCoreApplication.exec = staticmethod(run)
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
