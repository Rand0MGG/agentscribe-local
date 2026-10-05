import pytest

from linguaflow.audio_processing.config import AudioConfig, automatic_audio_config


def test_reject_invalid_audio_settings():
    for data in [{"peak_db": float("nan")}, {"peak_db": 1}, {"limiter": "false"},
                 {"output_db": None}, {"output_db": True}, []]:
        with pytest.raises(ValueError):
            AudioConfig.from_dict(data)


def test_legacy_enhancement_keys_cannot_restore_retired_features():
    data = {'deepfilter': True, 'df_device': 'cuda', 'apm': True, 'wpe': True, 'gain': True}
    assert AudioConfig.from_dict(data).to_dict() == AudioConfig().to_dict()
    assert set(automatic_audio_config()) == {'output_db', 'limiter', 'peak_db'}


def test_automatic_audio_sessions_have_independent_configs():
    first = automatic_audio_config()
    first['output_db'] = 10
    first['deepfilter'] = True
    second = automatic_audio_config()
    assert second['output_db'] == 3 and second['limiter']
    assert 'deepfilter' not in second


def test_silence_and_invalid_input_are_distinguished():
    import numpy as np

    from linguaflow.audio_processing.health import input_warning, signal_stats
    assert '全部为零' in input_warning(signal_stats(np.zeros(4800)))
    assert '电平很低' in input_warning(signal_stats(np.full(4800, 1e-5)))
    assert not input_warning(signal_stats(np.full(4800, .1)))
    with pytest.raises(ValueError):
        signal_stats([np.nan])
