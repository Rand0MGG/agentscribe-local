from types import SimpleNamespace as Item

from linguaflow.wlk_captions import CaptionMapper, caption_snapshot


def line(text, start=0, end=1):
    return {"text": text, "start": start, "end": end}


def text(mapper):
    return " ".join(c.source for c in mapper.previous.values())


def test_punctuation_creates_provisional_row_not_final():
    mapper = CaptionMapper("en")
    first = mapper.update({"lines": [], "buffer_transcription": "Hell"})[0]
    second = mapper.update({"lines": [line("Hello world.")], "buffer_transcription": "Next"})
    assert first.id == second[0].id
    assert second[0].ready and not second[0].final
    assert second[0].source == "Hello world."
    assert second[1].source == "Next" and not second[1].ready


def test_stable_partial_and_speculative_tail_are_distinguished():
    mapper = CaptionMapper("en")
    event = mapper.update({"lines": [line("Hello")], "buffer_transcription": "world"})[0]
    assert event.source == "Hello world" and event.stable_source == "Hello"
    events = mapper.update({"lines": [line("Hello world")], "buffer_transcription": ""}, done=True)
    assert events[0].final and events[0].source == "Hello world"
    assert mapper.update({"lines": [line("Hello world")]}, done=True) == []


def test_silence_and_elapsed_time_alone_do_not_finalize():
    clock = [0.]
    mapper = CaptionMapper("zh", clock=lambda: clock[0])
    snapshot = {"lines": [line("这个公式的前提是"), line("", 1, 60)]}
    events = mapper.update(snapshot)
    clock[0] = 60
    assert mapper.update(snapshot) == []
    assert not events[0].final and not events[0].ready


def test_later_context_and_repeated_stability_finalize_prefix_only():
    clock = [0.]
    mapper = CaptionMapper("zh", clock=lambda: clock[0])
    snapshot = {"lines": [line("这是第一个知识点。", 0, 2), line("接下来我们详细解释它的应用条件。", 2, 8)]}
    first = mapper.update(snapshot)
    assert not any(c.final for c in first)
    assert mapper.update(snapshot) == []
    clock[0] = 1
    final = mapper.update(snapshot)
    assert len(final) == 1 and final[0].final and final[0].id == first[0].id
    assert not mapper.previous[first[1].id].final


def test_unfinished_clause_can_be_abandoned_without_inventing_words():
    mapper = CaptionMapper("zh")
    original = "这个公式的前提是……我们先看右边这个图。"
    events = mapper.update({"lines": [line(original, end=6)]})
    assert events[0].source == "这个公式的前提是……"
    assert events[0].ready and not events[0].final
    assert ''.join(c.source for c in events) == original


def test_correction_merges_boundary_and_revises_same_id():
    mapper = CaptionMapper("en")
    first = mapper.update({"lines": [line("The value is five. Next detail.", end=5)]})
    changed = mapper.update({"lines": [line("The value is five. Actually it is six. Next detail.", end=7)]})
    assert changed[0].id == first[0].id and changed[0].revision > first[0].revision
    assert changed[0].source == "The value is five. Actually it is six."
    assert 'Next detail.' in text(mapper)


def test_retracted_tail_gets_tombstone_and_id_is_not_reused():
    mapper = CaptionMapper("en")
    events = mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "noise"})
    tail_id = events[-1].id
    assert mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "noise"}) == []
    events = mapper.update({"lines": [line("Welcome here.")]})
    assert any(c.id == tail_id and not c.source for c in events)
    events = mapper.update({"lines": [line("Welcome here.")], "buffer_transcription": "new text"})
    assert events[-1].id > tail_id


def test_display_limit_does_not_immediately_finalize_or_drop_words():
    tokens = [Item(start=i, end=i+1, text=f" word{i}") for i in range(21)]
    segment = Item(text="words", speaker=-1, tokens=tokens, detected_language="en")
    front = Item(lines=[segment], to_dict=lambda: {"buffer_transcription": ""})
    mapper = CaptionMapper("en", max_seconds=8)
    events = mapper.update(caption_snapshot(front))
    assert len(events) >= 3 and not any(c.final for c in events)
    assert ' '.join(c.source for c in events).split() == [f"word{i}" for i in range(21)]
    assert events[0].boundary_reason.startswith("显示换段")


def test_fragment_tokens_are_not_rewritten_by_joining():
    tokens = [Item(start=i, end=i+1, text=t) for i, t in enumerate(["学", "习", "知识"])]
    front = Item(lines=[Item(text="学习知识", speaker=-1, tokens=tokens, detected_language="zh")], to_dict=lambda: {})
    mapper = CaptionMapper("zh")
    assert mapper.update(caption_snapshot(front))[0].source == "学习知识"
    assert CaptionMapper().update({"lines": [line(".")]}) == []


def test_real_upstream_correction_can_reopen_committed_caption():
    mapper = CaptionMapper("en")
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
    mapper = CaptionMapper("en", clock=lambda: clock[0])
    lines = []
    for index in range(40):
        lines.append(line(f"This is classroom statement number {index}.", index * 4, (index + 1) * 4))
        snapshot = {"lines": list(lines)}
        mapper.update(snapshot)
        clock[0] += 1
        mapper.update(snapshot)
        ordered = sorted(mapper.previous.values(), key=lambda caption: caption.start)
        assert ' '.join(c.source for c in ordered) == ' '.join(row['text'] for row in lines)
    assert len(mapper.fixed) >= 35
    mapper.update(snapshot, done=True)
    assert all(c.final for c in mapper.previous.values())


def test_classroom_complements_stay_with_their_governing_phrase():
    for original in ["We will calculate. The average of x.",
                     "So this is a very. Useful property.",
                     "They will. The result is. A Gaussian distribution."]:
        mapper = CaptionMapper("en")
        events = mapper.update({"lines": [line(original, end=5)]})
        assert len(events) == 1 and events[0].source == original


def test_following_complement_rejoins_provisional_rows():
    mapper = CaptionMapper("en")
    mapper.update({"lines": [line("It is useful in generative modeling.", end=3)]})
    original = "It is useful in generative modeling. Area. Because this is helpful."
    events = mapper.update({"lines": [line(original, end=6)]})
    assert events[0].source.startswith("It is useful in generative modeling. Area.")
    assert not events[0].final
