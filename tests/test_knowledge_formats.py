"""Format routing, offline page completeness, resource snapshots and cancel/rollback boundaries."""
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from linguaflow.knowledge.files import material_cache, read_json
from linguaflow.knowledge.materials import course_for_folder, import_document, read_blocks
from linguaflow.knowledge.render_web import css_dependencies, pack_resources
from linguaflow.knowledge.rendering import IMPORT_SUFFIXES, OFFICE_SUFFIXES, image_bytes, page_images
from linguaflow.library import Library
from linguaflow.process_platform import spawn_options
from linguaflow.runtime_paths import document_renderer


def word(path):
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Complete document: first page</w:t></w:r></w:p>'
            '<w:p><w:r><w:br w:type="page"/></w:r></w:p><w:p><w:r><w:t>Second page evidence</w:t></w:r></w:p>'
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/></w:sectPr>'
            '</w:body></w:document>')


def workbook(path):
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1, 2)) + '</Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="First" sheetId="1" r:id="rId1"/><sheet name="Second" sheetId="2" r:id="rId2"/></sheets>'
            '<definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">First!$A$1:$A$1</definedName></definedNames></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in (1, 2)) + '</Relationships>')
        for i in (1, 2):
            archive.writestr(f'xl/worksheets/sheet{i}.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<dimension ref="A1:B3"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Header</t></is></c></row>'
                f'<row r="3"><c r="B3" t="inlineStr"><is><t>Beyond print area {i}</t></is></c></row></sheetData></worksheet>')


@pytest.fixture(scope='module')
def samples(tmp_path_factory):
    directory = tmp_path_factory.mktemp('formats')
    for source in (Path(__file__).parent / 'fixtures/course_formats').glob('*'):
        if source.suffix.lower() in ('.doc', '.xls', '.ppt'):
            shutil.copyfile(source, directory / source.name)
    from PySide6.QtGui import QImage
    image = QImage(300, 160, QImage.Format.Format_RGB32)
    image.fill(0xff27ae60)
    for suffix, encoding in [('.png', 'PNG'), ('.jpg', 'JPEG'), ('.jpeg', 'JPEG'), ('.webp', 'WEBP'), ('.bmp', 'BMP'), ('.ico', 'ICO')]:
        assert image.save(str(directory / ('figure'+suffix)), encoding)
    (directory / 'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="160"><rect width="300" height="160" fill="#2244cc"/></svg>', encoding='utf-8')
    # A genuine GIF, not a renamed PNG (single static frame).
    (directory / 'figure.gif').write_bytes(bytes.fromhex('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b'))
    (directory / 'topic.txt').write_text('Course text\n' + 'Last line evidence\n'*160, encoding='utf-8')
    (directory / 'topic.csv').write_text('term,definition\n"two, words","first\nsecond"\n', encoding='utf-8')
    (directory / 'topic.tsv').write_text('term\tdefinition\nQwen\tLocal ASR\n', encoding='utf-8')
    (directory / 'topic.md').write_text('# Course\n\n| Term | Definition |\n|---|---|\n| Qwen | ASR |\n\n![Diagram](figure.png)', encoding='utf-8')
    (directory / 'topic.markdown').write_text('## Markdown alias\n\n![Diagram](figure.png)', encoding='utf-8')
    (directory / 'theme.css').write_text('body{margin:0;background:white;}#edge{position:absolute;top:2000px;left:1350px;width:100px;height:100px;background:#cc2244;} .diagram{background:url(figure.png);height:160px;}', encoding='utf-8')
    (directory / 'draw.js').write_text("let c=document.querySelector('canvas').getContext('2d');c.fillStyle='#2244cc';c.fillRect(0,0,100,100);", encoding='utf-8')
    markup = '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="theme.css"><h1>Course HTML</h1><div class="diagram"></div><canvas width="100" height="100"></canvas><script src="draw.js"></script><div id="edge">Last corner</div><style>@media print{#edge,canvas{display:none}}</style>'
    for suffix in ('.html', '.htm'):
        (directory / ('topic'+suffix)).write_text(markup, encoding='utf-8')
    word(directory / 'document.docx')
    workbook(directory / 'workbook.xlsx')
    try:
        node, entry = document_renderer()
    except RuntimeError:
        return directory
    from test_knowledge_visual import deck
    deck(directory / 'slides.pptx')
    for filename, formats in [('document.docx', ('odt',)), ('workbook.xlsx', ('ods',)), ('slides.pptx', ('odp',))]:
        for extension in formats:
            subprocess.run([str(node), str(entry.with_name('cli.js')), 'convert', '--input', str(directory / filename),
                '--output', str(directory / (Path(filename).stem+'.'+extension))], check=True, capture_output=True,
                timeout=130, **spawn_options())
    return directory


