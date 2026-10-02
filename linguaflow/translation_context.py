"""Revision-triggered draft/final translation snapshots; no model dependencies."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TranslationContext:
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


class ContextPlanner:
    """Schedule submitted source changes; neighbours alone never cause retranslation."""

    def __init__(self, before=10, after=1, initial_before=1):
        self.before = max(0, min(10, int(before)))
        self.after = max(0, min(2, int(after)))
        self.initial_before = max(0, min(2, int(initial_before)))
        self.contexts = {}
        self.requests = {}
        self.positions = {}

    def update(self, captions):
        rows = sorted((c for c in captions if c.source), key=lambda c: (c.start, c.id))
        self.positions = {c.id: i for i, c in enumerate(rows)}
        ids = {c.id for c in rows}
        for cid in self.requests.keys() - ids:
            self.requests.pop(cid)
            self.contexts.pop(cid, None)
        stable = [c for c in rows if c.final]
        changed = []
        for caption in rows:
            old = self.requests.get(caption.id)
            if old and old.final and not caption.final:
                # An explicit ASR correction reopens the finalization cycle.
                self.requests.pop(caption.id)
                self.contexts.pop(caption.id, None)
                old = None
            if not caption.final and not (old or caption.ready):
                continue
            if (old and old.final == caption.final
                    and (old.source, old.language) == (caption.source, caption.language)):
                continue
            position = (caption.start, caption.id)
            before = [c for c in stable if (c.start, c.id) < position]
            after = [c for c in stable if (c.start, c.id) > position]
            count = self.before if caption.final else self.initial_before
            context = TranslationContext(
                tuple(c.source[-600:] for c in before[-count:]) if count else (),
                tuple(c.source[:600] for c in after[:self.after]) if caption.final else ())
            request = replace(caption, translation='', error='',
                              translation_phase='final' if caption.final else 'initial',
                              translation_source=caption.source)
            self.requests[caption.id] = request
            self.contexts[caption.id] = context
            changed.append(request)
        return changed

    def accepts(self, request):
        current = self.requests.get(request.id)
        return bool(current and (current.revision, current.source, current.language, current.translation_phase)
                    == (request.revision, request.source, request.language, request.translation_phase))

    def get(self, caption_id):
        return self.contexts.get(caption_id)

    def adjacent(self, left, right):
        return (left.language == right.language and left.translation_phase == right.translation_phase
                and left.id in self.positions and right.id in self.positions
                and self.positions[right.id] == self.positions[left.id] + 1)

    def shared_context(self, captions):
        """One background around the block; internal neighbours are source segments."""
        return TranslationContext(self.get(captions[0].id).before, self.get(captions[-1].id).after)
