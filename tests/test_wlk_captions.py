from linguaflow.wlk_captions import CaptionMapper


def line(text, start=0, end=1):
    return {"text": text, "start": f"0:00:{start:05.2f}", "end": f"0:00:{end:05.2f}"}


def test_punctuation_does_not_freeze_growing_upstream_line():
    mapper = CaptionMapper("en")
    first = mapper.update({"lines": [], "buffer_transcription": "Hell"})[0]
    second = mapper.update({"lines": [], "buffer_transcription": "Hello world"})[0]
    third = mapper.update({"lines": [line("Hello world.")], "buffer_transcription": "Next"})
    assert first.id == second.id == third[0].id
    assert not third[0].final and third[0].source == "Hello world. Next"
    fourth = mapper.update({"lines": [line("Hello world. Next sentence.", end=4)]}, done=True)
    assert fourth[0].final and fourth[0].source == "Hello world. Next sentence."


def test_stable_partial_is_joined_to_tail_and_flushed_on_stop():
    mapper = CaptionMapper("en")
    snapshot = {"lines": [line("Hello")], "buffer_transcription": "world"}
    event = mapper.update(snapshot)[0]
    assert event.source == "Hello world" and event.stable_source == "Hello"
    event = mapper.update({"lines": [line("Hello world")], "buffer_transcription": ""}, done=True)[0]
    assert event.final and event.source == "Hello world"


def test_silence_finalizes_previous_line_without_exporting_silence():
    mapper = CaptionMapper("zh")
    events = mapper.update({"lines": [line("你好"), line("", 1, 2)]})
    assert len(events) == 1 and events[0].final


def test_same_final_is_not_retranslated_and_tail_retracts():
    mapper = CaptionMapper("en")
    snapshot = {"lines": [line("Hello."), line("", 1, 2)], "buffer_transcription": "noise"}
    mapper.update(snapshot)
    assert mapper.update(snapshot) == []
    snapshot["buffer_transcription"] = ""
    event = mapper.update(snapshot)[0]
    assert event.id == 3 and not event.source


def test_committed_sentences_do_not_lock_subsequent_words_in_same_turn():
    from types import SimpleNamespace as Item

    from linguaflow.wlk_captions import caption_snapshot
    tokens = [Item(start=0, end=1, text="Hello to everybody."), Item(start=1, end=2, text=" Welcome"),
              Item(start=2, end=3, text=" back to the meeting.")]
    segment = Item(text="Hello to everybody.", speaker=-1, tokens=tokens[:1], detected_language="en")
    front = Item(lines=[segment], to_dict=lambda: {"buffer_transcription": ""})
    mapper = CaptionMapper("en")
    first = mapper.update(caption_snapshot(front))
    assert first[0].final and first[0].source == "Hello to everybody."
    segment.tokens = tokens
    second = mapper.update(caption_snapshot(front))
    assert len(second) == 1 and second[0].id == 2
    assert second[0].source == "Welcome back to the meeting." and second[0].final
    assert (second[0].start, second[0].end) == (1, 3)


def test_committed_run_without_punctuation_is_bounded_without_losing_tokens():
    from types import SimpleNamespace as Item

    from linguaflow.wlk_captions import caption_snapshot
    tokens = [Item(start=i, end=i+1, text=f" word{i}") for i in range(21)]
    segment = Item(text="words", speaker=-1, tokens=tokens, detected_language="en")
    front = Item(lines=[segment], to_dict=lambda: {"buffer_transcription": ""})
    result = caption_snapshot(front)["lines"]
    assert len(result) == 3
    assert [row["closed"] for row in result] == [True, True, False]
    assert "".join(row["text"] for row in result) == "".join(t.text for t in tokens)


def test_late_punctuation_is_not_translated_as_an_utterance():
    from types import SimpleNamespace as Item

    from linguaflow.wlk_captions import caption_snapshot
    segment = Item(text=".", speaker=-1, tokens=[Item(start=4, end=5, text=".")], detected_language="en")
    front = Item(lines=[segment], to_dict=lambda: {"buffer_transcription": ""})
    assert caption_snapshot(front)["lines"] == []
