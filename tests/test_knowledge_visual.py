"""Full-page image dispatch, provenance, consent, resume and real offline rendering."""
import asyncio
import hashlib
import json
import random
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from linguaflow.core import Caption
from linguaflow.knowledge.files import material_cache, write_json
from linguaflow.knowledge.materials import course_for_folder, import_material, read_blocks
from linguaflow.knowledge.readings import load_readings, save_reading, visual_blocks
from linguaflow.knowledge.rendering import RENDER_VERSION, page_images, render_material
from linguaflow.knowledge.worker import KnowledgeWorker
from linguaflow.library import Library


def png(width=16, height=12, noisy=False):
    pixels = random.Random(10).randbytes(width*height*3) if noisy else bytes([45, 110, 190])*width*height
    scanlines = b''.join(b'\0' + pixels[row*width*3:(row+1)*width*3] for row in range(height))
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) \
        + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b'')


def deck(path, count=3):
    """Authored valid OOXML: one text/formula slide, one drawn shape, then blank slides."""
    p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    r = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    rel = 'http://schemas.openxmlformats.org/package/2006/relationships'
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            + ''.join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, count+1)) + '</Types>')
        archive.writestr('_rels/.rels', f'<Relationships xmlns="{rel}"><Relationship Id="rId1" Type="{r}/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        archive.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
            + ''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1, count+1))
            + '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        archive.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{rel}">'
            + ''.join(f'<Relationship Id="rId{i}" Type="{r}/slide" Target="slides/slide{i}.xml"/>' for i in range(1, count+1)) + '</Relationships>')
        for i in range(1, count+1):
            text = 'Full courseware: E = mc^2' if i == 1 else ''
            shape = '' if i > 2 else ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Content"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
                '<p:spPr><a:xfrm><a:off x="457200" y="457200"/><a:ext cx="9144000" cy="3657600"/></a:xfrm>'
                f'<a:prstGeom prst="{"rect" if i == 1 else "triangle"}"><a:avLst/></a:prstGeom>'
                '<a:solidFill><a:srgbClr val="AED4F0"/></a:solidFill></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>'
                f'<a:p><a:r><a:rPr lang="en-US" sz="3600"/><a:t>{escape(text)}</a:t></a:r></a:p></p:txBody></p:sp>')
            archive.writestr(f'ppt/slides/slide{i}.xml', f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>'
                '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                + shape + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def fake_pages(library, course_path, descriptor, count):
    base = material_cache(library, course_path, descriptor) / 'pages'
    base.mkdir(parents=True, exist_ok=True)
    images = []
    for page in range(1, count+1):
        path = base / f'page-{page:04d}.png'
        path.write_bytes(png())
        images.append({'page': page, 'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {'render_version': RENDER_VERSION, 'sourceSha256': descriptor['id'], 'pageCount': count,
                'images': images, 'missingFonts': []}
    write_json(library.root, base / 'manifest.json', manifest)
    return manifest


def reading(block):
    return {'text': block.text or ('A visible triangle.' if block.page == 2 else 'Blank page.'),
            'terms': [], 'uncertainties': ['图形含义需核对'] if block.page == 2 else []}


def setup_course(tmp_path, count=3):
    library = Library(tmp_path / 'library')
    item = library.create(library.index['folders'][0]['id'], {}, '录音')
    library.save(item, [Caption(1, 0, 1, 'Full courseware', 'en')])
    source = tmp_path / '课件.pptx'
    deck(source, count)
    document = import_material(library, item['folder'], source)
    return library, item, document


@pytest.mark.parametrize('action', ['complete', 'cancel', 'revoke', 'source_change'])
def test_all_pages_resume_and_no_false_completion(monkeypatch, tmp_path, action):
    import linguaflow.knowledge.worker as module
    library, item, document = setup_course(tmp_path)
    events, calls, closed = [], [], []
    async def scenario():
        held, release = asyncio.Event(), asyncio.Event()
        async def renderer(*args):
            return fake_pages(*args)
        monkeypatch.setattr(module, 'render_material', renderer)
        class Service:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.budget = SimpleNamespace(view=lambda: {'requests': len(calls), 'tokens_or_reserved': 100,
                                                           'uncertain': False})
            async def read_page(self, block, image):
                self.options['before_request']()
                self.options['before_image_request']()
                calls.append(block.page)
                if len(calls) == 2 and action != 'complete':
                    held.set()
                    await release.wait()
                return reading(block)
            async def close(self):
                closed.append(True)
        monkeypatch.setattr(module, 'DeepSeekService', Service)
        worker = KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'visual'})
        await worker.command({'operation': 'permission', 'materials': True, 'notes': False})
        worker.start_task('extract')
        if action != 'complete':
            await held.wait()
            if action == 'cancel':
                await worker.command({'operation': 'cancel'})
            elif action == 'revoke':
                await worker.command({'operation': 'permission', 'materials': False, 'notes': False})
            else:
                (worker.course_path.parent / 'materials' / document['id'] / 'original.pptx').write_bytes(b'changed')
            release.set()
        await worker.task
        cache = load_readings(library, worker.course_path, document['id'])
        assert len(cache) == (3 if action == 'complete' else 1)
        if action == 'complete':
            assert calls == [1, 2, 3] and worker.coverage[document['id']]['complete']
            assert worker.coverage[document['id']]['uncertain'] == 1
            assert len([block for block in worker.blocks if block.evidence_type == 'visual']) == 3
        else:
            assert not any('全部 3 页已完成' in event.get('message', '') for event in events)
            if action == 'cancel':
                worker.start_task('extract')
                await worker.task
                assert calls == [1, 2, 2, 3]  # Page one is resumed from validated cache.
                assert worker.coverage[document['id']]['complete']
        assert closed
    asyncio.run(scenario())


