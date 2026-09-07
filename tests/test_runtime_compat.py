from types import SimpleNamespace

from linguaflow.runtime_compat import finalize_whisper_once


def test_silence_then_eof_does_not_decode_ended_utterance_twice():
    calls = []
    def decode():
        calls.append(True)
        return ["actual speech" if len(calls) == 1 else "spurious tail"], 1
    processor = SimpleNamespace(insert_audio_chunk=lambda *args: None,
                                start_silence=decode, end=1)
    finalize_whisper_once(processor)
    processor.insert_audio_chunk([1], 1)
    assert processor.start_silence()[0] == ["actual speech"]
    processor.end = 3  # padding silence extends the clock, not the utterance
    assert processor.finish() == ([], 3)
    assert len(calls) == 1


def test_new_speech_after_silence_still_flushes_on_stop():
    calls = []
    def decode():
        calls.append(True)
        return [f"utterance {len(calls)}"], 1
    processor = SimpleNamespace(insert_audio_chunk=lambda *args: None,
                                start_silence=decode, end=1)
    finalize_whisper_once(processor)
    processor.insert_audio_chunk([1], 1)
    assert processor.start_silence()[0] == ["utterance 1"]
    processor.insert_audio_chunk([2], 2)
    assert processor.finish()[0] == ["utterance 2"]


def test_pause_origin_uses_audio_clock_instead_of_last_word():
    origins = []
    processor = SimpleNamespace(insert_audio_chunk=lambda *args: None,
                                start_silence=lambda: ([], 10.25), end=10.25,
                                end_silence=lambda duration, offset: origins.append(duration + offset))
    finalize_whisper_once(processor)
    processor.end_silence(.5, 9.9)
    assert origins == [10.75]
