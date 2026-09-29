"""First submission and final translation snapshots; no ASR/model dependencies."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TranslationContext:
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


class ContextPlanner:
    """Freeze the first request; capture context once when the source finalizes."""

    def __init__(self, before=3, after=1):
        self.before = max(0, min(6, int(before)))
        self.after = max(0, min(2, int(after)))
        self.contexts = {}
        self.requests = {}

    def update(self, captions):
        rows = sorted((c for c in captions if c.source), key=lambda c: (c.start, c.id))
        ids = {c.id for c in rows}
        for cid in self.requests.keys() - ids:
            self.requests.pop(cid)
            self.contexts.pop(cid, None)
        stable = [c for c in rows if c.final or c.stable_source == c.source]
        changed = []
        for caption in rows:
            old = self.requests.get(caption.id)
            if old and old.final and not caption.final:
                # An explicit ASR correction reopens the finalization cycle.
                self.requests.pop(caption.id)
                self.contexts.pop(caption.id, None)
                old = None
            if not caption.final and (old or not caption.ready):
                continue
            if (old and old.final and caption.final
                    and (old.source, old.language) == (caption.source, caption.language)):
                continue
            context = TranslationContext()
            if caption.final:
                position = (caption.start, caption.id)
                before = [c for c in stable if (c.start, c.id) < position]
                after = [c for c in stable if (c.start, c.id) > position]
                context = TranslationContext(
                    tuple(c.source[-600:] for c in before[-self.before:]) if self.before else (),
                    tuple(c.source[:600] for c in after[:self.after]))
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
