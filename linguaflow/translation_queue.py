"""One pending translation per caption; newer revisions replace queued work."""
import asyncio
import time


def translation_is_current(current, requested):
    return bool(current is not None and current.revision == requested.revision
                and current.source == requested.source and current.source
                and (current.ready or current.final))


class TranslationQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.pending = {}

    def put_nowait(self, caption):
        if caption is None:
            self.queue.put_nowait(None)
            return
        fresh = caption.id not in self.pending
        self.pending[caption.id] = (caption, time.monotonic())
        if fresh:
            self.queue.put_nowait(caption.id)

    async def get(self):
        cid = await self.queue.get()
        return self.pending.pop(cid) if cid is not None else None

    def task_done(self):
        self.queue.task_done()

    def qsize(self):
        return self.queue.qsize()

    async def join(self):
        await self.queue.join()
