from dataclasses import replace

from linguaflow.core import Caption
from linguaflow.translation_queue import translation_is_current


def test_inflight_result_cannot_overwrite_new_version_even_if_text_returns():
    old = Caption(1, 0, 1, 'original', 'en', revision=1, ready=True)
    assert translation_is_current(old, old)
    assert not translation_is_current(replace(old, revision=3), old)
    assert not translation_is_current(replace(old, source='', revision=2), old)
    assert not translation_is_current(None, old)
