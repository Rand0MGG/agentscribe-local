"""Durability, retractions, user ownership, material identity and transport snapshots."""
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from linguaflow.core import Caption
from linguaflow.knowledge.files import write_json
from linguaflow.knowledge.glossary import compile_context, context_text
from linguaflow.knowledge.materials import (
    course_for_folder,
    extract_material,
    import_material,
    locate_course,
    read_blocks,
)
from linguaflow.knowledge.retrieval import markdown
from linguaflow.knowledge.schemas import DocumentBlock, Term
from linguaflow.knowledge.session import read_manifest, session_context, write_manifest
from linguaflow.knowledge.storage import KnowledgeStore
from linguaflow.library import Library


@pytest.fixture
def recording(tmp_path):
    library = Library(tmp_path / '中文 课程')
    item = library.create(library.index['folders'][0]['id'], {}, '讲课')
    return library, item, KnowledgeStore(library.root, library.directory(item['id']), item['id'])


def patch(text='讲述', identifier='caption:1', section='课堂讲述'):
    return {'upserts': [{'id': 'note1', 'section': section, 'text': text, 'origin': 'lecture',
                         'refs': [{'id': identifier, 'quote': text}]}], 'delete_note_ids': []}


def seed(store, text='讲述', identifier=1):
    caption = Caption(identifier, 0, 1, text, 'zh')
    store.observe(caption)
    store.saved([caption])
    return caption


def test_source_aba_versions_and_stale_receipt(recording):
    _, _, store = recording
    first = seed(store)
    job = store.make_job()
    store.observe(replace(first, source='修订', revision=2))
    store.saved([first])
    assert not store.view()['sources']['caption:1']['saved']
    assert store.make_job() is None
    store.observe(replace(first, revision=3))
    store.saved([first])
    assert store.view()['sources']['caption:1']['source_version'] == 3
    with pytest.raises(ValueError, match='来源已变化'):
        store.publish(job, patch())
    assert store.view()['notes'] == []


def test_append_does_not_invalidate_batch_but_still_needs_rechecking(recording):
    _, _, store = recording
    first = seed(store)
    job = store.make_job()
    second = Caption(2, 2, 3, '老师纠正上一句', 'zh')
    store.observe(second)
    assert store.publish(job, patch())
    assert store.view()['notes'][0]['status'] == 'pending'
    store.saved([first, second])
    newer = store.make_job()
    assert 'caption:1' in newer.sources and 'caption:2' in newer.sources
    with pytest.raises(ValueError, match='旧笔记尚未'):
        store.publish(newer, {'upserts': [], 'delete_note_ids': []})
    assert store.publish(newer, patch(second.source, 'caption:2'))
    assert store.view()['notes'][0]['status'] == 'valid'
    assert not store.publish(newer, patch(second.source, 'caption:2'))


def test_retraction_and_reopening_are_not_committable(recording):
    _, _, store = recording
    first = seed(store)
    store.publish(store.make_job(), patch())
    store.observe(replace(first, source='', revision=2))
    assert store.view()['notes'][0]['status'] == 'stale'
    assert store.make_job() is None  # Retraction still unsaved.
    store.saved([])
    job = store.make_job()
    assert job and job.sources == {}
    store.publish(job, {'upserts': [], 'delete_note_ids': ['note1']})
    assert store.view()['notes'] == []
    store.observe(replace(first, final=False, revision=3))
    store.saved([replace(first, final=False, revision=3)])
    assert store.make_job() is None


def test_atomic_patch_user_edit_and_epoch_guards(recording):
    library, item, store = recording
    first = seed(store)
    job = store.make_job()
    invalid = patch()
    invalid['upserts'].append({**invalid['upserts'][0], 'id': 'second', 'refs': [{'id': 'unknown', 'quote': 'x'}]})
    with pytest.raises(ValueError, match='引用'):
        store.publish(job, invalid)
    assert store.view()['notes'] == []
    store.publish(job, patch())
    second = seed(store, '后续', 2)
    old_job = store.make_job()
    store.edit_note('note1', '个人结论')
    with pytest.raises(ValueError, match='笔记或任务已更新'):
        store.publish(old_job, patch(second.source, 'caption:2'))
    new_job = store.make_job()
    with pytest.raises(ValueError, match='用户内容'):
        store.publish(new_job, patch(second.source, 'caption:2'))
    assert '个人结论' in markdown(store.view())
    restored = KnowledgeStore(library.root, library.directory(item['id']), item['id'])
    restored.saved([first], authoritative=True)
    with pytest.raises(ValueError, match='任务已更新'):
        store.publish(new_job, patch(second.source, 'caption:2'))


