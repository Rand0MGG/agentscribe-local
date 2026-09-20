import wave

import numpy as np

from linguaflow.audio_processing.recorder import Recorder


def test_sample_capture_is_bounded_and_tracks_health_without_an_audio_device(tmp_path):
    def capture(settings, stop, block):
        assert settings.input_sample_rate == 48000 and settings.loopback
        block(np.full(36000, .25, dtype=np.float32))
        block(np.full(36000, .25, dtype=np.float32))
        assert stop.is_set()

    path = tmp_path / 'sample.wav'
    recorder = Recorder(('fixture', True), path, 1, capture_fn=capture)
    recorder.run()
    with wave.open(str(path)) as audio:
        assert audio.getnframes() == 48000 and audio.getframerate() == 48000
    assert recorder.health['samples'] == 48000 and recorder.health['nonzero'] == 48000