@pytest.mark.parametrize('count', [8, 16])
def test_cached_course_reread_bounds_image_io_and_does_not_rewrite_sources(monkeypatch, tmp_path, count):
    import time

    library, item, document = setup_course(tmp_path, count)
    path, course = course_for_folder(library, item['folder'])
    native = read_blocks(library, path, course)
    manifest = fake_pages(library, path, document, count)
    for block, image in zip(native, manifest['images']):
        save_reading(library, path, block, image['sha256'], reading(block))
    course.update(material_cloud=True, material_images_cloud=True)
    write_json(library.root, path, course)
    reads, writes, views = [], [], []
    original = Path.read_bytes
    def counted(entry):
        data = original(entry)
        if entry.suffix == '.png':
            reads.append(len(data))
        return data
    class Service:
        async def read_page(self, *args):
            pytest.fail('A valid cached page must not make another model request')
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'cached'})
        monkeypatch.setattr(Path, 'read_bytes', counted)
        monkeypatch.setattr(worker.store, 'materials', lambda blocks: writes.append(blocks))
        monkeypatch.setattr(worker, 'view', lambda: views.append(True))
        started = time.perf_counter()
        await worker.extract_batches(Service(), worker.course_version())
        print({'pages': count, 'png_reads': len(reads), 'bytes': sum(reads),
               'seconds': round(time.perf_counter()-started, 4)})
        assert all(row['complete'] for row in worker.coverage.values())
        assert worker.checked_materials is None
    asyncio.run(scenario())
    assert count <= len(reads) <= 3*count
    assert not writes and not views


def test_task_file_checks_refresh_changed_files_and_new_reading_entries(tmp_path):
    from linguaflow.knowledge.files import FileChecks, read_json
    path = tmp_path / 'readings/page-0001.json'
    checks = FileChecks(tmp_path)
    assert checks.entries(path.parent) == () and checks.unchanged()
    write_json(tmp_path, path, {'text': 'Original'})
    assert not checks.unchanged()
    assert checks.entries(path.parent) == (path,)
    assert checks.json(path) == {'text': 'Original'} and checks.unchanged()
    write_json(tmp_path, path, {'text': 'Replacement'})
    assert not checks.unchanged()
    assert checks.json(path) == read_json(path) == {'text': 'Replacement'}
    assert checks.entries(path.parent) == (path,)
    assert checks.unchanged()


def test_legacy_text_consent_does_not_authorize_page_images(tmp_path):
    library, item, _ = setup_course(tmp_path)
    path, course = course_for_folder(library, item['folder'])
    course['material_cloud'] = True
    write_json(library.root, path, course)
    async def scenario():
        worker = KnowledgeWorker(lambda value: None)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': item['folder'], 'epoch': 'old-consent'})
        with pytest.raises(ValueError, match='页面图像'):
            worker.start_task('extract')
        await worker.command({'operation': 'permission', 'materials': False, 'notes': True})
        with pytest.raises(ValueError, match='全页视觉读取'):
            worker.start_task('notes')
    asyncio.run(scenario())


