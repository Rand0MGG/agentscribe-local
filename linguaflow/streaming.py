"""Mutable source captions over continuous audio; translation consumes finals only."""
import numpy as np

from .core import SAMPLE_RATE, Caption
from .vendor.hypothesis_buffer import HypothesisBuffer


class WhisperReviser:
    """Offline Whisper adapted online using overlapping decode and upstream local agreement.

    The whole current row stays editable until silence or a stable long-stream
    checkpoint. The last two seconds never become a forced length checkpoint.
    """
    def __init__(self, recognizer, settings):
        self.recognizer = recognizer
        self.settings = settings
        self.audio = np.empty(0, np.float32)
        self.offset = 0.0
        self.cutoff = 0.0
        self.history = ""
        self.row = 1
        self.revision = 0
        self.last_text = None
        self.language = settings.source or "auto"
        self.hypothesis = HypothesisBuffer()
        self.stable = []

    def _decode(self):
        if hasattr(self.recognizer, "recognize_words"):
            words, self.language = self.recognizer.recognize_words(self.audio, self.history[-300:])
        else:  # injectable test recognizers and legacy adapters
            words, self.language = self.recognizer.recognize(self.audio)
        return [(a + self.offset, b + self.offset, t) for a, b, t in words
                if b + self.offset > self.cutoff + 0.02]

    def _event(self, words, final=False):
        text = "".join(w[2] for w in words).strip()
        if not text and self.last_text is None:
            return None
        if text == self.last_text and not final:
            return None
        self.revision += 1
        self.last_text = text
        stable = "".join(w[2] for w in self.stable if w[1] <= (words[-1][1] if words else 0)).strip()
        return Caption(self.row, words[0][0] if words else self.cutoff,
                       words[-1][1] if words else self.offset + len(self.audio) / SAMPLE_RATE,
                       text, self.language, final=final, revision=self.revision, stable_source=stable)

    def _advance(self, boundary):
        # Preserve one second of audio before the confirmed boundary for acoustics.
        keep_from = max(self.offset, boundary - 1.0)
        count = int((keep_from - self.offset) * SAMPLE_RATE)
        self.audio = self.audio[count:]
        self.offset += count / SAMPLE_RATE
        self.cutoff = boundary
        self.row += 1
        self.revision = 0
        self.last_text = None
        self.hypothesis = HypothesisBuffer()
        self.hypothesis.last_commited_time = boundary
        self.stable = []

    def update(self, samples, final=False):
        self.audio = np.concatenate((self.audio, samples))
        if not len(self.audio):
            return []
        words = self._decode()
        self.hypothesis.insert(words, 0)
        self.stable.extend(self.hypothesis.flush())
        events = []
        end = self.offset + len(self.audio) / SAMPLE_RATE
        endpoint = (self.recognizer.endpoint(self.audio, self.settings.endpoint_seconds)
                    if hasattr(self.recognizer, "endpoint") else False)
        if final or (endpoint and (words or self.last_text is not None)):
            # Re-decoding already used all currently available right-hand context.
            event = self._event(words, final=True)
            if event:
                events.append(event)
                self.history = (self.history + " " + event.source)[-600:]
            self._advance(end)
        elif len(self.audio) >= 20 * SAMPLE_RATE and self.stable:
            # The editable whole-row decode can revise a formerly agreed word.
            # Never use stale agreement to finalize a newly different prefix.
            matching = []
            for agreed, current in zip(self.stable, words):
                if agreed[2] != current[2]:
                    break
                matching.append(current)
            candidates = [w for w in matching if w[1] <= end - 2.0]
            if candidates:
                boundary = candidates[-1][1]
                confirmed = [w for w in words if w[1] <= boundary + 0.02]
                event = self._event(confirmed, final=True)
                if event:
                    events.append(event)
                    self.history = (self.history + " " + event.source)[-600:]
                self._advance(boundary)
                event = self._event([w for w in words if w[1] > boundary + 0.02])
                if event:
                    events.append(event)
            else:
                event = self._event(words)
                if event:
                    events.append(event)
        else:
            event = self._event(words)
            if event:
                events.append(event)
        if len(self.audio) > 60 * SAMPLE_RATE:
            # Do not silently discard uncertain speech to maintain responsiveness.
            raise RuntimeError("连续 60 秒无法确认转录边界，已停止会话；未定稿原文仍可查看，剩余临时音频将删除。请切换引擎后重试。")
        # Long confirmed silence need not occupy the rolling inference window.
        if not words and self.last_text is None and endpoint and len(self.audio) > 10 * SAMPLE_RATE:
            self._advance(end - 1.0)
        return events

    def close(self):
        pass
