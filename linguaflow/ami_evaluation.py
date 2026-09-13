"""Pinned AMI reference import and explicit single-stream meeting WER protocol.

This is an ordered-reference WER, not diarization WER or an overlap-invariant
metric. Both turn order and word-time order are reported, never cherry-picked.
"""
from collections import Counter
import csv
import json
import math
from pathlib import Path
import re
import wave
import xml.etree.ElementTree as ET
import zipfile

from linguaflow.evaluation import FILLERS, POLICY, align, file_hash, final_captions, words

MEETING = 'ES2004a'
AUDIO_SHA256 = '3e2560b19bee6952c7c7ce041b0f1ea8a7ea9468044c4eea79d2a2c67e24ab0f'
ARCHIVE_SHA256 = 'b56e5babb2496b8795deeeda7e71178d7fbc9963f94276cf2a3f4b56ebbc9f9d'
PROTOCOL = 'ami-single-stream-v1'
NITE = '{http://nite.sourceforge.net/}'


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def interval(node, begin='starttime', end='endtime'):
    a, b = float(node.attrib[begin]), float(node.attrib[end])
    if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a:
        raise ValueError(f'Invalid AMI time: {node.attrib}')
    return a, b


def parse_speaker(word_xml, segment_xml, speaker):
    nodes = list(ET.fromstring(word_xml))
    indexes = {n.attrib[NITE+'id']: i for i, n in enumerate(nodes)}
    if len(indexes) != len(nodes):
        raise ValueError('Duplicate AMI word ID')
    lexical, annotations = {}, []
    for node in nodes:
        ident = node.attrib[NITE+'id']
        start, end = interval(node)
        entry = dict(id=ident, speaker=speaker, start=start, end=end,
                     raw_text=node.text or '', attributes=dict(node.attrib))
        if node.tag == 'w' and node.get('punc') != 'true':
            tokens = words(node.text or '')
            if not tokens:
                raise ValueError(f'Empty lexical AMI node: {ident}')
            lexical[ident] = dict(entry, tokens=tokens, partial=node.get('trunc') == 'true')
        elif node.tag in {'w', 'vocalsound', 'disfmarker', 'gap'}:
            annotations.append(dict(entry, kind='punctuation' if node.tag == 'w' else node.tag))
        else:
            raise ValueError(f'Unsupported AMI node: {node.tag}')
    assigned, segments = set(), []
    for segment in ET.fromstring(segment_xml):
        if segment.tag != 'segment':
            raise ValueError(f'Unsupported AMI segment: {segment.tag}')
        start, end = interval(segment, 'transcriber_start', 'transcriber_end')
        selected = []
        for child in segment.findall(NITE+'child'):
            href = child.attrib['href']
            if href.split('#')[0] != f'{MEETING}.{speaker}.words.xml':
                raise ValueError(f'Unexpected AMI reference: {href}')
            ids = re.findall(r'id\(([^)]+)\)', href)
            if len(ids) not in (1, 2):
                raise ValueError(f'Invalid AMI pointer: {href}')
            a, b = indexes[ids[0]], indexes[ids[-1]]
            if b < a:
                raise ValueError('Reversed AMI word range')
            selected.extend(n.attrib[NITE+'id'] for n in nodes[a:b+1] if n.attrib[NITE+'id'] in lexical)
        for ident in selected:
            if ident in assigned:
                raise ValueError(f'AMI lexical node belongs to multiple turns: {ident}')
            assigned.add(ident)
        segments.append(dict(id=segment.attrib[NITE+'id'], speaker=speaker,
                             start=start, end=end, word_ids=selected))
    if assigned != set(lexical):
        raise ValueError(f'Unassigned AMI words: {set(lexical)-assigned}')
    return list(lexical.values()), segments, annotations


def overlap_seconds(entries):
    """Union duration with >=2 distinct active speakers (not interval counts)."""
    points = []
    for e in entries:
        if e['end'] > e['start']:
            points.extend([(e['start'], 1, e['speaker']), (e['end'], -1, e['speaker'])])
    active, total, previous = Counter(), 0., 0.
    for at, change, speaker in sorted(points):
        if sum(v > 0 for v in active.values()) >= 2:
            total += at-previous
        active[speaker] += change
        previous = at
    return total


