"""Summarize true update/revision events; the other app's text is NOT truth."""
import argparse
import json
import re
import statistics
from pathlib import Path


def summarize(path):
    events = json.loads(Path(path).read_text(encoding='utf-8'))
    rows, updates, corrections = {}, [], []
    retractions = 0
    ready = next(e['received_monotonic'] for e in events if e['type'] == 'ready')
    for event in events:
        if event['type'] != 'caption':
            continue
        caption = event['data']
        old = rows.get(caption['id'])
        if not caption['source']:
            rows.pop(caption['id'], None)
            retractions += 1
            continue
        if not old or old['source'] != caption['source']:
            now = event['received_monotonic'] - ready
            if not updates or now - updates[-1] > .05:
                updates.append(now)
            if old and not caption['source'].startswith(old['source']):
                corrections.append({'before': old['source'], 'after': caption['source']})
        rows[caption['id']] = caption
    actual = ' '.join(c['source'] for c in sorted(rows.values(), key=lambda c: c['start']))
    return {'first_text_seconds': round(updates[0], 2), 'source_update_batches': len(updates),
            'median_update_gap_seconds_including_pauses': round(statistics.median(b-a for a,b in zip(updates,updates[1:])), 2),
            'non_append_revisions': len(corrections), 'retracted_rows': retractions,
            'final_rows': len(rows), 'final_words': len(re.findall(r'\w+', actual)),
            'revision_examples': corrections[:6]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('results', nargs='+')
    args = parser.parse_args()
    print(json.dumps({p: summarize(p) for p in args.results}, ensure_ascii=False, indent=2))
