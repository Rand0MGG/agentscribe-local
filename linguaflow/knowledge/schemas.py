"""Portable knowledge objects and limits, without Qt, models or API dependencies."""
import hashlib
import json
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 512
MAX_TERMS = 50
DEFAULT_TEXT_MODEL = 'deepseek-flash'


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
