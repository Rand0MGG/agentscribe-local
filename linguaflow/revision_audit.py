"""Lossless text comparison; no lexical normalization or ASR accuracy claims."""
import json
from difflib import SequenceMatcher
from pathlib import Path


def compact(text):
    return ''.join(c for c in text if not c.isspace())


def audit(events, complete=False):
    models, captions = {}, {}
    for event in events:
        row = event.get('data', {})
        if event['type'] == 'model_result':
            key = (row['session_id'], row['interval_id'])
            if row['revision'] > models.get(key, {}).get('revision', -1):
                models[key] = row
        elif event['type'] == 'caption':
            key = row['id']
            if row['revision'] > captions.get(key, {}).get('revision', -1):
                captions[key] = row
    model_rows = sorted(models.values(), key=lambda r: (r['start'], r['interval_id']))
    caption_rows = sorted((r for r in captions.values() if r['source']),
                          key=lambda r: (r['start'], r['id']))

    def flatten(rows, field, identity):
        text, locations = '', []
        for row in rows:
            value = compact(row[field])
            locations.append(dict(start=len(text), end=len(text)+len(value),
                                  **{key: row[key] for key in identity}))
            text += value
        return text, locations
    left, ml = flatten(model_rows, 'text', ['session_id', 'interval_id', 'revision'])
    right, cl = flatten(caption_rows, 'source', ['id', 'revision'])
    differences = []
    for op, a, b, c, d in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if op != 'equal':
            differences.append(dict(operation=op, model_range=[a, b], caption_range=[c, d],
                model_text=left[a:b], caption_text=right[c:d]))
    finished = complete and bool(models) and all(r['closed'] for r in model_rows) and all(r['final'] for r in caption_rows)
    return dict(status=('match' if left == right else 'mismatch') if finished else 'incomplete_or_unavailable',
                complete=finished, model_text='\n'.join(r['text'] for r in model_rows),
                caption_text='\n'.join(r['source'] for r in caption_rows),
                model_locations=ml, caption_locations=cl, differences=differences,
                comparison='Only whitespace ignored; offsets refer to whitespace-free text.')


def write_audit(run_dir):
    folder = Path(run_dir)
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    finished = manifest.get('complete', False) and any(e['type'] == 'session_finished' and e.get('complete') for e in events)
    result = audit(events, finished)
    for name, field in [('model-final.txt', 'model_text'), ('captions-final.txt', 'caption_text')]:
        (folder/name).write_text(result[field], encoding='utf-8')
    (folder/'revision-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
