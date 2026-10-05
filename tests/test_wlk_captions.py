from types import SimpleNamespace as Item

import pytest

from linguaflow.wlk_captions import BoundaryPolicy, CaptionMapper, caption_snapshot


def line(text, start=0, end=1):
    return {"text": text, "start": start, "end": end}


def text(mapper):
    return " ".join(c.source for c in mapper.previous.values())


def test_model_boundary_creates_provisional_row_not_final():
    mapper = CaptionMapper("en", predictor=lambda text: [12] if len(text) > 12 else [])
    first = mapper.update({"lines": [], "buffer_transcription": "Hell"})[0]
    second = mapper.update({"lines": [line("Hello world.")], "buffer_transcription": "Next"})
    assert first.id == second[0].id
    assert second[0].ready and not second[0].final
    assert second[0].source == "Hello world."
    assert second[1].source == "Next" and not second[1].ready


def test_stable_partial_and_speculative_tail_are_distinguished():
    mapper = CaptionMapper("en", predictor=lambda text: [])
    event = mapper.update({"lines": [line("Hello")], "buffer_transcription": "world"})[0]
    assert event.source == "Hello world" and event.stable_source == "Hello"
    events = mapper.update({"lines": [line("Hello world")], "buffer_transcription": ""}, done=True)
    assert events[0].final and events[0].source == "Hello world"
    assert mapper.update({"lines": [line("Hello world")]}, done=True) == []


def test_elapsed_time_submits_stable_tail_but_does_not_finalize():
    clock = [0.]
    mapper = CaptionMapper("zh", predictor=lambda text: [], clock=lambda: clock[0])
    snapshot = {"lines": [line("这个公式的前提是"), line("", 1, 60)]}
    events = mapper.update(snapshot)
    clock[0] = 60
    submitted = mapper.update(snapshot)
    assert submitted[0].ready and not submitted[0].final
    assert not events[0].final and not events[0].ready


def test_boundary_needs_fresh_context_and_confirmed_asr_characters():
    clock = [0.]
    mapper = CaptionMapper("zh", predictor=lambda text: [9] if len(text) > 9 else [], clock=lambda: clock[0])
    value = "这是第一个知识点。接下来我们详细解释它的应用条件。"
    snapshot = {'revision_text': value, 'stable_end': 0, 'revision_spans': [], 'closed_ends': []}
    first = mapper.update(snapshot)
    assert not any(c.final for c in first)
    assert mapper.update(snapshot) == []
    clock[0] = 1
    assert mapper.update(snapshot) == []
    snapshot['revision_text'] += '然后举例'
    mapper.update(snapshot)
    assert not any(c.boundary_final for c in mapper.previous.values())
    snapshot['stable_end'] = len(snapshot['revision_text'])
    final = mapper.update(snapshot)
    finalized = [c for c in final if c.final]
    assert len(finalized) == 1 and finalized[0].id == first[0].id
    assert not mapper.previous[first[1].id].final


def test_unfinished_clause_can_be_abandoned_without_inventing_words():
    mapper = CaptionMapper("zh", predictor=lambda text: [])
    original = "这个公式的前提是……我们先看右边这个图。"
    events = mapper.update({"lines": [line(original, end=6)]})
    assert len(events) == 1 and not events[0].final
    assert ''.join(c.source for c in events) == original


def test_correction_merges_boundary_and_revises_same_id():
    mapper = CaptionMapper("en", predictor=lambda text: [18, 38] if "Actually" in text else [18])
    first = mapper.update({"lines": [line("The value is five. Next detail.", end=5)]})
    changed = mapper.update({"lines": [line("The value is five. Actually it is six. Next detail.", end=7)]})
    assert changed[0].id == first[0].id and changed[0].revision > first[0].revision
    assert changed[0].source == "The value is five."
    assert any(c.source == "Actually it is six." for c in changed)
    assert 'Next detail.' in text(mapper)


def test_retracted_tail_gets_tombstone_and_id_is_not_reused():
    mapper = CaptionMapper("en", predictor=lambda text: [13])
    events = mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "noise"})
    tail_id = events[-1].id
    assert mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "noise"}) == []
    events = mapper.update({"lines": [line("Welcome here.")]})
    assert any(c.id == tail_id and not c.source for c in events)
    events = mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "new text"})
    assert events[-1].id > tail_id


def test_pending_model_boundary_preserves_long_text_and_timestamps():
    tokens = [Item(start=i, end=i+1, text=f" word{i}") for i in range(80)]
    segment = Item(text="words", speaker=-1, tokens=tokens, detected_language="en")
    front = Item(lines=[segment], to_dict=lambda: {"buffer_transcription": ""})
    mapper = CaptionMapper("en", predictor=lambda text: [])
    events = mapper.update(caption_snapshot(front))
    assert len(events) == 1 and not events[0].ready and not events[0].final
    assert events[0].source.split() == [f"word{i}" for i in range(80)]
    assert events[0].end == 80


