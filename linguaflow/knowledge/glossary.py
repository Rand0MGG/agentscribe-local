"""One immutable, bounded terminology snapshot for both Qwen adapters."""
import unicodedata

from .schemas import MAX_CONTEXT_BYTES, MAX_TERMS, ContextSnapshot, fingerprint


def term_text(value):
    value = unicodedata.normalize('NFKC', value).strip()
    if not value or len(value) > 80 or any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('术语须为 1–80 个可见字符，不包含换行或控制字符。')
    return value


def compile_context(terms, materials=()):
    """Compile reviewed terms only; byte bounds conservatively limit prompt size."""
    chosen, omitted, seen = [], [], set()
    prefix = 'Course terminology: '
    for term in terms:
        if not term.approved:
            continue
        for raw in (term.canonical, *term.aliases):
            value = term_text(raw)
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            proposal = prefix + '; '.join([*chosen, value])
            if len(chosen) >= MAX_TERMS or len(proposal.encode('utf-8')) > MAX_CONTEXT_BYTES:
                omitted.append(value)
            else:
                chosen.append(value)
    text = prefix + '; '.join(chosen) if chosen else ''
    materials = tuple(sorted(set(tuple(item) for item in materials)))
    data = {'text': text, 'terms': chosen, 'materials': materials}
    return ContextSnapshot(text, tuple(chosen), materials, tuple(omitted), fingerprint(data))


def context_text(snapshot):
    """Validate a transported snapshot once at startup; never call cloud decoding."""
    if not snapshot:
        return ''
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('text'), str):
        raise ValueError('课程术语快照格式无效，请重新审核术语。')
    text = snapshot['text']
    if len(text.encode('utf-8')) > MAX_CONTEXT_BYTES:
        raise ValueError('课程术语超出识别上下文长度，请减少术语。')
    terms, materials = snapshot.get('terms'), snapshot.get('materials')
    if not isinstance(terms, (tuple, list)) or not isinstance(materials, (tuple, list)):
        raise ValueError('课程术语快照缺少来源，请重新审核术语。')
    if any(not isinstance(term, str) or term_text(term) != term for term in terms):
        raise ValueError('课程术语内容无效。')
    if len(terms) > MAX_TERMS or text != ('Course terminology: ' + '; '.join(terms) if terms else ''):
        raise ValueError('课程术语文本与快照不一致。')
    if any(not isinstance(item, (tuple, list)) or len(item) != 2
           or any(not isinstance(value, str) for value in item) for item in materials):
        raise ValueError('课程术语来源格式无效。')
    if snapshot.get('version') != fingerprint({'text': text, 'terms': list(terms),
                                              'materials': list(materials)}):
        raise ValueError('课程术语快照校验失败，请重新审核术语。')
    return text
