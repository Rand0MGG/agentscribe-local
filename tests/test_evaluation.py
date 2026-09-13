import copy
import json

import pytest

from linguaflow.evaluation import (POLICY, align, chat_text, final_captions, parse_chat,
                                  review_problems, score, words)


def reference():
    return {'source': {'media_sha256': 'audio', 'duration_seconds': 2}, 'origin': {},
            'review': {'reviewer': 'test fixture reviewer', 'full_audio_listened': True,
                       'all_speech_covered': True, 'independent_of_test_output': True,
                       'overlap_order_checked': True},
            'utterances': [{'id': '1', 'text': 'we we agree', 'start_ms': 0, 'end_ms': 1000,
                            'review': {'status': 'verified', 'reviewed_at': '2026-01-01T00:00:00Z',
                                       'reviewed_text': 'we we agree', 'start_ms': 0, 'end_ms': 1000}}]}


def caption(text, revision=1, ident=1, final=True, at=1):
    return {'type': 'caption', 'elapsed_seconds': at,
            'data': {'id': ident, 'revision': revision, 'source': text,
                     'start': 0, 'end': 1, 'final': final}}


def run():
    manifest = {'complete': True, 'audio': {'source_sha256': 'audio', 'samples': 96000},
                'capture': {'samples_delivered': 96000}, 'replay_speed': 1.0,
                'reference_available_to_asr': False}
    events = [caption('we we agree'), {'type': 'session_finished', 'complete': True}]
    return manifest, events


def test_chat_keeps_spoken_repetitions_repairs_fillers_and_not_grammar(tmp_path):
    path = tmp_path/'sample.cha'
    path.write_text('@Media:\tsample, video\n@Comment:\tBatchalign, ASR Engine rev\n'
                    '*PAR:\t<I wanted> [//] &-um I thought I wanted\n'
                    '\tto go . \x1510_1000\x15\n%mor:\tTHIS IS NOT SPEECH\n', encoding='utf-8')
    parsed = parse_chat(path)
    assert parsed['origin']['asr_origin_detected']
    row = parsed['utterances'][0]
    assert row['text'] == 'i wanted um i thought i wanted to go'
    assert (row['start_ms'], row['end_ms']) == (10, 1000)
    assert row['review']['status'] == 'pending'


def test_chat_does_not_replace_spoken_word_with_editorial_correction():
    text, issues = chat_text('pezzle [: pretzel] &+s &-uh &=laughs xxx .')
    assert text == 'pezzle uh xxx'
    assert 'unintelligible_or_untranscribed_speech' in issues
    assert 'partial_word_requires_review' in issues
    assert any('pretzel' in issue for issue in issues)


def test_normalization_is_symmetric_and_preserves_contractions_and_repetition():
    assert words("I, I don’t know twenty_one.") == ['i', 'i', "don't", 'know', 'twenty', 'one']
    assert words('2') != words('two')  # No semantic guesses or reference-driven rewriting.
    assert words('um umbrella', exclude_fillers=True) == ['umbrella']


@pytest.mark.parametrize('expected,actual,s,d,i', [
    ('a b c', 'a x c', 1, 0, 0), ('a b c', 'a c', 0, 1, 0),
    ('a b', 'a b c', 0, 0, 1), ('we we go', 'we go', 0, 1, 0),
    ('a b', '', 0, 2, 0), ('', 'a b', 0, 0, 2), ('', '', 0, 0, 0),
    ('a b', 'b a', 2, 0, 0),
])
def test_exact_edit_counts_and_traceback(expected, actual, s, d, i):
    ref, hyp = expected.split(), actual.split()
    counts, ops = align(ref, hyp)
    assert (counts['substitute'], counts['delete'], counts['insert']) == (s, d, i)
    assert [ref[o['reference_index']] for o in ops if o['reference_index'] is not None] == ref
    assert [hyp[o['hypothesis_index']] for o in ops if o['hypothesis_index'] is not None] == hyp
    assert counts['ratio'] == ((s+d+i)/len(ref) if ref else None)


def test_final_state_revisions_tombstones_and_real_repetition():
    events = [caption('wrong draft', final=False), caption('we we agree', revision=2),
              caption('duplicate draft', ident=2, final=False), caption('', ident=2, revision=2)]
    rows, issues, metrics = final_captions(events)
    assert not issues
    assert [r['source'] for r in rows] == ['we we agree']
    assert metrics['retractions'] == 1 and metrics['non_append_revisions'] == 1


