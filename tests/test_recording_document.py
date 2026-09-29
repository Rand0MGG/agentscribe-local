from copy import deepcopy
from dataclasses import asdict

import pytest

from linguaflow.core import Caption
from linguaflow.recording_document import read_recording_document


def document():
    return {'session': dict(id='a'*32, name='test', folder='inbox', created='2026', state='complete'),
            'settings': {'translate': True}, 'captions': [asdict(Caption(1, 0, 1, 'source', 'en'))]}


@pytest.mark.parametrize('mutation', [
    lambda d: d.pop('captions'),
    lambda d: d.update(settings=None),
    lambda d: d.update(captions={}),
    lambda d: d['captions'][0].update(source=None),
    lambda d: d['captions'][0].update(translation_source=None),
    lambda d: d['captions'][0].update(translation_phase='unknown'),
    lambda d: d['captions'][0].update(start=float('nan')),
    lambda d: d['captions'][0].update(end=-1),
    lambda d: d['captions'].append(d['captions'][0].copy()),
    lambda d: d['session'].pop('state'),
])
def test_invalid_document_raises_recoverable_error(mutation):
    data = document()
    mutation(data)
    with pytest.raises(ValueError, match='录音元数据格式无效'):
        read_recording_document(data)


def test_valid_document_roundtrip_does_not_modify_input():
    data = document()
    original = deepcopy(data)
    _, captions = read_recording_document(data)
    assert captions[0].source == 'source' and data == original
