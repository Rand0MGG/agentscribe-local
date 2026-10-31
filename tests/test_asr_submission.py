"""P1: cumulative, position-scoped ASR votes and irreversible submission."""
import pytest

from linguaflow.asr_submission import CumulativeSubmission


def update(state, text, end, start=0, aligned=True):
    return state.update(text, start=start, audio_end=end, aligned=aligned)


@pytest.mark.p1
def test_nonconsecutive_votes_lock_and_ignore_later_replacement_or_deletion():
    state = CumulativeSubmission()
    for end, word in enumerate(['apple', 'apple', 'orange', 'apple'], 1):
        text, ranges, _ = update(state, word, end)
        assert text == word
        assert bool(ranges) == (end == 4)
    assert update(state, 'orange', 5)[:2] == ('apple', [(0, 5)])
    assert update(state, '', 6)[:2] == ('apple', [(0, 5)])


@pytest.mark.p1
def test_new_audio_only_and_no_four_second_or_tail_holdback():
    state = CumulativeSubmission()
    for _ in range(10):
        assert update(state, 'last word', 1)[1] == []
    assert update(state, 'last word', 1.5)[1] == []
    assert update(state, 'last word', 2)[1] == [(0, 9)]


@pytest.mark.p1
def test_uncertain_opening_does_not_block_later_words_or_lock_other_occurrences():
    state = CumulativeSubmission()
    for end, opening in enumerate(['Maybe', 'Perhaps', 'Possibly'], 1):
        text, ranges, _ = update(state, opening + ' we study probability.', end)
    assert text == 'Possibly we study probability.'
    assert ranges == [(9, len(text))]
    text, ranges, _ = update(state, 'Now we study probability. probability.', 4)
    assert text == 'Now we study probability. probability.'
    assert ranges == [(4, 25)]


@pytest.mark.p1
def test_window_roll_inherits_only_direct_votes_and_preserves_locked_history():
    state = CumulativeSubmission()
    for end in (1, 2):
        update(state, 'Old opening. Current words.', end)
    text, ranges, _ = update(state, 'Current words. Fresh tail.', 3, start=len('Old opening. '))
    assert text == 'Old opening. Current words. Fresh tail.'
    assert ranges == [(13, 27)]
    for end in (4, 5):
        text, ranges, _ = update(state, 'Different words. Fresh tail.', end, start=13)
    assert text == 'Old opening. Current words. Fresh tail.'
    assert ranges == [(13, len(text))]


@pytest.mark.p1
def test_multiple_word_candidate_keeps_nonconsecutive_votes():
    state = CumulativeSubmission()
    for end, middle in enumerate(['soft mass', 'softmax', 'softmax', 'soft mass', 'softmax'], 1):
        text, ranges, _ = update(state, 'Use ' + middle + ' here.', end)
    assert text == 'Use softmax here.'
    assert ranges == [(0, len(text))]
    assert update(state, 'Use soft mass here.', 6)[0] == text


@pytest.mark.p1
def test_chinese_change_preserves_locks_and_updates_only_unlocked_words():
    state = CumulativeSubmission()
    for end, tail in enumerate(['甲', '乙', '丙'], 1):
        update(state, '我们学习概率。' + tail, end)
    text, ranges, _ = update(state, '我们学习几何。丁', 4)
    assert text == '我们学习概率。丁'
    assert ranges == [(0, 7)]


@pytest.mark.p1
def test_unmatched_roll_does_not_grant_copied_votes_or_erase_locks():
    state = CumulativeSubmission()
    for end in (1, 2):
        update(state, 'Old words. New words.', end)
    text, ranges, _ = update(state, 'New words.', 3, start=11, aligned=False)
    assert ranges == []
    for end in (4, 5):
        text, ranges, _ = update(state, 'New words.', end, start=11)
    assert ranges == [(11, len(text))]


@pytest.mark.p1
def test_locked_run_rejects_internal_insertions_and_punctuation_changes():
    state = CumulativeSubmission()
    for end in (1, 2, 3):
        update(state, 'Keep these words.', end)
    assert update(state, 'Keep extra these words!', 4)[0] == 'Keep these words.'
    assert update(state, 'these', 5)[0] == 'Keep these words.'
    assert update(state, 'Keep these words. New tail.', 6)[0] == 'Keep these words. New tail.'


@pytest.mark.p1
def test_insertion_before_unlocked_word_moves_its_votes_without_borrowing_them():
    state = CumulativeSubmission()
    update(state, 'Use probability here.', 1)
    update(state, 'Use probability here.', 2)
    text, ranges, _ = update(state, 'Use conditional probability here.', 3)
    assert text == 'Use conditional probability here.'
    assert ranges == [(0, 3), (16, len(text))]
    assert update(state, 'Use conditional probability here.', 4)[1] == ranges
    assert update(state, 'Use conditional probability here.', 5)[1] == [(0, len(text))]


@pytest.mark.p1
def test_locked_multiword_candidate_survives_window_boundary_inside_it():
    state = CumulativeSubmission()
    for end, word in enumerate(['softmax', 'soft mass', 'soft mass', 'soft mass'], 1):
        update(state, 'Use ' + word + ' here.', end)
    text, ranges, _ = update(state, 'wrong here. New.', 5, start=len('Use soft '))
    assert text == 'Use soft mass here. New.'
    assert ranges == [(0, len('Use soft mass here.'))]


@pytest.mark.p1
def test_adjacent_replacements_keep_independent_votes():
    state = CumulativeSubmission()
    for end, phrase in enumerate(['One cat', 'Two dog', 'Three dog', 'Four dog'], 1):
        text, ranges, _ = update(state, phrase, end)
    assert text == 'Four dog'
    assert ranges == [(5, 8)]


@pytest.mark.p1
@pytest.mark.parametrize('values, expected', [
    (['Apple', 'Apple', '', 'Apple'], 'Apple'),
    (['Use apple here.', 'Use apple here.', 'Use here.', 'Use apple here.'], 'Use apple here.'),
    (['Keep apple', 'Keep apple', 'Keep orange', '', 'Keep apple'], 'Keep apple'),
])
def test_temporarily_omitted_word_keeps_earlier_votes(values, expected):
    state = CumulativeSubmission()
    for end, value in enumerate(values, 1):
        text, ranges, _ = update(state, value, end)
        if end == 3:
            assert text.strip() == value
    assert text == expected and ranges == [(0, len(expected))]
