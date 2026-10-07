"""Context boundaries, mutable presentation rows and separately committed text."""
import time
from bisect import bisect_right
from dataclasses import replace
from difflib import SequenceMatcher

from .asr_stability import units
from .core import Caption

DIFF_CONTEXT_ROWS = 10


def _common_prefix_end(previous, current):
    """Locate a correction without storing one history copy per caption."""
    if current.startswith(previous):
        return len(previous)
    limit = min(len(previous), len(current))
    start = 0
    # Native chunk comparisons keep long, unchanged classroom history cheap.
    while start < limit:
        end = min(start + 1024, limit)
        if previous[start:end] != current[start:end]:
            while start < end and previous[start] == current[start]:
                start += 1
            return start
        start = end
    return limit


def seconds(value):
    result = 0.
    for part in str(value or "0").split(":"):
        result = result * 60 + float(part)
    return result


def caption_snapshot(front):
    snapshot = front.to_dict()
    snapshot["lines"] = []
    for segment in front.lines:
        if not segment.text:
            continue
        if segment.tokens:
            snapshot["lines"].append({"text": "".join(t.text for t in segment.tokens),
                "start": segment.tokens[0].start, "end": segment.tokens[-1].end,
                "detected_language": segment.detected_language,
                "tokens": [{"text": t.text, "start": t.start, "end": t.end} for t in segment.tokens]})
        else:
            snapshot["lines"].append(segment.to_dict())
    return snapshot


def separator(left, right):
    if not left or not right or left[-1].isspace() or right[0].isspace():
        return ""
    if right[0] in ".,!?;:。！，？；：…" or ("\u3400" <= left[-1] <= "\u9fff" and "\u3400" <= right[0] <= "\u9fff"):
        return ""
    return " "


class BoundaryPolicy:
    """Map SaT offsets to provisional caption boundaries."""
    def __init__(self, predictor):
        if not callable(predictor):
            raise TypeError("字幕分句需要 SaT 边界预测器。")
        self.predictor = predictor
        self.cache = None

    def split(self, text):
        if self.cache and self.cache[0] == text:
            return list(self.cache[1])
        proposals = set()
        for start in range(0, len(text), 1024):
            window_start = max(0, start - 128)
            window = text[window_start:start + 1152]
            for offset in self.predictor(window):
                if not isinstance(offset, int) or not 0 < offset <= len(window):
                    raise ValueError("SaT 返回了无效的分句位置。")
                absolute = window_start + offset
                # A comma/colon/list separator joins clauses inside a sentence.
                if (start < absolute <= start + 1024
                        and not text[:absolute].rstrip().endswith((',', '，', ':', '：', ';', '；', '、'))):
                    proposals.add(absolute)
        boundaries = [(end, "上下文分句") for end in sorted(proposals)]
        if not boundaries or boundaries[-1][0] < len(text):
            boundaries.append((len(text), "等待后文"))
        self.cache = (text, tuple(boundaries))
        return boundaries


