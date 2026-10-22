from dataclasses import replace

import pytest

from linguaflow.core import Caption
from linguaflow.transcript import Transcript


@pytest.mark.p1
def test_caption_order_survives_revisions_removals_and_bulk_load():
    rows = Transcript({4: Caption(4, 1, 2, 'four', 'en'), 1: Caption(1, 0, 1, 'one', 'en')})
    order = rows.ordered_ids
    rows[1] = replace(rows[1], translation='translation', revision=2)
    assert rows.ordered_ids is order and order == (1, 4)
    rows[2] = Caption(2, .5, 1, 'two', 'en')
    assert rows.ordered_ids == (1, 2, 4)
    del rows[1]
    assert rows.ordered_ids == (2, 4)
    rows.clear()
    assert not rows and rows.ordered_ids == ()
