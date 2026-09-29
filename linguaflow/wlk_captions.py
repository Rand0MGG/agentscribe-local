"""Context boundaries, mutable presentation rows and separately committed text."""
import time
from dataclasses import replace
from difflib import SequenceMatcher

from .core import Caption


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


def sentence_end(text):
    """Conservative fallback for an ASR endpoint, not a replacement for SaT."""
    return text.rstrip().rstrip('\"\'”’」』）)]').endswith(('.', '!', '?', '。', '！', '？'))


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
        self.fixed = []  # (id, end character, exact committed prefix)
        self.next_id = 1
        self.observed = {}
        self.last_text = ''
        self.submitted = []  # (id, start, end, open tail); protect against repeat splits
        self.ranges = {}  # Row identity follows source spans when boundaries merge.

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
        closed_end = max(closed_ends, default=0)

        def at(pos):
            for lo, hi, start, end, _language in spans:
                if pos <= hi:
                    return start + max(0, pos - lo) / max(1, hi - lo) * (end - start)
            return spans[-1][3] if spans else 0.

        # An actual upstream correction reopens affected rows instead of losing it.
        keep = 0
        for _id, _end, prefix in self.fixed:
            if not text.startswith(prefix):
                break
            keep += 1
        # A decoder endpoint can be a breath in the middle of one sentence.
        # Reconsider only the last completed row when continuation arrives.
        # Completion still releases translation immediately while input is idle.
        if keep:
            _cid, end, prefix = self.fixed[keep-1]
            begin = self.fixed[keep-2][1] if keep > 1 else 0
            if text[end:].strip() and not sentence_end(prefix):
                context_boundaries = self.policy.split(text[begin:])
                if not any(text[begin:begin+p].rstrip() == text[begin:end].rstrip()
                           for p, reason in context_boundaries if reason == '上下文分句'):
                    keep -= 1
        self.active = [row[0] for row in self.fixed[keep:]] + self.active
        self.fixed = self.fixed[:keep]
        offset = self.fixed[-1][1] if self.fixed else 0
        remainder = text[offset:]
        boundaries = self.policy.split(remainder) if remainder else []
        edits = (SequenceMatcher(None, self.last_text, text, autojunk=False).get_opcodes()
                 if self.last_text != text else [('equal', 0, len(text), 0, len(text))])

        def mapped(pos):
            for tag, a, b, c, d in edits:
                if a <= pos <= b:
                    return c + pos - a if tag == 'equal' else (d if pos == b else c)
            return len(text)

        # Submission freezes the initial translation, not a mistaken boundary.
        # Let SaT withdraw old cuts, but don't split already submitted material
        # into more first-translation requests on every partial hypothesis.
        submitted_ranges = [(mapped(begin), mapped(end)) for _cid, begin, end, _tail in self.submitted]
        boundaries = [(p, r) for p, r in boundaries if r == '等待后文' or not any(
            begin < offset+p < end for begin, end in submitted_ranges)]
        # A completed acoustic segment alone must not cut a continuing clause.
        # At an idle tail, the normal tail boundary still finalizes immediately.
        for stop in closed_ends:
            if (offset < stop <= len(text) and sentence_end(text[:stop])
                    and all(offset+p != stop for p, _r in boundaries)):
                boundaries.append((stop-offset, '识别段结束'))
        boundaries.sort()
        events, next_active, new_observed = [], [], {}
        now, start = self.clock(), offset
        submitted = []
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
            # Only ASR completion (or session EOF) finalizes source text. Elapsed
            # time can submit a stable tail, never make it immutable.
            final = done or end <= closed_end
            old = self.previous.get(cid)
            ready = bool(old and old.ready) or (stable and (
                reason != '等待后文' or now - since >= self.lookahead))
            language = next((row[4] for row in spans if row[1] > start), self.language)
            raw = text[start:end]
            visible_start = start + len(raw) - len(raw.lstrip())
            visible_end = end - len(raw) + len(raw.rstrip())
            caption = Caption(cid, at(visible_start), at(visible_end), source, language, final=final,
                              stable_source=text[start:min(end, stable_end)].strip(),
                              ready=ready or final, boundary_reason=reason)
            if old:
                caption.translation = old.translation
                caption.error = old.error
                caption.translation_source = old.translation_source
                caption.translation_phase = old.translation_phase
                if old.translation_phase == 'final' and (old.source != source or not final):
                    caption.translation_phase = 'initial'
            same = old and (old.source, old.final, old.start, old.end, old.ready, old.stable_source, old.boundary_reason) == (
                caption.source, caption.final, caption.start, caption.end, caption.ready, caption.stable_source, caption.boundary_reason)
            if not same:
                caption.revision = old.revision + 1 if old else 1
                self.previous[cid] = caption
                events.append(caption)
            if final:
                self.fixed.append((cid, end, text[:end]))
            else:
                next_active.append(cid)
                if caption.ready:
                    submitted.append((cid, start, end, reason == '等待后文'))
            start = end
        used = fixed_ids | {row[0] for row in self.fixed} | set(next_active)
        for cid in self.active:
            if cid not in used and cid in self.previous:
                old = self.previous.pop(cid)
                events.append(replace(old, source="", translation="", final=True, revision=old.revision + 1))
        self.active = next_active
        self.observed = new_observed
        self.submitted = submitted
        self.ranges = new_ranges
        self.last_text = text
        return events
