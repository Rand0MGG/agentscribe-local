"""Small deterministic mixed-language retrieval, with original source IDs."""
import re
from collections import Counter


def tokens(text):
    words = re.findall(r'[a-zA-Z0-9_]+|[\u3400-\u9fff]+', text.casefold())
    return Counter(token for word in words for token in (
        [word] if word.isascii() or len(word) == 1 else [word[i:i+2] for i in range(len(word)-1)]))


def rank_sources(query, sources):
    wanted = tokens(query)
    def score(identifier):
        source = sources[identifier]
        found = tokens(source.get('title', '') + ' ' + source['text'])
        return sum(min(weight, found.get(word, 0)) for word, weight in wanted.items())
    return sorted((identifier for identifier in sources if score(identifier)), key=score, reverse=True)


def markdown(view):
    rows = ['# 课堂笔记', '']
    for note in view['notes']:
        if not note.get('user_locked') and note['status'] != 'valid':
            continue
        label = '个人编辑' if note.get('user_locked') else ('课件内容' if note['origin'] == 'material' else '课堂讲述')
        rows.extend([f"## {note['section']}", '', f"{note['text']}\n\n来源：{label}"])
        if note['status'] != 'valid':
            rows.append('来源已变化，待核对；保留个人编辑。')
        for ref in note.get('refs', []):
            source = view['sources'].get(ref['id'], {})
            if source.get('kind') == 'caption':
                rows.append(f"- 录音约 {source.get('start', 0):.1f}–{source.get('end', 0):.1f} 秒：{ref['quote']}")
            else:
                rows.append(f"- 课件第 {source.get('page', '?')} 页：{ref['quote']}")
        rows.append('')
    if len(rows) == 2:
        rows.append('暂无已核对的有效笔记。待处理或失效的 AI 内容未导出。')
    return '\n'.join(rows)
