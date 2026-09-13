"""Conservative, reference-aware scoring of final desktop caption state.

No ASR/model imports. CHAT provenance never grants human-review status. A review
is a recorded human attestation, not proof that a reference is infallible.
"""
import hashlib
import json
import re
import unicodedata
from array import array
from pathlib import Path

POLICY = 'lexical-v1: NFKC/lowercase; apostrophes retained; punctuation/underscore separators; repetitions and fillers retained; numbers not expanded'
FILLERS = frozenset({'uh', 'um', 'er', 'erm', 'ah', 'hmm', 'mhm'})
BULLET = re.compile(r'\x15(\d+)_(\d+)\x15')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def words(text, exclude_fillers=False):
    text = unicodedata.normalize('NFKC', text).lower().replace('’', "'").replace('‘', "'")
    result = re.findall(r"[^\W_]+(?:'[^\W_]+)*", text)
    return [word for word in result if not exclude_fillers or word not in FILLERS]


def chat_text(raw):
    """Keep spoken repetitions and repairs, never substitute editorial [: ...].

    Unhandled notation is surfaced for review, not silently certified.
    """
    issues = []
    text = BULLET.sub('', raw)
    for match in re.finditer(r'\[([^\]]*)\]', text):
        code = match.group(1)
        if code not in {'/', '//', '///', '/-', '/?', '!', '?', '<', '>'}:
            issues.append('annotation_requires_review:' + code)
    text = re.sub(r'\[[^\]]*\]', ' ', text)
    if re.search(r'\b(?:xxx|yyy|www)\b', text, re.I):
        issues.append('unintelligible_or_untranscribed_speech')
    if re.search(r'&\+\S+', text):
        issues.append('partial_word_requires_review')
    text = re.sub(r'&\+\S+', ' ', text)
    text = re.sub(r'&=\S+', ' ', text)  # non-speech event
    text = re.sub(r'&-([^\s<>]+)', r'\1', text)  # filled pause is spoken
    # CHAT (.)/(..)/(...) are pauses. Parenthesized letters, e.g. (be)cause,
    # need a human decision, rather than silently inventing an expanded word.
    text = re.sub(r'\(\.+\)', ' ', text)
    if re.search(r'[\[\]&@()\x15]|\b0\w', text):
        issues.append('unsupported_notation_requires_review')
    text = text.replace('<', '').replace('>', '')
    return ' '.join(words(text)), sorted(set(issues))


def parse_chat(path):
    path = Path(path)
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    utterances, comments, media, current = [], [], None, None
    def finish():
        nonlocal current
        if current is None:
            return
        times = BULLET.findall(current['raw_chat'])
        text, issues = chat_text(current['raw_chat'])
        if len(times) != 1:
            issues.append('missing_or_multiple_time_bullets')
        start, end = map(int, times[0]) if len(times) == 1 else (None, None)
        if start is not None and end <= start:
            issues.append('invalid_time_range')
        current.update(id=f'{path.stem}:{len(utterances)+1:05}', start_ms=start, end_ms=end,
                       text=text, issues=issues, review={'status': 'pending'})
        utterances.append(current)
        current = None
    for number, line in enumerate(lines, 1):
        if line.startswith('*'):
            finish()
            match = re.match(r'^\*([^:]+):\s*(.*)', line)
            if not match:
                raise ValueError(f'Malformed CHAT main tier at line {number}')
            current = {'speaker': match[1], 'raw_chat': match[2], 'line': number}
        elif line.startswith(('@', '%')):
            finish()
            if line.startswith('@Comment:'):
                comments.append(line.split(':', 1)[1].strip())
            elif line.startswith('@Media:'):
                media = line.split(':', 1)[1].split(',')[0].strip()
        elif line[:1].isspace() and current is not None:
            current['raw_chat'] += ' ' + line.strip()
    finish()
    return {'schema': 1, 'normalization': POLICY,
            'source': {'chat_path': str(path.resolve()), 'chat_sha256': file_hash(path), 'media_name': media},
            'origin': {'comments': comments, 'asr_origin_detected': any(
                re.search(r'ASR|automatic|batchalign', comment, re.I) for comment in comments)},
            'review': {'reviewer': '', 'full_audio_listened': False, 'all_speech_covered': False,
                       'independent_of_test_output': False, 'overlap_order_checked': False},
            'utterances': utterances}


