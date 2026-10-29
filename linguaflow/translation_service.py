"""Revision-aware translation consumption, independent of ASR, Qt and model libraries.

The publisher must recheck the revision while holding its caption-state lock.
The consumer checks before expensive work; neither check alone is sufficient.
"""
import asyncio
import time
from collections import OrderedDict
from dataclasses import replace
from threading import Lock

from . import diagnostic_log as diag
from .core import source_is_final
from .translation_queue import trace_item, translation_is_current


def matches_source(current, caption):
    return bool(current and current.source == caption.source and current.language == caption.language
                and current.segmentation_revision == caption.segmentation_revision
                and (caption.translation_phase != 'final' or source_is_final(current)))


def _publication(caption, current, outcome, reason=None):
    diag.event('translation_publication', caption_id=caption.id,
               caption_revision=caption.revision, segmentation_revision=caption.segmentation_revision,
               phase=caption.translation_phase, current_revision=current.revision if current else None,
               outcome=outcome, reason=reason, translated_chars=len(caption.translation),
               failed=bool(caption.error))


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
            _publication(caption, current, 'applied')
        else:
            _publication(caption, current, 'rejected',
                         'source_or_request_changed' if not valid else 'context_changed')


async def publish_translation_batch(captions, contexts, current_caption, lock, publish, planner):
    """Publish a shared-context response atomically, or reject the entire block."""
    async with lock:
        current = [current_caption(c.id) for c in captions]
        if any(not matches_source(row, caption) or not planner.accepts(caption)
               or planner.get(caption.id) != context
               for row, caption, context in zip(current, captions, contexts, strict=True)):
            for row, caption, context in zip(current, captions, contexts, strict=True):
                reason = ('source_changed' if not matches_source(row, caption) else
                          'request_changed' if not planner.accepts(caption) else
                          'context_changed' if planner.get(caption.id) != context else 'batch_peer_changed')
                _publication(caption, row, 'rejected', reason)
            return False
        for row, caption in zip(current, captions, strict=True):
            publish(replace(row, translation=caption.translation or row.translation, error=caption.error,
                            translation_phase=caption.translation_phase if caption.translation else row.translation_phase,
                            translation_source=caption.translation_source if caption.translation else row.translation_source))
            _publication(caption, row, 'applied')
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
        for item in queue.pending.values():
            trace_item('translation_task_end', item, outcome='consumer_closed_before_start')
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
        translator = await asyncio.to_thread(create_translator)
    except Exception as exc:
        from .diagnostic_log import exception
        exception('translation_load_exception', exc)
        load_error = str(exc)
        status('翻译加载失败，原文继续：' + load_error)
    while True:
        item = await queue.get()
        batch = [item]
        try:
            if item is None:
                return
            dequeued = time.monotonic()
            trace_item('translation_dequeued', item, wait_seconds=dequeued - item[1])
            # Finish active SaT work before starting another HY request.
            # In-flight inference is not interrupted; its result is rechecked.
            await queue.source_ready.wait()
            gate_done = time.monotonic()
            caption, queued_at = item
            if not (planner.accepts(caption) if planner else translation_is_current(current_caption(caption.id), caption)):
                trace_item('translation_task_end', item, outcome='stale_before_inference',
                           source_gate_seconds=gate_done - dequeued)
                continue
            if (planner and context_for and publish_batch
                    and callable(getattr(translator, 'translate_batch', None))):
                batch = queue.take_batch(item, lambda left, right: planner.accepts(right) and planner.adjacent(left, right))
            captions = [entry[0] for entry in batch]
            batch_id = diag.trace_id()
            started = time.monotonic()
            contexts = [context_for(c.id) if context_for else None for c in captions]
            context = planner.shared_context(captions) if len(batch) > 1 else contexts[0]
            members = [dict(getattr(entry, 'trace', {})) for entry in batch]
            diag.event('translation_batch_start', translation_batch_id=batch_id, batch_size=len(batch),
                       members=[dict(member, wait_seconds=started - entry[1])
                                for member, entry in zip(members, batch, strict=True)],
                       context_before=len(context.before) if context else 0,
                       context_after=len(context.after) if context else 0,
                       source_gate_seconds=gate_done - dequeued)
            cache_hit = False
            try:
                if load_error:
                    raise RuntimeError(load_error)
                key = (('batch', tuple((c.source, c.language, c.segmentation_revision) for c in captions), context)
                       if len(batch) > 1 else (caption.source, caption.language, caption.segmentation_revision, context))
                if key in cache:
                    cache_hit = True
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
                from .diagnostic_log import exception
                with diag.trace_scope(translation_batch_id=batch_id):
                    exception('translation_exception', exc)
                results = [replace(c, error=str(exc)) for c in captions]
            diag.event('translation_batch_compute_end', translation_batch_id=batch_id, cache_hit=cache_hit,
                       compute_seconds=time.monotonic() - started,
                       members=[dict(member, translated_chars=len(result.translation), failed=bool(result.error))
                                for member, result in zip(members, results, strict=True)])
            if len(batch) > 1:
                with diag.trace_scope(translation_batch_id=batch_id):
                    published = await publish_batch(results, contexts)
                if published is False:
                    # A neighbour changed during this shared inference. Still-current
                    # members need fresh work too; errors themselves are never retried.
                    for c in captions:
                        if planner.accepts(c):
                            original = next(entry for entry in batch if entry[0].id == c.id)
                            with diag.trace_scope(**{**getattr(original, 'trace', {}),
                                                      'retry_of': getattr(original, 'trace', {}).get('translation_task_id')}):
                                queue.put_nowait(c)
            elif context_for:
                with diag.trace_scope(**{**getattr(item, 'trace', {}), 'translation_batch_id': batch_id}):
                    await publish(results[0], context)
            else:
                with diag.trace_scope(**{**getattr(item, 'trace', {}), 'translation_batch_id': batch_id}):
                    await publish(results[0])
            metrics({'pending': queue.qsize(), 'wait_seconds': started - queued_at,
                     'compute_seconds': time.monotonic() - started, 'error': results[0].error,
                     'caption_id': caption.id, 'phase': caption.translation_phase,
                     'batch_size': len(batch), 'caption_ids': [c.id for c in captions]})
            diag.event('translation_batch_end', translation_batch_id=batch_id,
                       outcome='publication_returned', members=members)
        except asyncio.CancelledError:
            for entry in batch:
                trace_item('translation_task_end', entry, outcome='cancelled',
                           inference_may_still_run=True)
            raise
        except BaseException as exc:
            for entry in batch:
                trace_item('translation_task_end', entry, outcome='failed', error_type=type(exc).__name__)
            raise
        finally:
            # Also release unfinished work on publish failure or cancellation.
            for _ in batch:
                queue.task_done()
