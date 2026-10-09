"""Portable knowledge objects and limits, without Qt, models or API dependencies."""
import hashlib
import json
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 512
MAX_TERMS = 50
DEFAULT_TEXT_MODEL = 'deepseek-flash'
# Leave room for schemas, tool definitions and model messages under the API's 16 KiB limit.
MAX_NOTE_PAYLOAD_BYTES = 7500
MAX_NOTES_PER_BATCH = 2


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class DocumentBlock:
    id: str
    document_id: str
    page: int
    title: str
    text: str
    version: str
    needs_review: bool = False
    evidence_type: str = 'native'
    image_path: str = ''
    image_hash: str = ''


@dataclass(frozen=True)
class Term:
    canonical: str
    aliases: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    approved: bool = False
    origin: str = 'material'


@dataclass(frozen=True)
class ContextSnapshot:
    text: str = ''
    terms: tuple[str, ...] = ()
    materials: tuple[tuple[str, str], ...] = ()
    omitted: tuple[str, ...] = ()
    version: str = ''

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class NoteJob:
    id: str
    epoch: str
    notes_version: int
    sources: dict
    sections: tuple[str, ...]
    notes: tuple[dict, ...] = ()
    course_version: str = ''
    event_seq: int = 0
    question: str = ''
    mode: str = 'notes'
    pending: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    remaining_note_ids: tuple[str, ...] = ()


def note_content(job):
    return {'allowed_sections': job.sections, 'sources': job.sources, 'old_notes': job.notes,
            'new_note_id_prefix': 'new-' + job.id[:8] + '-'}


def agent_content(job):
    catalog = [{key: row.get(key) for key in ('kind', 'title', 'section', 'start', 'end', 'page')}
               | {'id': identifier} for identifier, row in list(job.sources.items())[:10]]
    return {'question': job.question or '整理本次课程的带引用笔记。',
            'first_source_ids': catalog, 'source_count': len(job.sources),
            'instruction': 'Search tools can inspect all sources; catalog is only the first ten. '
                           'Do not claim full course coverage without reading the corresponding evidence.',
            'allowed_sections': job.sections, 'old_notes': job.notes}


def job_payload_bytes(job):
    content = note_content(job) if job.mode == 'notes' else agent_content(job)
    return len(json.dumps(content, ensure_ascii=False).encode('utf-8'))
