"""Display-only ASR revisions; semantic captions remain the source of truth."""
from .wlk_captions import _common_prefix_end, source_snapshot


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
