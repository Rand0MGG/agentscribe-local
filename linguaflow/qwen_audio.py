"""Original PCM routing and advisory VAD labels for full-window Qwen."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from threading import RLock

import numpy as np

from . import diagnostic_log as diag


@dataclass(frozen=True)
class ZeroAudioGap:
    start: float
    end: float


class NonzeroPCM:
    """Drop whole 10 ms zero frames, never individual waveform zero crossings.

    A partial frame waits for the next packet (or explicit flush), so queue
    coalescing and packet boundaries cannot change which samples are retained.
    """
    def __init__(self, rate):
        self.rate, self.frame = rate, rate // 100
        self.pending = np.empty(0, np.float32)
        self.pending_start = 0
        self.input_end = None

    def feed(self, audio, start):
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1:
            raise ValueError('PCM 音频必须为一维单声道采样。')
        start = round(start * self.rate)
        if self.input_end is not None and start != self.input_end:
            raise ValueError('Qwen 原声音频时间不连续，已停止而不是补零或跳过音频')
        self.input_end = start + len(audio)
        if len(self.pending):
            audio = np.concatenate((self.pending, audio))
            start = self.pending_start
        count = len(audio) // self.frame * self.frame
        self.pending = audio[count:].copy()
        self.pending_start = start + count
        if not count:
            return []
        active = np.any(audio[:count].reshape(-1, self.frame), axis=1)
        cuts = np.r_[0, np.flatnonzero(active[1:] != active[:-1]) + 1, len(active)] * self.frame
        return [(start + int(a), audio[a:b].copy() if active[a // self.frame]
                 else ZeroAudioGap((start + a) / self.rate, (start + b) / self.rate))
                for a, b in zip(cuts, cuts[1:])]

    def flush(self):
        if not len(self.pending):
            return []
        start, audio = self.pending_start, self.pending
        self.pending = np.empty(0, np.float32)
        return [(start, audio if np.any(audio) else ZeroAudioGap(start / self.rate,
                                                              (start + len(audio)) / self.rate))]


class KeptAudioClock:
    """Compact model-sample coordinates mapped to the untouched recording."""
    def __init__(self, rate):
        self.rate = rate
        self.starts, self.ends, self.sources = [], [], []
        self.count = self.source_end = 0
        self.lock = RLock()

    def append(self, source, count):
        # EOF can flush a partial frame on the decoder thread while the event
        # loop reads revision times. Publish the three indexes together.
        with self.lock:
            start = self.count
            if count:
                if self.ends and self.sources[-1] + self.ends[-1] - self.starts[-1] == source:
                    self.ends[-1] += count
                else:
                    self.starts.append(start)
                    self.ends.append(start + count)
                    self.sources.append(source)
                self.count += count
            self.source_end = source + count
            return start / self.rate

    def source_time(self, seconds, *, end=False):
        if seconds is None:
            return None
        with self.lock:
            if not self.starts:
                return self.source_end / self.rate
            sample = seconds * self.rate
            index = (min(bisect_left(self.ends, sample), len(self.ends)-1) if end else
                     max(0, bisect_right(self.starts, sample)-1))
            offset = min(max(0, sample - self.starts[index]), self.ends[index] - self.starts[index])
            return (self.sources[index] + offset) / self.rate

    def model_time(self, seconds):
        with self.lock:
            if not self.sources:
                return 0.
            sample = seconds * self.rate
            index = max(0, bisect_right(self.sources, sample)-1)
            offset = min(max(0, sample - self.sources[index]), self.ends[index] - self.starts[index])
            return (self.starts[index] + offset) / self.rate


class VADTimeline:
    """Capture writes labels; the serialized decoder reads only its audio horizon."""
    def __init__(self):
        self.lock = RLock()
        self.silences = []

    def event(self, kind, timestamp, observed_at=None):
        observed_at = timestamp if observed_at is None else observed_at
        with self.lock:
            if kind == 'silence_started':
                if not self.silences or self.silences[-1][1] is not None:
                    self.silences.append((timestamp, None, observed_at, None))
            elif kind == 'speech_started' and self.silences and self.silences[-1][1] is None:
                start, _, known, _ = self.silences[-1]
                self.silences[-1] = (start, max(start, timestamp), known, observed_at)

    def snapshot(self, start, end):
        with self.lock:
            visible = [(a, b if ended is not None and ended <= end else end)
                       for a, b, known, ended in self.silences if known <= end]
            return [(max(start, a), min(end, b)) for a, b in visible if a < end and b > start + 1e-6]

    def prune(self, before):
        with self.lock:
            self.silences = [row for row in self.silences if row[1] is None or row[1] >= before]


def reference_cut(silences, start, end):
    """Exclude the first silence, take the longest five, then the earliest start."""
    visible = [(max(start, a), min(end, b)) for a, b in silences if a < end and b > start + 1e-6]
    candidates = sorted(visible[1:], key=lambda p: (-round(p[1] - p[0], 6), p[0]))[:5]
    return min((a for a, _ in candidates if a > start + 1e-6), default=None)


def fallback_cut(audio, target, rate=16000):
    """Prefer a relative energy dip in the next 0.5 s; never claim a word boundary."""
    desired = max(1, len(audio) - round(target * rate))
    frame = max(1, round(.02 * rate))
    positions = list(range(desired, min(len(audio) - frame + 1, desired + rate // 2 + 1), frame))
    if not positions:
        return desired
    energy = [float(np.mean(np.square(audio[i:i + frame], dtype=np.float64))) for i in positions]
    best = int(np.argmin(energy))
    return positions[best] if energy[best] < .5 * float(np.median(energy)) else desired


class ContinuousQwenPCM:
    """WLK mixin: its queue still coalesces PCM, but VAD cannot remove samples.

    Natural silence never creates WLK Silence messages. Those messages remain
    reserved for an explicit user pause (zero duration on the capture clock).
    """
    async def _process_pcm_array(self, pcm_array):
        if pcm_array is None or not len(pcm_array):
            return
        end_sample = self.total_pcm_samples + len(pcm_array)
        if self.current_silence is not None:
            # Initial placeholder / explicit pause, not a missing PCM interval.
            self.current_silence = None
        events = (self.vac(pcm_array) or []) if self.args.vac else []
        for event in events:
            for key, kind in (('start', 'speech_started'), ('end', 'silence_started')):
                if key in event:
                    # Silero timestamps include its debounce; never clamp a
                    # backdated label to a later packet boundary.
                    self.transcription.observe_capture_event(kind, int(event[key]) / self.sample_rate,
                                                           observed_at=end_sample / self.sample_rate)
        self.transcription.observe_capture_event('audio_advanced', end_sample / self.sample_rate)
        await self._enqueue_active_audio(pcm_array)
        self.total_pcm_samples = end_sample
        await self._emit_stream_event('audio_advanced', end_sample / self.sample_rate)

    async def _finalize_current_silence_at_stream_end(self):
        # All PCM was queued, so a duration marker would double-count time.
        self.current_silence = None

    def begin_continuous_pcm(self):
        self.current_silence = None
        if self.args.vac:
            self.transcription.observe_capture_event('silence_started', 0.)
        diag.event('asr_audio_policy', policy='original_pcm', silence_seconds=.5,
                   window_seconds=self.transcription.window_seconds, margin_seconds=5,
                   reference_points=5, resume_context_seconds=1.,
                   min_new_seconds=self.transcription.update_seconds,
                   max_new_seconds=self.transcription.MAX_NEW_SECONDS,
                   zero_frame_ms=10, zero_input='skip_and_flush_tail')
