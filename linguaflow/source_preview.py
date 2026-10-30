"""Display-only ASR revisions; semantic captions remain the source of truth."""
from bisect import bisect_left
from dataclasses import replace
from difflib import SequenceMatcher

from .core import Caption
from .wlk_captions import _common_prefix_end, source_snapshot


def preview_captions(captions, event):
    """Freeze latest source as a recoverable draft, without changing live IDs."""
    if event is None:
        return list(captions.values())
    if 'rows' in event:
        retained = [captions[key] for key in event['keep_ids'] if key in captions]
        next_id = max(captions, default=0) + 1
        for row in event['rows']:
            if not row['source']:
                continue
            old = captions.get(row['id'])
            if old and old.source == row['source']:
                retained.append(old)
                continue
            identifier = row['id'] if row['id'] is not None else next_id
            next_id = max(next_id, identifier + 1)
            old = old or Caption(identifier, row['start'], row['end'], '', event['language'])
            retained.append(replace(old, source=row['source'], start=row['start'], end=row['end'],
                final=False, asr_final=False, boundary_final=False, stable_source='',
                revision=old.revision+1, translation_source=old.translation_source or old.source,
                translation_phase='initial', error='实时原文草稿，尚未完成分句，请对照录音。'))
        return retained
    keep = set(event['keep_ids'])
    retained = [c for key, c in captions.items() if key in keep]
    replaced = [c for key, c in captions.items() if key not in keep]
    if event['source']:
        identifier = min((c.id for c in replaced), default=max(captions, default=0)+1)
        retained.append(Caption(identifier, event['start'], event['end'], event['source'], event['language'],
            translation='\n'.join(c.translation for c in replaced if c.translation),
            translation_source=' '.join(c.translation_source or c.source for c in replaced if c.translation),
            translation_phase='initial',
            final=False, revision=max((c.revision for c in replaced), default=0)+1,
            error='实时原文草稿，尚未完成分句，请对照录音。'))
    return retained


class SourcePreview:
    def __init__(self, language):
        self.language = language
        self.sequence = 0
        self.latest_text = ''
        self.mapped_text = ''
        self.rows = ()
        self.latest_snapshot = {}

    def _project(self, text, spans, offset):
        """Move existing display cuts through edits; never predict new cuts."""
        old = self.mapped_text
        edits = []

        def changed(a, b, c, d):
            # Whole unchanged cards anchor sparse edits in long recordings.
            # Bound an unanchored wholesale rewrite rather than blocking the
            # event loop with a quadratic character diff of the entire history.
            if max(b-a, d-c) > 4096:
                edits.append(('replace', a, b, c, d))
            else:
                edits.extend((tag, i+a, j+a, k+c, m+c) for tag, i, j, k, m in
                             SequenceMatcher(None, old[a:b], text[c:d], autojunk=False).get_opcodes())

        a = b = 0
        for _, start, end in self.rows:
            found = text.find(old[start:end], b)
            if found >= 0:
                changed(a, start, b, found)
                edits.append(('equal', start, end, found, found + end-start))
                a, b = end, found + end-start
        changed(a, len(old), b, len(text))

        def mapped(pos):
            for tag, a, b, c, d in edits:
                if a <= pos <= b:
                    # A replacement crossing a display cut stays together in
                    # its first affected slot until SaT supplies actual cuts.
                    return c + pos - a if tag == 'equal' else c if pos == a else d
            return len(text)

        def at(pos):
            index = bisect_left(spans, pos, key=lambda row: row[1])
            if index < len(spans):
                lo, hi, start, end, _ = spans[index]
                return start + max(0, pos-lo) / max(1, hi-lo) * (end-start)
            return spans[-1][3] if spans else 0.

        result = []
        for index, (identifier, start, end) in enumerate(self.rows):
            if end <= offset and index < len(self.rows)-1:
                continue
            lo = mapped(start)
            hi = len(text) if index == len(self.rows)-1 else mapped(end)
            raw = text[lo:hi]
            result.append(dict(id=identifier, index=index, source=raw.strip(),
                               start=at(lo + len(raw)-len(raw.lstrip())),
                               end=at(hi - len(raw)+len(raw.rstrip()))))
        if not self.rows:
            result.append(dict(id=None, index=0, source=text.strip(), start=at(0), end=at(len(text))))
        return result

    def begin(self, snapshot, *, force=False):
        text, spans, stable = source_snapshot(snapshot, self.language)
        if text == self.latest_text and not force:
            return self.sequence, None
        self.latest_text = text
        self.latest_snapshot = dict(revision_text=text, revision_spans=spans, stable_end=stable)
        self.sequence += 1
        common = _common_prefix_end(self.mapped_text, text)
        keep, offset = [], 0
        for index, (identifier, start, end) in enumerate(self.rows):
            # SaT can reopen the last sentence when continuation arrives.
            if end > common or index == len(self.rows)-1:
                offset = start
                break
            keep.append(identifier)
            offset = end
        start_time = next((a for lo, hi, a, _b, _lang in spans if hi > offset), 0.)
        return self.sequence, dict(sequence=self.sequence, keep_ids=keep,
            source=text[offset:].strip(), start=start_time,
            end=spans[-1][3] if spans else start_time, language=self.language,
            rows=self._project(text, spans, offset))

    def complete(self, mapper, sequence=None):
        # Called on the event-loop thread only after mapper.update has returned.
        # A preview never reads mutable mapper state while SaT is running.
        self.mapped_text = mapper.last_text
        self.rows = tuple((identifier, start, end) for identifier, (start, end)
                          in sorted(mapper.ranges.items(), key=lambda item: item[1][0])
                          if identifier in mapper.previous and mapper.previous[identifier].source)
        if sequence is not None and sequence != self.sequence:
            # An older segmentation can change IDs or a formerly unchanged
            # prefix. Rebase the newest preview before publishing those rows.
            return self.begin(self.latest_snapshot, force=True)[1]
        return None
