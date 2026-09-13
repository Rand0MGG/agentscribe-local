import csv
import json
import sys

import pytest

from linguaflow.ami_evaluation import (MEETING, PROTOCOL, evaluate, overlap_seconds,
                                      parse_speaker, reference_tokens, validate_run, write_json)
from linguaflow.evaluation import file_hash
from scripts.benchmark_ami import frozen_settings, run as benchmark


def test_xml_word_pointer_coverage_and_nonlexical_annotations():
    w = '''<root xmlns:nite="http://nite.sourceforge.net/">
    <w nite:id="a0" starttime="0" endtime=".1">We</w>
    <w nite:id="a1" starttime=".1" endtime=".2">we</w>
    <w nite:id="a2" starttime=".2" endtime=".3" trunc="true">ag</w>
    <vocalsound nite:id="a3" starttime=".3" endtime=".4" type="laugh"/>
    <gap nite:id="a4" starttime=".4" endtime=".5"/>
    <w nite:id="a5" starttime=".5" endtime=".5" punc="true">.</w>
    </root>'''
    s = f'''<root xmlns:nite="http://nite.sourceforge.net/">
    <segment nite:id="s0" transcriber_start="0" transcriber_end=".5">
      <nite:child href="{MEETING}.A.words.xml#id(a0)..id(a5)"/>
    </segment></root>'''
    lexical, turns, annotations = parse_speaker(w, s, 'A')
    assert [t for e in lexical for t in e['tokens']] == ['we', 'we', 'ag']
    assert lexical[2]['partial']
    assert turns[0]['word_ids'] == ['a0', 'a1', 'a2']
    assert [e['kind'] for e in annotations] == ['vocalsound', 'gap', 'punctuation']
    with pytest.raises(ValueError, match='Unassigned'):
        parse_speaker(w, s.replace('id(a5)', 'id(a1)'), 'A')
    with pytest.raises(ValueError, match='multiple turns'):
        parse_speaker(w, s.replace('</root>', s[s.index('<segment'):s.index('</root>')]+'</root>'), 'A')


def reference():
    entries = [dict(id='a0', speaker='A', start=0., end=1., tokens=['hello']),
               dict(id='a1', speaker='A', start=2., end=3., tokens=['there']),
               dict(id='b0', speaker='B', start=.5, end=1.5, tokens=['yes'])]
    return dict(protocol=PROTOCOL, source=dict(audio_sha256='audio'), duration_seconds=4.,
                words=entries, segments=[dict(id='s0', speaker='A', start=0., end=3., word_ids=['a0','a1']),
                                         dict(id='s1', speaker='B', start=.5, end=1.5, word_ids=['b0'])],
                audit=dict(partial_words=0, annotation_types={}, gap_seconds=0., word_interval_overlap_seconds=.5))


def test_overlap_orders_are_explicit_and_keep_every_word():
    ref = reference()
    assert [w['word'] for w in reference_tokens(ref, 'turn')] == ['hello', 'there', 'yes']
    assert [w['word'] for w in reference_tokens(ref, 'word_time')] == ['hello', 'yes', 'there']
    assert overlap_seconds(ref['words']) == .5
    # Two same-speaker intervals are not counted as multi-speaker overlap.
    assert overlap_seconds([dict(speaker='A',start=0.,end=2.), dict(speaker='A',start=1.,end=3.)]) == 0


def run_fixture():
    manifest = dict(complete=True, audio=dict(source_sha256='audio', samples=192000, rate=48000),
                    capture=dict(samples_delivered=192000, wall_seconds=4., max_delivery_lateness_seconds=.01),
                    replay_speed=1., reference_available_to_asr=False, capture_block_samples=4800,
                    total_wall_seconds=5.)
    events = [dict(type='caption', elapsed_seconds=1., data=dict(id=1, revision=1, source='wrong', start=0.,end=3., final=False)),
              dict(type='caption', elapsed_seconds=4., data=dict(id=1, revision=2, source='hello there yes', start=0.,end=3., final=True)),
              dict(type='session_finished', elapsed_seconds=5., complete=True)]
    return manifest, events


@pytest.mark.parametrize('defect', ['incomplete', 'end', 'source', 'length', 'samples', 'speed', 'leak', 'pacing', 'draft', 'clock', 'runtime'])
def test_protocol_rejects_invalid_runs(defect):
    manifest, events = run_fixture()
    if defect == 'incomplete': manifest['complete'] = False
    elif defect == 'end': events.pop()
    elif defect == 'source': manifest['audio']['source_sha256'] = 'different'
    elif defect == 'length': manifest['audio']['samples'] -= 50
    elif defect == 'samples': manifest['capture']['samples_delivered'] -= 1
    elif defect == 'speed': manifest['replay_speed'] = 2.
    elif defect == 'leak': manifest['reference_available_to_asr'] = True
    elif defect == 'pacing': manifest['capture']['max_delivery_lateness_seconds'] = .3
    elif defect == 'draft': events[1]['data']['final'] = False
    elif defect == 'clock': events[1]['elapsed_seconds'] = float('nan')
    elif defect == 'runtime': events.insert(-1,dict(type='error',elapsed_seconds=4.5,text='failed'))
    with pytest.raises(ValueError, match='No score issued'):
        validate_run(reference(), manifest, events)