def test_current_unsaved_view_is_seeded_when_opened_mid_recording(recording):
    _, _, store = recording
    first = seed(store)
    store.live_snapshot([replace(first, source='尚未保存')])
    assert store.make_job() is None
    store.live_snapshot([])
    assert store.view()['sources']['caption:1']['deleted']


def test_context_review_bounds_and_checksum():
    terms = [Term('unapproved'), Term(' Gradient ', approved=True), Term('gradient', approved=True),
             *(Term('术语' + str(i) * 20, approved=True) for i in range(80))]
    context = compile_context(terms, [('doc', 'version')]).to_dict()
    assert context_text(json.loads(json.dumps(context))) == context['text']
    assert 'unapproved' not in context['text'] and len(context['text'].encode()) <= 512
    assert context['omitted'] and context['terms'].count('Gradient') == 1
    with pytest.raises(ValueError, match='校验失败'):
        context_text({**context, 'version': 'wrong'})
    with pytest.raises(ValueError, match='控制字符'):
        compile_context([Term('wrong\nterm', approved=True)])


def pptx(path):
    with ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types>presentationml.presentation.main+xml</Types>')
        archive.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="rId1" Target="slides/slide1.xml"/>'
                        '<Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>')
        archive.writestr('ppt/presentation.xml', '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>'
            '<p:sldId r:id="rId2"/><p:sldId r:id="rId1"/></p:sldIdLst></p:presentation>')
        for index, text in [(1, 'gradient descent'), (2, '梯度下降')]:
            archive.writestr(f'ppt/slides/slide{index}.xml', '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                            f'<a:p><a:r><a:t>{text}</a:t></a:r></a:p><p:pic/></p:sld>')


def test_import_order_cache_tampering_and_course_move(recording, tmp_path):
    library, item, _ = recording
    path = tmp_path / '课件.pptx'
    pptx(path)
    result = extract_material(path)
    assert [row['text'] for row in result['blocks']] == ['梯度下降', 'gradient descent']
    assert all(row['needs_review'] for row in result['blocks'])
    import_material(library, item['folder'], path)
    course_path, course = course_for_folder(library, item['folder'])
    assert len(read_blocks(library, course_path, course)) == 2
    course['terms'] = [{'canonical': 'gradient descent', 'approved': True}]
    write_json(library.root, course_path, course)
    assert session_context(library, item['id'])['text'] == 'Course terminology: gradient descent'
    course_id = read_manifest(library, item['id'])['course_id']
    other = library.folder('其他课程')
    library.move(item, other['id'])
    assert read_manifest(library, item['id'])['course_id'] == course_id
    path2, course2 = locate_course(library, course_id)
    assert course2['id'] == course_id
    original = path2.parent / 'materials' / result['id'] / 'original.pptx'
    original.write_text('changed')
    with pytest.raises(ValueError, match='原件校验'):
        read_blocks(library, path2, course2)


def test_legacy_material_layout_remains_readable_and_can_be_reimported(recording, tmp_path):
    import shutil

    from linguaflow.knowledge.files import material_cache
    library, item, _ = recording
    source = tmp_path / 'legacy.pptx'
    pptx(source)
    document = import_material(library, item['folder'], source)
    path, course = course_for_folder(library, item['folder'])
    expected = read_blocks(library, path, course)
    base = path.parent / 'materials' / document['id']
    shutil.copyfile(material_cache(library, path, document) / 'blocks.json', base / 'blocks.json')
    course['documents'][0].pop('snapshot')
    write_json(library.root, path, course)
    assert read_blocks(library, path, course) == expected
    assert import_material(library, item['folder'], source)['snapshot']
    _, course = course_for_folder(library, item['folder'])
    assert read_blocks(library, path, course) == expected


def test_course_purge_blocks_external_references(recording, tmp_path):
    library, item, _ = recording
    original_folder = next(row for row in library.index['folders'] if row['id'] == item['folder'])
    _, course = course_for_folder(library, original_folder['id'], True)
    manifest = read_manifest(library, item['id'])
    manifest['course_id'] = course['id']
    write_manifest(library, manifest)
    other = library.folder('保留录音')
    library.move(item, other['id'])
    token = library.trash(original_folder)
    with pytest.raises(ValueError, match='仍被其他录音引用'):
        library.purge_deleted(token)
    assert library.directory(item['id']).exists() and library.deleted()
    library.restore_deleted(token)
    assert locate_course(library, course['id'])[1]['id'] == course['id']


def test_zip_paths_and_symlinks_are_rejected(tmp_path):
    path = tmp_path / 'bad.pptx'
    with ZipFile(path, 'w') as archive:
        archive.writestr('../evil.xml', 'x')
    with pytest.raises(ValueError, match='不安全路径'):
        extract_material(path)


def test_pdf_page_extraction(tmp_path):
    pytest.importorskip('pypdf')
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(500, 500)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 50 400 Td (gradient descent) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    path = tmp_path / 'test.pdf'
    writer.write(path)
    result = extract_material(path)
    assert result['blocks'][0]['page'] == 1 and result['blocks'][0]['text'] == 'gradient descent'


def test_corrupt_consent_cannot_enable_cloud(recording):
    library, item, _ = recording
    manifest = read_manifest(library, item['id'])
    write_manifest(library, {'schema_version': 1, 'session_id': item['id']})
    assert read_manifest(library, item['id'])['notes_cloud'] is False
    manifest['notes_cloud'] = 'false'
    write_manifest(library, manifest)
    with pytest.raises(ValueError, match='损坏配置'):
        read_manifest(library, item['id'])
    path, course = course_for_folder(library, item['folder'], True)
    course['material_cloud'] = 'false'
    write_json(library.root, path, course)
    with pytest.raises(ValueError, match='损坏配置'):
        course_for_folder(library, item['folder'])


def test_new_owner_fences_all_writes_from_old_worker(recording):
    library, item, old = recording
    new = KnowledgeStore(library.root, library.directory(item['id']), item['id'])
    with pytest.raises(ValueError, match='任务已更新'):
        old.observe(Caption(1, 0, 1, 'stale source', 'en'))
    assert new.view()['sources'] == {}


def test_material_only_claim_cannot_be_labeled_as_teacher_speech(recording):
    _, _, store = recording
    seed(store, 'gradient descent')
    store.materials([DocumentBlock('doc:1', 'doc', 1, 'gradient descent', 'gradient descent', '1')])
    job = store.make_job()
    with pytest.raises(ValueError, match='不能只引用课件'):
        store.publish(job, patch('gradient descent', 'block:doc:1'))
    assert not store.view()['notes']


def test_answer_rejects_new_evidence_even_if_old_citation_unchanged(recording):
    _, _, store = recording
    seed(store)
    job = store.make_job(question='What was said?', mode='question')
    seed(store, '新的纠正', 2)
    store.validate_job(job)  # Append-only partial note batches retain their own validity.
    with pytest.raises(ValueError, match='新证据'):
        store.validate_job(job, require_latest=True)


def test_external_saved_mismatch_and_time_change_do_not_reuse_eligibility(recording):
    _, _, store = recording
    first = seed(store)
    job = store.make_job()
    with pytest.raises(ValueError, match='外部发生变化'):
        store.verify_saved([replace(first, source='external change')])
    assert not store.view()['sources']['caption:1']['saved']
    assert store.view()['sources']['caption:1']['source_version'] == 2
    store.observe(replace(first, end=2))
    store.saved([first])
    assert not store.view()['sources']['caption:1']['saved']
    store.saved([replace(first, end=2)])
    with pytest.raises(ValueError, match='来源已变化'):
        store.publish(job, patch())


def retained_patch(job):
    return {'upserts': [{**{key: row[key] for key in ('id', 'section', 'text', 'origin')},
                        'refs': [{'id': ref['id'], 'quote': ref['quote']} for ref in row['refs']]}
                        for row in job.notes], 'delete_note_ids': []}


def long_notes(store):
    caption = seed(store, 'gradient descent')
    notes = [{'id': f'long-{index}', 'section': '课堂讲述', 'text': 'gradient descent ' + '课程' * 480,
              'origin': 'lecture', 'refs': [{'id': 'caption:1', 'quote': caption.source}]} for index in range(6)]
    store.publish(store.make_job(), {'upserts': notes, 'delete_note_ids': []})
    return caption


def test_delete_cannot_remove_valid_note_not_supplied_to_this_batch(recording):
    _, _, store = recording
    captions = [Caption(index, index, index+1, word, 'en')
                for index, word in enumerate(('apple', 'banana', 'cherry', 'date'), 1)]
    for caption in captions:
        store.observe(caption)
    store.saved(captions)
    store.publish(store.make_job(), {'upserts': [{**patch(caption.source, f'caption:{caption.id}')['upserts'][0],
                                                'id': f'n{caption.id}'} for caption in captions], 'delete_note_ids': []})
    new = Caption(5, 5, 6, 'elephant', 'en')
    store.observe(new)
    store.saved([*captions, new])
    job = store.make_job()
    assert 'n1' not in {row['id'] for row in job.notes}
    before = store.view()
    assert next(row for row in before['notes'] if row['id'] == 'n1')['status'] == 'valid'
    invalid = retained_patch(job)
    invalid['delete_note_ids'] = ['n1']
    with pytest.raises(ValueError, match='不能删除未提供'):
        store.publish(job, invalid)
    assert store.view() == before


def test_incremental_batches_keep_new_evidence_for_all_deferred_notes(recording):
    from linguaflow.knowledge.schemas import MAX_NOTE_PAYLOAD_BYTES, job_payload_bytes
    _, _, store = recording
    first = long_notes(store)
    new = Caption(2, 2, 3, 'gradient descent was corrected', 'en')
    store.observe(new)
    store.saved([first, new])
    updated = set()
    for _ in range(6):
        job = store.make_job()
        if job is None:
            break
        assert 0 < len(job.notes) <= 2
        assert job_payload_bytes(job) <= MAX_NOTE_PAYLOAD_BYTES
        assert job.sources['caption:2']['text'] == new.source
        assert not updated & {row['id'] for row in job.notes}
        updated.update(row['id'] for row in job.notes)
        store.publish(job, retained_patch(job))
    assert updated == {f'long-{index}' for index in range(6)}
    assert store.make_job() is None
    assert all(row['status'] == 'valid' and not row['pending_sources'] for row in store.view()['notes'])


@pytest.mark.parametrize('damage', ['corrupt', 'missing'])
def test_reimport_repairs_original_without_reparsing_valid_cache(recording, tmp_path, monkeypatch, damage):
    import linguaflow.knowledge.materials as module
    library, item, _ = recording
    source = tmp_path / 'intact.pptx'
    pptx(source)
    document = import_material(library, item['folder'], source)
    path, course = course_for_folder(library, item['folder'])
    original = path.parent / 'materials' / document['id'] / 'original.pptx'
    if damage == 'corrupt':
        original.write_bytes(b'corruption')
    else:
        original.unlink()
    monkeypatch.setattr(module, 'extract_material', lambda *args: pytest.fail('A valid text cache should be reused'))
    restored = import_material(library, item['folder'], source)
    path, course = course_for_folder(library, item['folder'])
    assert original.read_bytes() == source.read_bytes()
    assert restored['version'] == document['version']
    assert [row.text for row in read_blocks(library, path, course)] == ['梯度下降', 'gradient descent']


@pytest.mark.parametrize('state', ['draft', 'recording', 'complete', 'incomplete'])
def test_draft_refreshes_shared_glossary_but_started_recording_keeps_snapshot(recording, state):
    library, item, _ = recording
    path, course = course_for_folder(library, item['folder'], create=True)
    course['terms'] = [{'canonical': 'old-term', 'approved': True}]
    write_json(library.root, path, course)
    previous = session_context(library, item['id'])
    library.save(item, [], state)
    course['terms'] = [{'canonical': 'new-term', 'approved': True}]
    write_json(library.root, path, course)
    current = session_context(library, item['id'])
    assert list(current['terms']) == (['new-term'] if state == 'draft' else ['old-term'])
    if state != 'draft':
        assert current == read_manifest(library, item['id'])['asr_context'] == json.loads(json.dumps(previous))


def test_moved_draft_refreshes_its_bound_course_not_destination_glossary(recording):
    library, item, _ = recording
    path, course = course_for_folder(library, item['folder'], create=True)
    course['terms'] = [{'canonical': 'old-term', 'approved': True}]
    write_json(library.root, path, course)
    session_context(library, item['id'])
    destination = library.folder('other course')
    other_path, other = course_for_folder(library, destination['id'], create=True)
    other['terms'] = [{'canonical': 'wrong-course', 'approved': True}]
    write_json(library.root, other_path, other)
    library.move(item, destination['id'])
    course['terms'] = [{'canonical': 'new-term', 'approved': True}]
    write_json(library.root, path, course)
    assert session_context(library, item['id'])['terms'] == ('new-term',)