def test_visual_cache_is_separate_and_corruption_revokes_coverage(tmp_path):
    library, item, document = setup_course(tmp_path)
    path, course = course_for_folder(library, item['folder'])
    native = read_blocks(library, path, course)
    images = fake_pages(library, path, document, 3)['images']
    for block, image in zip(native, images):
        save_reading(library, path, block, image['sha256'], reading(block))
    visual, progress = visual_blocks(library, path, native, [document])
    assert progress[document['id']]['complete']
    assert native[1].text == '' and visual[1].text.startswith('A visible triangle.')
    assert all(block.evidence_type == 'visual' for block in visual)
    image = Path(visual[1].image_path)
    image.write_bytes(png(width=18))
    visual, progress = visual_blocks(library, path, native, [document])
    assert progress[document['id']]['read'] == 2 and not progress[document['id']]['complete']
    assert read_blocks(library, path, course)[1].text == ''
    with pytest.raises(ValueError, match='校验失败'):
        page_images(library, material_cache(library, path, document), document['id'], 3)


@pytest.mark.parametrize('truncated', [False, True])
def test_real_sdk_image_payload_budget_and_consent(monkeypatch, tmp_path, truncated):
    pytest.importorskip('langchain_deepseek')
    import base64

    import httpx

    import linguaflow.knowledge.api as api
    from linguaflow.knowledge.schemas import DocumentBlock
    image = tmp_path / 'page.png'
    data = png(400, 400, noisy=True)
    image.write_bytes(data)
    captured, checks = [], []
    original_client = httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        content = {'text': 'A labeled triangle.', 'uncertainties': [], 'terms': [{'canonical': 'triangle',
            'aliases': [], 'refs': [{'id': 'doc:1:visual', 'quote': 'triangle'}]}]}
        return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion', 'created': 0,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'length' if truncated else 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(content)}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 80, 'total_tokens': 280}})
    class OfflineClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', OfflineClient)
    monkeypatch.setattr(api, 'read_credential', lambda: 'test-placeholder-key')
    async def scenario():
        service = api.DeepSeekService(page_count=14, before_image_request=lambda: checks.append('image-consent'))
        try:
            if truncated:
                with pytest.raises(ValueError, match='未保存不完整结果'):
                    await service.read_page(DocumentBlock('doc:1', 'doc', 1, '', '', 'v1'),
                        {'image_path': str(image), 'image_hash': hashlib.sha256(data).hexdigest()})
                assert service.budget.calls == 1 and service.budget.view()['uncertain']
                assert service.budget.tokens >= api.PAGE_OUTPUT_TOKENS
                return
            for _ in range(14):
                result = await service.read_page(DocumentBlock('doc:1', 'doc', 1, '', '', 'v1'),
                    {'image_path': str(image), 'image_hash': hashlib.sha256(data).hexdigest()})
                assert result['terms'][0]['canonical'] == 'triangle'
            assert service.budget.calls == 14 and service.budget.tokens == 14*280
        finally:
            await service.close()
        assert service.http.is_closed and service.model.root_client.is_closed()
    asyncio.run(scenario())
    parts = captured[0]['messages'][1]['content']
    assert [part['type'] for part in parts] == ['text', 'image_url']
    assert base64.b64decode(parts[1]['image_url']['url'].split(',', 1)[1]) == data
    assert len(checks) == (1 if truncated else 14) and len(data) > 16000
    assert captured[0]['max_tokens'] == api.PAGE_OUTPUT_TOKENS
    size, images = api.request_size(captured[0]['messages'])
    assert size < 16000 and images == 1
    assert api.request_size(['data:image/png;base64,' + 'a'*18000])[0] > 16000