def write_run(tmp_path, empty=False):
    manifest, events = run_fixture()
    if empty: events = events[-1:]
    (tmp_path/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
    write_json(tmp_path/'settings.json', {})
    manifest.update(events_sha256=file_hash(tmp_path/'events.jsonl'), settings_sha256=file_hash(tmp_path/'settings.json'))
    write_json(tmp_path/'manifest.json', manifest)


def test_complete_score_exports_both_orderings_and_keeps_final_revision(tmp_path):
    write_run(tmp_path)
    result = evaluate(reference(), tmp_path, tmp_path/'score')
    assert result['primary_ordered_wer']['ratio'] == 0
    assert result['word_time_order_sensitivity']['ratio'] > 0
    assert result['final_caption_count'] == 1
    assert 'wrong' not in (tmp_path/'score/final-hypothesis.txt').read_text(encoding='utf-8')
    assert (tmp_path/'score/report.md').is_file()


def test_empty_output_is_full_deletion_and_csv_counts_match(tmp_path):
    write_run(tmp_path, empty=True)
    result = evaluate(reference(), tmp_path, tmp_path/'score')
    assert result['primary_ordered_wer']['ratio'] == 1
    with (tmp_path/'score/word-errors.csv').open(encoding='utf-8-sig') as f:
        assert len(list(csv.DictReader(f))) == 3


def test_tampered_event_file_cannot_generate_score(tmp_path):
    write_run(tmp_path)
    with (tmp_path/'events.jsonl').open('a', encoding='utf-8') as f:
        f.write('\n')
    with pytest.raises(ValueError, match='integrity'):
        evaluate(reference(), tmp_path, tmp_path/'score')
    assert not (tmp_path/'score').exists()


def test_default_settings_and_windowed_path_rejection(tmp_path):
    settings = frozen_settings()
    assert settings['qwen_model'] == 'Qwen/Qwen3-ASR-1.7B'
    assert settings['qwen_mode'] == 'fast' and not settings['translate']
    settings['qwen_mode'] = 'accurate'
    write_json(tmp_path/'settings.json', settings)
    with pytest.raises(ValueError, match='requires'):
        frozen_settings(tmp_path/'settings.json')


def test_orchestrator_failure_does_not_start_scoring(tmp_path, monkeypatch):
    import argparse
    import subprocess
    import scripts.benchmark_ami as script
    ref = reference()
    ref['source']['audio_path'] = 'fixture.wav'
    monkeypatch.setattr(script, 'import_reference', lambda _: ref)
    monkeypatch.setattr(script, 'interpreter', lambda _: sys.executable)
    monkeypatch.setattr(script, 'runtime_versions', lambda _: {})
    called = []
    def fail(argv, log):
        called.append(argv)
        raise subprocess.CalledProcessError(1, argv)
    monkeypatch.setattr(script, 'command', fail)
    args = argparse.Namespace(score_only=None, corpus=tmp_path, settings=None, output=tmp_path/'experiment', check_only=False)
    with pytest.raises(subprocess.CalledProcessError):
        benchmark(args)
    assert len(called) == 1
    state = json.loads((args.output/'experiment.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'failed_or_interrupted'
    assert not (args.output/'score').exists()


def test_score_existing_checks_frozen_inputs_then_writes_report(tmp_path):
    from scripts.benchmark_ami import ROOT, score_existing
    folder = tmp_path/'experiment'
    (folder/'run').mkdir(parents=True)
    write_run(folder/'run')
    manifest = json.loads((folder/'run/manifest.json').read_text(encoding='utf-8'))
    write_json(folder/'reference.json', reference())
    write_json(folder/'settings.json', {})
    write_json(folder/'input.f32.json', manifest['audio'])
    write_json(folder/'experiment.json', dict(protocol=PROTOCOL,
        frozen_sha256={n:file_hash(folder/n) for n in ['reference.json','settings.json','input.f32.json']},
        source_sha256={n:file_hash(ROOT/n) for n in ['linguaflow/ami_evaluation.py','linguaflow/evaluation.py']}))
    output = score_existing(folder)
    assert (output/'report.md').is_file()
    write_json(folder/'reference.json', {})
    with pytest.raises(ValueError, match='Frozen experiment input changed'):
        score_existing(folder)
