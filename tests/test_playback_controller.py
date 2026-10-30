"""Real WAV transport and playback ownership, with no audio devices."""
import urllib.error
import urllib.request
import wave

import pytest

from linguaflow.playback_controller import PlaybackController


@pytest.mark.p2
def test_loopback_playback_does_not_require_hostname_resolution(tmp_path, monkeypatch):
    import socket

    path = tmp_path/'recording.wav'
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        output.writeframes(bytes(32000))

    def unavailable_resolver(*args):
        raise AssertionError('Loopback playback must not wait for reverse DNS')

    controller = PlaybackController()
    commands = []
    controller.command.connect(commands.append)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(socket, 'getfqdn', unavailable_resolver)
            controller.load(path, [])
        load = commands[-1]
        assert load['operation'] == 'load'
        assert controller.server.server_address[0] == '127.0.0.1'
        assert controller.duration_ms == 2000
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(load['url'], timeout=2) as response:
            assert response.read() == path.read_bytes()
        controller.seek(1000, play=True)
        assert commands[-1] == dict(operation='seek', epoch=load['epoch'], position=1000, play=True)
    finally:
        controller.release()
    assert controller.server is None and controller.stream is None


@pytest.mark.p0
def test_bounded_media_ranges_stale_events_and_release_preserve_original(tmp_path):
    path = tmp_path/'recording.wav'
    with wave.open(str(path),'wb') as output:
        output.setparams((1,2,8000,0,'NONE','not compressed'))
        output.writeframes(bytes(32000))
    original = path.read_bytes()
    controller = PlaybackController()
    commands, positions = [], []
    controller.command.connect(commands.append)
    controller.position_changed.connect(positions.append)
    try:
        controller.load(path, [])
        load = commands[-1]
        request = urllib.request.Request(load['url'],headers={'Range':'bytes=44-63'})
        with urllib.request.urlopen(request,timeout=2) as response:
            assert response.status == 206
            assert response.headers['Content-Range'] == f'bytes 44-63/{len(original)}'
            assert response.read() == original[44:64]
        for url, headers, code in ((load['url']+'/other',{},404),(load['url'],{'Range':'bytes=9999999-'},416)):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=2)
            assert error.value.code == code
        controller.seek(1000,play=True)
        controller.receive(load['epoch'],'PlayingState',1000)
        assert controller.playing and positions[-1] == 1000
        controller.load(path,[])
        controller.receive(load['epoch'],'PlayingState',1500)
        assert not controller.playing and controller.position == 0
        assert commands[-1]['epoch'] != load['epoch']
    finally:
        controller.release()
    assert controller.server is None and controller.stream is None
    assert path.read_bytes() == original
