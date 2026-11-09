"""Shared first-use, feedback, playback and recording lifecycle acceptance."""
import base64

import pytest

from linguaflow.core import Caption
from linguaflow.playback import PlaybackIndex
from linguaflow.update_config import bundle_version, update_identity


@pytest.mark.p2
def test_playback_boundaries_silence_and_order():
    index = PlaybackIndex([Caption(2, 8, 10, 'second', 'en'), Caption(1, 1, 4, 'first', 'en')])
    assert [index.at(t) for t in (0, 1, 3.9, 4, 7, 8, 10)] == [None, 1, 1, None, None, 2, None]


@pytest.mark.p2
@pytest.mark.parametrize('target', ['macos-arm64', 'windows-x64'])
def test_update_identity_platform_and_channel(target):
    config = {'feed_base': 'https://example.org/updates',
              'targets': {target: {'public_key': base64.b64encode(bytes(32)).decode()}}}
    assert update_identity(config, target, '0.7.0')['feed_url'] == f'https://example.org/updates/{target}/stable.xml'
    assert update_identity(config, target, '0.8.0-beta.2')['channel'] == 'beta'
    assert bundle_version('0.8.0-beta.2') == '0.8.0b2'


@pytest.mark.p0
@pytest.mark.parametrize('target', ['macos-arm64', 'windows-x64'])
def test_update_identity_rejects_missing_trust_key(target):
    config = {'feed_base': 'https://example.org/updates',
              'targets': {target: {'public_key': ''}}}
    with pytest.raises(ValueError, match='公钥'):
        update_identity(config, target, '0.7.0')
