"""Position-scoped cumulative votes; submitted text is never rewritten by ASR.

Like WhisperStreaming's hypothesis buffer, keep submitted output separate from
new hypotheses. Unlike LocalAgreement-2, three nonconsecutive observations vote
for a candidate. Only directly decoded text with fresh audio supplies a vote.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .asr_stability import confirmation_ranges, units


def _parts(text):
    matches = units(text)
    return tuple(text[0 if i == 0 else matches[i-1].end():m.end()] for i, m in enumerate(matches))


def _key(parts):
    return tuple(p.lstrip() for p in parts)


@dataclass
class _Span:
    parts: tuple
    observations: dict = field(default_factory=dict)
    locked: bool = False

    @property
    def alignment_parts(self):
        # Keep the position of a temporarily omitted, unlocked word. Otherwise
        # A,A,omitted,A loses its votes and may be mistaken for a new insertion.
        return self.parts or next((p for p in reversed(self.observations.values()) if p), ())

    def observe(self, parts, end):
        if self.locked:
            return
        self.parts = parts
        if end is not None:
            self.observations[end] = parts
            if parts and sum(_key(p) == _key(parts) for p in self.observations.values()) >= 3:
                self.locked = True
                self.observations.clear()


class CumulativeSubmission:
    def __init__(self):
        self.spans = []
        self.last_audio_end = float('-inf')
        self.diagnostic = {}

    def _split_at(self, start):
        """Locate a textual window boundary, never estimate votes from time."""
        offset = 0
        for i, span in enumerate(self.spans):
            size = sum(map(len, span.parts))
            if not size and offset == start:
                return i
            if offset + size > start:
                count, cursor = 0, offset
                for part in span.parts:
                    if cursor + len(part) > start:
                        break
                    cursor += len(part)
                    count += 1
                if count:
                    # A multiword alternative can straddle the next text window.
                    # Preserve only observations with this exact word structure.
                    pieces = []
                    for lo, hi in ((0, count), (count, len(span.parts))):
                        observations = {end: value[lo:hi] for end, value in span.observations.items()
                                        if len(value) == len(span.parts)}
                        pieces.append(_Span(span.parts[lo:hi], observations, span.locked))
                    self.spans[i:i+1] = pieces
                    return i + 1
                return i
            offset += size
        return len(self.spans)

    def _replace(self, old, parts, end):
        if not old:
            result = [_Span((p,)) for p in parts]
            for span in result:
                span.observe(span.parts, end)
            return result
        if len(old) > 1 and sum(len(span.alignment_parts) for span in old) == len(parts):
            # A length-preserving substitution keeps distinct word positions;
            # disagreement at one word must not reset its unchanged neighbor.
            result, cursor = [], 0
            for span in old:
                stop = cursor + len(span.alignment_parts)
                result.extend(self._replace([span], parts[cursor:stop], end))
                cursor = stop
            return result
        if any(span.locked for span in old):
            self.diagnostic['protected_changes'] += 1
            if not parts:
                return [item for span in old for item in
                        ([span] if span.locked else self._replace([span], (), end))]
            if all(span.locked for span in old):
                return old
            # No trustworthy split around immutable words: do not guess which
            # new words replace a lock. Await a hypothesis with usable anchors.
            self.diagnostic['ambiguous_changes'] += 1
            return old
        # Keep previous variants of the same aligned range, including alternate
        # tokenizations such as "soft mass" / "softmax". A combined range only
        # inherits observations in which every constituent was really decoded.
        rounds = set(old[0].observations)
        for span in old[1:]:
            rounds.intersection_update(span.observations)
        observations = {r: tuple(p for span in old for p in span.observations[r]) for r in sorted(rounds)}
        span = _Span(parts, observations)
        span.observe(parts, end)
        return [span]

    def update(self, local, *, start, audio_end, aligned=True):
        fresh = audio_end > self.last_audio_end
        end = audio_end if fresh else None
        self.last_audio_end = max(self.last_audio_end, audio_end)
        self.diagnostic = dict(reason='cumulative_votes', fresh_observation=fresh,
                               protected_changes=0, ambiguous_changes=0)
        index = self._split_at(start)
        prefix, old = self.spans[:index], self.spans[index:]
        if not aligned:
            for span in old:
                if not span.locked:
                    span.observations.clear()
            old = [span for span in old if span.parts]
        incoming = list(_parts(local))
        if incoming and prefix:
            # Window decodes omit the preceding separator; it is not a new word.
            previous = ''.join(p for span in prefix for p in span.parts)
            first = incoming[0].lstrip()
            gap = ' ' if previous and first else ''
            if previous and first and '\u3400' <= previous[-1] <= '\u9fff' and '\u3400' <= first[0] <= '\u9fff':
                gap = ''
            incoming[0] = gap + first
        flat = [p for span in old for p in span.alignment_parts]
        edges, pos = {0: 0}, 0
        for i, span in enumerate(old):
            pos += len(span.alignment_parts)
            edges[pos] = i + 1
        opcodes = SequenceMatcher(None, _key(flat), _key(incoming), autojunk=False).get_opcodes()
        result, pending = [], None
        for tag, a, b, c, d in opcodes:
            if pending is None:
                pending = [tag, a, b, c, d]
            else:
                pending[0] = 'replace'
                pending[2], pending[4] = b, d
            if b not in edges:
                continue
            kind, lo, hi, begin, stop = pending
            group = old[edges[lo]:edges[hi]]
            parts = tuple(incoming[begin:stop])
            if kind == 'equal':
                cursor = 0
                for span in group:
                    count = len(span.alignment_parts)
                    span.observe(parts[cursor:cursor+count], end)
                    result.append(span)
                    cursor += count
            elif kind == 'insert' and result and edges[lo] < len(old) and result[-1].locked and old[edges[lo]].locked:
                # An insertion inside an already submitted run is a rewrite too.
                self.diagnostic['protected_changes'] += 1
            else:
                result.extend(self._replace(group, parts, end))
            pending = None
        self.spans = prefix + result
        text, ranges, cursor = '', [], 0
        for span in self.spans:
            value = ''.join(span.parts)
            if span.locked:
                ranges.append((cursor + len(value)-len(value.lstrip()), cursor + len(value)))
            text += value
            cursor += len(value)
        prefix_size = sum(len(p) for span in prefix for p in span.parts)
        window_start = prefix_size + len(text[prefix_size:])-len(text[prefix_size:].lstrip())
        return text, confirmation_ranges(text, ranges), window_start
