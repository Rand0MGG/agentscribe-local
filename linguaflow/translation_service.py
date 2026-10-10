"""Revision-aware translation consumption, independent of ASR, Qt and model libraries.

The publisher must recheck the revision while holding its caption-state lock.
The consumer checks before expensive work; neither check alone is sufficient.
"""
import asyncio
import time
from collections import OrderedDict
from dataclasses import replace
from threading import Lock

from .core import source_is_final
from .translation_queue import translation_is_current


def matches_source(current, caption):
    return bool(current and current.source == caption.source and current.language == caption.language
                and current.segmentation_revision == caption.segmentation_revision
                and (caption.translation_phase != 'final' or source_is_final(current)))


async def publish_translation_result(caption, current_caption, lock, publish,
                                     expected_context=None, current_context=None, planner=None):
    """Apply only translation fields to the current revision, atomically."""
    async with lock:
        current = current_caption(caption.id)
        valid = (matches_source(current, caption) and planner.accepts(caption)
                 if planner else translation_is_current(current, caption))
        if (valid
                and (current_context is None or current_context(caption.id) == expected_context)):
            publish(replace(current, translation=caption.translation or current.translation, error=caption.error,
                            translation_phase=(caption.translation_phase if caption.translation else current.translation_phase),
                            translation_source=(caption.translation_source if caption.translation else current.translation_source)))


async def publish_translation_batch(captions, contexts, current_caption, lock, publish, planner):
    """Publish a shared-context response atomically, or reject the entire block."""
    async with lock:
        current = [current_caption(c.id) for c in captions]
        if any(not matches_source(row, caption) or not planner.accepts(caption)
               or planner.get(caption.id) != context
               for row, caption, context in zip(current, captions, contexts, strict=True)):
            return False
        for row, caption in zip(current, captions, strict=True):
            publish(replace(row, translation=caption.translation or row.translation, error=caption.error,
                            translation_phase=caption.translation_phase if caption.translation else row.translation_phase,
                            translation_source=caption.translation_source if caption.translation else row.translation_source))
        return True


async def run_translations(queue, create_translator, current_caption, publish, status, metrics,
                           context_for=None, planner=None, publish_batch=None):
    lock, closing, translator = Lock(), False, None

    def create_owned():
        nonlocal translator
        value = create_translator()
        with lock:
            if not closing:
                translator = value
                return value
        close = getattr(value, 'close', None)
        if close:
            close()
        raise RuntimeError('翻译会话已取消')

    try:
        await _consume_translations(queue, create_owned, current_caption, publish, status, metrics,
                                    context_for, planner, publish_batch)
    finally:
        with lock:
            closing = True
            close = getattr(translator, 'close', None)
        if close:
            await asyncio.to_thread(close)


async def _consume_translations(queue, create_translator, current_caption, publish, status, metrics,
                                context_for=None, planner=None, publish_batch=None):
    cache = OrderedDict()
    translator, load_error = None, None
    try:
        await queue.wait_source_ready()
        translator = await asyncio.to_thread(create_translator)
    except Exception as exc:
        load_error = str(exc)
        status('翻译加载失败，原文继续：' + load_error)
    while True:
        item = await queue.get()
        batch = [item]
        try:
            if item is None:
                return
            # Let active/queued ASR and active SaT work finish before a HY request.
            # In-flight inference is not interrupted; its result is rechecked.
            await queue.wait_source_ready()
            caption, queued_at = item
            if not (planner.accepts(caption) if planner else translation_is_current(current_caption(caption.id), caption)):
                continue
            if (planner and context_for and publish_batch
                    and callable(getattr(translator, 'translate_batch', None))):
                batch = queue.take_batch(item, lambda left, right: planner.accepts(right) and planner.adjacent(left, right))
            captions = [entry[0] for entry in batch]
            started = time.monotonic()
            contexts = [context_for(c.id) if context_for else None for c in captions]
            context = planner.shared_context(captions) if len(batch) > 1 else contexts[0]
            try:
                if load_error:
                    raise RuntimeError(load_error)
                key = (('batch', tuple((c.source, c.language, c.segmentation_revision) for c in captions), context)
                       if len(batch) > 1 else (caption.source, caption.language, caption.segmentation_revision, context))
                if key in cache:
                    texts = cache[key]
                    cache.move_to_end(key)
                else:
                    if len(batch) > 1:
                        outputs = await asyncio.to_thread(translator.translate_batch, captions, context)
                        if set(outputs) != {c.id for c in captions}:
                            raise ValueError('合并翻译返回的字幕 ID 不完整；已保留原文和已有译文。')
                        texts = tuple(outputs[c.id] for c in captions)
                    else:
                        args = (caption.source, caption.language, context) if context_for else (caption.source, caption.language)
                        texts = (await asyncio.to_thread(translator.translate, *args),)
                    if any(not isinstance(text, str) or not text.strip() for text in texts):
                        raise ValueError('翻译模型返回空译文')
                    cache[key] = texts
                    if len(cache) > 512:
                        cache.popitem(last=False)
                results = [replace(c, translation=text.strip(), error='') for c, text in zip(captions, texts, strict=True)]
            except Exception as exc:
                results = [replace(c, error=str(exc)) for c in captions]
            if len(batch) > 1:
                published = await publish_batch(results, contexts)
                if published is False:
                    # A neighbour changed during this shared inference. Still-current
                    # members need fresh work too; errors themselves are never retried.
                    for c in captions:
                        if planner.accepts(c):
                            queue.put_nowait(c)
            elif context_for:
                await publish(results[0], context)
            else:
                await publish(results[0])
            metrics({'pending': queue.qsize(), 'wait_seconds': started - queued_at,
                     'compute_seconds': time.monotonic() - started, 'error': results[0].error,
                     'caption_id': caption.id, 'phase': caption.translation_phase,
                     'batch_size': len(batch), 'caption_ids': [c.id for c in captions]})
        finally:
            # Also release unfinished work on publish failure or cancellation.
            for _ in batch:
                queue.task_done()
