"""Short-lived SQLite transactions for source versions and conditional note publication."""
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, replace
from uuid import uuid4

from ..core import source_is_final
from .files import checked_path
from .schemas import MAX_NOTE_PAYLOAD_BYTES, MAX_NOTES_PER_BATCH, NoteJob, fingerprint, job_payload_bytes


class KnowledgeStore:
    def __init__(self, root, directory, session_id, epoch=None):
        self.root, self.session_id = root, session_id
        self.epoch = epoch or uuid4().hex
        self.path = checked_path(root, directory / 'knowledge' / 'state.sqlite')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(create=True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    data TEXT NOT NULL, saved INTEGER NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
                    event_seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, section TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL, result TEXT);
            ''')
            for key, value in [('schema', '1'), ('session_id', session_id), ('notes_version', '0'), ('event_seq', '0')]:
                db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', (key, value))
            if self._meta(db, 'session_id') != session_id or self._meta(db, 'schema') != '1':
                raise ValueError('知识库归属或格式无效，原数据未修改。')
            db.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', ('epoch', self.epoch))

    @contextmanager
    def connection(self, create=False):
        checked_path(self.root, self.path)
        if not create and not self.path.is_file():
            raise FileNotFoundError('笔记数据已被移动或删除，请重新打开录音；不会自动重建并覆盖旧数据。')
        with closing(sqlite3.connect(self.path, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            with db:
                if not create and (self._meta(db, 'session_id') != self.session_id
                                   or self._meta(db, 'epoch') != self.epoch):
                    raise ValueError('笔记或任务已更新，请重新打开录音。')
                yield db

    @staticmethod
    def _meta(db, key):
        return db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0]

    def _observe(self, db, identifier, data, saved):
        old = db.execute('SELECT * FROM sources WHERE id=?', (identifier,)).fetchone()
        content = {key: data.get(key) for key in ('text', 'language', 'segmentation_revision', 'final', 'deleted',
                   'version', 'start', 'end', 'title', 'page', 'document_id', 'persisted_mismatch')}
        if data.get('evidence_type') == 'visual':
            content.update(evidence_type='visual', image_hash=data.get('image_hash'))
        digest = fingerprint(content)
        changed = old is None or old['fingerprint'] != digest
        version = (old['version'] + int(changed)) if old else 1
        seq = int(self._meta(db, 'event_seq')) + int(changed)
        db.execute('UPDATE meta SET value=? WHERE key=?', (str(seq), 'event_seq'))
        processed = old['processed'] if old else 0
        db.execute('INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (identifier, version, digest, json.dumps(data, ensure_ascii=False),
                    int(saved if changed else saved or old['saved']), processed, seq))
        if changed:
            self._mark_affected(db, identifier, data)
        return version

    @staticmethod
    def _mark_affected(db, identifier, data):
        from .retrieval import rank_sources
        notes = {row['id']: json.loads(row['data']) for row in db.execute('SELECT * FROM notes')}
        candidates = {key: {'text': note['text'] + ' ' + ' '.join(ref['quote'] for ref in note.get('refs', []))}
                      for key, note in notes.items() if not note.get('user_locked')}
        related = set(rank_sources(data.get('text', ''), candidates)[:4])
        if data.get('kind') == 'caption':
            # References such as "I meant Monday" may lack vocabulary overlap; revisit recent speech notes too.
            related.update([key for key, note in notes.items()
                            if not note.get('user_locked') and note.get('origin') == 'lecture'][-2:])
        for key, note in notes.items():
            if any(ref['id'] == identifier for ref in note.get('refs', [])):
                note['status'] = 'stale'
            elif key in related and data.get('final') and not data.get('deleted'):
                note['status'] = 'pending'
            else:
                continue
            if not note.get('user_locked'):
                version = db.execute('SELECT version FROM sources WHERE id=?', (identifier,)).fetchone()[0]
                note.setdefault('pending_sources', {})[identifier] = version
            db.execute('UPDATE notes SET data=? WHERE id=?', (json.dumps(note, ensure_ascii=False), key))

    @staticmethod
    def caption_data(caption):
        return {'text': caption.source, 'language': caption.language,
                'segmentation_revision': caption.segmentation_revision,
                'final': source_is_final(caption), 'deleted': not bool(caption.source.strip()),
                'start': caption.start, 'end': caption.end, 'kind': 'caption', 'section': '课堂讲述'}

    def observe(self, caption):
        with self.connection() as db:
            return self._observe(db, f'caption:{caption.id}', self.caption_data(caption), False)

    def live_snapshot(self, captions):
        rows = {f'caption:{caption.id}': self.caption_data(caption) for caption in captions}
        with self.connection() as db:
            for identifier, data in rows.items():
                self._observe(db, identifier, data, False)
            for row in db.execute("SELECT * FROM sources WHERE id LIKE 'caption:%'").fetchall():
                if row['id'] not in rows:
                    data = json.loads(row['data'])
                    data.update(text='', deleted=True, final=False)
                    self._observe(db, row['id'], data, False)

    def saved(self, captions, authoritative=False):
        """A live save receipt grants eligibility only to the matching current source."""
        rows = {f'caption:{caption.id}': self.caption_data(caption) for caption in captions}
        with self.connection() as db:
            for identifier, data in rows.items():
                if authoritative:
                    self._observe(db, identifier, data, True)
                else:
                    row = db.execute('SELECT data FROM sources WHERE id=?', (identifier,)).fetchone()
                    if row and all(json.loads(row['data']).get(key) == data.get(key)
                                   for key in ('text', 'language', 'segmentation_revision', 'final', 'deleted', 'start', 'end')):
                        if json.loads(row['data']).get('persisted_mismatch'):
                            self._observe(db, identifier, data, True)
                        else:
                            db.execute('UPDATE sources SET saved=1 WHERE id=?', (identifier,))
            if authoritative:
                for row in db.execute("SELECT * FROM sources WHERE id LIKE 'caption:%'").fetchall():
                    if row['id'] not in rows:
                        data = json.loads(row['data'])
                        data.update(text='', deleted=True, final=False)
                        self._observe(db, row['id'], data, True)
            else:
                for row in db.execute("SELECT id,data FROM sources WHERE id LIKE 'caption:%'").fetchall():
                    if row['id'] not in rows and json.loads(row['data']).get('deleted'):
                        db.execute('UPDATE sources SET saved=1 WHERE id=?', (row['id'],))

    def verify_saved(self, captions):
        """External document edits revoke eligibility without overwriting an unsaved live view."""
        actual = {f'caption:{caption.id}': self.caption_data(caption) for caption in captions}
        mismatched = False
        with self.connection() as db:
            for row in db.execute("SELECT * FROM sources WHERE id LIKE 'caption:%'").fetchall():
                data = json.loads(row['data'])
                if not row['saved'] or data.get('deleted'):
                    continue
                if row['id'] not in actual or any(data.get(key) != actual[row['id']].get(key)
                    for key in ('text', 'language', 'segmentation_revision', 'final', 'deleted', 'start', 'end')):
                    self._observe(db, row['id'], {**data, 'persisted_mismatch': True}, False)
                    mismatched = True
        if mismatched:
            raise ValueError('已保存的字幕文件在外部发生变化，请重新打开录音；旧结果未发布。')

    def materials(self, blocks):
        rows = {f'block:{block.id}': {'text': block.text, 'title': block.title, 'page': block.page,
                'version': block.version, 'document_id': block.document_id, 'kind': 'block',
                'evidence_type': block.evidence_type, 'image_path': block.image_path, 'image_hash': block.image_hash,
                'section': block.title, 'final': bool(block.text), 'deleted': False} for block in blocks}
        with self.connection() as db:
            for identifier, data in rows.items():
                self._observe(db, identifier, data, True)
            for row in db.execute("SELECT * FROM sources WHERE id LIKE 'block:%'").fetchall():
                if row['id'] not in rows:
                    data = json.loads(row['data'])
                    data.update(deleted=True, final=False)
                    self._observe(db, row['id'], data, True)

    def view(self):
        with self.connection() as db:
            notes = [json.loads(row['data']) for row in db.execute('SELECT data FROM notes ORDER BY rowid')]
            rows = db.execute('SELECT * FROM sources').fetchall()
            sources = {row['id']: {**json.loads(row['data']), 'source_version': row['version'],
                                  'saved': bool(row['saved']), 'processed': row['processed'], 'event_seq': row['event_seq']} for row in rows}
            pending = [key for key, row in sources.items() if row['kind'] == 'caption' and row['final']
                       and not row['deleted'] and row['source_version'] != row['processed']]
            return {'notes': notes, 'sources': sources, 'pending': pending,
                    'notes_version': int(self._meta(db, 'notes_version')),
                    'event_seq': int(self._meta(db, 'event_seq'))}

    def make_job(self, course_version='', question='', mode='notes', section='', note_ids=None):
        view, selected, used = self.view(), {}, 0
        pending = []
        identifier = uuid4().hex
        def build(sources, notes=(), remaining=()):
            sections = (section,) if section else tuple(dict.fromkeys([
                '课堂讲述', *(row['section'] for row in sources.values() if mode == 'notes'),
                *(note['section'] for note in notes)]))
            return NoteJob(identifier, self.epoch, view['notes_version'], sources, sections, tuple(notes),
                course_version, event_seq=view['event_seq'], question=question, mode=mode,
                pending=tuple(pending), remaining_note_ids=tuple(remaining))
        # Process oldest eligible speech first; unsaved/unselected entries stay pending.
        for key in view['pending']:
            source = view['sources'][key]
            if not source['saved']:
                continue
            cost = len(source['text'].encode('utf-8'))
            if used + cost > 3500:
                if not selected and mode == 'notes':
                    raise ValueError('单条定稿原文超出增量处理预算；可先针对具体知识点提问，已保存原文保留。')
                break
            proposal = {**selected, key: source}
            if mode == 'notes' and job_payload_bytes(build(proposal)) > MAX_NOTE_PAYLOAD_BYTES:
                break
            selected[key] = source
            pending.append((key, source['source_version']))
            used += cost
        if mode != 'notes':
            selected = {key: row for key, row in view['sources'].items() if row['kind'] == 'caption'
                        and row['saved'] and row['final'] and not row['deleted']}
        dirty = [note for note in view['notes'] if not note.get('user_locked') and note['status'] != 'valid']
        if not selected and not question and not dirty:
            return None
        # A bounded lexical retrieval supplies original material, never previous summaries alone.
        from .retrieval import rank_sources, visual_excerpt
        query = question or ' '.join(row['text'] for row in selected.values())
        material = {key: row for key, row in view['sources'].items() if row['kind'] == 'block'
                    and not row['deleted'] and row['final']}
        for key in rank_sources(query, material)[:5]:
            source = visual_excerpt(material[key], query) if mode == 'notes' else material[key]
            if mode == 'notes' and used + len(source['text'].encode('utf-8')) > 5000:
                continue
            if mode == 'notes' and job_payload_bytes(build({**selected, key: source})) > MAX_NOTE_PAYLOAD_BYTES:
                continue
            selected[key] = source
            used += len(source['text'].encode('utf-8'))
        if mode != 'notes':
            selected.update(material)  # Scoped tools can retrieve any frozen original, without uploading it all.
        if section:
            sections = {'课堂讲述', *(row['section'] for row in selected.values()),
                        *(note['section'] for note in view['notes'])}
            if section not in sections:
                raise ValueError('所选章节已不存在，请刷新。')
        notes = [note for note in view['notes'] if (not section or note['section'] == section)
                 and (note_ids is None or note['id'] in note_ids)
                 and (mode == 'question' or not note.get('user_locked'))
                 and (mode != 'notes' or note['status'] != 'valid')]
        if mode == 'question':
            ranked = rank_sources(question, {note['id']: {'text': note['text'], 'title': note['section']} for note in notes})[:6]
            notes = [note for note in notes if note['id'] in ranked]
        # Re-check an old conclusion using its original current evidence as well as new speech.
        chosen, remaining, oversized = [], [], []
        for note in notes:
            proposal, blocked = dict(selected), False
            dependencies = {ref['id'] for ref in note.get('refs', [])} | set(note.get('pending_sources', {}))
            for key in dependencies:
                row = view['sources'].get(key)
                if row and row['saved'] and row['final'] and not row['deleted']:
                    proposal[key] = visual_excerpt(row, query, [ref['quote'] for ref in note.get('refs', [])
                        if ref['id'] == key]) if mode == 'notes' else row
                elif row and (not row['saved'] or not row['final'] and not row['deleted']):
                    blocked = True
            candidate = build(proposal, [*chosen, note])
            if blocked or len(chosen) >= MAX_NOTES_PER_BATCH or job_payload_bytes(candidate) > MAX_NOTE_PAYLOAD_BYTES:
                remaining.append(note['id'])
                if not blocked and not chosen:
                    oversized.append(note['id'])
                continue
            selected, chosen = proposal, [*chosen, note]
        if mode == 'notes' and not selected and not chosen:
            if oversized:
                raise ValueError('单条笔记及其证据超出处理预算，请缩短该条个人编辑或针对具体知识点提问；原内容保留。')
            return None
        if mode == 'organize' and remaining and not chosen:
            raise ValueError('当前笔记或证据无法纳入单批预算，请先核对未保存原文或缩短过长笔记；原内容保留。')
        job = build(selected, chosen, remaining if mode != 'question' else ())
        with self.connection() as db:
            job = replace(job, event_seq=int(self._meta(db, 'event_seq')))
            metadata = {**asdict(job), 'sources': {key: source['source_version'] for key, source in job.sources.items()}, 'notes': []}
            db.execute('INSERT INTO jobs VALUES (?, ?, NULL)', (job.id, json.dumps(metadata, ensure_ascii=False)))
            db.execute('DELETE FROM jobs WHERE rowid NOT IN (SELECT rowid FROM jobs ORDER BY rowid DESC LIMIT 20)')
        return job

    def _validate_job(self, db, job):
        if self._meta(db, 'epoch') != job.epoch or int(self._meta(db, 'notes_version')) != job.notes_version:
            raise ValueError('笔记或任务已更新，旧结果已拒绝。')
        for identifier, source in job.sources.items():
            row = db.execute('SELECT * FROM sources WHERE id=?', (identifier,)).fetchone()
            current = json.loads(row['data']) if row else {}
            if (not row or row['version'] != source['source_version'] or not row['saved']
                    or not current.get('final') or current.get('deleted')):
                raise ValueError('笔记来源已变化或尚未保存，旧结果已拒绝。')

    def validate_job(self, job, require_latest=False):
        with self.connection() as db:
            self._validate_job(db, job)
            if require_latest and int(self._meta(db, 'event_seq')) != job.event_seq:
                raise ValueError('问答期间出现新证据，请重新提问。')

    def publish(self, job, patch):
        """Validate the complete patch and all actual inputs before one atomic transaction."""
        with self.connection() as db:
            existing = db.execute('SELECT result FROM jobs WHERE id=?', (job.id,)).fetchone()
            if not existing:
                raise ValueError('任务已失效，请重新生成。')
            if existing['result']:
                return False
            self._validate_job(db, job)
            notes = {row['id']: json.loads(row['data']) for row in db.execute('SELECT * FROM notes')}
            upserts, deletes = patch.get('upserts', []), patch.get('delete_note_ids', [])
            ids = set()
            supplied = {note['id'] for note in job.notes}
            for note in upserts:
                identifier = note['id']
                if not identifier or identifier in ids or note['section'] not in job.sections:
                    raise ValueError('笔记补丁标识或章节范围无效。')
                ids.add(identifier)
                old = notes.get(identifier)
                if old and (old.get('user_locked') or old['section'] not in job.sections):
                    raise ValueError('模型不能覆盖用户内容或其他章节。')
                if old and identifier not in supplied:
                    raise ValueError('模型不能修改未提供的旧笔记。')
                if not note['text'].strip() or len(note['text']) > 1600 or not note.get('refs'):
                    raise ValueError('笔记缺少内容或证据。')
                if note.get('origin') not in ('material', 'lecture'):
                    raise ValueError('笔记来源分类无效。')
                if note['origin'] == 'lecture' and not any(job.sources.get(ref['id'], {}).get('kind') == 'caption'
                                                          for ref in note['refs']):
                    raise ValueError('课堂讲述必须引用已保存定稿原文，不能只引用课件。')
                for ref in note['refs']:
                    source = job.sources.get(ref['id'])
                    if not source or not ref.get('quote') or ref['quote'] not in source['text']:
                        raise ValueError('笔记引用不存在或原文引句不匹配。')
                    if note['origin'] == 'material' and source['kind'] != 'block':
                        raise ValueError('课件内容必须引用课件证据。')
            for identifier in deletes:
                if identifier in ids or identifier not in notes or notes[identifier].get('user_locked'):
                    raise ValueError('删除补丁不能修改用户内容或未知条目。')
                if notes[identifier]['section'] not in job.sections:
                    raise ValueError('删除补丁超出本批范围。')
                if identifier not in supplied:
                    raise ValueError('模型不能删除未提供的旧笔记。')
            required = {note['id'] for note in job.notes if not note.get('user_locked')}
            if not required <= ids | set(deletes):
                raise ValueError('旧笔记尚未逐条核对，未发布不完整补丁。')
            for note in upserts:
                note = dict(note)
                note.update(user_locked=False, status='valid', pending_sources={},
                            revision=notes.get(note['id'], {}).get('revision', 0)+1)
                note['refs'] = [{**ref, 'version': job.sources[ref['id']]['source_version']} for ref in note['refs']]
                db.execute('INSERT OR REPLACE INTO notes VALUES (?, ?, ?)',
                           (note['id'], note['section'], json.dumps(note, ensure_ascii=False)))
            for identifier in deletes:
                db.execute('DELETE FROM notes WHERE id=?', (identifier,))
            for identifier, version in job.pending:
                db.execute('UPDATE sources SET processed=? WHERE id=? AND version=?', (version, identifier, version))
            # Also retain evidence for dirty notes created before pending_sources existed.
            for identifier, note in notes.items():
                if identifier not in supplied and not note.get('user_locked') and note['status'] != 'valid':
                    note.setdefault('pending_sources', {}).update(dict(job.pending))
                    db.execute('UPDATE notes SET data=? WHERE id=?', (json.dumps(note, ensure_ascii=False), identifier))
            for row in db.execute("SELECT * FROM sources WHERE id LIKE 'caption:%'").fetchall():
                data = json.loads(row['data'])
                if row['version'] != row['processed'] and data.get('final') and not data.get('deleted'):
                    supplied_source = job.sources.get(row['id'])
                    if not supplied_source or supplied_source['source_version'] != row['version']:
                        self._mark_affected(db, row['id'], data)
            db.execute('UPDATE meta SET value=? WHERE key=?', (str(job.notes_version+1), 'notes_version'))
            db.execute('UPDATE jobs SET result=? WHERE id=?', (json.dumps(patch, ensure_ascii=False), job.id))
            return True

    def edit_note(self, identifier, text):
        if not text.strip() or len(text) > 10000:
            raise ValueError('笔记内容为空或过长。')
        with self.connection() as db:
            row = db.execute('SELECT data FROM notes WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise ValueError('笔记已不存在，请刷新。')
            note = json.loads(row[0])
            note.update(text=text, user_locked=True, revision=note['revision']+1)
            db.execute('UPDATE notes SET data=? WHERE id=?', (json.dumps(note, ensure_ascii=False), identifier))
            db.execute('UPDATE meta SET value=? WHERE key=?',
                       (str(int(self._meta(db, 'notes_version'))+1), 'notes_version'))