def test_same_text_in_distinct_captions_is_not_deduplicated():
    rows, _, _ = final_captions([caption('yes'), caption('yes', ident=2)])
    assert len(rows) == 2


def test_unreviewed_reference_never_gets_wer_even_if_identical():
    ref = reference()
    ref['review']['full_audio_listened'] = False
    manifest, events = run()
    result, _ = score(ref, manifest, events)
    assert result['wer'] is None
    assert result['unverified_word_disagreement'] == 0
    assert result['status'] == 'unverified_reference_comparison_only'


def test_review_attestation_allows_wer_but_text_or_time_edits_revoke_it():
    manifest, events = run()
    assert score(reference(), manifest, events)[0]['wer'] == 0
    for field, value in [('text', 'we agree'), ('start_ms', 20)]:
        ref = reference()
        ref['utterances'][0][field] = value
        assert score(ref, manifest, events)[0]['wer'] is None


def test_unintelligible_reference_cannot_be_certified():
    ref = reference()
    ref['utterances'][0]['text'] = ref['utterances'][0]['review']['reviewed_text'] = 'xxx'
    assert any('unresolved_speech' in issue for issue in review_problems(ref))


def test_missing_timestamp_keeps_all_words_but_prevents_certified_score():
    ref = reference()
    ref['utterances'][0]['start_ms'] = None
    manifest, events = run()
    result, _ = score(ref, manifest, events)
    assert result['wer'] is None and result['comparison']['reference_words'] == 3
    assert result['reference_audit_issues']
    assert not result['invalid_reasons']  # A reference defect is not a runtime failure.


@pytest.mark.parametrize('defect', ['partial_audio', 'incomplete', 'missing_end', 'hash', 'speed', 'leak', 'draft', 'revision'])
def test_invalid_run_is_not_scored(defect):
    manifest, events = run()
    if defect == 'partial_audio':
        manifest['capture']['samples_delivered'] -= 1
    elif defect == 'incomplete':
        manifest['complete'] = False
    elif defect == 'missing_end':
        events.pop()
    elif defect == 'hash':
        manifest['audio']['source_sha256'] = 'different'
    elif defect == 'speed':
        manifest['replay_speed'] = 2
    elif defect == 'leak':
        manifest['reference_available_to_asr'] = True
    elif defect == 'draft':
        events[0]['data']['final'] = False
    elif defect == 'revision':
        events = [caption('we', revision=2), caption('we we agree'), events[-1]]
    result, ops = score(reference(), manifest, events)
    assert result['status'] == 'invalid_run'
    assert result['wer'] is None and result['comparison'] is None and ops == []


def test_empty_hypothesis_is_full_deletion_not_a_crash():
    manifest, events = run()
    result, _ = score(reference(), manifest, events[1:])
    assert result['wer'] == 1 and result['comparison']['delete'] == 3


@pytest.mark.parametrize('defect', ['unfinished', 'events_tampered', 'settings_tampered'])
def test_cli_rejects_incomplete_or_changed_run_files(tmp_path, defect):
    from scripts.evaluate_streaming import evaluate
    from linguaflow.evaluation import file_hash
    ref_path = tmp_path/'reference.json'
    ref_path.write_text(json.dumps(reference()), encoding='utf-8')
    manifest, events = run()
    events_path = tmp_path/'events.jsonl'
    events_path.write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
    settings_path = tmp_path/'settings.json'
    settings_path.write_text('{}', encoding='utf-8')
    manifest.update(events_sha256=file_hash(events_path), settings_sha256=file_hash(settings_path))
    if defect == 'unfinished':
        manifest['complete'] = False
    elif defect == 'events_tampered':
        events_path.write_text('', encoding='utf-8')
    else:
        settings_path.write_text('{"changed": true}', encoding='utf-8')
    (tmp_path/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='no score issued'):
        evaluate(ref_path, tmp_path, tmp_path/'score')
    assert not (tmp_path/'score'/'score.json').exists()


def test_empty_review_requires_explicit_non_speech_attestation():
    ref = reference()
    row = ref['utterances'][0]
    row['text'] = row['review']['reviewed_text'] = ''
    assert any('empty_reference' in p for p in review_problems(ref))
    row['review']['non_speech'] = True
    assert not review_problems(ref)
