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


@pytest.mark.p0
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


@pytest.mark.p2
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


@pytest.mark.p2
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


@pytest.mark.p0
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


@pytest.mark.p0
@pytest.mark.parametrize('change', ['live', 'saved', 'unrelated'])
def test_every_model_turn_revalidates_frozen_sources(monkeypatch, tmp_path, change):
    import linguaflow.knowledge.worker as module
    library = Library(tmp_path / 'library')
    item = library.create('inbox', {}, '录音')
    caption = Caption(1, 0, 1, 'original evidence', 'en')
    library.save(item, [caption], 'complete')
    calls, events = [], []

    class FakeService:
        def __init__(self, **kwargs):
            self.before_request = kwargs['before_request']
            self.budget = SimpleNamespace(view=lambda: {})

        async def update_notes(self, job):
            self.before_request()
            calls.append('first')
            if change == 'live':
                await worker.command({'operation': 'caption', 'caption': asdict(replace(caption, source='new evidence', revision=2))})
            elif change == 'saved':
                library.save(item, [replace(caption, source='externally changed', revision=2)])
            else:
                from linguaflow.knowledge.files import write_json
                course = read_json(worker.course_path)
                course['terms'].append({'canonical': 'Unrelated term', 'aliases': [], 'approved': False,
                                        'origin': 'manual', 'evidence_ids': []})
                write_json(library.root, worker.course_path, course)
            self.before_request()
            calls.append('second')
            return {'upserts': [{'id': 'note', 'section': '课堂讲述', 'text': '说明', 'origin': 'lecture',
                     'refs': [{'id': 'caption:1', 'quote': 'original evidence'}]}], 'delete_note_ids': []}

        async def close(self):
            calls.append('closed')

    monkeypatch.setattr(module, 'DeepSeekService', FakeService)
    worker = KnowledgeWorker(events.append)

    async def scenario():
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        worker.start_task('notes')
        await worker.task
        if change == 'unrelated':
            assert calls == ['first', 'second', 'closed'] and worker.store.view()['notes']
        else:
            assert calls == ['first', 'closed'] and not worker.store.view()['notes']
            assert worker.last_error
    asyncio.run(scenario())


@pytest.mark.p0
@pytest.mark.parametrize('action', ['cancel', 'failure'])
def test_local_preview_failure_or_cancel_preserves_original_and_old_pages(monkeypatch, tmp_path, action):
    from test_knowledge_visual import fake_pages, setup_course

    import linguaflow.knowledge.worker as module
    from linguaflow.knowledge.files import material_cache
    from linguaflow.knowledge.rendering import page_images
    library, item, document = setup_course(tmp_path)
    events = []

    async def scenario():
        worker = KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'preview'})
        before = fake_pages(library, worker.course_path, document, 3)
        course_before = worker.course_path.read_bytes()
        original = worker.course_path.parent / 'materials' / document['id'] / 'original.pptx'
        original_before = original.read_bytes()
        entered, release = asyncio.Event(), asyncio.Event()

        async def held(*args):
            entered.set()
            await release.wait()
            raise ValueError('课件组件不可用，请安装后重试。')

        monkeypatch.setattr(module, 'render_material', held)
        await worker.command({'operation': 'preview'})
        await entered.wait()
        if action == 'cancel':
            await worker.command({'operation': 'cancel'})
        else:
            release.set()
        await worker.task
        assert original.read_bytes() == original_before and worker.course_path.read_bytes() == course_before
        assert page_images(library, material_cache(library, worker.course_path, document), document['id'], 3) == before
        assert any('取消' in event.get('message', '') for event in events) if action == 'cancel' else any(
            event['type'] == 'error' and '课件组件' in event['message'] for event in events)
        assert events[-1] == {'type': 'idle', 'busy': False}
    asyncio.run(scenario())


