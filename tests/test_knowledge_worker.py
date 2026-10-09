"""Concurrent source/consent changes and cancellation against a held fake API call."""
import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from linguaflow.core import Caption
from linguaflow.knowledge.files import read_json
from linguaflow.knowledge.session import manifest_path
from linguaflow.knowledge.worker import KnowledgeWorker
from linguaflow.library import Library


@pytest.mark.parametrize('operation', ['revision', 'cancel', 'permission', 'move', 'external_edit'])
def test_inflight_cloud_result_obeys_source_consent_and_lifecycle(monkeypatch, tmp_path, operation):
    import linguaflow.knowledge.worker as module
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    caption = Caption(1, 0, 1, 'original evidence', 'en')
    library.save(item, [caption], 'complete')
    events, closed = [], []
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class FakeService:
            def __init__(self, **kwargs):
                self.budget = SimpleNamespace(view=lambda: {'requests': 1, 'tokens_or_reserved': 20, 'uncertain': False})
            async def update_notes(self, job):
                started.set()
                await release.wait()
                return {'upserts': [{'id': 'note', 'section': '课堂讲述', 'text': '说明', 'origin': 'lecture',
                         'refs': [{'id': 'caption:1', 'quote': 'original evidence'}]}], 'delete_note_ids': []}
            async def close(self):
                closed.append(True)
        monkeypatch.setattr(module, 'DeepSeekService', FakeService)
        worker = KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        worker.start_task('notes')
        await started.wait()
        if operation == 'revision':
            await worker.command({'operation': 'caption', 'caption': asdict(replace(caption, source='corrected', revision=2))})
        elif operation == 'cancel':
            await worker.command({'operation': 'cancel'})
        elif operation == 'permission':
            await worker.command({'operation': 'permission', 'materials': False, 'notes': False})
        elif operation == 'move':
            library.move(item, library.folder('移动后')['id'])
        else:
            library.save(item, [replace(caption, source='external correction', revision=2)])
        release.set()
        await worker.task
        assert closed == [True]
        assert not any(event.get('notes') for event in events)
        assert not (library.directory(item['id']) / '课堂笔记.md').exists()
        if operation == 'permission':
            assert not read_json(manifest_path(library, item['id']))['notes_cloud']
    asyncio.run(scenario())


def test_course_unavailable_keeps_notes_editable_and_can_reassociate(tmp_path):
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    course_folder = next(row for row in library.index['folders'] if row['id'] == item['folder'])
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'before'})
        library.move(item, library.folder('其他课程')['id'])
        library.trash(course_folder)
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'after'})
        assert worker.material_error and not worker.automatic
        await worker.command({'operation': 'export'})
        assert (library.directory(item['id']) / '课堂笔记.md').is_file()
        await worker.command({'operation': 'associate', 'folder_id': item['folder']})
        assert not worker.material_error and not worker.manifest['notes_cloud']
    asyncio.run(scenario())


