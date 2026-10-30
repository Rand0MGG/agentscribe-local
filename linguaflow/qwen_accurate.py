"""Bounded full-encoder Qwen inference behind WhisperLiveKit's online contract.

Only completed utterances enter WLK's scheduling token store. The shared
revision store owns source text; capacity rollovers keep an overlapping tail.
"""
import logging
import re
import time
from collections import OrderedDict, deque
from types import SimpleNamespace

from . import diagnostic_log as diag
from .asr_stability import StablePrefix, stitch_window
from .audio_processing.buffer import PCMBuffer
from .qwen_audio import VADTimeline, fallback_cut, reference_cut

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = dict(en='English', zh='Chinese', ja='Japanese', ko='Korean',
                      fr='French', de='German', es='Spanish', ru='Russian',
                      ar='Arabic', pt='Portuguese', it='Italian')


class QwenAccurateOnline:
    SAMPLING_RATE = 16000
    MAX_NEW_SECONDS = 10.

    def __init__(self, decode, language, update_seconds=.5,
                 window_seconds=30., token_type=None, transcript_type=None):
        if token_type is None:
            from whisperlivekit.timed_objects import ASRToken, Transcript
            token_type, transcript_type = ASRToken, Transcript
        self.token_type, self.transcript_type = token_type, transcript_type
        self.decode = decode
        self.language = language
        self.asr = SimpleNamespace(sep=' ')
        self.update_seconds = max(1., min(self.MAX_NEW_SECONDS, float(update_seconds)))
        self.window_seconds = max(8., min(40., float(window_seconds)))
        self._audio = PCMBuffer(round((self.window_seconds + 5) * self.SAMPLING_RATE))
        self.start = self.end = 0.
        self.text = ''
        self.decoded_samples = 0
        self.drafts = OrderedDict()
        self.any_emitted = False
        self.finalized_until = -1.
        self.vad = VADTimeline()
        self._queued_audio = deque()
        self._idle_start = None
        self._idle_tail = PCMBuffer(self.SAMPLING_RATE)
        self._suspended = []
        self.revisions = None
        self.interval = 0
        self.capture_time = 0.
        self.force_endpoint = False
        self.force_endpoint_time = None
        self.agreement = StablePrefix()
        self.utterance_start = None
        self.window_text = ''
        self.window_text_start = 0
        self.overlap = None
        self.decoded_end = 0.
        self.confirmed_end = 0
        self.frozen_limit = None
        self.decode_sequence = 0
        self.progress_end = 0.
        self._input_floor = 0.
        self.window_decoded_start = 0.

    def set_revision_store(self, store):
        """Use the same full-hypothesis store as the streaming Qwen backend."""
        self.revisions = store

    @property
    def audio_buffer(self):
        return self._audio.samples

    def _observe(self, text, stable, end, closed=False):
        if self.revisions is not None:
            with diag.trace_scope(decode_id=self.decode_sequence):
                self.revisions.update(self.interval, self.utterance_start, end, text, stable, closed)

    def observe_capture_event(self, kind, timestamp, observed_at=None):
        """Capture annotations do not close source text or mutate decoder PCM."""
        self.vad.event(kind, timestamp, observed_at)
        if kind == 'audio_advanced':
            self.capture_time = timestamp
        else:
            diag.event('vad_boundary', kind=kind, audio_seconds=timestamp, observed_at=observed_at)

    def force_next_endpoint(self, at_time=None):
        """An explicit recording pause must drain the current utterance."""
        self.force_endpoint = True
        self.force_endpoint_time = at_time
        if at_time is not None:
            # The capture-side pause resets Silero to its initial quiet state.
            # Mirror that state so resumed pure quiet can still enter idle.
            self.vad.event('silence_started', at_time)
            diag.event('vad_reset', audio_seconds=at_time)

    def _forced_endpoint_ready(self):
        return self.force_endpoint and (self.force_endpoint_time is None
                                       or self.end >= self.force_endpoint_time - .001)

    def insert_audio_chunk(self, audio, audio_stream_end_time):
        if (self.force_endpoint_time is not None
                and audio_stream_end_time > self.force_endpoint_time + .001):
            self.force_endpoint = False
            self.force_endpoint_time = None
        if len(audio):
            self._queued_audio.append((audio_stream_end_time - len(audio) / self.SAMPLING_RATE, audio.copy()))
        self.end = audio_stream_end_time

    def _append(self, audio, start):
        if not len(audio):
            return
        if not len(self.audio_buffer):
            self.start = start
            self.utterance_start = start
        elif abs(self.start + len(self.audio_buffer) / self.SAMPLING_RATE - start) > 1 / self.SAMPLING_RATE:
            raise ValueError('Qwen 原声音频时间不连续，已停止而不是补零或跳过音频')
        self._audio.append(audio)

    def _reset_acoustics(self):
        self._audio.discard(len(self.audio_buffer))
        self.text = self.window_text = ''
        self.decoded_samples = self.window_text_start = self.confirmed_end = 0
        self.agreement = StablePrefix()
        self.overlap = self.frozen_limit = self.utterance_start = None

    def _resume(self, at):
        # Preserve the old draft as an OPEN source row; SaT still owns sentence
        # boundaries. New word times start at real resumed audio, never the gap.
        if self.utterance_start is not None and self.text:
            self._suspended.append((self.interval, self.utterance_start, self.decoded_end,
                                    self.text, self.decode_sequence))
            self.interval += 1
        self._reset_acoustics()
        # The original pre-speech protection is context, not newly admitted speech.
        self._input_floor = at
        tail = self._idle_tail.samples.copy()
        self._append(tail, at - len(tail) / self.SAMPLING_RATE)
        self._idle_tail.discard(len(self._idle_tail.samples))
        diag.event('asr_idle_end', interval=self.interval, audio_seconds=at,
                   skipped_start=self._idle_start + self.window_seconds, retained_seconds=len(tail) / self.SAMPLING_RATE)
        self._idle_start = None

    def _fresh_samples(self, end=None):
        end = self.start + len(self.audio_buffer) / self.SAMPLING_RATE if end is None else end
        return max(0, round((end - max(self.start, self.decoded_end, self._input_floor)) * self.SAMPLING_RATE))

    def _consume_audio(self, final=False):
        rate = self.SAMPLING_RATE
        minimum = round(self.update_seconds * rate)
        maximum = round(self.MAX_NEW_SECONDS * rate)
        while self._queued_audio:
            fresh = self._fresh_samples() if self._idle_start is None else 0
            # Keep a short tail queued until there is enough useful new audio.
            # Idle still consumes capture/VAD data, without requiring a decode.
            if (not final and self._idle_start is None
                    and fresh + sum(len(a) for _, a in self._queued_audio) < minimum):
                break
            budget = maximum - fresh
            if budget <= 0:
                # Also retries buffered input after a surfaced decoder failure;
                # do not append another batch before it has been recognized.
                self._update_window()
                continue
            start, audio = self._queued_audio.popleft()
            if len(audio) > budget:
                self._queued_audio.appendleft((start + budget / rate, audio[budget:]))
                audio = audio[:budget]
            end = start + len(audio) / self.SAMPLING_RATE
            # Keep the original silence start for the long-idle threshold.
            silences = self.vad.snapshot(0., end)
            cursor = 0
            if self._idle_start is not None:
                if any(a == self._idle_start and b <= start for a, b in silences):
                    self._resume(start)
            for quiet_start, quiet_end in silences:
                stop = quiet_start + self.window_seconds
                if quiet_end < stop or quiet_end <= start:
                    continue
                lo = max(cursor, min(len(audio), round((stop - start) * self.SAMPLING_RATE)))
                hi = max(lo, min(len(audio), round((quiet_end - start) * self.SAMPLING_RATE)))
                if self._idle_start is None:
                    self._append(audio[cursor:lo], start + cursor / self.SAMPLING_RATE)
                    try:
                        self._update_window()
                    except Exception:
                        # The prefix is already buffered. Keep the unconsumed
                        # tail queued if this bounded decode fails.
                        self._queued_audio.appendleft((start + lo / self.SAMPLING_RATE, audio[lo:]))
                        raise
                    self._idle_start = quiet_start
                    # Protect the first resumed packet even if it contains less
                    # than one second of pre-speech silence.
                    self._idle_tail.append(self.audio_buffer[-self.SAMPLING_RATE:])
                    diag.event('asr_idle_start', interval=self.interval, audio_seconds=stop,
                               silence_start=quiet_start)
                self._idle_tail.append(audio[lo:hi])
                self._idle_tail.discard(max(0, len(self._idle_tail.samples) - self.SAMPLING_RATE))
                cursor = hi
                if quiet_end < end:
                    self._resume(quiet_end)
                else:
                    break
            self._append(audio[cursor:], start + cursor / self.SAMPLING_RATE)
            self.vad.prune(min(self.start, self._idle_start if self._idle_start is not None else self.start))
            if self._idle_start is None:
                self._update_window()

    def _decode(self, count, reason='update'):
        if not 0 < count <= round((self.window_seconds + 5) * self.SAMPLING_RATE):
            raise ValueError('Qwen 推理窗口超出上限')
        # A copied, bounded input cannot be changed by the capture thread.
        self.decode_sequence += 1
        end = self.start + count / self.SAMPLING_RATE
        fresh = max(0., end - max(self.start, self.progress_end))
        fields = dict(decode_id=self.decode_sequence, interval=self.interval, reason=reason,
                      window_start=self.start, window_end=end, audio_seconds=count / self.SAMPLING_RATE,
                      new_audio_seconds=fresh, admitted_audio_seconds=self._fresh_samples(end) / self.SAMPLING_RATE,
                      buffered_seconds=len(self.audio_buffer) / self.SAMPLING_RATE,
                      received_audio_end=self.end, vad_audio_end=self.capture_time)
        diag.event('asr_decode_start', **fields)
        began = time.perf_counter()
        try:
            text = self.decode(self.audio_buffer[:count].copy()).strip()
        except Exception as exc:
            diag.event('asr_decode_failed', **fields, compute_seconds=time.perf_counter() - began)
            diag.exception('asr_exception', exc)
            raise
        compute_seconds = time.perf_counter() - began
        diag.event('asr_decode_end', **fields, compute_seconds=compute_seconds, chars=len(text))
        self.progress_end = max(self.progress_end, end)
        logger.info('Qwen decode: audio=%.2fs compute=%.2fs chars=%d',
                    count / self.SAMPLING_RATE, compute_seconds, len(text))
        return text

    def _recognize(self, count, reason='update'):
        local = self._decode(count, reason)
        self.window_text = local
        self.window_decoded_start = self.start
        anchored = True
        if self.overlap:
            prior, expected, floor = self.overlap
            text, self.window_text_start, anchored = stitch_window(prior, local, expected, floor)
        else:
            text, self.window_text_start = local, 0
        self.text = text
        self.decoded_samples = count
        self.decoded_end = self.start + count / self.SAMPLING_RATE
        stable = self.agreement.observe(text, self.decoded_end)
        candidate_stable = stable
        limits = []
        if self.frozen_limit is not None and self.window_text_start > self.frozen_limit:
            # A backlog may provide only one decode before old PCM rolls out.
            # Copying those words into later hypotheses is not new recognition
            # evidence. Retain them as a draft until explicit utterance closure.
            stable = min(stable, self.frozen_limit)
            limits.append('frozen_prefix')
        if not anchored:
            stable = min(stable, self.window_text_start)
            limits.append('overlap_unmatched')
        previous_stable = self.confirmed_end
        self.confirmed_end = stable
        diag.event('asr_revision', decode_id=self.decode_sequence, interval=self.interval,
                   chars=len(text), stable_chars=stable, overlap_matched=anchored,
                   candidate_stable_chars=candidate_stable, previous_stable_chars=previous_stable,
                   frozen_limit=self.frozen_limit, window_text_start=self.window_text_start,
                   confirmation_limits=limits, confirmation_limited=stable < candidate_stable,
                   agreement=self.agreement.diagnostic,
                   agreement_observations=len(self.agreement.history),
                   agreement_audio_span=(self.agreement.history[-1][0] - self.agreement.history[0][0]
                                         if self.agreement.history else 0.),
                   agreement_rounds=self.agreement.rounds, agreement_horizon=self.agreement.horizon,
                   agreement_holdback=self.agreement.holdback,
                   audio_start=self.utterance_start, audio_end=self.decoded_end)
        self.drafts[text] = (self.utterance_start, self.decoded_end, stable)
        self._observe(text, stable, self.decoded_end)
        self.drafts.move_to_end(text)
        while len(self.drafts) > 8:
            self.drafts.popitem(last=False)

    def _release(self, drop, reason):
        """Release only previously decoded PCM; preserve the revision overlap."""
        count = max(1, round((self.decoded_end - self.window_decoded_start) * self.SAMPLING_RATE))
        offset = round((self.start - self.window_decoded_start) * self.SAMPLING_RATE) + drop
        from .asr_stability import units
        matches = units(self.window_text)
        index = min(len(matches) - 1, int(len(matches) * offset / count)) if matches else 0
        local_start = matches[index].start() if matches else 0
        self.overlap = (self.text, self.window_text_start + local_start, self.window_text_start)
        self.frozen_limit = self.confirmed_end
        diag.event('asr_window_roll', reason=reason, interval=self.interval,
                   decode_id=self.decode_sequence, frozen_limit=self.frozen_limit,
                   chars=len(self.text), window_text_start=self.window_text_start,
                   old_start=self.start, new_start=self.start + drop / self.SAMPLING_RATE,
                   dropped_seconds=drop / self.SAMPLING_RATE,
                   retained_seconds=(len(self.audio_buffer) - drop) / self.SAMPLING_RATE)
        self._audio.discard(drop)
        self.start = round(self.start * self.SAMPLING_RATE + drop) / self.SAMPLING_RATE
        # The overlap changes the next full-window hypothesis, but not which
        # absolute samples the model has already seen.
        self.decoded_samples = max(0, self.decoded_samples - drop)

    def _prepare_window(self):
        rate = self.SAMPLING_RATE
        target, cap = round(self.window_seconds * rate), round((self.window_seconds + 5) * rate)
        forced = False
        while len(self.audio_buffer) >= target:
            end = self.start + len(self.audio_buffer) / rate
            point = reference_cut(self.vad.snapshot(self.start, end), self.start, end)
            reason = 'vad_reference'
            if point is None:
                if not forced and len(self.audio_buffer) <= cap:
                    break
                drop = fallback_cut(self.audio_buffer, self.window_seconds - 1)
                reason = 'no_reference_low_energy'
            else:
                drop = round((point - self.start) * rate)
            cut_end = self.start + drop / rate
            if cut_end > self.decoded_end + 1e-6:
                # Never delete unseen speech, even when a queue delivered far
                # more than the model limit. Decode the oldest bounded input.
                bounded = min(cap, len(self.audio_buffer))
                safe_drop = fallback_cut(self.audio_buffer[:bounded], self.window_seconds - 1)
                bounded_fresh = self._fresh_samples(self.start + bounded / rate)
                if (bounded_fresh < round(self.update_seconds * rate)
                        and self.start + safe_drop / rate <= self.decoded_end + 1e-6):
                    # Make room using already recognized context, instead of
                    # decoding an unchanged (or sub-minimum) capped window.
                    drop = safe_drop
                    reason = 'backlog_overlap'
                else:
                    self._recognize(bounded, 'backlog_before_release')
                    if cut_end > self.decoded_end:
                        drop = safe_drop
                        reason = 'backlog_overlap'
            self._release(drop, reason)
            if not forced:
                if len(self.audio_buffer) <= cap:
                    break
                forced = True
            # Once forced, stay in this loop until strictly below target.

    def _update_window(self, final=False):
        if self.start + len(self.audio_buffer) / self.SAMPLING_RATE <= self.decoded_end + 1e-6:
            return
        if not final and self._fresh_samples() < round(self.update_seconds * self.SAMPLING_RATE):
            return
        self._prepare_window()
        fresh = self._fresh_samples()
        if len(self.audio_buffer) and fresh > 0 and (final or fresh >= round(self.update_seconds * self.SAMPLING_RATE)):
            self._recognize(len(self.audio_buffer))

    def _tokens(self, text, start, end):
        matches = list(re.finditer(r'\S+', text))
        output = []
        for index, match in enumerate(matches):
            lo = 0 if index == 0 else matches[index-1].end()
            value = text[lo:match.end()]
            if index == 0 and self.any_emitted and value and not value[0].isspace():
                value = ' ' + value
            output.append(self.token_type(start=start + (end-start)*index/len(matches),
                end=start + (end-start)*(index+1)/len(matches), text=value,
                detected_language=self.language))
            self.any_emitted = True
        return output

    def _commit(self, count, reason='finish'):
        text = self.text
        end = self.decoded_end
        tokens = self._tokens(text, self.utterance_start, end)
        self._observe(text, len(text), end, closed=True)
        diag.event('asr_commit', interval=self.interval, reason=reason, audio_start=self.utterance_start,
                   audio_end=end, chars=len(text), decode_id=self.decode_sequence)
        self.interval += 1
        self.finalized_until = end
        self._audio.discard(count)
        self.start = end
        self.text = ''
        self.decoded_samples = 0
        self.agreement = StablePrefix()
        self.overlap = None
        self.window_text = ''
        self.window_text_start = 0
        self.utterance_start = None
        self.confirmed_end = 0
        self.frozen_limit = None
        return tokens

    def process_iter(self):
        self._consume_audio()
        if self._idle_start is None:
            self._update_window()
        return [], self.end

    def get_buffer(self):
        # Called from WLK's event loop too: never run inference here. Explicit
        # pause has its own ordered queue marker and counted worker-thread call.
        if self._forced_endpoint_ready() and not self._queued_audio and not len(self.audio_buffer):
            self.force_endpoint = False
            self.force_endpoint_time = None
        return self.transcript_type(start=self.start, end=self.end, text=self.text)

    def start_silence(self):
        if self._forced_endpoint_ready():
            return self.finish('explicit_pause')
        # Kept for WLK's online contract. Natural VAD labels never call this.
        return self.process_iter()

    def _drain(self, reason='finish'):
        self._consume_audio(final=True)
        self._update_window(final=True)
        tokens = []
        for interval, start, end, text, decode_id in self._suspended:
            if self.revisions is not None:
                with diag.trace_scope(decode_id=decode_id):
                    self.revisions.update(interval, start, end, text, len(text), closed=True)
            tokens.extend(self._tokens(text, start, end))
            self.finalized_until = max(self.finalized_until, end)
            diag.event('asr_commit', interval=interval, reason=reason, decode_id=decode_id,
                       audio_start=start, audio_end=end, chars=len(text))
        self._suspended.clear()
        # An idle window is frozen. EOF confirms its last hypothesis without
        # appending the skipped long silence or decoding the same PCM again.
        if self.utterance_start is not None and self.text:
            count = max(0, round((self.decoded_end - self.start) * self.SAMPLING_RATE))
            tokens.extend(self._commit(count, reason))
        self._reset_acoustics()
        self._idle_start = None
        self._idle_tail.discard(len(self._idle_tail.samples))
        self.start = self.end
        return tokens

    def finish(self, reason='finish'):
        tokens = self._drain(reason)
        self.drafts.clear()
        self.force_endpoint = False
        self.force_endpoint_time = None
        return tokens, self.end

    def end_silence(self, duration, offset):
        if duration:
            raise ValueError('Qwen 需要连续原声 PCM，不能用静音标记替代音频')

    def new_speaker(self, change_speaker=None):
        return self.finish()

    def augment_snapshot(self, snapshot):
        """Soft agreement is revisable; do not insert it into WLK's token log."""
        snapshot['closed_audio_time'] = self.finalized_until
        text = snapshot.get('buffer_transcription', '')
        draft = self.drafts.get(text)
        if not draft or not text:
            return snapshot
        start, end, offset = draft
        # Keep timestamps for speculative text too, instead of a zero-time tail.
        snapshot['draft_span'] = {'start': start, 'end': end}
        if offset:
            stable_end = start + (end-start) * offset / len(text)
            snapshot['lines'].append({'text': text[:offset], 'start': start,
                'end': stable_end, 'detected_language': self.language})
            snapshot['buffer_transcription'] = text[offset:].strip()
            snapshot['draft_span']['start'] = stable_end
        return snapshot


def build_official_online(model_path, device, language, update_seconds, window_seconds, context=''):
    from .model_cache import reject_alignment_model
    reject_alignment_model(model_path)
    from .knowledge.schemas import MAX_CONTEXT_BYTES
    if not isinstance(context, str) or len(context.encode('utf-8')) > MAX_CONTEXT_BYTES:
        raise ValueError('课程术语上下文无效或超长，请重新审核术语。')
    import torch
    from qwen_asr import Qwen3ASRModel
    canonical = LANGUAGE_NAMES.get(language)
    if canonical is None:
        raise ValueError('准确优先模式需要选择支持的原文语言')
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_bf16_supported() else (
        torch.float16 if device in ('cuda', 'mps') else torch.float32)
    model = Qwen3ASRModel.from_pretrained(model_path, dtype=dtype, device_map=device,
        attn_implementation='sdpa', local_files_only=True, max_inference_batch_size=1,
        max_new_tokens=512)
    model.model.generation_config.do_sample = False
    def decode(audio):
        return model.transcribe((audio, 16000), language=canonical, context=context)[0].text
    return QwenAccurateOnline(decode, language, update_seconds, window_seconds)
