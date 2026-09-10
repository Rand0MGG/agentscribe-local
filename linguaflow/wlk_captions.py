"""Context boundaries, mutable presentation rows and separately committed text."""
import re
import time
from dataclasses import replace

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


class BoundaryPolicy:
    """SaT proposals with continuation guards and display-only length limits."""
    incomplete = re.compile(r"(?:\b(?:because|although|if|when|unless|the|a|an|to|of|is|are|and|or|will|would|can|could|should|must|very|some|such|these|those|that|this|actually|calculate|estimate)|因为|如果|虽然|但是|所以说|前提是|也就是说|是指|比如|例如|的)\s*[.。,…:：]*\s*$", re.I)
    restart = re.compile(r"我们先|我们来看|先看(?:这|那|右|左)|换个(?:例子|问题)|接下来|\blet['’]s\s+(?:look|consider)|\bnow\s+let", re.I)
    correction = re.compile(r"\s*(?:不对|不是|我是说|应该是|\bactually\b|\bi mean\b|\brather\b)", re.I)

    @staticmethod
    def continuation(left, right):
        # Inspect both sides: ASR punctuation is a proposal, not syntactic proof.
        left = re.sub(r"[.!?。！？…]+$", "", left.strip()).strip()
        right = right.lstrip()
        return bool(
            re.search(r"\b(?:based|depends|depending)\s*$", left, re.I) and re.match(r"(?:on|upon)\b", right, re.I)
            or re.search(r"\b(?:density|distribution|modeling)\s*$", left, re.I) and re.match(r"(?:function|area)\b", right, re.I)
            or re.search(r"\b(?:we|they|it|you|i)\s*$", left, re.I) and re.match(r"(?:will|would|can|are|is|still|need)\b", right, re.I)
        )

    def __init__(self, predictor=None, max_seconds=12):
        self.predictor = predictor
        self.max_seconds = max_seconds
        self.cache = None

    def split(self, text, time_at):
        if self.cache and self.cache[0] == text:
            proposals = dict(self.cache[1])
        else:
            proposals = {}
            if self.predictor:
                for start in range(0, len(text), 1024):
                    window_start = max(0, start - 128)
                    window = text[window_start:start + 1152]
                    for offset in self.predictor(window):
                        absolute = window_start + offset
                        if start < absolute <= start + 1024:
                            proposals[absolute] = "上下文分句"
            else:
                for match in re.finditer(r"[。！？!?]+\s*|(?<!\.)\.(?![.\d])\s*", text):
                    word = text[:match.end()].rstrip().split()[-1].lower()
                    if word not in {"mr.", "mrs.", "dr.", "prof.", "e.g.", "i.e."}:
                        proposals[match.end()] = "标点候选"
            for match in self.restart.finditer(text):
                if match.start() > 0:
                    proposals[match.start()] = "话题转向"
            if re.search(r"[。！？.!?]$", text.strip()) and not text.rstrip().endswith("..."):
                proposals[len(text)] = "句末候选"
            self.cache = (text, dict(proposals))
        boundaries, previous = [], 0
        for end in sorted(proposals):
            if not 0 < end <= len(text):
                continue
            part = text[previous:end]
            if not part.strip():
                continue
            if len(re.sub(r"[\W_]", "", part)) < 8 and proposals[end] != "话题转向":
                continue  # Keep tiny acknowledgements with their following context.
            if end < len(text) and text[end-1].isascii() and text[end-1].isalnum() and text[end].isascii() and text[end].isalnum():
                continue
            if self.correction.match(text[end:]):
                continue
            if self.continuation(part, text[end:]):
                continue
            if self.incomplete.search(part) and proposals[end] != "话题转向":
                continue
            boundaries.append((end, proposals[end]))
            previous = end
        if not boundaries or boundaries[-1][0] < len(text):
            boundaries.append((len(text), "等待后文"))
        result, start = [], 0
        for end, reason in boundaries:
            while end - start > 240 or time_at(end) - time_at(start) > self.max_seconds:
                limit = min(end, start + 240)
                for pos in range(start + 1, limit + 1):
                    if time_at(pos) - time_at(start) >= self.max_seconds:
                        limit = pos
                        break
                choices = [m.end() + start for m in re.finditer(r"[,，;；:：]\s*|\s+", text[start:limit])]
                cut = choices[-1] if choices else limit
                if cut <= start or cut >= end:
                    break
                result.append((cut, "显示换段 · 未判定句完"))
                start = cut
            result.append((end, reason))
            start = end
        return result


class CaptionMapper:
    def __init__(self, language="auto", predictor=None, lookahead=3., max_seconds=12., clock=time.monotonic):
        self.language = language
        self.policy = BoundaryPolicy(predictor, max_seconds)
        self.lookahead, self.clock = lookahead, clock
        self.previous = {}
        self.active = []
        self.fixed = []  # (id, end character, exact committed prefix)
        self.next_id = 1
        self.observed = {}

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
            text += separator(text, tail) + tail
        if not text.strip(" .,!?。！？…"):
            text = ""

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
        self.active = [row[0] for row in self.fixed[keep:]] + self.active
        self.fixed = self.fixed[:keep]
        offset = self.fixed[-1][1] if self.fixed else 0
        remainder = text[offset:]
        boundaries = self.policy.split(remainder, lambda p: at(offset + p)) if remainder else []
        events, next_active, new_observed = [], [], {}
        now, start, can_lock = self.clock(), offset, True
        fixed_ids = {row[0] for row in self.fixed}
        for slot, (relative_end, reason) in enumerate(boundaries):
            end = offset + relative_end
            source = text[start:end].strip()
            if not source:
                continue
            cid = self.active[slot] if slot < len(self.active) else self.next_id
            if cid == self.next_id:
                self.next_id += 1
            key = (start, end, source, reason)
            since, count = self.observed.get(key, (now, 0))
            new_observed[key] = (since, count + 1)
            stable = end <= stable_end or not text[stable_end:end].strip()
            following = text[end:stable_end].strip()
            contextual = len(following) >= 8 and at(stable_end) - at(end) >= self.lookahead
            if reason.startswith("显示换段"):
                contextual = contextual and at(stable_end) - at(end) >= max(12., self.lookahead * 2)
            final = done or (can_lock and stable and contextual and count >= 1 and now - since >= .8)
            if not final:
                can_lock = False
            ready = stable and reason != "等待后文"
            language = next((row[4] for row in spans if row[1] > start), self.language)
            raw = text[start:end]
            visible_start = start + len(raw) - len(raw.lstrip())
            visible_end = end - len(raw) + len(raw.rstrip())
            caption = Caption(cid, at(visible_start), at(visible_end), source, language, final=final,
                              stable_source=text[start:min(end, stable_end)].strip(),
                              ready=ready or final, boundary_reason=reason)
            old = self.previous.get(cid)
            same = old and (old.source, old.final, old.end, old.ready, old.stable_source, old.boundary_reason) == (
                caption.source, caption.final, caption.end, caption.ready, caption.stable_source, caption.boundary_reason)
            if not same:
                caption.revision = old.revision + 1 if old else 1
                self.previous[cid] = caption
                events.append(caption)
            if final:
                self.fixed.append((cid, end, text[:end]))
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
        return events