@pytest.mark.parametrize('pipe_encoding', ['utf-8', 'cp1252'])
def test_continuous_caption_messages_do_not_starve_automatic_notes(tmp_path, pipe_encoding):
    import json
    import subprocess
    import sys
    import time
    from queue import Empty, Queue
    from threading import Event, Thread

    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    caption = Caption(1, 0, 1, 'saved evidence', 'en')
    library.save(item, [caption])
    code = '''
import asyncio
import sys
from types import SimpleNamespace
import linguaflow.knowledge.worker as worker
sys.stdin.reconfigure(encoding=sys.argv[1])
sys.stdout.reconfigure(encoding=sys.argv[1])
class FakeService:
    def __init__(self,**kwargs):
        self.budget=SimpleNamespace(view=lambda:{'requests':1,'tokens_or_reserved':20,'uncertain':False})
    async def update_notes(self,job):
        return {'upserts':[{'id':'note','section':'课堂讲述','text':'示例','origin':'lecture',
                'refs':[{'id':'caption:1','quote':'saved evidence'}]}],'delete_note_ids':[]}
    async def close(self): pass
worker.DeepSeekService=FakeService
asyncio.run(worker.serve())
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code, pipe_encoding], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    queue, stop = Queue(), Event()
    def read():
        for line in process.stdout:
            queue.put(json.loads(line))
    def write(value):
        process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
        process.stdin.flush()
    def feed():
        while not stop.is_set():
            try:
                write({'operation': 'caption', 'caption': asdict(caption)})
                write({'operation': 'saved', 'captions': [asdict(caption)]})
            except OSError:
                queue.put({'worker_exited': True})
                return
            stop.wait(.1)
    reader = Thread(target=read, daemon=True)
    feeder = Thread(target=feed, daemon=True)
    reader.start()
    try:
        write({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
               'folder_id': item['folder'], 'epoch': 'stream'})
        write({'operation': 'permission', 'materials': False, 'notes': True})
        feeder.start()
        deadline, published = time.monotonic()+8, False
        while time.monotonic() < deadline:
            try:
                event = queue.get(timeout=.2)
            except Empty:
                continue
            if event.get('worker_exited'):
                break
            if event.get('notes'):
                assert event['notes'][0]['text'] == '示例'
                published = True
                break
        assert published, 'Automatic notes did not run under continuous source events'
    finally:
        stop.set()
        feeder.join(timeout=2)
        process.terminate()
        process.wait(timeout=3)
        reader.join(timeout=2)
        # A failed child leaves a pending stdin buffer; its flush must not mask the assertion.
        try:
            process.stdin.close()
        except OSError:
            pass
        process.stdout.close()
        process.stderr.close()


def test_material_corruption_before_task_starts_prevents_any_model_request(monkeypatch, tmp_path):
    from test_knowledge import pptx
    from test_knowledge_visual import fake_pages, reading

    import linguaflow.knowledge.worker as module
    from linguaflow.knowledge.materials import course_for_folder, import_material, read_blocks
    from linguaflow.knowledge.readings import save_reading
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    library.save(item, [Caption(1, 0, 1, 'gradient descent', 'en')])
    path = tmp_path / 'slides.pptx'
    pptx(path)
    document = import_material(library, item['folder'], path)
    course_path, course = course_for_folder(library, item['folder'])
    native = read_blocks(library, course_path, course)
    images = fake_pages(library, course_path, document, len(native))['images']
    for block, image in zip(native, images):
        save_reading(library, course_path, block, image['sha256'], reading(block))
    calls = []
    monkeypatch.setattr(module, 'DeepSeekService', lambda **kwargs: calls.append('dispatch'))
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        worker.start_task('notes')
        original = worker.course_path.parent / 'materials' / document['id'] / 'original.pptx'
        original.write_bytes(b'changed before request')
        await worker.task
        assert not calls and worker.material_error and worker.last_error
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['notes', 'organize', 'question', 'extract'])
def test_permission_revoked_before_dispatch_prevents_service_creation(monkeypatch, tmp_path, operation):
    import linguaflow.knowledge.worker as module
    from linguaflow.knowledge.files import write_json
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    library.save(item, [Caption(1, 0, 1, 'private lecture', 'en')])
    calls = []
    monkeypatch.setattr(module, 'DeepSeekService', lambda **kwargs: calls.append('dispatch'))
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        await worker.command({'operation': 'permission', 'materials': True, 'notes': True})
        worker.start_task(operation, 'What was said?' if operation == 'question' else '')
        path = worker.course_path if operation == 'extract' else manifest_path(library, item['id'])
        value = read_json(path)
        value['material_cloud' if operation == 'extract' else 'notes_cloud'] = False
        write_json(library.root, path, value)
        await worker.task
        assert not calls and worker.last_error
        assert not worker.store.view()['notes']
    asyncio.run(scenario())


@pytest.mark.parametrize('revoke', [False, True])
def test_post_class_organize_batches_all_long_notes_with_one_shared_budget(monkeypatch, tmp_path, revoke):
    pytest.importorskip('deepagents')
    from langchain_core.messages import AIMessage
    from test_knowledge import long_notes
    from test_knowledge_api import ScriptedModel

    import linguaflow.knowledge.worker as module
    from linguaflow.knowledge.api import DeepSeekService
    from linguaflow.knowledge.storage import KnowledgeStore
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    store = KnowledgeStore(library.root, library.directory(item['id']), item['id'])
    first = long_notes(store)
    new = Caption(2, 2, 3, 'gradient descent was corrected', 'en')
    library.save(item, [first, new])
    model = ScriptedModel(responses=[AIMessage(content='', tool_calls=[{'name': 'NotePatch', 'id': f'batch-{batch}',
        'args': {'upserts': [{'id': f'long-{index}', 'section': '课堂讲述', 'text': f'已核对 {index}', 'origin': 'lecture',
                             'refs': [{'id': 'caption:2', 'quote': new.source}]} for index in range(batch*2, batch*2+2)],
                 'delete_note_ids': []}}]) for batch in range(3)])
    services, events = [], []
    def notify(value):
        events.append(value)
        if revoke and value.get('type') == 'view' and any(row['text'].startswith('已核对') for row in value['notes']):
            from linguaflow.knowledge.files import write_json
            path = manifest_path(library, item['id'])
            manifest = read_json(path)
            manifest['notes_cloud'] = False
            write_json(library.root, path, manifest)
    def service(**kwargs):
        result = DeepSeekService(model=model, **kwargs)
        services.append(result)
        return result
    monkeypatch.setattr(module, 'DeepSeekService', service)
    async def scenario():
        worker = KnowledgeWorker(notify)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        worker.start_task('organize', section='课堂讲述')
        await worker.task
        assert worker.last_error is revoke, events
        assert len(services) == 1 and services[0].budget.calls == (1 if revoke else 3)
        notes = worker.store.view()['notes']
        updated = {row['text'] for row in notes if row['text'].startswith('已核对')}
        assert updated == {f'已核对 {index}' for index in range(2 if revoke else 6)}
        if revoke:
            assert all(row['pending_sources'].get('caption:2') for row in notes if row['status'] != 'valid')
        else:
            assert all(row['status'] == 'valid' for row in notes)
    asyncio.run(scenario())