@pytest.mark.p0
def test_model_turn_checks_reuse_unchanged_materials_but_detect_changed_original(monkeypatch, tmp_path):
    from pathlib import Path

    from test_knowledge_visual import fake_pages, reading, setup_course

    import linguaflow.knowledge.worker as module
    from linguaflow.knowledge.materials import course_for_folder, read_blocks
    from linguaflow.knowledge.readings import save_reading
    library, item, document = setup_course(tmp_path)
    course_path, course = course_for_folder(library, item['folder'])
    images = fake_pages(library, course_path, document, 3)['images']
    for block, image in zip(read_blocks(library, course_path, course), images, strict=True):
        save_reading(library, course_path, block, image['sha256'], reading(block))
    original = course_path.parent / 'materials' / document['id'] / 'original.pptx'
    calls, reads, events = [], [], []
    read_bytes = Path.read_bytes

    def counted(path):
        if path == original:
            reads.append(path)
        return read_bytes(path)

    class FakeService:
        def __init__(self, **kwargs):
            self.before_request = kwargs['before_request']
            self.budget = SimpleNamespace(view=lambda: {})

        async def update_notes(self, job):
            self.before_request()
            calls.append('first')
            count = len(reads)
            assert count > 0
            self.before_request()
            calls.append('second')
            assert len(reads) == count, 'Unchanged source was fully reread for another model turn'
            original.write_bytes(b'externally changed during model task')
            self.before_request()
            calls.append('must not send')
            raise AssertionError('Changed material allowed another request')

        async def close(self):
            calls.append('closed')

    monkeypatch.setattr(Path, 'read_bytes', counted)
    monkeypatch.setattr(module, 'DeepSeekService', FakeService)

    async def scenario():
        worker = KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'checks'})
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        worker.start_task('notes')
        await worker.task
        assert calls == ['first', 'second', 'closed'] and worker.last_error
        assert any(event['type'] == 'error' and '来源已变化' in event.get('message', '') for event in events)
        assert not worker.store.view()['notes']
    asyncio.run(scenario())


@pytest.mark.p0
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


@pytest.mark.p0
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


@pytest.mark.p0
def test_late_terms_save_cannot_write_into_another_course(tmp_path):
    from linguaflow.knowledge.materials import course_for_folder
    library = Library(tmp_path / 'library')
    item = library.create('inbox', {}, '录音')
    folder_b = library.folder('Course B')['id']
    path_b, course_b = course_for_folder(library, folder_b, create=True)
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'test'})
        course_a = worker.course['id']
        await worker.command({'operation': 'associate', 'folder_id': folder_b})
        with pytest.raises(ValueError, match='课程关联已变化'):
            await worker.command({'operation': 'terms', 'course_id': course_a,
                                  'terms': [{'canonical': 'wrong course', 'approved': True}]})
        assert worker.course['id'] == course_b['id'] and read_json(path_b)['terms'] == []
    asyncio.run(scenario())


@pytest.mark.p1
def test_note_edit_receipt_follows_durable_write_and_missing_note_keeps_editor(tmp_path):
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '课堂')
    library.save(item, [Caption(1, 0, 2, 'evidence', 'en')], 'complete')
    events = []

    async def scenario():
        worker = KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'edit'})
        worker.store.publish(worker.store.make_job(), {'upserts': [{'id': 'note', 'section': '课堂讲述',
            'text': '初稿', 'origin': 'lecture', 'refs': [{'id': 'caption:1', 'quote': 'evidence'}]}], 'delete_note_ids': []})
        await worker.command({'operation': 'edit', 'id': 'note', 'text': '个人修改', 'request': 'receipt-1'})
        receipt = next(event for event in events if event['type'] == 'note_saved')
        assert receipt['id'] == 'note' and receipt['request'] == 'receipt-1'
        saved = worker.store.view()['notes'][0]
        assert saved['text'] == '个人修改' and saved['user_locked']
        events.clear()
        with pytest.raises(ValueError, match='已不存在'):
            await worker.command({'operation': 'edit', 'id': 'missing', 'text': '保留编辑', 'request': 'receipt-2'})
        assert not any(event['type'] == 'note_saved' for event in events)
    asyncio.run(scenario())