def test_fragment_tokens_are_not_rewritten_by_joining():
    tokens = [Item(start=i, end=i+1, text=t) for i, t in enumerate(["学", "习", "知识"])]
    front = Item(lines=[Item(text="学习知识", speaker=-1, tokens=tokens, detected_language="zh")], to_dict=lambda: {})
    mapper = CaptionMapper("zh", predictor=lambda text: [])
    assert mapper.update(caption_snapshot(front))[0].source == "学习知识"
    assert CaptionMapper(predictor=lambda text: []).update({"lines": [line(".")]})[0].source == "."


def test_real_upstream_correction_can_reopen_committed_caption():
    mapper = CaptionMapper("en", predictor=lambda text: [])
    first = mapper.update({"lines": [line("Incorrect word.")]}, done=True)[0]
    changed = mapper.update({"lines": [line("Correct word.")]})[0]
    assert first.final and not changed.final
    assert changed.id == first.id and changed.revision > first.revision


def test_learned_boundaries_are_used_without_punctuation():
    mapper = CaptionMapper("zh", predictor=lambda s: [8])
    events = mapper.update({"lines": [line("这是第一段的内容我们现在看第二段", end=7)]})
    assert len(events) == 2 and events[0].source == "这是第一段的内容"
    assert events[0].ready and events[0].boundary_reason == "上下文分句"


def test_growing_stream_preserves_all_text_across_many_commits():
    clock = [0.]
    sentences = [f"This is classroom statement number {i}." for i in range(40)]
    def predict(text):
        return [text.index(sentence) + len(sentence) for sentence in sentences if sentence in text]
    mapper = CaptionMapper("en", predictor=predict, clock=lambda: clock[0])
    lines = []
    for index in range(40):
        lines.append(line(f"This is classroom statement number {index}.", index * 4, (index + 1) * 4))
        snapshot = {"lines": list(lines), 'closed_audio_time': (index+1)*4}
        mapper.update(snapshot)
        clock[0] += 1
        mapper.update(snapshot)
        ordered = sorted(mapper.previous.values(), key=lambda caption: caption.start)
        assert ' '.join(c.source for c in ordered) == ' '.join(row['text'] for row in lines)
    assert len(mapper.fixed) >= 35
    mapper.update(snapshot, done=True)
    assert all(c.final for c in mapper.previous.values())


def test_long_session_diffs_with_ten_stable_context_rows(monkeypatch):
    import linguaflow.wlk_captions as module
    mapper = CaptionMapper('en', predictor=lambda text: [
        i + 1 for i, char in enumerate(text) if char == '.'])
    history = ' '.join(f'Classroom statement {i}.' for i in range(200))
    mapper.update({'lines': [line(history)]}, done=True)
    original_ids = list(mapper.previous)
    context = ' ' + ' '.join(f'Classroom statement {i}.' for i in range(190, 200))
    matcher = module.SequenceMatcher
    compared = []
    def compare(junk, old, new, **kwargs):
        compared.append((old, new))
        assert old.startswith(context) and new.startswith(context)
        assert len(old) < 300 and len(new) < 300
        return matcher(junk, old, new, **kwargs)
    monkeypatch.setattr(module, 'SequenceMatcher', compare)
    mapper.update({'lines': [line(history + ' A new sentence.')]})
    assert compared == [(context, context + ' A new sentence.')]
    assert list(mapper.previous)[:len(original_ids)] == original_ids
    assert all(mapper.previous[cid].final for cid in original_ids)
    assert ' '.join(c.source for c in mapper.previous.values()) == history + ' A new sentence.'
    tail_id = next(cid for cid in mapper.previous if cid not in original_ids)
    mapper.update({'lines': [line(history + ' A corrected sentence.')]}, done=True)
    assert compared[-1] == (context + ' A new sentence.', context + ' A corrected sentence.')
    assert mapper.previous[tail_id].source == 'A corrected sentence.'
    assert mapper.previous[tail_id].final
    assert ' '.join(c.source for c in mapper.previous.values()) == history + ' A corrected sentence.'


@pytest.mark.parametrize('count', [3, 10, 20])
def test_diff_context_includes_up_to_ten_stable_rows(monkeypatch, count):
    import linguaflow.wlk_captions as module
    mapper = CaptionMapper('en', predictor=lambda text: [
        i + 1 for i, char in enumerate(text) if char == '.'])
    sentences = [f'Sentence {i}.' for i in range(count)]
    history = ' '.join(sentences)
    mapper.update({'lines': [line(history)]}, done=True)
    compared = []
    matcher = module.SequenceMatcher
    def compare(junk, old, new, **kwargs):
        compared.append((old, new))
        return matcher(junk, old, new, **kwargs)
    monkeypatch.setattr(module, 'SequenceMatcher', compare)
    mapper.update({'lines': [line(history + ' Next sentence.')]})
    context = (' ' if count > 10 else '') + ' '.join(sentences[-10:])
    assert compared == [(context, context + ' Next sentence.')]


