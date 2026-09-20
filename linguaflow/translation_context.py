"""Bounded source context and revision scheduling; no model or UI dependencies."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationContext:
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


class ContextPlanner:
    """Translate immediately, then refresh only captions whose context changed.

    Only ready/final neighbours participate, avoiding every partial ASR token
    triggering another inference. Context contains source text, never old translations.
    """

    def __init__(self, before=3, after=1):
        self.before = max(0, min(6, int(before)))
        self.after = max(0, min(2, int(after)))
        self.contexts = {}
        self.signatures = {}

    def update(self, captions):
        rows = sorted((c for c in captions if c.source and (c.ready or c.final)),
                      key=lambda c: (c.start, c.id))
        contexts, signatures, changed = {}, {}, []
        for i, caption in enumerate(rows):
            context = TranslationContext(
                tuple(c.source[-600:] for c in rows[max(0, i-self.before):i]),
                tuple(c.source[:600] for c in rows[i+1:i+1+self.after]))
            signature = (caption.source, caption.language, caption.revision, context)
            contexts[caption.id] = context
            signatures[caption.id] = signature
            if self.signatures.get(caption.id) != signature:
                changed.append(caption)
        self.contexts, self.signatures = contexts, signatures
        return changed

    def get(self, caption_id):
        return self.contexts.get(caption_id)
