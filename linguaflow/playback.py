"""Segment lookup for existing recording timestamps; no additional ASR model."""
from bisect import bisect_right


class PlaybackIndex:
    def __init__(self, captions=()):
        self.segments = sorted((c.start, c.end, c.id) for c in captions if c.source and c.end > c.start)
        self.starts = [start for start, _, _ in self.segments]

    def at(self, seconds):
        index = bisect_right(self.starts, seconds)-1
        if index < 0:
            return None
        start, end, identifier = self.segments[index]
        return identifier if start <= seconds < end else None
