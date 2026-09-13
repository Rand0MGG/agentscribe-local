"""Audit CHAT references, create a local listening-review page, score live runs.

audit uses PyAV (.venv-wlk); review and score need only the standard library.
"""
import argparse
import csv
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from linguaflow.evaluation import (POLICY, file_hash, parse_chat, reference_issues,
                                  review_problems, score, final_captions, words)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def audit(folder, output):
    import av
    folder, output = Path(folder).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted(folder.glob('*.cha')):
        reference = parse_chat(path)
        media_name = reference['source']['media_name']
        if not media_name or Path(media_name).name != media_name:
            raise ValueError(f'Invalid @Media in {path}')
        candidates = [folder/(media_name+suffix) for suffix in ['.mp4', '.wav', '.m4a', '.mp3']]
        media = next((p for p in candidates if p.is_file()), None)
        if media is None:
            raise ValueError(f'No matching media for {path}')
        with av.open(str(media)) as container:
            stream = container.streams.audio[0]
            duration = float(stream.duration*stream.time_base) if stream.duration is not None else container.duration/1e6
            first_pts = float(stream.start_time*stream.time_base) if stream.start_time is not None else None
            audio_info = {'duration_seconds': duration, 'sample_rate': stream.codec_context.sample_rate,
                          'channels': stream.codec_context.channels, 'first_audio_pts': first_pts}
        reference['source'].update(media_path=str(media), media_sha256=file_hash(media), **audio_info)
        rows = reference['utterances']
        end = 0
        gaps, overlaps = [], []
        for row in rows:
            if row['start_ms'] is None:
                continue
            if row['start_ms']-end > 1000:
                gaps.append({'start_ms': end, 'end_ms': row['start_ms']})
            if row['start_ms'] < end:
                overlaps.append(row['id'])
            end = max(end, row['end_ms'])
        if duration*1000-end > 1000:
            gaps.append({'start_ms': end, 'end_ms': round(duration*1000)})
        reference['audit'] = {'utterances': len(rows), 'speakers': sorted({r['speaker'] for r in rows}),
                              'words': sum(len(words(r['text'])) for r in rows),
                              'issues': reference_issues(reference), 'gaps_over_one_second': gaps,
                              'overlap_utterances': overlaps,
                              'notation_review_needed': sum(bool(r['issues']) for r in rows),
                              'reference_status': 'unverified'}
        target = output/(path.stem+'.reference.json')
        if target.exists():
            raise ValueError(f'Reference already exists; preserve edits and choose a new output folder: {target}')
        write_json(target, reference)
        create_review(target, output/(path.stem+'.review.html'))
        results.append({'name': path.stem, 'reference': str(target), 'audio': audio_info,
                        'origin': reference['origin'], **reference['audit']})
    if not results:
        raise ValueError('No CHAT files found')
    write_json(output/'audit.json', results)
    lines = ['# MacWhinney 参考数据审计', '',
             '本报告没有把数据库来源自动视为人工标准答案。所有新导入参考默认未核对。', '',
             '| 文件 | 分钟 | 句数 | 词数 | ASR 来源标记 | 格式/时间问题 |',
             '|---|---:|---:|---:|---|---:|']
    for row in results:
        lines.append(f'| {row["name"]} | {row["audio"]["duration_seconds"]/60:.1f} | {row["utterances"]} | '
                     f'{row["words"]} | {row["origin"]["asr_origin_detected"]} | {len(row["issues"])} |')
    lines.extend(['', '每个 reference.json 保存原始 CHAT 主层、自动清理文本、时间戳、哈希、来源和待核对状态。',
                  'review.html 是离线听音校对入口。原始音频和原始转写未修改。',
                  '时间戳空白不能自动解释为静音，重叠说话不能自动删除；都需要听音确认。'])
    (output/'audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


def create_review(reference_path, output):
    reference = json.loads(Path(reference_path).read_text(encoding='utf-8'))
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    media = Path(reference['source']['media_path'])
    # A file-relative URL works in a local browser without sending classroom
    # media to any server. No CDN, analytics, or network requests are used.
    from urllib.parse import quote
    media_url = quote(os.path.relpath(media, output.parent).replace('\\', '/'), safe='/')
    payload = json.dumps(reference, ensure_ascii=False).replace('<', '\\u003c')
    template = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>课堂参考转写校对</title>
<style>body{font:16px/1.6 system-ui;background:#17191d;color:#eee;margin:24px auto;max-width:1100px;padding:0 20px}video{width:100%;max-height:320px;background:#000}button,input,textarea{font:inherit;color:inherit;background:#282d34;border:1px solid #59616d;border-radius:6px;padding:8px}button{cursor:pointer}button:hover{background:#3c4551}textarea{box-sizing:border-box;width:100%;min-height:130px}.box{background:#22262c;padding:18px;margin:18px 0;border-radius:12px}.muted{color:#bdc5d0}label{display:block;margin:9px 0}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}pre{white-space:pre-wrap;font-size:13px}strong{color:#f0ce87}input[type=number]{width:120px}</style>
<h1>课堂参考转写校对</h1>
<p><strong>当前原稿含自动识别来源，尚不是标准答案。</strong>请按实际听到的词核对，保留重复和口头纠正，不按知识猜写术语。不确定的位置保留 xxx；含 xxx 的参考不能获得正式 WER。</p>
<p class="muted">本页只读取本地视频。刷新前请导出进度；没有自动保存，也不会上传。请勿查看待测系统的识别输出后再决定参考答案。</p>
<video id="media" controls src="__MEDIA__"></video>
<div class="box"><div class="row"><button id="prev">上一句</button><button id="play">播放本句及前后文</button><button id="next">下一句</button><span id="position"></span></div>
<label>跳转到句子 <select id="jump" style="max-width:100%;font:inherit;padding:8px"></select></label>
<p id="state"></p><div class="row"><label>开始毫秒 <input type="number" id="start"></label><label>结束毫秒 <input type="number" id="end"></label></div>
<textarea id="text" aria-label="核对后的逐字文本"></textarea><p class="muted" id="issues"></p>
<label><input type="checkbox" id="non_speech"> 原稿误识别了非讲话声音，本句文本应为空（听不清的讲话请保留 xxx）</label>
<div class="row"><button id="verify">已听音核对这一句</button><button id="add">在本句后补充漏标讲话</button></div><details><summary>原始 CHAT 主层</summary><pre id="raw"></pre></details></div>
<div class="box"><h2>完整录音确认</h2><label>校对者 <input id="reviewer" placeholder="姓名或可追溯的标识"></label>
<label><input type="checkbox" id="full_audio_listened"> 已听完整段录音，包括转写句子间的空白和末尾</label>
<label><input type="checkbox" id="all_speech_covered"> 所有可辨认讲话均已覆盖；没有漏掉未标注的句子</label>
<label><input type="checkbox" id="independent_of_test_output"> 校对过程未参考这次待测系统的输出</label>
<label><input type="checkbox" id="overlap_order_checked"> 已核对插话/重叠；接受按开始时间排列全部说话人的评分约定</label>
<p class="muted">如发现漏标整句，请先补充句子和时间，再勾选“全部覆盖”。缺少时间戳的句子播放按钮会定位到相邻上下文，时间仍需听音填写。每句核对和以上声明都完成后，评分器才允许报告基于人工核对参考的 WER。</p>
<div class="row"><button id="export">导出校对进度 JSON</button><label>导入进度 <input id="import" type="file" accept=".json"></label></div></div>
<script>let data=__DATA__;let index=0;const $=x=>document.getElementById(x);let stopAt=null;
const fields=['full_audio_listened','all_speech_covered','independent_of_test_output','overlap_order_checked'];
function choices(){const j=$('jump');j.textContent='';data.utterances.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${i+1} ${r.start_ms===null?'[缺时间]':(r.start_ms/1000).toFixed(1)+'s'} ${r.text.slice(0,48)}`;j.appendChild(o)})}
function show(){const r=data.utterances[index];$('jump').value=index;$('position').textContent=`${index+1} / ${data.utterances.length} · ${r.speaker}`;$('text').value=r.text;$('start').value=r.start_ms??'';$('end').value=r.end_ms??'';$('non_speech').checked=r.review?.non_speech===true;$('raw').textContent=r.raw_chat;$('issues').textContent=(r.issues||[]).join('；');status();}
function status(){const r=data.utterances[index];$('state').textContent=`本句：${r.review?.status==='verified'?'已核对':'待核对'}；总计 ${data.utterances.filter(x=>x.review?.status==='verified').length}/${data.utterances.length} 已核对`;}
function edit(){const r=data.utterances[index];r.text=$('text').value;r.start_ms=$('start').value===''?null:Number($('start').value);r.end_ms=$('end').value===''?null:Number($('end').value);r.review={status:'pending'};status();}
for(const id of ['text','start','end','non_speech'])$(id).addEventListener('input',edit);
$('jump').onchange=e=>{index=Number(e.target.value);show()};
$('prev').onclick=()=>{index=Math.max(0,index-1);show()};$('next').onclick=()=>{index=Math.min(data.utterances.length-1,index+1);show()};
$('play').onclick=()=>{const r=data.utterances[index];const start=r.start_ms??data.utterances[index-1]?.start_ms??0;const end=r.end_ms??data.utterances[index+1]?.end_ms??start+10000;stopAt=end/1000+1.5;$('media').currentTime=Math.max(0,start/1000-1.5);$('media').play()};
$('media').ontimeupdate=()=>{if(stopAt!==null&&$('media').currentTime>=stopAt){$('media').pause();stopAt=null}};
$('verify').onclick=()=>{const r=data.utterances[index];if(!Number.isInteger(r.start_ms)||!Number.isInteger(r.end_ms)||!(r.start_ms>=0&&r.end_ms>r.start_ms)||(!r.text.trim()&&!$('non_speech').checked)||(r.text.trim()&&$('non_speech').checked)){alert('请填写有效时间和逐字文本；非讲话项应为空文本');return}r.review={status:'verified',reviewed_at:new Date().toISOString(),reviewed_text:r.text,start_ms:r.start_ms,end_ms:r.end_ms,non_speech:$('non_speech').checked};status()};
$('add').onclick=()=>{const current=data.utterances[index];data.utterances.splice(index+1,0,{id:'manual:'+Date.now(),speaker:current.speaker,raw_chat:'人工补充（原稿漏标）',text:'',start_ms:null,end_ms:null,issues:['manual_addition_requires_review'],review:{status:'pending'}});index++;choices();show()};
function header(){ $('reviewer').value=data.review.reviewer||'';for(const f of fields)$(f).checked=data.review[f]===true;}
$('export').onclick=()=>{data.review.reviewer=$('reviewer').value.trim();for(const f of fields)data.review[f]=$(f).checked;data.review.exported_at=new Date().toISOString();const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=url;a.download=data.source.media_name+'.reviewed.reference.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
$('import').onchange=async e=>{try{const next=JSON.parse(await e.target.files[0].text());if(next.source.media_sha256!==data.source.media_sha256||next.source.chat_sha256!==data.source.chat_sha256)throw Error('不是同一份音频/转写');data=next;index=0;header();choices();show()}catch(err){alert(err.message)}};
header();choices();show();</script></html>'''
    output.write_text(template.replace('__MEDIA__', html.escape(media_url, quote=True)).replace('__DATA__', payload), encoding='utf-8')


def evaluate(reference_path, run_dir, output):
    reference = json.loads(Path(reference_path).read_text(encoding='utf-8'))
    run_dir, output = Path(run_dir), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((run_dir/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('complete'):
        raise ValueError('Run is unfinished or failed; no score issued')
    for name, expected in [('events.jsonl', manifest.get('events_sha256')),
                           ('settings.json', manifest.get('settings_sha256'))]:
        if not expected or file_hash(run_dir/name) != expected:
            raise ValueError(f'{name} integrity check failed; no score issued')
    events = [json.loads(line) for line in (run_dir/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    result, operations = score(reference, manifest, events)
    result['reference_sha256'] = file_hash(reference_path)
    result['run_manifest_sha256'] = file_hash(run_dir/'manifest.json')
    result['scorer_sha256'] = file_hash(ROOT/'linguaflow/evaluation.py')
    result['reference_origin'] = reference['origin']
    result['reference_reviewer'] = reference.get('review', {}).get('reviewer', '')
    capture = manifest.get('capture', {})
    first = result['timing']['first_source_elapsed_seconds']
    result['timing']['first_source_after_capture_start_seconds'] = (
        first-capture['start_after_launch_seconds'] if first is not None else None)
    result['timing']['capture'] = capture
    result['timing']['total_wall_seconds'] = manifest.get('total_wall_seconds')
    write_json(output/'score.json', result)
    rows, _, _ = final_captions(events)
    ref_tokens = [(word, row) for row in reference['utterances'] for word in words(row['text'])]
    hyp_tokens = [(word, row) for row in rows for word in words(row['source'])]
    with (output/'word-errors.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['operation', 'reference_word', 'hypothesis_word', 'reference_utterance',
                         'reference_start_ms', 'caption_id', 'caption_start_seconds'])
        for op in operations:
            if op['op'] == 'equal':
                continue
            expected, rr = ref_tokens[op['reference_index']] if op['reference_index'] is not None else ('', {})
            actual, hr = hyp_tokens[op['hypothesis_index']] if op['hypothesis_index'] is not None else ('', {})
            writer.writerow([op['op'], expected, actual, rr.get('id', ''), rr.get('start_ms', ''),
                             hr.get('id', ''), hr.get('start', '')])
    (output/'final-hypothesis.txt').write_text(result['hypothesis_text'], encoding='utf-8')
    title = '人工核对参考评分' if result['reference_status'] == 'human_review_attested' else '未核对参考：仅报告差异'
    lines = ['# 实时课堂评分结果', '', f'**{title}**', '',
             f'状态：`{result["status"]}`。音频按 1 倍速经过桌面 Session、AudioJournal 和真实流式 worker；没有固定时长分段识别。', '',
             '人工核对记录尚未完成时，WER 字段为空。数据库名称、自动时间戳和较低差异率均不构成正确答案的证明。', '']
    counts = result['comparison']
    if counts:
        value = counts['ratio']
        lines += [f'{"WER" if result["wer"] is not None else "未核对词差异率"}：{value:.2%}' if value is not None else '参考无词，比例未定义。',
                  f'参考 {counts["reference_words"]} 词；输出 {counts["hypothesis_words"]} 词；替换 {counts["substitute"]}，漏词 {counts["delete"]}，插入 {counts["insert"]}。', '']
        secondary = result['secondary_filler_excluded']
        label = '排除固定填充词后的 WER' if result['wer'] is not None else '排除固定填充词后的未核对词差异率'
        lines += [f'辅助指标——{label}：{secondary["ratio"]:.2%}' if secondary['ratio'] is not None else '辅助指标：排除填充词后参考无词，比例未定义。',
                  '固定排除词表：' + ', '.join(secondary['excluded_tokens']) + '。', '']
    if result['invalid_reasons']:
        lines += ['无效原因：' + ', '.join(result['invalid_reasons']), '']
    lines += [f'尚未满足的参考检查：{len(result["review_problems"])} 项（详见 JSON）。',
              f'原文更新 {result["timing"]["source_changes"]} 次；非追加修订 {result["timing"]["non_append_revisions"]} 次；撤回 {result["timing"]["retractions"]} 次。',
              '', '评分使用最终保留字幕，草稿不重复计数；不同字幕中真实重复的词不会自动去重。',
              '主指标保留口头重复、纠正和填充词；另提供固定填充词排除后的辅助指标，不能择低报告。',
              '错误 CSV 的位置由全局文本最短编辑对齐给出，歧义处可能有其他等价对齐；字幕时间仅用于定位，不是经过验证的词级延迟。',
              '整体评分按参考起始时间串接所有说话人；插话重叠的排列需要人工确认。音频空白不被自动删除。',
              '', f'规范：{POLICY}']
    (output/'score.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    if result['invalid_reasons']:
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('audit')
    p.add_argument('--corpus', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('review')
    p.add_argument('--reference', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('score')
    p.add_argument('--reference', required=True)
    p.add_argument('--run', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'audit':
        audit(args.corpus, args.output)
    elif args.command == 'review':
        create_review(args.reference, args.output)
    else:
        evaluate(args.reference, args.run, args.output)