def import_reference(corpus):
    corpus = Path(corpus).resolve()
    audio = corpus / MEETING / f'{MEETING}.Mix-Headset.wav'
    archive = corpus / 'ami_public_manual_1.6.2.zip'
    # Pin to the official files downloaded for this experiment, not an editable
    # display transcript or a caller-supplied "human reviewed" flag.
    if file_hash(audio) != AUDIO_SHA256 or file_hash(archive) != ARCHIVE_SHA256:
        raise ValueError('AMI source hash mismatch; restore the original audio/manual archive')
    with wave.open(str(audio), 'rb') as stream:
        rate, frames = stream.getframerate(), stream.getnframes()
        duration = frames/rate
        if (rate, stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Expected original AMI 16k mono PCM16 recording')
    lexical, segments, annotations, hashes = [], [], [], {}
    import hashlib
    with zipfile.ZipFile(archive) as bundle:
        for speaker in 'ABCD':
            paths = [f'words/{MEETING}.{speaker}.words.xml', f'segments/{MEETING}.{speaker}.segments.xml']
            data = [bundle.read(p) for p in paths]
            hashes.update({p: hashlib.sha256(b).hexdigest() for p, b in zip(paths, data)})
            w, s, a = parse_speaker(*data, speaker)
            lexical.extend(w)
            segments.extend(s)
            annotations.extend(a)
    if any(e['end'] > duration+.1 for e in lexical+segments+annotations):
        raise ValueError('AMI annotation outside recording')
    segments.sort(key=lambda e: (e['start'], e['speaker'], e['id']))
    gaps = [e for e in annotations if e['kind'] == 'gap']
    return dict(protocol=PROTOCOL, normalization=POLICY, meeting=MEETING,
                source=dict(audio_path=str(audio), audio_sha256=AUDIO_SHA256,
                            annotation_archive_sha256=ARCHIVE_SHA256, member_sha256=hashes,
                            provenance='official AMI public manual 1.6.2 archive; not locally re-reviewed'),
                duration_seconds=duration, words=lexical, segments=segments, annotations=annotations,
                audit=dict(lexical_nodes=len(lexical), partial_words=sum(e['partial'] for e in lexical),
                           annotation_types=dict(Counter(e['kind'] for e in annotations)),
                           gap_seconds=sum(e['end']-e['start'] for e in gaps),
                           word_interval_overlap_seconds=overlap_seconds(lexical)))


def reference_tokens(reference, order):
    by_id = {w['id']: w for w in reference['words']}
    if order == 'turn':
        entries = [by_id[i] for s in reference['segments'] for i in s['word_ids']]
    elif order == 'word_time':
        # Preserve within-speaker XML order for tied timestamps.
        entries = sorted(reference['words'], key=lambda w: (w['start'], w['speaker']))
    else:
        raise ValueError(order)
    return [dict(word=t, id=e['id'], speaker=e['speaker'], start=e['start'], end=e['end'])
            for e in entries for t in e['tokens']]


def validate_run(reference, manifest, events):
    rows, failures, metrics = final_captions(events)
    audio, capture = manifest.get('audio', {}), manifest.get('capture', {})
    if not manifest.get('complete'):
        failures.append('incomplete_run')
    if not events or events[-1].get('type') != 'session_finished' or not events[-1].get('complete'):
        failures.append('missing_successful_end')
    if any(e['type'] == 'error' for e in events):
        failures.append('runtime_error')
    if audio.get('source_sha256') != reference['source']['audio_sha256']:
        failures.append('wrong_audio')
    expected = reference['duration_seconds'] * 48000
    if audio.get('rate') != 48000 or abs(audio.get('samples', -1)-expected) > 1:
        failures.append('wrong_audio_duration_or_rate')
    if capture.get('samples_delivered') != audio.get('samples'):
        failures.append('missing_audio_samples')
    if (manifest.get('replay_speed') != 1 or manifest.get('reference_available_to_asr') is not False
            or manifest.get('capture_block_samples') != 4800):
        failures.append('wrong_replay_protocol')
    wall = capture.get('wall_seconds', -1)
    late = capture.get('max_delivery_lateness_seconds', float('inf'))
    if (not math.isfinite(wall) or wall < reference['duration_seconds']-.05
            or not math.isfinite(late) or late > .25):
        failures.append('pacing_not_within_250ms_tolerance')
    if any(not math.isfinite(r['start']) or not math.isfinite(r['end']) for r in rows):
        failures.append('nonfinite_caption_time')
    elapsed = [e['elapsed_seconds'] for e in events]
    if any(not math.isfinite(t) or t < 0 for t in elapsed) or elapsed != sorted(elapsed):
        failures.append('invalid_event_clock')
    if failures:
        raise ValueError('No score issued: ' + ', '.join(sorted(set(failures))))
    return rows, metrics


def evaluate(reference, run_dir, destination):
    run_dir, destination = Path(run_dir), Path(destination)
    manifest = json.loads((run_dir/'manifest.json').read_text(encoding='utf-8'))
    for name, field in [('events.jsonl', 'events_sha256'), ('settings.json', 'settings_sha256')]:
        if file_hash(run_dir/name) != manifest.get(field):
            raise ValueError(f'No score issued: {name} integrity check failed')
    events = [json.loads(line) for line in (run_dir/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    rows, metrics = validate_run(reference, manifest, events)
    ref = reference_tokens(reference, 'turn')
    hyp = [dict(word=t, id=r['id'], start=r['start'], end=r['end']) for r in rows for t in words(r['source'])]
    primary, edits = align([t['word'] for t in ref], [t['word'] for t in hyp])
    alternative, _ = align([t['word'] for t in reference_tokens(reference, 'word_time')], [t['word'] for t in hyp])
    filler_excluded, _ = align([t['word'] for t in ref if t['word'] not in FILLERS],
                               [t['word'] for t in hyp if t['word'] not in FILLERS])
    capture = manifest['capture']
    result = dict(protocol=PROTOCOL, status='completed', meeting=MEETING,
        reference_status='official_manual_annotation', primary_ordered_wer=primary,
        word_time_order_sensitivity=alternative, secondary_filler_excluded=filler_excluded,
        excluded_fillers=sorted(FILLERS), reference_audit=reference['audit'],
        final_caption_count=len(rows), caption_metrics=metrics, capture=capture,
        total_wall_seconds=manifest['total_wall_seconds'],
        end_to_end_wall_audio_ratio=manifest['total_wall_seconds']/reference['duration_seconds'],
        reference_source=reference['source'], run_manifest_sha256=file_hash(run_dir/'manifest.json'),
        scorer_sha256=file_hash(__file__),
        limitations=[
            'Single-stream ordered-reference WER; not cpWER, ORC-WER, or overlap-invariant WER.',
            'Primary order: human turn start, speaker ID tie-break, original word order within each turn.',
            'Word-time order is a sensitivity diagnostic, not a lower score to select.',
            'All decoded audio is processed, including overlap, silence and annotation gaps.',
            'Only lexical w nodes enter references. Punctuation/non-lexical nodes are audited, not spoken words.',
            'Partial words and fillers are retained; numbers are not expanded. No hypothesis deduplication.',
            'Gap regions have no lexical reference; differences near them need review, not automatic ASR blame.',
            'Annotation and caption timestamps are not calibrated word-level latency measurements.',
            'This is one near-microphone meeting, not a classroom/far-field accuracy estimate.'])
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination/'score.json', result)
    write_json(destination/'final-captions.json', rows)
    (destination/'final-hypothesis.txt').write_text('\n'.join(r['source'] for r in rows), encoding='utf-8')
    with (destination/'word-errors.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['operation', 'reference_word', 'hypothesis_word', 'reference_id', 'speaker',
                         'reference_start_seconds', 'caption_id', 'caption_start_seconds'])
        for op in edits:
            if op['op'] == 'equal':
                continue
            r = ref[op['reference_index']] if op['reference_index'] is not None else {}
            h = hyp[op['hypothesis_index']] if op['hypothesis_index'] is not None else {}
            writer.writerow([op['op'], r.get('word', ''), h.get('word', ''), r.get('id', ''),
                             r.get('speaker', ''), r.get('start', ''), h.get('id', ''), h.get('start', '')])
    report = f'''# AMI ES2004a 连续实时识别测试

已完成整场音频，输入采样完整，1 倍速交付和事件完整性检查通过。

| 指标 | 结果 |
|---|---:|
| 主指标：按话轮排序的参考 WER | {primary['ratio']:.2%} |
| 按词时间排序的敏感性指标 | {alternative['ratio']:.2%} |
| 固定填充词排除后辅助 WER | {filler_excluded['ratio']:.2%} |
| 参考词数 / 输出词数 | {primary['reference_words']} / {primary['hypothesis_words']} |
| 替换 / 删除 / 插入 | {primary['substitute']} / {primary['delete']} / {primary['insert']} |
| 输入音频秒数 | {reference['duration_seconds']:.3f} |
| 总运行秒数（含加载/收尾） | {manifest['total_wall_seconds']:.3f} |
| 最大输入交付迟到秒数 | {capture['max_delivery_lateness_seconds']:.4f} |
| 最终字幕条数 | {len(rows)} |

本表不是 AMI 官方排行榜分数。当前单条字幕流不能表达多人并行讲话；两种参考排序必须同时报告，不能择低。参考包含 {reference['audit']['partial_words']} 个残词，标注 gap 共 {reference['audit']['annotation_types'].get('gap', 0)} 处、合计 {reference['audit']['gap_seconds']:.3f} 秒；词时间区间的跨说话人重叠约 {reference['audit']['word_interval_overlap_seconds']:.3f} 秒。这些区域的差异需复核。

保留所有口头重复和填充词；只忽略参考的标点及非词语 XML 标记，不裁剪音频，不根据参考切分识别。辅助指标固定排除 {', '.join(sorted(FILLERS))}。数字不做语义改写。

逐词差异见 word-errors.csv；字幕原文见 final-hypothesis.txt；原始事件和冻结设置见上级 run 目录。时间仅便于定位，不冒充逐词识别延迟。未定稿、运行失败、音频不完整、输入迟到超过 250ms 或文件校验失败时，脚本拒绝出分。
'''
    (destination/'report.md').write_text(report, encoding='utf-8')
    return result
