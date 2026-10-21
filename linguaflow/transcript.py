"""Mutable caption rows with a lazily rebuilt ID order, independent of Qt."""
from collections.abc import MutableMapping


class Transcript(MutableMapping):
    def __init__(self, rows=()):
        self._rows = dict(rows)
        self._ordered = None

    def __getitem__(self, identifier):
        return self._rows[identifier]

    def __setitem__(self, identifier, caption):
        if identifier not in self._rows:
            self._ordered = None
        self._rows[identifier] = caption

    def __delitem__(self, identifier):
        del self._rows[identifier]
        self._ordered = None

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def clear(self):
        self._rows.clear()
        self._ordered = ()

    @property
    def ordered_ids(self):
        if self._ordered is None:
            self._ordered = tuple(sorted(self._rows))
        return self._ordered
