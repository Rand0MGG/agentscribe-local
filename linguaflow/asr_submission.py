"""LocalAgreement-2 submission with immutable output and a Qwen text adapter.

The pending hypotheses follow Whisper-Streaming's HypothesisBuffer.flush:
https://github.com/ufal/whisper_streaming/blob/main/whisper_online.py
Qwen has no word timestamps here. Raw word alignment removes already submitted
context instead; it must remain separate from the immutable displayed spelling.
"""
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

from .asr_stability import confirmation_ranges, units


def _parts(text):
    matches = units(text)
    return tuple(text[0 if i == 0 else matches[i-1].end():m.end()] for i, m in enumerate(matches))


def _key(parts):
    return tuple(p.lstrip() for p in parts)


@dataclass(eq=False)
class _Word:
    text: str
    raw: tuple
    locked: bool = False
    changed_at: float = 0.


class LocalAgreementSubmission:
    HISTORY_SECONDS = 10.

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.words = []
        self.previous = []
        self.last_audio_end = float('-inf')
        self.diagnostic = {}
        self.history_count = 0
        self.history_due = float('inf')

    def _replace(self, old, parts, now, internal=False):
        """Project raw corrections without changing submitted spellings.

        An internal rewrite wholly inside submitted text is absorbed there.
        At the open right edge, additional words are new pending output; a
        disagreeing submitted word must never swallow the entire new suffix.
        """
        result, cursor = [], 0
        absorb = internal and old and all(w.locked for w in old)
        for i, word in enumerate(old):
            stop = len(parts) if absorb and i == len(old)-1 else min(len(parts), cursor+len(word.raw))
            value = parts[cursor:stop]
            if word.locked:
                if value != word.raw:
                    self.diagnostic['protected_changes'] += 1
                if value:
                    word.raw = value
                result.append(word)
            else:
                if value == (word.text,):
                    result.append(word)
                else:
                    result.extend(_Word(p, (p,), changed_at=now) for p in value)
            cursor = stop
        result.extend(_Word(p, (p,), changed_at=now) for p in parts[cursor:])
        return result

    def update(self, local, *, start, audio_end, aligned=True):
        now = self.clock()
        fresh = audio_end > self.last_audio_end
        self.last_audio_end = max(self.last_audio_end, audio_end)
        self.diagnostic = dict(reason='local_agreement_2', fresh_observation=fresh,
                               protected_changes=0, committed_units=0)
        offset, index = 0, len(self.words)
        for i, word in enumerate(self.words):
            if offset + len(word.text) > start:
                index = i
                break
            offset += len(word.text)
        prefix, old = self.words[:index], self.words[index:]
        active = set(old)
        previous = [key for word, key in self.previous if word in active and not word.locked] if aligned else []
        incoming = list(_parts(local))
        if incoming and prefix:
            before = ''.join(w.text for w in prefix)
            first = incoming[0].lstrip()
            gap = ' ' if before and first else ''
            if before and first and '\u3400' <= before[-1] <= '\u9fff' and '\u3400' <= first[0] <= '\u9fff':
                gap = ''
            incoming[0] = gap + first
        flat = [p for word in old for p in word.raw]
        edges, pos = {0: 0}, 0
        for i, word in enumerate(old):
            pos += len(word.raw)
            edges[pos] = i+1
        result, pending = [], None

        def apply(kind, lo, hi, begin, stop):
            group = old[edges[lo]:edges[hi]]
            parts = tuple(incoming[begin:stop])
            if kind == 'equal':
                cursor = 0
                for word in group:
                    count = len(word.raw)
                    word.raw = parts[cursor:cursor+count]
                    if not word.locked:
                        value = ''.join(word.raw)
                        if value != word.text:
                            word.changed_at = now
                            word.text = value
                    result.append(word)
                    cursor += count
            elif kind == 'insert' and edges[lo] < len(old) and old[edges[lo]].locked:
                # Inserting before submitted words would rewrite that prefix.
                self.diagnostic['protected_changes'] += 1
            else:
                result.extend(self._replace(group, parts, now, internal=hi < len(flat)))

        for tag, a, b, c, d in SequenceMatcher(None, _key(flat), _key(incoming), autojunk=False).get_opcodes():
            if pending is None:
                pending = [tag, a, b, c, d]
            else:
                pending[0] = 'replace'
                pending[2], pending[4] = b, d
            kind, lo, hi, begin, stop = pending
            if hi not in edges:
                # A partial match in a submitted multiword correction must not
                # absorb the complete, unchanged words before it.
                if kind == 'equal':
                    cut = max(edge for edge in edges if edge <= hi)
                    if cut > lo:
                        apply(kind, lo, cut, begin, begin+cut-lo)
                        pending = [kind, cut, hi, begin+cut-lo, stop]
                continue
            apply(*pending)
            pending = None

        draft = [word for word in result if not word.locked]
        keys = [word.text.lstrip() for word in draft]
        if fresh:
            count = 0
            for before, current in zip(previous, keys):
                if before != current:
                    break
                count += 1
            for word in draft[:count]:
                word.locked = True
            self.diagnostic['committed_units'] = count
            self.previous = list(zip(draft[count:], keys[count:]))
        elif keys != previous:
            # A repeated-PCM correction is displayable, but is not a new
            # independent hypothesis that can supply an agreement observation.
            self.previous = []
        else:
            self.previous = list(zip(draft, keys))
        self.words = prefix + result
        self.mark_history(len(prefix))
        self.diagnostic['history_timeout_units'] = self.expire_history(now)
        text, ranges = self.snapshot()
        prefix_size = sum(len(w.text) for w in prefix)
        window_start = prefix_size + len(text[prefix_size:])-len(text[prefix_size:].lstrip())
        return text, ranges, window_start

    def mark_history(self, count):
        """Only text before the aligned current window (or a suspended row)."""
        self.history_count = count
        self.history_due = min((w.changed_at + self.HISTORY_SECONDS
                                for w in self.words[:count] if not w.locked), default=float('inf'))

    def expire_history(self, now=None):
        now = self.clock() if now is None else now
        if now < self.history_due:
            return 0
        count = 0
        for word in self.words[:self.history_count]:
            if not word.locked and now - word.changed_at >= self.HISTORY_SECONDS:
                word.locked = True
                count += 1
        self.mark_history(self.history_count)
        return count

    def snapshot(self):
        text, ranges, cursor = '', [], 0
        for word in self.words:
            if word.locked:
                ranges.append((cursor+len(word.text)-len(word.text.lstrip()), cursor+len(word.text)))
            text += word.text
            cursor += len(word.text)
        return text, confirmation_ranges(text, ranges)
