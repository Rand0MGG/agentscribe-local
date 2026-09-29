"""Revision-aware translation consumption, independent of ASR, Qt and model libraries.

The publisher must recheck the revision while holding its caption-state lock.
The consumer checks before expensive work; neither check alone is sufficient.
"""
import asyncio
import time
from collections import OrderedDict
from dataclasses import replace

from .translation_queue import translation_is_current


async def publish_translation_result(caption, current_caption, lock, publish,
                                     expected_context=None, current_context=None, planner=None):
    """Apply only translation fields to the current revision, atomically."""
    async with lock:
        current = current_caption(caption.id)
        valid = (bool(current and current.source) and planner.accepts(caption)
                 if planner else translation_is_current(current, caption))
        if (valid
                and (current_context is None or current_context(caption.id) == expected_context)):
            publish(replace(current, translation=caption.translation or current.translation, error=caption.error,
                            translation_phase=(caption.translation_phase if caption.translation else current.translation_phase),
                            translation_source=(caption.translation_source if caption.translation else current.translation_source)))


async def run_translations(queue, create_translator, current_caption, publish, status, metrics,
                           context_for=None, planner=None):
    cache = OrderedDict()
    translator, load_error = None, None
    try:
        translator = await asyncio.to_thread(create_translator)
    except Exception as exc:
        load_error = str(exc)
        status('翻译加载失败，原文继续：' + load_error)
    while True:
        item = await queue.get()
        try:
            if item is None:
                return
            caption, queued_at = item
            if not (planner.accepts(caption) if planner else translation_is_current(current_caption(caption.id), caption)):
                continue
            started = time.monotonic()
            context = context_for(caption.id) if context_for else None
            try:
                if load_error:
                    raise RuntimeError(load_error)
                key = (caption.source, caption.language, context)
                if key in cache:
                    text = cache[key]
                    cache.move_to_end(key)
                else:
                    args = (caption.source, caption.language, context) if context_for else (caption.source, caption.language)
                    text = await asyncio.to_thread(translator.translate, *args)
                    if not text or not text.strip():
                        raise ValueError('翻译模型返回空译文')
                    cache[key] = text
                    if len(cache) > 512:
                        cache.popitem(last=False)
                result = replace(caption, translation=text, error='')
            except Exception as exc:
                result = replace(caption, error=str(exc))
            if context_for:
                await publish(result, context)
            else:
                await publish(result)
            metrics({'pending': queue.qsize(), 'wait_seconds': started - queued_at,
                     'compute_seconds': time.monotonic() - started, 'error': result.error,
                     'caption_id': caption.id, 'phase': caption.translation_phase})
        finally:
            # Also release unfinished work on publish failure or cancellation.
            queue.task_done()
