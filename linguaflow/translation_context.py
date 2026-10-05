"""Revision-triggered draft/final translation snapshots; no model dependencies."""
from bisect import bisect_left, bisect_right, insort
from dataclasses import dataclass, replace

from .core import source_is_final
from .translation_config import (
    DEFAULT_CONTEXT_AFTER,
    DEFAULT_CONTEXT_BEFORE,
    DEFAULT_INITIAL_CONTEXT_BEFORE,
    MAX_CONTEXT_AFTER,
    MAX_CONTEXT_BEFORE,
    MAX_CONTEXT_CHARACTERS,
    MAX_INITIAL_CONTEXT_BEFORE,
    context_count,
)


@dataclass(frozen=True)
class TranslationContext:
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


def validate_translation_context(context):
    """Reject unbounded background before tokenization or model IO.

    The planner normally selects and clips neighbours. Model adapters also
    enforce this limit so an incorrect caller cannot pass the full recording.
    None represents a request without background; invalid input raises ValueError.
    """
    if context is None:
        return
    if not isinstance(context, TranslationContext):
        raise ValueError('翻译背景格式无效；已保留原文和已有译文。')
    if len(context.before) > MAX_CONTEXT_BEFORE or len(context.after) > MAX_CONTEXT_AFTER:
        raise ValueError(f'翻译背景超出范围，最多参考前 {MAX_CONTEXT_BEFORE} 段、后 {MAX_CONTEXT_AFTER} 段；'
                         '请检查上下文设置，已保留原文和已有译文。')
    if any(not isinstance(text, str) or len(text) > MAX_CONTEXT_CHARACTERS
           for text in (*context.before, *context.after)):
        raise ValueError(f'翻译背景每段最多 {MAX_CONTEXT_CHARACTERS} 字符；'
                         '请检查上下文内容，已保留原文和已有译文。')


class ContextPlanner:
    """Schedule submitted source changes; neighbours alone never cause retranslation."""

    def __init__(self, before=DEFAULT_CONTEXT_BEFORE, after=DEFAULT_CONTEXT_AFTER,
                 initial_before=DEFAULT_INITIAL_CONTEXT_BEFORE):
        self.before = context_count(before, DEFAULT_CONTEXT_BEFORE, MAX_CONTEXT_BEFORE)
        self.after = context_count(after, DEFAULT_CONTEXT_AFTER, MAX_CONTEXT_AFTER)
        self.initial_before = context_count(initial_before, DEFAULT_INITIAL_CONTEXT_BEFORE, MAX_INITIAL_CONTEXT_BEFORE)
        self.contexts = {}
        self.requests = {}
        self._rows = {}
        self._keys = []
        self._stable_keys = []

    def update(self, captions):
        """Accept a complete snapshot for existing callers; omitted IDs are removed."""
        rows = {c.id: c for c in captions if c.source}
        for cid in self._rows.keys() - rows.keys():
            self._remove(cid)
        return self.update_changes(c for cid, c in rows.items() if c != self._rows.get(cid))

    def _remove(self, cid):
        old = self._rows.pop(cid, None)
        if old is not None:
            key = (old.start, cid)
            self._keys.pop(bisect_left(self._keys, key))
            if old.final:
                self._stable_keys.pop(bisect_left(self._stable_keys, key))
        self.requests.pop(cid, None)
        self.contexts.pop(cid, None)

    def update_changes(self, captions):
        """Accept mapper deltas, including empty-source removals, in any order.

        Index all changes before freezing request backgrounds. Only changed rows
        are planned; unchanged neighbours never trigger another translation.
        """
        incoming = {c.id: replace(c, final=source_is_final(c)) for c in captions}
        for cid, caption in incoming.items():
            if not caption.source:
                self._remove(cid)
                continue
            old_row = self._rows.get(cid)
            key = (caption.start, cid)
            if old_row is None:
                insort(self._keys, key)
            elif old_row.start != caption.start:
                self._keys.pop(bisect_left(self._keys, (old_row.start, cid)))
                insort(self._keys, key)
            if old_row and old_row.final and (not caption.final or old_row.start != caption.start):
                self._stable_keys.pop(bisect_left(self._stable_keys, (old_row.start, cid)))
            if caption.final and (old_row is None or not old_row.final or old_row.start != caption.start):
                insort(self._stable_keys, key)
            # Caption is mutable; freeze the index's source/position independently.
            self._rows[cid] = replace(caption)
        changed = []
        for caption in sorted((c for c in incoming.values() if c.source), key=lambda c: (c.start, c.id)):
            old = self.requests.get(caption.id)
            if old and old.final and not caption.final:
                # An explicit ASR correction reopens the finalization cycle.
                self.requests.pop(caption.id)
                self.contexts.pop(caption.id, None)
                old = None
            if not caption.final and not (old or caption.ready):
                continue
            if (old and old.final == caption.final
                    and (old.source, old.language, old.segmentation_revision)
                    == (caption.source, caption.language, caption.segmentation_revision)):
                continue
            position = (caption.start, caption.id)
            count = self.before if caption.final else self.initial_before
            index = bisect_left(self._stable_keys, position)
            before = self._stable_keys[max(0, index - count):index]
            index = bisect_right(self._stable_keys, position)
            after = self._stable_keys[index:index + self.after] if caption.final else ()
            context = TranslationContext(
                tuple(self._rows[cid].source[-MAX_CONTEXT_CHARACTERS:] for _start, cid in before),
                tuple(self._rows[cid].source[:MAX_CONTEXT_CHARACTERS] for _start, cid in after))
            request = replace(caption, translation='', error='',
                              translation_phase='final' if caption.final else 'initial',
                              translation_source=caption.source)
            self.requests[caption.id] = request
            self.contexts[caption.id] = context
            changed.append(request)
        return changed

    def accepts(self, request):
        current = self.requests.get(request.id)
        return bool(current and (current.revision, current.source, current.language,
                                 current.translation_phase, current.segmentation_revision)
                    == (request.revision, request.source, request.language,
                        request.translation_phase, request.segmentation_revision)
                    and (request.translation_phase != 'final' or source_is_final(current)))

    def get(self, caption_id):
        return self.contexts.get(caption_id)

    def adjacent(self, left, right):
        if (left.language != right.language or left.translation_phase != right.translation_phase
                or left.id not in self._rows or right.id not in self._rows):
            return False
        index = bisect_left(self._keys, (self._rows[left.id].start, left.id))
        return index + 1 < len(self._keys) and self._keys[index + 1][1] == right.id

    def shared_context(self, captions):
        """One background around the block; internal neighbours are source segments."""
        return TranslationContext(self.get(captions[0].id).before, self.get(captions[-1].id).after)
