"""Map WLK stable lines and revisable tail into desktop caption revisions."""
from dataclasses import replace

from .core import Caption


def caption_snapshot(front):
    """Split only committed upstream tokens, never the speculative ASR buffer.

    WLK speaker turns can grow indefinitely without a long pause. Presentation
    chunks use token timestamps and preserve all text; they do not trim audio
    or override the upstream ASR commit policy.
    """
    snapshot = front.to_dict()
    lines = []
    for segment in front.lines:
        if not segment.text and segment.speaker != -2:
            continue
        if not segment.tokens:
            lines.append(segment.to_dict())
            continue
        group = []
        def append(closed):
            lines.append({"start": group[0].start, "end": group[-1].end,
                          "text": "".join(t.text for t in group), "closed": closed,
                          "detected_language": segment.detected_language})
        for token in segment.tokens:
            # A decoder may append a late full stop after a silence marker.
            # It is not a standalone utterance to translate.
            if not group and token.text.strip() in {".", ",", "!", "?", "。", "，", "！", "？"}:
                continue
            group.append(token)
            word = token.text.strip()
            punctuation = word.endswith((".", "!", "?", "。", "！", "？"))
            abbreviation = word.lower() in {"mr.", "mrs.", "ms.", "dr.", "prof.", "e.g.", "i.e."}
            enough_context = len("".join(t.text for t in group).strip()) >= 16
            if (punctuation and not abbreviation and enough_context) or token.end - group[0].start >= 8:
                append(True)
                group = []
        if group:
            append(False)
    snapshot["lines"] = lines
    return snapshot


def seconds(value):
    result = 0.0
    for part in str(value or "0").split(":"):
        result = result * 60 + float(part)
    return result


class CaptionMapper:
    def __init__(self, language="auto"):
        self.language = language
        self.previous = {}

    def update(self, snapshot, done=False):
        lines = snapshot.get("lines", [])
        current = {}
        tail = snapshot.get("buffer_transcription", "").strip()
        for index, line in enumerate(lines, 1):
            text = (line.get("text") or "").strip()
            if not text:
                continue
            final = done or index < len(lines) or line.get("closed", False)
            current[index] = Caption(index, seconds(line["start"]), seconds(line["end"]), text,
                                     line.get("detected_language") or self.language, final=final)
        if tail and not done:
            last = current.get(len(lines))
            if last and not last.final:
                current[last.id] = replace(last, source=last.source + " " + tail, stable_source=last.source)
            else:
                index = len(lines) + 1
                start = seconds(lines[-1]["end"]) if lines else 0.0
                current[index] = Caption(index, start, start, tail, self.language, final=False)
        events = []
        for index, caption in current.items():
            old = self.previous.get(index)
            if old and old.final:
                continue
            if old and (old.source, old.final, old.end) == (caption.source, caption.final, caption.end):
                continue
            caption.revision = old.revision + 1 if old else 1
            self.previous[index] = caption
            events.append(caption)
        for index, old in list(self.previous.items()):
            if index not in current and not old.final:
                events.append(replace(old, source="", revision=old.revision + 1, final=True))
                del self.previous[index]
        return events
