"""P1: LocalAgreement-2, immutable source, and real-replay counterexamples."""
import pytest

from linguaflow.asr_submission import LocalAgreementSubmission


def update(state, text, end, start=0, aligned=True):
    return state.update(text, start=start, audio_end=end, aligned=aligned)


@pytest.mark.p1
def test_two_consecutive_hypotheses_lock_only_the_common_prefix():
    state = LocalAgreementSubmission()
    assert update(state, 'We learn this today.', 1)[1] == []
    text, ranges, _ = update(state, 'We learn this in class.', 2)
    assert text == 'We learn this in class.' and ranges == [(0, 13)]
    text, ranges, _ = update(state, 'We learn this in school now.', 3)
    assert ranges == [(0, len('We learn this in'))]
    assert text == 'We learn this in school now.'


@pytest.mark.p1
def test_aba_does_not_accumulate_votes_and_latest_draft_is_visible():
    state = LocalAgreementSubmission()
    for end, word in enumerate(['Apple', 'Orange', 'Apple'], 1):
        assert update(state, word, end)[:2] == (word, [])
    assert update(state, 'Apple', 4)[:2] == ('Apple', [(0, 5)])
    assert update(state, 'Orange', 5)[:2] == ('Apple', [(0, 5)])
    assert update(state, '', 6)[:2] == ('Apple', [(0, 5)])


@pytest.mark.p1
def test_new_audio_only_without_four_second_or_tail_holdback():
    state = LocalAgreementSubmission()
    for _ in range(10):
        assert update(state, 'last word', 1)[1] == []
    assert update(state, 'last word', 1.5)[1] == [(0, 9)]


@pytest.mark.p1
def test_disagreeing_first_pending_word_defers_later_common_words():
    state = LocalAgreementSubmission()
    update(state, 'Maybe we study probability.', 1)
    assert update(state, 'Perhaps we study probability.', 2)[1] == []
    text, ranges, _ = update(state, 'Perhaps we study probability. More.', 3)
    assert ranges == [(0, len('Perhaps we study probability.'))]
    assert text.endswith(' More.')


@pytest.mark.p1
def test_new_suffix_survives_model_disagreement_with_locked_word():
    state = LocalAgreementSubmission()
    for end in (1, 2):
        update(state, 'Oh.', end)
    text, ranges, _ = update(state, 'TV. We discuss 3D television.', 3)
    assert text == 'Oh. We discuss 3D television.' and ranges == [(0, 3)]
    text, ranges, _ = update(state, 'TV. We discuss 3D television.', 4)
    assert text == 'Oh. We discuss 3D television.' and ranges == [(0, len(text))]


@pytest.mark.p1
def test_window_roll_keeps_direct_pending_observation_not_copied_history():
    state = LocalAgreementSubmission()
    update(state, 'Old opening. Current words.', 1)
    text, ranges, _ = update(state, 'Current words. Fresh tail.', 2, start=13)
    assert text == 'Old opening. Current words. Fresh tail.'
    assert ranges == [(13, 27)]
    text, ranges, _ = update(state, 'Different words. Fresh tail.', 3, start=13)
    assert text == 'Old opening. Current words. Fresh tail.'
    assert ranges == [(13, len(text))]


@pytest.mark.p1
def test_unmatched_roll_resets_pending_evidence_but_retains_history():
    state = LocalAgreementSubmission()
    update(state, 'Old words. New words.', 1)
    assert update(state, 'New words.', 2, start=11, aligned=False)[1] == []
    text, ranges, _ = update(state, 'New words.', 3, start=11)
    assert ranges == [(11, len(text))]


@pytest.mark.p1
def test_locked_tokenization_changes_do_not_duplicate_internal_words():
    state = LocalAgreementSubmission()
    for end in (1, 2):
        update(state, 'Use softmax here.', end)
    for end, text in enumerate(['Use soft mass here. New.', 'Use soft maths here. New.'], 3):
        actual, ranges, _ = update(state, text, end)
        assert actual == 'Use softmax here. New.'
    assert ranges == [(0, len(actual))]


@pytest.mark.p1
def test_locked_run_rejects_internal_insertions_but_appends_new_tail():
    state = LocalAgreementSubmission()
    for end in (1, 2):
        update(state, 'Keep these words.', end)
    assert update(state, 'Keep extra these words!', 3)[0] == 'Keep these words.'
    assert update(state, 'these', 4)[0] == 'Keep these words.'
    assert update(state, 'Keep these words. New tail.', 5)[0] == 'Keep these words. New tail.'


@pytest.mark.p1
def test_chinese_locks_and_latest_unlocked_suffix():
    state = LocalAgreementSubmission()
    update(state, '我们学习概率。甲', 1)
    assert update(state, '我们学习概率。乙', 2)[1] == [(0, 7)]
    assert update(state, '我们学习几何。丙', 3)[:2] == ('我们学习概率。丙', [(0, 7)])


@pytest.mark.p1
def test_omission_interrupts_consecutive_agreement():
    state = LocalAgreementSubmission()
    for end, word in enumerate(['Apple', '', 'Apple'], 1):
        assert update(state, word, end)[:2] == (word, [])
    assert update(state, 'Apple', 4)[1] == [(0, 5)]


@pytest.mark.p1
def test_new_repeated_occurrence_needs_its_own_second_observation():
    state = LocalAgreementSubmission()
    for end in (1, 2):
        update(state, 'Again.', end)
    assert update(state, 'Again. Again.', 3)[:2] == ('Again. Again.', [(0, 6)])
    assert update(state, 'Again. Again.', 4)[1] == [(0, 13)]


@pytest.mark.p1
def test_same_pcm_correction_does_not_supply_agreement():
    state = LocalAgreementSubmission()
    update(state, 'Apple', 1)
    assert update(state, 'Orange', 1)[1] == []
    assert update(state, 'Orange', 2)[1] == []
    assert update(state, 'Orange', 3)[1] == [(0, 6)]
