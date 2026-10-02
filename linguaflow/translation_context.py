"""Revision-triggered draft/final translation snapshots; no model dependencies."""
from dataclasses import dataclass, replace

MAX_CONTEXT_BEFORE = 10
MAX_CONTEXT_AFTER = 2
MAX_INITIAL_CONTEXT_BEFORE = 2
MAX_CONTEXT_CHARACTERS = 600


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

    def __init__(self, before=10, after=1, initial_before=1):
        self.before = max(0, min(MAX_CONTEXT_BEFORE, int(before)))
        self.after = max(0, min(MAX_CONTEXT_AFTER, int(after)))
        self.initial_before = max(0, min(MAX_INITIAL_CONTEXT_BEFORE, int(initial_before)))
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
                tuple(c.source[-MAX_CONTEXT_CHARACTERS:] for c in before[-count:]) if count else (),
                tuple(c.source[:MAX_CONTEXT_CHARACTERS] for c in after[:self.after]) if caption.final else ())
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