def reference_issues(reference):
    issues = []
    rows = reference.get('utterances', [])
    if not rows:
        return ['no_reference_utterances']
    duration = reference['source'].get('duration_seconds')
    seen, previous = set(), -1
    for row in rows:
        if row['id'] in seen:
            issues.append(f'duplicate_id:{row["id"]}')
        seen.add(row['id'])
        start, end = row.get('start_ms'), row.get('end_ms')
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            issues.append(f'invalid_time:{row["id"]}')
            continue
        if start < previous:
            issues.append(f'nonchronological_reference:{row["id"]}')
        if duration is not None and end/1000 > duration + .1:
            issues.append(f'time_outside_audio:{row["id"]}')
        previous = start
    return issues


def review_problems(reference):
    result = reference_issues(reference)
    review = reference.get('review', {})
    if not str(review.get('reviewer', '')).strip():
        result.append('missing_human_reviewer')
    for field in ['full_audio_listened', 'all_speech_covered', 'independent_of_test_output', 'overlap_order_checked']:
        if review.get(field) is not True:
            result.append('not_attested:' + field)
    for row in reference.get('utterances', []):
        stamp = row.get('review', {})
        if (stamp.get('status') != 'verified' or not stamp.get('reviewed_at')
                or stamp.get('reviewed_text') != row['text']
                or stamp.get('start_ms') != row.get('start_ms')
                or stamp.get('end_ms') != row.get('end_ms')):
            result.append('unreviewed_or_modified:' + row['id'])
        if re.search(r'\b(?:xxx|yyy|www)\b|\[|\]|&', row['text'], re.I):
            result.append('unresolved_speech:' + row['id'])
        if not words(row['text']) and stamp.get('non_speech') is not True:
            result.append('empty_reference_without_non_speech_review:' + row['id'])
    return result


def align(reference, hypothesis):
    """Exact unit-cost Levenshtein alignment; diagonal/delete/insert tie order.

    One byte per cell stores traceback; scores use only two integer rows.
    This avoids heuristic matching and preserves genuine repetitions.
    """
    n, m = len(reference), len(hypothesis)
    if (n+1)*(m+1) > 250_000_000:
        raise ValueError('Alignment exceeds 250 million cells; use a bounded full recording or an optimized exact aligner')
    back = bytearray((n+1)*(m+1))
    for j in range(1, m+1):
        back[j] = 2
    previous = array('I', range(m+1))
    for i, expected in enumerate(reference, 1):
        current = array('I', [i])
        base = i*(m+1)
        back[base] = 1
        for j, actual in enumerate(hypothesis, 1):
            diag = previous[j-1] + (expected != actual)
            delete, insert = previous[j]+1, current[j-1]+1
            if diag <= delete and diag <= insert:
                current.append(diag)
            elif delete <= insert:
                current.append(delete)
                back[base+j] = 1
            else:
                current.append(insert)
                back[base+j] = 2
        previous = current
    i, j, operations = n, m, []
    while i or j:
        op = back[i*(m+1)+j]
        if op == 0:
            i, j = i-1, j-1
            operations.append({'op': 'equal' if reference[i] == hypothesis[j] else 'substitute',
                               'reference_index': i, 'hypothesis_index': j})
        elif op == 1:
            i -= 1
            operations.append({'op': 'delete', 'reference_index': i, 'hypothesis_index': None})
        else:
            j -= 1
            operations.append({'op': 'insert', 'reference_index': None, 'hypothesis_index': j})
    operations.reverse()
    counts = {name: sum(op['op'] == name for op in operations) for name in ['equal', 'substitute', 'delete', 'insert']}
    errors = counts['substitute'] + counts['delete'] + counts['insert']
    return {'reference_words': n, 'hypothesis_words': m, **counts, 'errors': errors,
            'ratio': errors/n if n else None}, operations