def test_long_visual_reading_is_retrieved_with_full_image_without_rewriting_evidence(tmp_path):
    from linguaflow.core import Caption
    from linguaflow.knowledge.materials import course_for_folder, read_blocks
    from linguaflow.knowledge.readings import save_reading, visual_blocks
    from linguaflow.knowledge.schemas import job_payload_bytes
    from linguaflow.knowledge.storage import KnowledgeStore

    library, item, document = setup_course(tmp_path)
    path, course = course_for_folder(library, item['folder'])
    native = read_blocks(library, path, course)
    images = fake_pages(library, path, document, len(native))['images']
    content = {'text': '详细图形说明。' * 550 + '\ntriangle relationships on this page.',
               'uncertainties': [], 'terms': []}
    save_reading(library, path, native[1], images[1]['sha256'], content)
    visual, _ = visual_blocks(library, path, native, course['documents'])
    store = KnowledgeStore(library.root, library.directory(item['id']), item['id'], 'epoch')
    store.materials(native + visual)
    caption = Caption(1, 0, 2, 'Explain triangle relationships.', 'en')
    store.observe(caption)
    store.saved([caption])
    job = store.make_job('course')
    source = job.sources['block:' + native[1].id + ':visual']
    assert source['text_excerpt'] and 'triangle relationships' in source['text']
    assert len(source['text'].encode('utf-8')) <= 2000 and source['image_path']
    assert job_payload_bytes(job) <= 7500
    assert store.view()['sources']['block:' + native[1].id + ':visual']['text'] == content['text']
    # A late-page citation can still be re-evaluated in a subsequent note batch.
    store.publish(job, {'upserts': [{'id': 'diagram', 'section': source['section'], 'text': 'Triangle relationships.',
        'origin': 'material', 'refs': [{'id': 'block:' + native[1].id + ':visual', 'quote': 'triangle relationships'}]}],
        'delete_note_ids': []})
    caption = Caption(1, 0, 2, 'Correct the triangle relationships.', 'en', revision=2)
    store.observe(caption)
    store.saved([caption])
    revised = store.make_job('course')
    assert revised.notes and 'triangle relationships' in revised.sources['block:' + native[1].id + ':visual']['text']


