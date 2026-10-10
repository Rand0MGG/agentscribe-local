"""One pending translation per caption; newer revisions replace queued work."""
import asyncio
import time

from .core import source_is_final

_EMPTY = object()


def translation_is_current(current, requested):
    return bool(current is not None and current.revision == requested.revision
                and current.language == requested.language
                and current.source == requested.source and current.source
                and current.segmentation_revision == requested.segmentation_revision
                and (current.ready or source_is_final(current))
                and (requested.translation_phase != 'final' or source_is_final(current)))


class TranslationQueue:
    def __init__(self, source_pending=lambda: False):
        self.source_pending = source_pending
        self.queue = asyncio.Queue()
        self.pending = {}
        self.deferred = _EMPTY
        self.stop_pending = False
        self.source_ready = asyncio.Event()
        self.source_ready.set()
        self.source_updates = 0

    def begin_source_update(self):
        self.source_updates += 1
        self.source_ready.clear()

    def end_source_update(self):
        self.source_updates -= 1
        if not self.source_updates:
            self.source_ready.set()

    async def wait_source_ready(self):
        """Admit new translation only after active/queued recognition clears."""
        while True:
            await self.source_ready.wait()
            if not self.source_pending():
                return
            # The upstream audio queue has no drained signal. Never block its loop.
            await asyncio.sleep(.02)

    def put_nowait(self, caption):
        if caption is None:
            self.stop_pending = True
            self.queue.put_nowait(None)
            return
        fresh = caption.id not in self.pending
        self.pending[caption.id] = (caption, time.monotonic())
        if fresh:
            self.queue.put_nowait(caption.id)

    def discard(self, caption_id):
        """Invalidate a removed source span without waiting for HY to consume it."""
        self.pending.pop(caption_id, None)

    async def get(self):
        while True:
            if self.deferred is _EMPTY:
                cid = await self.queue.get()
            else:
                cid, self.deferred = self.deferred, _EMPTY
            if cid is None:
                self.stop_pending = False
                return None
            item = self.pending.pop(cid, None)
            if item is not None:
                return item
            self.queue.task_done()

    def take_batch(self, first, can_join, max_rows=4, max_chars=1200):
        """Take already queued adjacent work; never wait to fill a batch.

        A nonmatching head remains pending (and can still be superseded). Its
        original unfinished-task count is released only when get() consumes it.
        """
        batch, count = [first], len(first[0].source)
        while len(batch) < max_rows and not self.queue.empty():
            cid = self.queue.get_nowait()
            item = self.pending.get(cid) if cid is not None else None
            if cid is not None and item is None:
                self.queue.task_done()
                continue
            if item is None or count + len(item[0].source) > max_chars or not can_join(batch[-1][0], item[0]):
                self.deferred = cid
                break
            batch.append(self.pending.pop(cid))
            count += len(item[0].source)
        return batch

    def task_done(self):
        self.queue.task_done()

    def qsize(self):
        return len(self.pending) + self.stop_pending

    async def join(self):
        await self.queue.join()