def final_captions(events):
    """Reconstruct what the desktop retains, including retractions and revisions."""
    rows, issues, updates, retractions, nonappend = {}, [], [], 0, 0
    revisions = {}
    for event in events:
        if event['type'] != 'caption':
            continue
        caption = event['data']
        key = caption['id']
        old = rows.get(key)
        revision = caption.get('revision', 1)
        if revision < revisions.get(key, 0):
            issues.append(f'caption_revision_regressed:{key}')
        revisions[key] = revision
        if not caption['source']:
            rows.pop(key, None)
            retractions += 1
        else:
            if old is None or old['source'] != caption['source']:
                updates.append(event['elapsed_seconds'])
                if old and not caption['source'].startswith(old['source']):
                    nonappend += 1
            rows[key] = caption.copy()
    if any(not row.get('final') for row in rows.values()):
        issues.append('unfinalized_captions')
    for row in rows.values():
        if row['start'] < 0 or row['end'] < row['start']:
            issues.append('invalid_caption_time')
    return sorted(rows.values(), key=lambda row: (row['start'], row['id'])), issues, {
        'source_changes': len(updates), 'non_append_revisions': nonappend, 'retractions': retractions,
        'first_source_elapsed_seconds': updates[0] if updates else None}


def score(reference, manifest, events):
    rows, invalid, timing = final_captions(events)
    if not manifest.get('complete'):
        invalid.append('incomplete_run')
    if not events or events[-1].get('type') != 'session_finished' or not events[-1].get('complete'):
        invalid.append('missing_successful_session_end')
    if any(event['type'] == 'error' for event in events):
        invalid.append('runtime_error')
    audio = manifest['audio']
    if reference['source'].get('media_sha256') != audio['source_sha256']:
        invalid.append('reference_audio_hash_mismatch')
    if manifest.get('capture', {}).get('samples_delivered') != audio['samples']:
        invalid.append('input_not_fully_delivered')
    if manifest.get('replay_speed') != 1.0:
        invalid.append('not_real_time_replay')
    if manifest.get('reference_available_to_asr') is not False:
        invalid.append('reference_isolation_not_recorded')
    reference_audit = reference_issues(reference)
    reference_tokens = [word for row in reference['utterances'] for word in words(row['text'])]
    hypothesis_tokens = [word for row in rows for word in words(row['source'])]
    review_failures = review_problems(reference)
    verified = not review_failures
    result = {'schema': 1, 'normalization': POLICY, 'invalid_reasons': sorted(set(invalid)),
              'reference_audit_issues': reference_audit,
              'reference_status': 'human_review_attested' if verified else 'unverified',
              'review_problems': review_failures, 'wer': None, 'comparison': None,
              'final_caption_count': len(rows), 'timing': timing,
              'hypothesis_text': ' '.join(row['source'] for row in rows),
              'reference_text': ' '.join(row['text'] for row in reference['utterances']),
              'scope': 'complete recording; all speakers in CHAT main-tier order; final caption text'}
    if invalid:
        result['status'] = 'invalid_run'
        return result, []
    counts, operations = align(reference_tokens, hypothesis_tokens)
    result['comparison'] = counts
    result['status'] = 'scored_against_reviewed_reference' if verified else 'unverified_reference_comparison_only'
    if verified:
        result['wer'] = counts['ratio']
    else:
        result['unverified_word_disagreement'] = counts['ratio']
    secondary, _ = align([w for w in reference_tokens if w not in FILLERS],
                         [w for w in hypothesis_tokens if w not in FILLERS])
    result['secondary_filler_excluded'] = {'excluded_tokens': sorted(FILLERS), **secondary,
        'label': 'WER excluding fixed filler vocabulary' if verified else 'Unverified disagreement excluding fixed filler vocabulary'}
    return result, operations