@pytest.mark.parametrize('suffix', [suffix for suffix in IMPORT_SUFFIXES if suffix not in ('.pdf', '.pptx')])
def test_real_offline_import_preserves_whole_pages_and_sources(samples, tmp_path, suffix):
    if suffix in OFFICE_SUFFIXES:
        try:
            document_renderer()
        except RuntimeError:
            pytest.skip('Optional DSH rendering component unavailable')
    source = next(samples.glob('*'+suffix), None)
    if source is None:
        pytest.skip('DSH rendering component unavailable')
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    document = asyncio.run(import_document(library, folder, source))
    course_path, course = course_for_folder(library, folder)
    blocks = read_blocks(library, course_path, course)
    base = material_cache(library, course_path, document)
    manifest = page_images(library, base, document['id'], len(blocks))
    assert hashlib.sha256((course_path.parent / 'materials' / document['id'] / ('original'+suffix)).read_bytes()).hexdigest() == document['id']
    assert not course['material_cloud'] and not course.get('material_images_cloud', False)
    assert len(blocks) == len(manifest['images']) > 0
    for row in manifest['images']:
        assert image_bytes(base / 'pages' / row['path'], row['sha256'])
    if suffix in ('.docx', '.odt'):
        assert len(blocks) == 2
    if suffix in ('.xlsx', '.ods'):
        assert manifest['sheetCount'] == 2
        assert {row['sheet'] for row in manifest['images']} == {'First', 'Second'}
        assert all('B3' in row['range'] for row in manifest['images'])  # Not restricted to saved print area.
        assert all('工作表' in row.title for row in blocks)
    if suffix == '.xls':
        assert manifest['sheetCount'] > 0 and all('工作表' in row.title for row in blocks)
    if suffix in ('.html', '.htm'):
        assert len(blocks) == 4  # Includes both vertical and horizontal overflow, using screen CSS.
        assert {row['path'] for row in document['resources']} == {'theme.css', 'draw.js', 'figure.png'}
        from PySide6.QtGui import QImage
        first = QImage(str(base / 'pages' / manifest['images'][0]['path']))
        assert first.pixelColor(50, 280).blue() == 204  # Local script's Canvas actually rendered.
        last = QImage(str(base / 'pages' / manifest['images'][-1]['path']))
        assert last.pixelColor(180, 550).red() == 204  # Last corner is visible, including @media-print-hidden content.
    if document['resources']:
        (base / 'resources' / document['resources'][0]['path']).write_bytes(b'changed')
        with pytest.raises(ValueError, match='资源快照'):
            read_blocks(library, course_path, course)
    else:
        (base / 'pages' / manifest['images'][0]['path']).write_bytes(b'corrupt')
        with pytest.raises(ValueError, match='页面图片'):
            read_blocks(library, course_path, course)


def test_scoped_resource_packing_rejects_missing_remote_and_parent_paths(tmp_path):
    source = tmp_path / 'course.html'
    source.write_text('course', encoding='utf-8')
    for reference in ('missing.png', '../outside.png', 'https://example.org/course.png', 'file:///C:/private.png'):
        destination = tmp_path / hashlib.sha256(reference.encode()).hexdigest()[:8]
        destination.mkdir()
        with pytest.raises((ValueError, FileNotFoundError)):
            pack_resources(source, f'<img src="{reference}">', destination)
    assert css_dependencies("a{background:url('a b.png')} @import \"theme.css\";") == ['a b.png', 'theme.css']


def test_missing_optional_renderer_keeps_image_and_text_fixtures(monkeypatch, tmp_path_factory, tmp_path):
    import sys
    module = sys.modules[__name__]
    def unavailable():
        raise RuntimeError('Optional renderer unavailable')
    monkeypatch.setattr(module, 'document_renderer', unavailable)
    directory = samples.__wrapped__(tmp_path_factory)
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    document = asyncio.run(import_document(library, folder, directory / 'figure.png'))
    assert len(document['blocks']) == 1
    assert (directory / 'topic.html').is_file() and (directory / 'topic.md').is_file()


