from types import SimpleNamespace

from linguaflow.runtime_compat import finalize_whisper_once


def test_eof_publishes_tokens_committed_while_consumer_handles_previous_snapshot():
    import asyncio

    from linguaflow.runtime_compat import results_with_final_snapshot
    async def scenario():
        state = ['first sentence']
        async def formatter():
            snapshot = state[0]
            yield snapshot
            # Models may have completed while the consumer was awaiting SaT.
            if processor.is_stopping:
                return
        processor = SimpleNamespace(is_stopping=True, results_formatter=formatter)
        seen = []
        async for snapshot in results_with_final_snapshot(processor, formatter()):
            seen.append(snapshot)
            state[0] = 'first sentence and the final words'
            await asyncio.sleep(0)
        assert seen == ['first sentence', 'first sentence and the final words']
    asyncio.run(scenario())


def test_user_pause_flushes_tail_and_preserves_vad_sample_clock():
    import asyncio

    from linguaflow.runtime_compat import pause_audio_processor
    calls = []
    async def flush():
        calls.append('flush')
        processor.total_pcm_samples += 123
    async def begin(at_sample):
        calls.append(('silence', at_sample))
    vad = SimpleNamespace(current_sample=0, reset_states=lambda: calls.append('reset'))
    processor = SimpleNamespace(_flush_remaining_pcm=flush, _begin_silence=begin,
                                total_pcm_samples=16000, vac=vad)
    asyncio.run(pause_audio_processor(processor))
    assert calls == ['flush', ('silence', 16123), 'reset']
    assert vad.current_sample == 16123


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