@pytest.mark.parametrize('changed_index, context_start', [(4, 0), (14, 4)])
def test_correction_before_sliding_window_expands_to_affected_history(monkeypatch, changed_index, context_start):
    import linguaflow.wlk_captions as module
    mapper = CaptionMapper('en', predictor=lambda text: [
        i + 1 for i, char in enumerate(text) if char == '.'])
    sentences = [f'Classroom statement {i}.' for i in range(30)]
    history = ' '.join(sentences)
    mapper.update({'lines': [line(history)]}, done=True)
    original_ids = list(mapper.previous)
    versions = {cid: c.revision for cid, c in mapper.previous.items()}
    compared = []
    matcher = module.SequenceMatcher
    def compare(junk, old, new, **kwargs):
        compared.append((old, new))
        return matcher(junk, old, new, **kwargs)
    monkeypatch.setattr(module, 'SequenceMatcher', compare)
    # These corrections precede the normal window covering sentences 21–30.
    sentences[changed_index] = f'Corrected classroom statement {changed_index}.'
    corrected = ' '.join(sentences)
    mapper.update({'lines': [line(corrected)]})
    context = (' ' if context_start else '') + ' '.join(
        f'Classroom statement {i}.' for i in range(context_start, 30))
    changed_context = (' ' if context_start else '') + ' '.join(sentences[context_start:])
    assert compared == [(context, changed_context)]
    assert list(mapper.previous) == original_ids
    assert text(mapper) == corrected
    assert all(mapper.previous[cid].final and mapper.previous[cid].revision == versions[cid]
               for cid in original_ids[:changed_index])
    affected = mapper.previous[original_ids[changed_index]]
    assert affected.source == sentences[changed_index] and affected.revision > versions[affected.id]
    assert not affected.final
    mapper.update({'lines': [line(corrected)]}, done=True)
    assert text(mapper) == corrected and all(c.final for c in mapper.previous.values())


def test_model_offsets_determine_short_and_unpunctuated_segments():
    mapper = CaptionMapper("zh", predictor=lambda text: [2, 4])
    events = mapper.update({"lines": [line("好。开始我们继续", end=5)]})
    assert [c.source for c in events] == ["好。", "开始", "我们继续"]
    assert [c.ready for c in events] == [True, True, False]


def test_model_can_rejoin_provisional_rows():
    mapper = CaptionMapper("en", predictor=lambda text: [6] if text == "Hello world" else [])
    first = mapper.update({"buffer_transcription": "Hello world"})
    changed = mapper.update({"buffer_transcription": "Hello world again"})
    assert changed[0].id == first[0].id and changed[0].source == "Hello world again"
    assert not changed[0].ready and not changed[0].final
    assert any(c.id == first[1].id and not c.source for c in changed)


def test_model_pending_tail_waits_for_context_or_session_end():
    mapper = CaptionMapper("en", predictor=lambda text: [])
    snapshot = {"lines": [line("Hello world. Is this complete? Yes!", end=30)]}
    pending = mapper.update(snapshot)
    assert len(pending) == 1 and not pending[0].ready
    final = mapper.update(snapshot, done=True)
    assert len(final) == 1 and final[0].ready and final[0].final
    assert final[0].source == pending[0].source


def test_predictor_is_required_and_errors_leave_captions_intact():
    with pytest.raises(TypeError):
        CaptionMapper(predictor=None)
    def predict(text):
        if text.endswith("again"):
            raise RuntimeError("SaT inference failed")
        return []
    mapper = CaptionMapper(predictor=predict)
    first = mapper.update({"lines": [line("Hello world")]})[0]
    with pytest.raises(RuntimeError, match="SaT inference failed"):
        mapper.update({"lines": [line("Hello world again")]})
    assert mapper.previous == {first.id: first}


def test_overlapping_model_windows_and_cache_preserve_offsets():
    calls = []
    def predict(text):
        calls.append(text)
        return [i + 1 for i, char in enumerate(text) if char == "界"]
    original = "文" * 1023 + "界" + "文" * 1023 + "界" + "文" * 20
    policy = BoundaryPolicy(predict)
    boundaries = policy.split(original)
    assert boundaries == [(1024, "上下文分句"), (2048, "上下文分句"), (2068, "等待后文")]
    assert len(calls) == 3
    boundaries.clear()
    assert len(policy.split(original)) == 3 and len(calls) == 3


@pytest.mark.parametrize('mark', [',', '，', ';', '；', ':', '：', '、'])
def test_clause_separator_does_not_create_sentence_boundary(mark):
    policy = BoundaryPolicy(lambda text: [len('First' + mark + ' ')])
    assert policy.split('First' + mark + ' second') == [(len('First' + mark + ' second'), '等待后文')]


@pytest.mark.parametrize("offset", [0, -1, 100, 1.5])
def test_invalid_model_offsets_raise(offset):
    with pytest.raises(ValueError, match="SaT"):
        BoundaryPolicy(lambda text: [offset]).split("hello")