def test_harness_can_recheck_original_page_as_user_image(tmp_path):
    pytest.importorskip('deepagents')
    from langchain_core.messages import AIMessage, HumanMessage
    from pydantic import Field
    from test_knowledge_api import ScriptedModel

    from linguaflow.knowledge.api import DeepSeekService
    from linguaflow.knowledge.harness import run_agent
    from linguaflow.knowledge.schemas import NoteJob
    path = tmp_path / 'page.png'
    path.write_bytes(png())
    class InspectModel(ScriptedModel):
        seen_messages: list = Field(default_factory=list)
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen_messages.append(messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
    model = InspectModel(responses=[
        AIMessage(content='', tool_calls=[{'name': 'read_material_page', 'id': 'look',
            'args': {'identifier': 'block:doc:1:visual'}}]),
        AIMessage(content='', tool_calls=[{'name': 'CourseAnswer', 'id': 'answer', 'args': {
            'answer': 'A triangle.', 'refs': [{'id': 'block:doc:1:visual', 'quote': 'triangle'}]}}])])
    checks = []
    service = DeepSeekService(model=model, images_enabled=True, before_image_request=lambda: checks.append(True))
    job = NoteJob('job', 'epoch', 0, {'block:doc:1:visual': {'text': 'A triangle.', 'kind': 'block', 'page': 1,
        'evidence_type': 'visual', 'image_path': str(path), 'image_hash': hashlib.sha256(path.read_bytes()).hexdigest(),
        'source_version': 1}}, ('课堂讲述',), question='Describe this page')
    result = asyncio.run(run_agent(service, job, answer=True))
    assert result['answer'] == 'A triangle.' and checks == [True]
    requests = service.model.seen_messages
    images = [message for message in requests[1] if isinstance(message, HumanMessage)
              and isinstance(message.content, list) and any(part.get('type') == 'image_url' for part in message.content)]
    assert len(images) == 1
    assert 'read_material_page' in service.model.seen_tools
    assert all(not isinstance(message.content, list) for message in requests[1] if message.type == 'tool')


@pytest.mark.parametrize('revoke', [False, True])
def test_actual_sdk_harness_page_tool_and_revoked_image_consent(monkeypatch, tmp_path, revoke):
    pytest.importorskip('deepagents')
    import httpx

    import linguaflow.knowledge.api as api
    from linguaflow.knowledge.harness import run_agent
    from linguaflow.knowledge.schemas import NoteJob
    path = tmp_path / 'page.png'
    path.write_bytes(png())
    captured = []
    original_client = httpx.AsyncClient
    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        name = 'read_material_page' if len(captured) == 1 else 'CourseAnswer'
        args = ({'identifier': 'block:doc:1:visual'} if len(captured) == 1 else
                {'answer': 'Triangle.', 'refs': [{'id': 'block:doc:1:visual', 'quote': 'triangle'}]})
        return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion', 'created': 0,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'tool-' + str(len(captured)),
                'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}})
    class OfflineClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', OfflineClient)
    monkeypatch.setattr(api, 'read_credential', lambda: 'test-placeholder-key')
    def image_consent():
        if revoke:
            raise ValueError('课件上传许可已关闭。')
    job = NoteJob('job', 'epoch', 0, {'block:doc:1:visual': {'text': 'A triangle.', 'kind': 'block', 'page': 1,
        'evidence_type': 'visual', 'image_path': str(path), 'image_hash': hashlib.sha256(path.read_bytes()).hexdigest(),
        'source_version': 1}}, ('课堂讲述',), question='Describe this page')
    async def scenario():
        service = api.DeepSeekService(images_enabled=True, before_image_request=image_consent)
        try:
            if revoke:
                with pytest.raises(ValueError, match='上传许可已关闭'):
                    await run_agent(service, job, answer=True)
                assert len(captured) == 1 and service.budget.calls == 1
            else:
                assert (await run_agent(service, job, answer=True))['answer'] == 'Triangle.'
                assert service.budget.calls == 2
                image_messages = [message for message in captured[1]['messages'] if isinstance(message['content'], list)
                                  and any(part['type'] == 'image_url' for part in message['content'])]
                assert len(image_messages) == 1 and image_messages[0]['role'] == 'user'
                assert all(isinstance(message['content'], str) for message in captured[1]['messages'] if message['role'] == 'tool')
        finally:
            await service.close()
    asyncio.run(scenario())


def test_renderer_cancellation_awaits_disposal(monkeypatch, tmp_path):
    import shutil

    import linguaflow.knowledge.rendering as module
    from linguaflow.runtime_paths import DOCUMENT_RENDERER_VERSION
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is not installed')
    library, item, document = setup_course(tmp_path)
    path, _ = course_for_folder(library, item['folder'])
    base = material_cache(library, path, document)
    fake = tmp_path / 'kit'
    (fake / 'lib').mkdir(parents=True)
    (fake / 'package.json').write_text(json.dumps({'type': 'module', 'version': DOCUMENT_RENDERER_VERSION}))
    entry = fake / 'lib/index.js'
    entry.write_text('''
import { writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { spawn } from 'node:child_process';
export async function createConverter() {
 let child, base;
 return {
  async renderImages(request, signal) {
   base = dirname(dirname(request.outputDir));
   child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], {stdio:'ignore',windowsHide:true});
   await writeFile(join(base,'render-started'),String(child.pid));
   await new Promise((resolve,reject)=>{
    if(signal.aborted) reject(signal.reason);
    else signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
   });
  },
  async dispose() {
   if(child) {
    const closed = new Promise(resolve=>child.once('exit',resolve));
    child.kill(); await closed;
    await writeFile(join(base,'render-disposed'),'child exited');
   }
  }
 };
}
''', encoding='utf-8')
    monkeypatch.setattr(module, 'document_renderer', lambda: (Path(node), entry))
    async def scenario():
        task = asyncio.create_task(module.render_material(library, path, document, 3))
        async def started():
            while not (base / 'render-started').exists():
                if task.done():
                    await task  # Surface startup errors, rather than a missing-file assertion.
                    raise AssertionError('renderer returned before starting')
                await asyncio.sleep(.01)
        try:
            # Synchronize with the child, not an assumed five-second startup.
            await asyncio.wait_for(started(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert (base / 'render-disposed').read_text() == 'child exited'
            assert not list(base.glob('.render-*')) and not (base / 'pages').exists()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('suffix', ['.pdf', '.pptx'])
def test_real_offline_renderer_includes_every_page(tmp_path, suffix):
    from linguaflow.runtime_paths import document_renderer
    try:
        document_renderer()
    except RuntimeError:
        pytest.skip('Optional pinned DSH renderer is not installed on this CI host')
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    source = tmp_path / ('真实课件' + suffix)
    if suffix == '.pptx':
        deck(source)
    else:
        pytest.importorskip('pypdf')
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        for i in range(3):
            page = writer.add_blank_page(600, 450)
            if i < 2:
                stream = DecodedStreamObject()
                stream.set_data(b'0.15 0.4 0.7 rg 90 90 m 450 90 l 270 340 l h f')
                page[NameObject('/Contents')] = writer._add_object(stream)
                page[NameObject('/Resources')] = DictionaryObject()
        writer.write(source)
    document = import_material(library, folder, source)
    path, course = course_for_folder(library, folder)
    result = asyncio.run(render_material(library, path, document, 3))
    assert result['pageCount'] == 3 and [row['page'] for row in result['images']] == [1, 2, 3]
    assert result['backend'] == 'native'
    assert result['rasterEngine'] == ('pdfium' if suffix == '.pdf' else 'libreoffice')
    assert result['images'][0]['width'] > 600 and result['images'][0]['height'] > 450
    assert result['images'][-1]['byteLength'] > 0
    second = asyncio.run(render_material(library, path, document, 3))
    assert second == result  # Valid unchanged source never rerenders.