def test_import_is_cancellable_and_never_publishes_partial_course(monkeypatch, tmp_path):
    import linguaflow.knowledge.materials as module
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    source = tmp_path / 'test.html'
    source.write_text('<h1>Course</h1>', encoding='utf-8')
    async def scenario():
        held = asyncio.Event()
        async def renderer(*args, **kwargs):
            held.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(module, 'render_source', renderer)
        task = asyncio.create_task(import_document(library, folder, source))
        await held.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        path, course = course_for_folder(library, folder)
        assert not course['documents']
        assert list((path.parent / 'materials').iterdir()) == []
        assert source.exists()
    asyncio.run(scenario())


def test_reimport_versions_resources_and_rolls_back_failed_publication(monkeypatch, samples, tmp_path):
    import linguaflow.knowledge.materials as module
    source = tmp_path / 'course.md'
    source.write_text('![Diagram](figure.png)', encoding='utf-8')
    shutil.copyfile(samples / 'figure.png', tmp_path / 'figure.png')
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    old = asyncio.run(import_document(library, folder, source))
    path, course = course_for_folder(library, folder)
    old_blocks = read_blocks(library, path, course)
    base = material_cache(library, path, old)
    old_manifest = read_json(base / 'pages/manifest.json')
    from PySide6.QtGui import QImage
    image = QImage(str(tmp_path / 'figure.png'))
    image.fill(0xffcc2244)
    assert image.save(str(tmp_path / 'figure.png'))
    original = module.write_json
    def fail_course(root, target, value):
        if target == path:
            raise OSError('simulated publication failure')
        return original(root, target, value)
    monkeypatch.setattr(module, 'write_json', fail_course)
    with pytest.raises(OSError, match='publication failure'):
        asyncio.run(import_document(library, folder, source))
    assert read_blocks(library, path, course) == old_blocks
    assert read_json(base / 'pages/manifest.json') == old_manifest
    monkeypatch.setattr(module, 'write_json', original)
    # A corrupt previous blocks file is repairable by importing the unchanged original again.
    (base / 'blocks.json').write_text('broken JSON', encoding='utf-8')
    new = asyncio.run(import_document(library, folder, source))
    assert new['id'] == old['id'] and new['version'] != old['version']
    path, course = course_for_folder(library, folder)
    assert read_blocks(library, path, course)[0].version == new['version']
    assert not list((path.parent / 'materials').glob('.import-*'))


@pytest.mark.parametrize('phase', ['copy', 'before', 'after'])
def test_killed_reimport_publishes_only_complete_versions(tmp_path, phase):
    source = tmp_path / 'course.html'
    source.write_text('<link rel="stylesheet" href="theme.css"><h1>Source</h1>', encoding='utf-8')
    css = tmp_path / 'theme.css'
    css.write_text('body{background:white}', encoding='utf-8')
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    old = asyncio.run(import_document(library, folder, source))
    path, course = course_for_folder(library, folder)
    old_blocks = read_blocks(library, path, course)
    old_page = material_cache(library, path, old) / 'pages/page-0001.png'
    old_hash = hashlib.sha256(old_page.read_bytes()).hexdigest()
    css.write_text('body{background:#334455}', encoding='utf-8')
    program = '''
import asyncio, os, sys
from pathlib import Path
from linguaflow.library import Library
import linguaflow.knowledge.materials as m
library = Library(sys.argv[1])
folder, phase = sys.argv[2:4]
course_path, _ = m.course_for_folder(library, folder)
write, copy = m.write_json, m.shutil.copytree
def interrupted(root, path, value):
    if Path(path) == course_path and phase == 'before': os._exit(77)
    write(root, path, value)
    if Path(path) == course_path and phase == 'after': os._exit(77)
def interrupted_copy(source, target, *args, **kwargs):
    result = copy(source, target, *args, **kwargs)
    if phase == 'copy': os._exit(77)
    return result
m.write_json, m.shutil.copytree = interrupted, interrupted_copy
asyncio.run(m.import_document(library, folder, Path(sys.argv[4])))
'''
    result = subprocess.run([sys.executable, '-c', program, str(library.root), folder, phase, str(source)],
                            capture_output=True, timeout=35, **spawn_options())
    assert result.returncode == 77, result.stderr.decode('utf-8', errors='replace')
    _, retained = course_for_folder(library, folder)
    retained_blocks = read_blocks(library, path, retained)
    assert retained_blocks and hashlib.sha256(old_page.read_bytes()).hexdigest() == old_hash
    if phase == 'after':
        assert retained_blocks[0].version != old_blocks[0].version
    else:
        assert retained == course and retained_blocks == old_blocks
    # A later import repairs an unpublished partial directory and reuses complete versions.
    new = asyncio.run(import_document(library, folder, source))
    _, current = course_for_folder(library, folder)
    assert read_blocks(library, path, current)[0].version == new['version'] != old['version']
    assert old_page.is_file()


