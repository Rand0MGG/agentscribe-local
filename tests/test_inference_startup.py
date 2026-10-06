import asyncio
from threading import Event, get_ident

import pytest

from linguaflow.inference_startup import load_components


def test_both_loaders_overlap_and_no_component_is_exposed_early():
    recognition_entered, semantic_entered, release = Event(), Event(), Event()
    main_thread, delivered = get_ident(), []

    def recognition(own):
        assert get_ident() != main_thread
        recognition_entered.set()
        assert semantic_entered.wait(2) and release.wait(2)
        return 'ASR'

    def semantic():
        assert get_ident() != main_thread
        semantic_entered.set()
        assert recognition_entered.wait(2) and release.wait(2)
        return 'SaT'

    async def exercise():
        async def start():
            async with load_components(recognition, semantic) as pair:
                delivered.append(pair)
        task = asyncio.create_task(start())
        try:
            assert await asyncio.to_thread(recognition_entered.wait, 2)
            assert await asyncio.to_thread(semantic_entered.wait, 2)
            assert not delivered and not task.done()
            release.set()
            await asyncio.wait_for(task, 3)
            assert delivered == [('ASR', 'SaT')]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize('failure', ['semantic', 'cancel', 'session'])
def test_failed_or_cancelled_startup_closes_resources_and_joins_loader(failure):
    entered, released, exited = Event(), Event(), Event()
    closed = []

    class Resource:
        def close(self):
            closed.append(True)
            released.set()

    def recognition(own):
        own(Resource())
        entered.set()
        try:
            assert released.wait(3)
            return 'ASR'
        finally:
            exited.set()

    def semantic():
        assert entered.wait(2)
        if failure == 'semantic':
            raise ValueError('SaT failed')
        return 'SaT'

    async def exercise():
        async def start():
            async with load_components(recognition, semantic):
                raise ValueError('Session setup failed')
        task = asyncio.create_task(start())
        assert await asyncio.to_thread(entered.wait, 2)
        if failure == 'cancel':
            task.cancel()
        elif failure == 'session':
            released.set()
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else ValueError):
            await asyncio.wait_for(task, 3)
        assert closed == [True] and exited.is_set()
    asyncio.run(exercise())


def test_cancelled_startup_rejects_and_closes_late_resources():
    entered, released, exited = Event(), Event(), Event()
    closed = []

    class Resource:
        def __init__(self, name):
            self.name = name
        def close(self):
            closed.append(self.name)
            released.set()

    def recognition(own):
        own(Resource('first'))
        entered.set()
        try:
            assert released.wait(3)
            own(Resource('late'))
        finally:
            exited.set()

    async def exercise():
        async def start():
            async with load_components(recognition, lambda: 'SaT'):
                pytest.fail('cancelled startup became ready')
        task = asyncio.create_task(start())
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert closed == ['first', 'late'] and exited.is_set()
    asyncio.run(exercise())
