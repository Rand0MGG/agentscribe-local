"""Bounded full-encoder Qwen inference behind WhisperLiveKit's online contract.

Only completed utterances enter WLK's scheduling token store. The shared
revision store owns source text; capacity rollovers keep an overlapping tail.
"""
import logging
import re
import time
from collections import OrderedDict, deque
from functools import wraps
from threading import RLock
from types import SimpleNamespace

import numpy as np

from . import diagnostic_log as diag
from .asr_stability import confirmed_until, stitch_window
from .asr_submission import LocalAgreementSubmission
from .audio_processing.buffer import PCMBuffer
from .qwen_audio import KeptAudioClock, VADTimeline, fallback_cut, reference_cut

logger = logging.getLogger(__name__)


def _text_transaction(method):
    @wraps(method)
    def serialized(self, *args, **kwargs):
        with self._submission_lock:
            return method(self, *args, **kwargs)
    return serialized

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
        self._input_end = None
        self._clock = KeptAudioClock(self.SAMPLING_RATE)
        self._zero_window = False
        self._zero_input = False
        self._waiting_for_speech = False
        self._vad_silent_window = False
        self._skipped_window = False
        self._suspended = []
        self.revisions = None
        self.interval = 0
        self.capture_time = 0.
        self.force_endpoint = False
        self.force_endpoint_time = None
        self._submission_lock = RLock()
        self.submission = LocalAgreementSubmission()
        self._submission_window_start = None
        self.confirmed_ranges = []
        self.utterance_start = None
        self.window_text = ''
        self.window_text_start = 0
        self.overlap = None
        self.decoded_end = 0.
        self.processed_end = 0.  # Includes rejected zero windows, without a text observation.
        self.confirmed_end = 0
        self.decode_sequence = 0
        self._submission_decode_id = 0
        self.window_decoded_start = 0.

    def set_revision_store(self, store):
        """Use the same full-hypothesis store as the streaming Qwen backend."""
        self.revisions = store
        store.audio_clock = self._clock
        store.refresh = self.expire_history

    @property
    def audio_buffer(self):
        return self._audio.samples

    def _observe(self, text, stable, end, closed=False, decode_id=None):
        if self.revisions is not None:
            with diag.trace_scope(decode_id=self.decode_sequence if decode_id is None else decode_id):
                self.revisions.update(self.interval, self.utterance_start, end, text, stable, closed,
                                      stable_ranges=self.confirmed_ranges)

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
            # Mirror that state so resumed pure quiet can still skip inference.
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
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError('PCM 音频必须为一维单声道采样。')
        if len(audio):
            source = round(audio_stream_end_time * self.SAMPLING_RATE) - len(audio)
            if self._input_end is not None and source != self._input_end:
                raise ValueError('Qwen 原声音频时间不连续，已停止而不是补零或跳过音频')
            self._input_end = source + len(audio)
            zero = not np.any(audio)
            if zero != self._zero_input:
                diag.event('asr_zero_input_start' if zero else 'asr_zero_input_end',
                           audio_seconds=source / self.SAMPLING_RATE)
            if zero:
                # Keep an ordered boundary, not zero PCM. Advancing the source
                # clock preserves the gap without joining words across it.
                start = self._clock.append(source + len(audio), 0)
                if not self._zero_input:
                    self._queued_audio.append((start, None))
            else:
                start = self._clock.append(source, len(audio))
                self._queued_audio.append((start, audio.copy()))
            self._zero_input = zero
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

    @_text_transaction
    def _reset_acoustics(self):
        self._audio.discard(len(self.audio_buffer))
        self._reset_text()

    def _reset_text(self):
        self.text = self.window_text = ''
        self.decoded_samples = self.window_text_start = self.confirmed_end = 0
        self.submission = LocalAgreementSubmission()
        self._submission_window_start = None
        self.confirmed_ranges = []
        self.overlap = self.utterance_start = None

    @_text_transaction
    def _suspend_text(self):
        if self.text:
            self.submission.mark_history(len(self.submission.words))
            self._suspended.append((self.interval, self.utterance_start, self.decoded_end,
                                    self.text, self._submission_decode_id, self.submission))
            self.interval += 1
        self._reset_text()

    @_text_transaction
    def _resume_text(self, source_start, source_end):
        # Keep the previous text/clock while new words start after the gap.
        self._suspend_text()
        at = self.vad.speech_after_quiet(source_start, source_end)
        if at is None:
            at = max(source_start, self._clock.source_time(self.processed_end, end=True))
        self.utterance_start = self._clock.model_time(at)
        diag.event('asr_text_resume', interval=self.interval, audio_seconds=at)

    def _fresh_samples(self, end=None):
        end = self.start + len(self.audio_buffer) / self.SAMPLING_RATE if end is None else end
        return max(0, round((end - max(self.start, self.processed_end)) * self.SAMPLING_RATE))

    def _consume_audio(self, final=False):
        rate = self.SAMPLING_RATE
        minimum = round(self.update_seconds * rate)
        maximum = round(self.MAX_NEW_SECONDS * rate)
        while self._queued_audio:
            start, audio = self._queued_audio[0]
            if audio is None:
                # Flush only real, previously unprocessed tail audio. A zero
                # gap is not a hypothesis and does not force text confirmation.
                self._update_window(final=True, reason='before_zero_gap')
                self._suspend_text()
                self._audio.discard(len(self.audio_buffer))
                self.start = self.processed_end = start
                self._waiting_for_speech = self._skipped_window = True
                self._queued_audio.popleft()
                continue
            fresh = self._fresh_samples()
            available, boundary = fresh, False
            for _, pending in self._queued_audio:
                if pending is None:
                    boundary = True
                    break
                available += len(pending)
            if not (final or boundary or self._waiting_for_speech) and available < minimum:
                break
            budget = maximum if self._waiting_for_speech else maximum - fresh
            if budget <= 0:
                self._update_window()
                continue
            self._queued_audio.popleft()
            if len(audio) > budget:
                self._queued_audio.appendleft((start + budget / rate, audio[budget:]))
                audio = audio[:budget]
            self._append(audio, start)
            if self._waiting_for_speech:
                # Reuse the PCM buffer as a bounded recent-audio cache. VAD
                # still sees every packet. No periodic window preparation or
                # model call occurs while its complete contents remain quiet.
                limit = round((self.window_seconds + 5) * rate)
                drop = max(0, len(self.audio_buffer) - limit)
                self._audio.discard(drop)
                self.start += drop / rate
                if self._vad_quiet(len(self.audio_buffer)):
                    self.processed_end = self.start + len(self.audio_buffer) / rate
                    self.vad.prune(self._clock.source_time(self.start))
                    continue
                self._waiting_for_speech = False
            self.vad.prune(self._clock.source_time(self.start))
            self._update_window(final=final or boundary)

    def _vad_quiet(self, count):
        end = self.start + count / self.SAMPLING_RATE
        return self.vad.is_silent(self._clock.source_time(self.start),
                                 self._clock.source_time(end, end=True),
                                 observed_until=self.capture_time)

    def _decode(self, count, reason='update'):
        if not 0 < count <= round((self.window_seconds + 5) * self.SAMPLING_RATE):
            raise ValueError('Qwen 推理窗口超出上限')
        # Inspect exactly the bounded PCM that would enter the model. Never
        # remove individual quiet samples from a mixed speech/noise window.
        audio = self.audio_buffer[:count].copy()
        zero = not np.any(audio)
        if zero != self._zero_window:
            diag.event('asr_zero_window_start' if zero else 'asr_zero_window_end',
                       interval=self.interval, decode_id=self.decode_sequence,
                       window_start=self._clock.source_time(self.start),
                       window_end=self._clock.source_time(self.start + count / self.SAMPLING_RATE, end=True))
            self._zero_window = zero
        if zero:
            self._skipped_window = True
            return None
        end = self.start + count / self.SAMPLING_RATE
        source_start = self._clock.source_time(self.start)
        source_end = self._clock.source_time(end, end=True)
        quiet = self.vad.is_silent(source_start, source_end, observed_until=self.capture_time)
        if quiet != self._vad_silent_window:
            diag.event('asr_vad_window_start' if quiet else 'asr_vad_window_end',
                       interval=self.interval, decode_id=self.decode_sequence,
                       window_start=source_start, window_end=source_end,
                       vad_audio_end=self.capture_time)
            self._vad_silent_window = quiet
        if quiet:
            self._waiting_for_speech = True
            self._skipped_window = True
            return None
        if self._skipped_window:
            self._resume_text(source_start, source_end)
            self._skipped_window = False
        # A copied, bounded input cannot be changed by the capture thread.
        self.decode_sequence += 1
        fresh = max(0., end - max(self.start, self.processed_end))
        fields = dict(decode_id=self.decode_sequence, interval=self.interval, reason=reason,
                      window_start=source_start, window_end=source_end, audio_seconds=count / self.SAMPLING_RATE,
                      new_audio_seconds=fresh, admitted_audio_seconds=self._fresh_samples(end) / self.SAMPLING_RATE,
                      buffered_seconds=len(self.audio_buffer) / self.SAMPLING_RATE,
                      received_audio_end=self.end, vad_audio_end=self.capture_time)
        diag.event('asr_decode_start', **fields)
        began = time.perf_counter()
        try:
            text = self.decode(audio).strip()
        except Exception as exc:
            diag.event('asr_decode_failed', **fields, compute_seconds=time.perf_counter() - began)
            diag.exception('asr_exception', exc)
            raise
        compute_seconds = time.perf_counter() - began
        diag.event('asr_decode_end', **fields, compute_seconds=compute_seconds, chars=len(text))
        logger.info('Qwen decode: audio=%.2fs compute=%.2fs chars=%d',
                    count / self.SAMPLING_RATE, compute_seconds, len(text))
        return text

    def _recognize(self, count, reason='update'):
        local = self._decode(count, reason)
        if local is not None:
            self._accept_hypothesis(local, count)
        # A skipped zero/quiet window is consumed, but cannot erase/vote on text or
        # extend the last real hypothesis's timestamps. It is safe to release.
        self.processed_end = self.start + count / self.SAMPLING_RATE

    @_text_transaction
    def _accept_hypothesis(self, local, count):
        self._submission_decode_id = self.decode_sequence
        self.window_text = local
        self.window_decoded_start = self.start
        anchored = True
        previous_window_text_start = self.window_text_start
        if self.overlap:
            prior, expected, floor = self.overlap
            text, self.window_text_start, anchored = stitch_window(prior, local, expected, floor)
        else:
            text, self.window_text_start = local, 0
        if not anchored:
            # An estimated acoustic cut is not permission to overwrite submitted
            # words. Start a new provisional text tail when overlap is unknown;
            # subsequent decodes of this same window keep that textual origin.
            self.window_text_start = (previous_window_text_start
                                      if self.start == self._submission_window_start else len(self.text))
        self.decoded_samples = count
        self.decoded_end = self.start + count / self.SAMPLING_RATE
        previous_stable = self.confirmed_end
        text, self.confirmed_ranges, self.window_text_start = self.submission.update(
            local, start=self.window_text_start, audio_end=self.decoded_end,
            aligned=anchored or self.start == self._submission_window_start)
        self._submission_window_start = self.start
        self.text = text
        # Rollover matching must use the text we actually kept, including locks;
        # raw conflicting model output cannot re-enter through the overlap path.
        self.window_text = text[self.window_text_start:]
        stable = confirmed_until(text, self.confirmed_ranges)
        self.confirmed_end = stable
        self._history_event(self.interval, self.decode_sequence, self.submission.diagnostic['history_timeout_units'])
        diag.event('asr_revision', decode_id=self.decode_sequence, interval=self.interval,
                   chars=len(text), stable_chars=stable, overlap_matched=anchored,
                   previous_stable_chars=previous_stable, window_text_start=self.window_text_start,
                   confirmed_chars=sum(b-a for a, b in self.confirmed_ranges),
                   confirmed_range_count=len(self.confirmed_ranges),
                   submission=self.submission.diagnostic, submission_rounds=2,
                   audio_start=self._clock.source_time(self.utterance_start),
                   audio_end=self._clock.source_time(self.decoded_end, end=True))
        self.drafts[text] = (self.utterance_start, self.decoded_end, stable)
        self._observe(text, stable, self.decoded_end)
        self.drafts.move_to_end(text)
        while len(self.drafts) > 8:
            self.drafts.popitem(last=False)

    def _history_event(self, interval, decode_id, count):
        if count:
            diag.event('asr_history_finalized', interval=interval, decode_id=decode_id,
                       reason='history_unchanged_timeout', unchanged_seconds=LocalAgreementSubmission.HISTORY_SECONDS,
                       finalized_units=count)

    def expire_history(self):
        """Refresh text deadlines without decoding, touching PCM or blocking UI."""
        if not self._submission_lock.acquire(blocking=False):
            return
        try:
            for interval, start, end, text, decode_id, submission in self._suspended:
                count = submission.expire_history()
                if count:
                    _, ranges = submission.snapshot()
                    if self.revisions is not None:
                        with diag.trace_scope(decode_id=decode_id):
                            self.revisions.update(interval, start, end, text, confirmed_until(text, ranges),
                                                  stable_ranges=ranges)
                    self._history_event(interval, decode_id, count)
            count = self.submission.expire_history()
            if count and self.utterance_start is not None:
                _, self.confirmed_ranges = self.submission.snapshot()
                self.confirmed_end = confirmed_until(self.text, self.confirmed_ranges)
                self.drafts[self.text] = (self.utterance_start, self.decoded_end, self.confirmed_end)
                self._observe(self.text, self.confirmed_end, self.decoded_end,
                              decode_id=self._submission_decode_id)
                self._history_event(self.interval, self._submission_decode_id, count)
        finally:
            self._submission_lock.release()

    def _release(self, drop, reason):
        """Release recognized or skipped PCM; preserve the text overlap."""
        count = max(1, round((self.decoded_end - self.window_decoded_start) * self.SAMPLING_RATE))
        offset = round((self.start - self.window_decoded_start) * self.SAMPLING_RATE) + drop
        from .asr_stability import units
        matches = units(self.window_text)
        index = min(len(matches) - 1, int(len(matches) * offset / count)) if matches else 0
        local_start = matches[index].start() if matches else 0
        self.overlap = (self.text, self.window_text_start + local_start, self.window_text_start)
        diag.event('asr_window_roll', reason=reason, interval=self.interval,
                   decode_id=self.decode_sequence, stable_chars=self.confirmed_end,
                   chars=len(self.text), window_text_start=self.window_text_start,
                   old_start=self._clock.source_time(self.start),
                   new_start=self._clock.source_time(self.start + drop / self.SAMPLING_RATE),
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
            # Rank VAD gaps on the original recording clock.
            source_start = self._clock.source_time(self.start)
            source_end = self._clock.source_time(end, end=True)
            point = reference_cut(self.vad.snapshot(source_start, source_end), source_start, source_end)
            point = self._clock.model_time(point) if point is not None else None
            if point is not None and point <= self.start + 1 / rate:
                point = None
            reason = 'vad_reference'
            if point is None:
                if not forced and len(self.audio_buffer) <= cap:
                    break
                drop = fallback_cut(self.audio_buffer, self.window_seconds - 1)
                reason = 'no_reference_low_energy'
            else:
                drop = round((point - self.start) * rate)
            cut_end = self.start + drop / rate
            if cut_end > self.processed_end + 1e-6:
                # Never delete unseen speech, even when a queue delivered far
                # more than the model limit. Decode the oldest bounded input.
                bounded = min(cap, len(self.audio_buffer))
                safe_drop = fallback_cut(self.audio_buffer[:bounded], self.window_seconds - 1)
                bounded_fresh = self._fresh_samples(self.start + bounded / rate)
                if (bounded_fresh < round(self.update_seconds * rate)
                        and self.start + safe_drop / rate <= self.processed_end + 1e-6):
                    # Make room using already recognized context, instead of
                    # decoding an unchanged (or sub-minimum) capped window.
                    drop = safe_drop
                    reason = 'backlog_overlap'
                else:
                    self._recognize(bounded, 'backlog_before_release')
                    if cut_end > self.processed_end:
                        drop = safe_drop
                        reason = 'backlog_overlap'
            self._release(drop, reason)
            if not forced:
                if len(self.audio_buffer) <= cap:
                    break
                forced = True
            # Once forced, stay in this loop until strictly below target.

    def _update_window(self, final=False, reason='update'):
        if self._waiting_for_speech:
            return
        if self.start + len(self.audio_buffer) / self.SAMPLING_RATE <= self.processed_end + 1e-6:
            return
        if not final and self._fresh_samples() < round(self.update_seconds * self.SAMPLING_RATE):
            return
        self._prepare_window()
        fresh = self._fresh_samples()
        if len(self.audio_buffer) and fresh > 0 and (final or fresh >= round(self.update_seconds * self.SAMPLING_RATE)):
            self._recognize(len(self.audio_buffer), reason)

    def _tokens(self, text, start, end):
        matches = list(re.finditer(r'\S+', text))
        output = []
        for index, match in enumerate(matches):
            lo = 0 if index == 0 else matches[index-1].end()
            value = text[lo:match.end()]
            if index == 0 and self.any_emitted and value and not value[0].isspace():
                value = ' ' + value
            output.append(self.token_type(start=self._clock.source_time(start + (end-start)*index/len(matches)),
                end=self._clock.source_time(start + (end-start)*(index+1)/len(matches), end=True), text=value,
                detected_language=self.language))
            self.any_emitted = True
        return output

    @_text_transaction
    def _commit(self, count, reason='finish'):
        text = self.text
        end = self.decoded_end
        tokens = self._tokens(text, self.utterance_start, end)
        # Explicit pause/EOF accepts the remaining latest draft, including
        # history whose PCM has left the window. Existing locks remain intact.
        self.confirmed_ranges = [(0, len(text))] if text else []
        self.confirmed_end = len(text)
        self._observe(text, self.confirmed_end, end, closed=True)
        diag.event('asr_commit', interval=self.interval, reason=reason,
                   audio_start=self._clock.source_time(self.utterance_start),
                   audio_end=self._clock.source_time(end, end=True), chars=len(text), decode_id=self.decode_sequence)
        self.interval += 1
        self.finalized_until = self._clock.source_time(end, end=True)
        self._audio.discard(count)
        self.start = end
        self.text = ''
        self.decoded_samples = 0
        self.submission = LocalAgreementSubmission()
        self._submission_window_start = None
        self.confirmed_ranges = []
        self.overlap = None
        self.window_text = ''
        self.window_text_start = 0
        self.utterance_start = None
        self.confirmed_end = 0
        return tokens

    def process_iter(self):
        self._consume_audio()
        self._update_window()
        return [], self.end

    def get_buffer(self):
        # Called from WLK's event loop too: never run inference here. Explicit
        # pause has its own ordered queue marker and counted worker-thread call.
        if self._forced_endpoint_ready() and not self._queued_audio and not len(self.audio_buffer):
            self.force_endpoint = False
            self.force_endpoint_time = None
        return self.transcript_type(start=self._clock.source_time(self.start), end=self.end, text=self.text)

    def start_silence(self):
        if self._forced_endpoint_ready():
            return self.finish('explicit_pause')
        # Kept for WLK's online contract. Natural VAD labels never call this.
        return self.process_iter()

    @_text_transaction
    def _drain(self, reason='finish'):
        self._consume_audio(final=True)
        self._update_window(final=True)
        tokens = []
        for interval, start, end, text, decode_id, submission in self._suspended:
            if self.revisions is not None:
                with diag.trace_scope(decode_id=decode_id):
                    self.revisions.update(interval, start, end, text, len(text),
                                          closed=True, stable_ranges=[(0, len(text))])
            tokens.extend(self._tokens(text, start, end))
            self.finalized_until = max(self.finalized_until, self._clock.source_time(end, end=True))
            diag.event('asr_commit', interval=interval, reason=reason, decode_id=decode_id,
                       audio_start=self._clock.source_time(start),
                       audio_end=self._clock.source_time(end, end=True), chars=len(text))
        self._suspended.clear()
        # Close the last direct hypothesis without replaying unchanged PCM.
        # Historical and current drafts are finalized at explicit EOF as well.
        if self.utterance_start is not None and self.text:
            count = max(0, round((self.decoded_end - self.start) * self.SAMPLING_RATE))
            tokens.extend(self._commit(count, reason))
        self._reset_acoustics()
        self._skipped_window = self._waiting_for_speech = False
        self._zero_input = False
        self.start = self._clock.count / self.SAMPLING_RATE
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
        """The revision bridge owns text locks; WLK tokens still track acoustic closure."""
        snapshot['closed_audio_time'] = self.finalized_until
        text = snapshot.get('buffer_transcription', '')
        draft = self.drafts.get(text)
        if not draft or not text:
            return snapshot
        start, end, offset = draft
        # Keep timestamps for speculative text too, instead of a zero-time tail.
        snapshot['draft_span'] = {'start': self._clock.source_time(start),
                                  'end': self._clock.source_time(end, end=True)}
        if offset:
            stable_end = start + (end-start) * offset / len(text)
            snapshot['lines'].append({'text': text[:offset], 'start': self._clock.source_time(start),
                'end': self._clock.source_time(stable_end, end=True), 'detected_language': self.language})
            snapshot['buffer_transcription'] = text[offset:].strip()
            snapshot['draft_span']['start'] = self._clock.source_time(stable_end)
        return snapshot


def build_official_online(model_path, device, language, update_seconds, window_seconds, context=''):
    from .asr_review import MAX_TOKENS
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
        max_new_tokens=MAX_TOKENS)
    model.model.generation_config.do_sample = False
    from .qwen_generation import install_generation_review
    install_generation_review(model)
    def decode(audio):
        return model.transcribe((audio, 16000), language=canonical, context=context)[0].text
    return QwenAccurateOnline(decode, language, update_seconds, window_seconds)
