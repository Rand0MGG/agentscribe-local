import pytest
from linguaflow.audio_processing.config import AudioConfig, PRESETS


def test_reject_invalid_audio_settings():
    for data in [{"df_mix": float("nan")}, {"wpe_alpha": 1}, {"df_device": "auto"}, {"apm_level": 4},
                 {"wpe_taps": 3.5}, {"apm": "false"}, {"output_db": None}, []]:
        with pytest.raises(ValueError):
            AudioConfig.from_dict(data)


def test_default_bypasses_enhancement_and_presets_are_valid():
    config = AudioConfig()
    assert not any([config.apm, config.wpe, config.deepfilter, config.gain, config.eq, config.limiter])
    for preset in PRESETS.values():
        assert AudioConfig.from_dict(preset.to_dict()) == preset


def test_silence_and_invalid_input_are_distinguished():
    import numpy as np
    from linguaflow.audio_processing.health import signal_stats, input_warning
    assert '全部为零' in input_warning(signal_stats(np.zeros(4800)))
    assert '电平很低' in input_warning(signal_stats(np.full(4800, 1e-5)))
    assert not input_warning(signal_stats(np.full(4800, .1)))
    with pytest.raises(ValueError):
        signal_stats([np.nan])