@pytest.mark.parametrize('position', ['fixed', 'sticky'])
def test_scrolling_headers_preserve_middle_and_last_corner_evidence(tmp_path, position):
    from PySide6.QtGui import QImage
    source = tmp_path / 'course.html'
    source.write_text('<style>body{margin:0;background:white;width:1400px;height:3100px}'
        f'#head{{position:{position};top:0;left:0;width:100%;height:100px;background:#228844;z-index:100}}'
        '#middle{position:absolute;top:1540px;left:100px;width:200px;height:40px;background:#cc2244}'
        '#corner{position:absolute;top:3060px;left:1360px;width:40px;height:40px;background:#2233cc}</style>'
        '<div id="head">Header content</div><div id="middle">Evidence</div><div id="corner"></div>', encoding='utf-8')
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    document = asyncio.run(import_document(library, folder, source))
    path, course = course_for_folder(library, folder)
    assert len(read_blocks(library, path, course)) == 6
    base = material_cache(library, path, document)
    manifest = read_json(base / 'pages/manifest.json')
    counts = dict.fromkeys(('228844', 'cc2244', '2233cc'), 0)
    for row in manifest['images']:
        image = QImage(str(base / 'pages' / row['path'])).convertToFormat(QImage.Format.Format_RGB888)
        pixels = bytes(image.constBits())
        for color in counts:
            counts[color] += pixels.count(bytes.fromhex(color))
    assert counts['cc2244'] > 7000 and counts['2233cc'] == 1600 and counts['228844'] > 100000
    # Previously captured scrolling pages cannot claim completeness under the new layout.
    manifest.pop('layoutVersion')
    (base / 'pages/manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='旧布局版本'):
        page_images(library, base, document['id'], 6)


def test_new_format_worker_previews_and_dispatches_every_actual_page(monkeypatch, samples, tmp_path):
    from types import SimpleNamespace

    import linguaflow.knowledge.worker as module
    from linguaflow.core import Caption
    library = Library(tmp_path / 'library')
    folder = library.index['folders'][0]['id']
    item = library.create(folder, {}, 'course')
    library.save(item, [Caption(1, 0, 1, 'Course lecture', 'en')])
    events, calls = [], []
    class Service:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.budget = SimpleNamespace(view=lambda: {})
        async def read_page(self, block, image):
            self.options['before_request']()
            self.options['before_image_request']()
            assert image_bytes(image['image_path'], image['image_hash'])
            calls.append(block.page)
            return {'text': f'Visible course page {block.page}', 'terms': [], 'uncertainties': []}
        async def close(self):
            pass
    monkeypatch.setattr(module, 'DeepSeekService', Service)
    async def scenario():
        worker = module.KnowledgeWorker(events.append)
        await worker.command({'operation': 'open', 'root': str(library.root), 'identifier': item['id'],
                              'folder_id': folder, 'epoch': 'formats'})
        await worker.command({'operation': 'import', 'path': str(samples / 'topic.html')})
        await worker.task
        view = next(row for row in reversed(events) if row['type'] == 'view')
        assert len(view['blocks']) == 4
        assert all(Path(row['preview_image_path']).is_file() for row in view['blocks'])
        assert not calls  # Local import/preview cannot upload anything.
        await worker.command({'operation': 'permission', 'materials': True, 'notes': False})
        worker.start_task('extract')
        await worker.task
        assert calls == [1, 2, 3, 4]
        assert all(row['complete'] for row in worker.coverage.values())
        assert len([row for row in worker.blocks if row.evidence_type == 'visual']) == 4
    asyncio.run(scenario())
