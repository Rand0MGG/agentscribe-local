"""One pending translation per caption; newer revisions replace queued work."""
import asyncio
import time

_EMPTY = object()


def translation_is_current(current, requested):
    return bool(current is not None and current.revision == requested.revision
                and current.language == requested.language
                and current.source == requested.source and current.source
                and (current.ready or current.final))


class TranslationQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.pending = {}
        self.deferred = _EMPTY

    def put_nowait(self, caption):
        if caption is None:
            self.queue.put_nowait(None)
            return
        fresh = caption.id not in self.pending
        self.pending[caption.id] = (caption, time.monotonic())
        if fresh:
            self.queue.put_nowait(caption.id)

    async def get(self):
        if self.deferred is _EMPTY:
            cid = await self.queue.get()
        else:
            cid, self.deferred = self.deferred, _EMPTY
        return self.pending.pop(cid) if cid is not None else None

    def take_batch(self, first, can_join, max_rows=4, max_chars=1200):
        """Take already queued adjacent work; never wait to fill a batch.

        A nonmatching head remains pending (and can still be superseded). Its
        original unfinished-task count is released only when get() consumes it.
        """
        batch, count = [first], len(first[0].source)
        while len(batch) < max_rows and not self.queue.empty():
            cid = self.queue.get_nowait()
            item = self.pending.get(cid) if cid is not None else None
            if item is None or count + len(item[0].source) > max_chars or not can_join(batch[-1][0], item[0]):
                self.deferred = cid
                break
            batch.append(self.pending.pop(cid))
            count += len(item[0].source)
        return batch

    def task_done(self):
        self.queue.task_done()

    def qsize(self):
        return self.queue.qsize() + (self.deferred is not _EMPTY)

    async def join(self):
        await self.queue.join()
