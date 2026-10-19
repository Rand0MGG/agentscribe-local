"""Display-only ASR revisions; semantic captions remain the source of truth."""
from .core import Caption
from .wlk_captions import _common_prefix_end, source_snapshot


def preview_captions(captions, event):
    """Freeze latest source as a recoverable draft, without changing live IDs."""
    if event is None:
        return list(captions.values())
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
            end=spans[-1][3] if spans else start_time, language=self.language)

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
