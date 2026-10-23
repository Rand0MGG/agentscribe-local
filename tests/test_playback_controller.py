"""Exercise asynchronous media ordering without importing an audio backend."""
from PySide6.QtCore import QCoreApplication

from linguaflow.playback_controller import PlaybackController
from scripts.desktop_playback_fixture import Output, Player


def test_seek_waits_for_ready_then_positions_before_playing():
    app = QCoreApplication.instance() or QCoreApplication([])
    controller = PlaybackController()
    controller._create_player(Player, Output)
    player = controller.player
    calls = []
    player.log = lambda action: calls.append((action, player.position()))
    player.status = 'LoadingMedia'
    controller.seek(6000, play=True)
    controller.seek(12000, play=True)
    assert not calls
    player.status = 'LoadedMedia'
    player.mediaStatusChanged.emit(player.mediaStatus())
    player.seekableChanged.emit(True)
    assert calls == [('seek', 12000), ('play', 12000)]
    assert controller.pending_seek is None
    controller.release()
    app.processEvents()


def test_release_or_error_invalidates_pending_seek_and_toggle_can_cancel_autoplay():
    app = QCoreApplication.instance() or QCoreApplication([])
    controller = PlaybackController()
    controller._create_player(Player, Output)
    player = controller.player
    calls = []
    player.log = lambda action: calls.append((action, player.position()))
    player.status = 'LoadingMedia'
    controller.seek(6000, play=True)
    controller.toggle()
    player.status = 'LoadedMedia'
    player.seekableChanged.emit(True)
    assert calls == [('seek', 6000)]
    for cancel in (controller.release, controller._playback_error):
        calls.clear()
        player.status = 'LoadingMedia'
        controller.seek(9000, play=True)
        cancel()
        player.status = 'LoadedMedia'
        player.mediaStatusChanged.emit(player.mediaStatus())
        assert not calls and controller.pending_seek is None
    controller.release()
    app.processEvents()