class CaptionMapper:
    def __init__(self, language="auto", *, predictor, lookahead=3., clock=time.monotonic):
        self.language = language
        self.policy = BoundaryPolicy(predictor)
        self.lookahead, self.clock = lookahead, clock
        self.previous = {}
        self.active = []
        self.fixed = []  # (id, end character); last_text owns the common history.
        self.next_id = 1
        self.observed = {}
        self.last_text = ''
        self.ranges = {}  # Row identity follows source spans when boundaries merge.
        self.boundary_observed = {}

    def update(self, snapshot, done=False):
        text, spans = "", []
        for line in snapshot.get("lines", []):
            if not (line.get("text") or "").strip():
                continue
            tokens = line.get("tokens") or [line]
            text += separator(text, tokens[0].get("text", ""))
            for token in tokens:
                value = token.get("text", "")
                if not value:
                    continue
                start = len(text)
                text += value
                spans.append((start, len(text), seconds(token.get("start")), seconds(token.get("end")),
                              line.get("detected_language") or self.language))
        stable_end = len(text)
        tail = snapshot.get("buffer_transcription", "").strip()
        if tail and not done:
            text += separator(text, tail)
            tail_start = len(text)
            text += tail
            if snapshot.get("draft_span"):
                draft = snapshot["draft_span"]
                spans.append((tail_start, len(text), seconds(draft.get("start")),
                              seconds(draft.get("end")), self.language))
        if "revision_text" in snapshot:
            text = snapshot["revision_text"]
            stable_end = snapshot["stable_end"]
            spans = snapshot["revision_spans"]
        if not text.strip():
            text = ""
        closed_ends = list(snapshot.get('closed_ends', []))
        if 'closed_audio_time' in snapshot:
            # Token timestamps locate one completed utterance endpoint; they
            # must not turn every word into a new caption boundary.
            completed = [hi for _lo, hi, _a, b, _lang in spans
                         if b <= snapshot['closed_audio_time'] + .001 and hi <= stable_end]
            if completed:
                closed_ends.append(max(completed))
        # ASR's acoustic completion confirms characters, never a sentence cut.
        # Authoritative revision snapshots already express this in stable_end.
        if 'revision_text' not in snapshot and closed_ends:
            stable_end = max(stable_end, max(closed_ends))

        def at(pos):
            for lo, hi, start, end, _language in spans:
                if pos <= hi:
                    return start + max(0, pos - lo) / max(1, hi - lo) * (end - start)
            return spans[-1][3] if spans else 0.

        # An actual upstream correction reopens affected rows instead of losing it.
        valid_end = min(stable_end, _common_prefix_end(self.last_text, text))
        keep = bisect_right(self.fixed, valid_end, key=lambda row: row[1])
        # A decoder endpoint can be a breath in the middle of one sentence.
        # Reconsider only the last completed row when continuation arrives.
        # Completion still releases translation immediately while input is idle.
        if keep:
            _cid, end = self.fixed[keep-1]
            begin = self.fixed[keep-2][1] if keep > 1 else 0
            if text[end:].strip():
                context_boundaries = self.policy.split(text[begin:])
                cuts = [begin + p for p, reason in context_boundaries if reason == '上下文分句']
                if (not any(text[:p].rstrip() == text[:end].rstrip() for p in cuts)
                        or any(begin < p < end and text[p:end].strip() for p in cuts)):
                    keep -= 1
        self.active = [row[0] for row in self.fixed[keep:]] + self.active
        self.fixed = self.fixed[:keep]
        offset = self.fixed[-1][1] if self.fixed else 0
        remainder = text[offset:]
        boundaries = self.policy.split(remainder) if remainder else []
        # Include ten unchanged caption rows as context, plus the entire mutable
        # suffix. Earlier corrections already reduced `keep`, moving this window
        # back with them; never discard a correction to enforce a fixed cutoff.
        if self.last_text != text:
            diff_start = (self.fixed[-DIFF_CONTEXT_ROWS - 1][1]
                          if len(self.fixed) > DIFF_CONTEXT_ROWS else 0)
            edits = [('equal', 0, diff_start, 0, diff_start)] if diff_start else []
            edits.extend((tag, a + diff_start, b + diff_start, c + diff_start, d + diff_start)
                         for tag, a, b, c, d in SequenceMatcher(
                             None, self.last_text[diff_start:], text[diff_start:], autojunk=False).get_opcodes())
        else:
            edits = [('equal', 0, len(text), 0, len(text))]

        def mapped(pos):
            if pos <= offset:
                return pos  # Stable context participates in matching, not revision.
            for tag, a, b, c, d in edits:
                if a <= pos <= b:
                    return c + pos - a if tag == 'equal' else (d if pos == b else c)
            return len(text)

        # SaT may revise submitted rows. Acoustic ends and ASR punctuation must
        # not manufacture a text boundary or protect an incorrect old cut.
        events, next_active, new_observed = [], [], {}
        now, start = self.clock(), offset
        new_boundary_observed = {}
        fixed_ids = {row[0] for row in self.fixed}
        assigned = set(fixed_ids)
        candidates = [(cid, mapped(self.ranges[cid][0]), mapped(self.ranges[cid][1]))
                      for cid in self.active if cid in self.ranges]
        new_ranges = {cid: span for cid, span in self.ranges.items() if cid in fixed_ids}
        for relative_end, reason in boundaries:
            end = offset + relative_end
            source = text[start:end].strip()
            if not source:
                continue
            cid = next((cid for cid, a, b in candidates if cid not in assigned
                        and a < end and (b > start or a == start)), self.next_id)
            assigned.add(cid)
            new_ranges[cid] = (start, end)
            if cid == self.next_id:
                self.next_id += 1
            key = (start, end, source, stable_end >= end)
            since, count = self.observed.get(key, (now, 0))
            new_observed[key] = (since, count + 1)
            stable = end <= stable_end or not text[stable_end:end].strip()
            boundary_key = (start, end, source)
            observations = self.boundary_observed.get(boundary_key, 0)
            if reason == '上下文分句' and text != self.last_text:
                observations += 1
            new_boundary_observed[boundary_key] = observations
            asr_final = stable
            # The tail has no following evidence: even a closed ASR utterance
            # only submits an initial translation until SaT sees more context
            # or an explicit session EOF closes its last row. Heartbeats do not
            # count as independent boundary observations.
            boundary_final = asr_final and (done or (
                reason == '上下文分句' and observations >= 2
                and len(units(text[end:stable_end])) >= 4))
            final = asr_final and boundary_final
            old = self.previous.get(cid)
            ready = bool(old and old.ready) or (stable and (
                reason != '等待后文' or now - since >= self.lookahead))
            language = next((row[4] for row in spans if row[1] > start), self.language)
            raw = text[start:end]
            visible_start = start + len(raw) - len(raw.lstrip())
            visible_end = end - len(raw) + len(raw.rstrip())
            caption = Caption(cid, at(visible_start), at(visible_end), source, language, final=final,
                              stable_source=text[start:min(end, stable_end)].strip(),
                              ready=ready or final, boundary_reason=reason,
                              asr_final=asr_final, boundary_final=boundary_final)
            # Position-only timestamp updates do not change segmentation.
            structural_change = (old is None or self.ranges.get(cid) != (start, end)
                                 or old.boundary_reason != reason)
            caption.segmentation_revision = ((old.segmentation_revision + int(structural_change))
                                             if old else 1)
            if old:
                caption.translation = old.translation
                caption.error = old.error
                caption.translation_source = old.translation_source
                caption.translation_phase = old.translation_phase
                if old.translation_phase == 'final' and (old.source != source or not final
                        or old.segmentation_revision != caption.segmentation_revision):
                    caption.translation_phase = 'initial'
            same = old and (old.source, old.final, old.start, old.end, old.ready, old.stable_source,
                           old.boundary_reason, old.asr_final, old.boundary_final, old.segmentation_revision) == (
                caption.source, caption.final, caption.start, caption.end, caption.ready, caption.stable_source,
                caption.boundary_reason, caption.asr_final, caption.boundary_final, caption.segmentation_revision)
            if not same:
                caption.revision = old.revision + 1 if old else 1
                self.previous[cid] = caption
                events.append(caption)
            if final:
                self.fixed.append((cid, end))
            else:
                next_active.append(cid)
            start = end
        used = fixed_ids | {row[0] for row in self.fixed} | set(next_active)
        for cid in self.active:
            if cid not in used and cid in self.previous:
                old = self.previous.pop(cid)
                events.append(replace(old, source="", translation="", final=True, revision=old.revision + 1))
        self.active = next_active
        self.observed = new_observed
        self.boundary_observed = new_boundary_observed
        self.ranges = new_ranges
        self.last_text = text
        return events
