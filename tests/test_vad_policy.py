from types import SimpleNamespace

import pytest

from linguaflow.runtime_compat import configure_vad_pause


def test_ui_pause_reaches_the_detector_not_just_caption_metadata():
    detector = SimpleNamespace(min_silence_samples=1600)
    processor = SimpleNamespace(vac=detector, sample_rate=16000)
    configure_vad_pause(processor, 1.5)
    assert detector.min_silence_samples == 24000
    configure_vad_pause(processor, .5)
    assert detector.min_silence_samples == 8000
    configure_vad_pause(SimpleNamespace(vac=None), 1.5)
    with pytest.raises(ValueError):
        configure_vad_pause(processor, float('nan'))
