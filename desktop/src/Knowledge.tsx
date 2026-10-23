import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button, Choice, EditDialog, Modal } from './components';
import { bridge, request, type Bootstrap } from './types';

type Term = { canonical: string; aliases: string[]; aliasesText?: string; evidence_ids: string[]; approved: boolean; origin: string };
const courseDrafts = new Map<string, Term[]>();
export function Knowledge({ onClose, active, onSeek }: { onClose: () => void; active: boolean; onSeek: (seconds: number) => void }) {
  const [view, setView] = useState<any>({}), [message, setMessage] = useState('正在打开课程…'), [taskBusy, setBusy] = useState(false), [connected, setConnected] = useState(false);
  const busy = taskBusy || !connected;
  const [tab, setTab] = useState('课件'), [page, setPage] = useState(''), [question, setQuestion] = useState('');
  const [terms, setTerms] = useState<Term[]>([]), [dirty, setDirty] = useState(false), [credential, setCredential] = useState<string | null>(null);
  const [editing, setEditing] = useState<any>(null), [text, setText] = useState('');
  const [selectedNote, setSelectedNote] = useState(''), [savingNote, setSavingNote] = useState(false);
  const submittedNote = useRef<string | null>(null);
  const [answer, setAnswer] = useState<any>(null), [usage, setUsage] = useState('');
  const submittedTerms = useRef<{ course: string; rows: Term[] } | null>(null);
  const reading = useRef<HTMLDivElement>(null), closeAction = useRef<() => void>(() => {});
  const [association, setAssociation] = useState(''), [section, setSection] = useState('');
  const [image, setImage] = useState<string | null>(null);
  const [savingTerms, setSavingTerms] = useState(false), [selectedTerms, setSelectedTerms] = useState<number[]>([]), [addingTerm, setAddingTerm] = useState(false);
  const selectionAnchor = useRef(0);
  const recording = useRef<string | null>(null);
  const identity = useRef('');
  const drafts = useRef(courseDrafts), course = useRef(''), dirtyRef = useRef(false), termsRef = useRef<Term[]>([]);
  dirtyRef.current = dirty; termsRef.current = terms;
  useEffect(() => {
    request('window.edited', { owner: 'knowledge', dirty: addingTerm || dirty || drafts.current.size > 0 || !!editing && text !== editing.text }).catch(() => {});
    return () => { request('window.edited', { owner: 'knowledge', dirty: drafts.current.size > 0 }).catch(() => {}); };
  }, [dirty, editing, text, addingTerm]);
  useEffect(() => {
    const unsubscribe = bridge?.subscribe(({ event, data }) => {
      if (event === 'knowledge-close') { closeAction.current(); return; }
      if (event === 'state' && recording.current !== (data.item?.id ?? null)) {
        recording.current = data.item?.id ?? null;
        setAnswer(null); setPage(''); setSelectedNote(''); setSection(''); setQuestion(''); setUsage(''); setConnected(false); setView({});
        if (!data.item) setMessage('请先新建或打开录音。');
      }
      if (event !== 'knowledge') return;
      if (data.type === 'view') {
        setConnected(true);
        setView((old: any) => ({ ...old, ...data }));
        setAssociation(data.course_folder_id || '');
        const identifier = data.course?.id || '';
        recording.current = data.manifest?.session_id ?? recording.current;
        const nextIdentity = `${identifier}:${data.manifest?.session_id || ''}`;
        if (identity.current !== nextIdentity) {
          identity.current = nextIdentity;
          setAnswer(null); setPage(''); setSelectedNote(''); setSection(''); setQuestion(''); setUsage(''); setSelectedTerms([]);
        }
        if (identifier !== course.current) {
          if (course.current && dirtyRef.current) drafts.current.set(course.current, termsRef.current);
          course.current = identifier;
          const draft = drafts.current.get(identifier);
          setTerms(draft || data.course?.terms || []); setDirty(!!draft);
        } else if (!dirtyRef.current) setTerms(data.course?.terms || []);
        const coverage = Object.values(data.reading_coverage || {}) as { read: number; total: number }[];
        setMessage(data.material_error || `本机已保存 ${data.course?.documents?.length ?? 0} 份课件 · 视觉读取 ${coverage.reduce((n, row) => n + row.read, 0)}/${coverage.reduce((n, row) => n + row.total, 0)} 页 · ${data.pending?.length ?? 0} 条原文待处理${data.busy ? ' · 正在处理…' : ''}`);
        setAnswer((previous: any) => previous && (data.event_seq !== undefined && previous.event_seq !== data.event_seq || data.notes_version !== undefined && previous.notes_version !== data.notes_version) ? { answer: '回答所依据的原文或笔记已更新，请重新提问。', refs: [] } : previous);
      }
      const submitted = submittedTerms.current;
      if (data.type === 'terms_saved' && submitted && submitted.course === data.course_id) {
        if (JSON.stringify(termsRef.current) === JSON.stringify(submitted.rows)) {
          setDirty(false); drafts.current.delete(data.course_id);
        }
        submittedTerms.current = null;
        setSavingTerms(false);
      }
      if (data.type === 'note_saved' && data.request === submittedNote.current && submittedNote.current) {
        submittedNote.current = null; setSavingNote(false); setEditing(null);
      }
      if (data.type === 'error' || data.type === 'disconnected') { submittedTerms.current = null; setSavingTerms(false); submittedNote.current = null; setSavingNote(false); }
      if (data.type === 'disconnected') setConnected(false);
      if (data.type === 'answer') { setAnswer(data); setTab('课堂笔记'); }
      if (data.type === 'usage') setUsage(`本次任务 ${data.requests} 次请求 · ${data.uncertain ? '保守预留' : '已返回用量'} ${data.tokens_or_reserved} tokens`);
      if (data.message) setMessage(data.message);
      if (typeof data.busy === 'boolean') setBusy(data.busy);
    });
    request('knowledge.open').catch(error => setMessage(error.message));
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.isComposing && !event.defaultPrevented && !document.querySelector('[role="dialog"],.popup')) closeAction.current(); };
    document.addEventListener('keydown', escape);
    return () => { unsubscribe?.(); document.removeEventListener('keydown', escape); };
  }, []);
  async function command(operation: string, values: Record<string, unknown> = {}) {
    try { await request('knowledge.command', { operation, values }); return true; }
    catch (error) { setMessage((error as Error).message); return false; }
  }
  function close() {
    if (addingTerm) { setMessage('请先添加或取消当前术语。'); return; }
    if (editing && text !== editing.text) { setMessage('笔记有未保存修改，请先保存或取消编辑。'); return; }
    if (dirty || drafts.current.size) { setMessage('术语有未保存修改，请先保存，或明确放弃修改后关闭。'); return; }
    request('window.edited', { owner: 'knowledge', dirty: false }).then(onClose).catch(error => setMessage(error.message));
  }
  closeAction.current = close;
  const blocks = (view.blocks || []).filter((row: any) => row.evidence_type !== 'visual');
  const block = blocks.find((row: any) => row.id === page) || blocks[0];
  const note = (view.notes || []).find((row: any) => row.id === selectedNote) || view.notes?.[0];
  const visual = (view.blocks || []).find((row: any) => row.id === `${block?.id}:visual`);
  useEffect(() => {
    let current = true;
    setImage(null);
    if (block?.preview_image_path || visual?.image_path) request<string>('knowledge.image', { identifier: visual?.image_path ? visual.id : block.id }).then(value => {
      if (current) setImage(value);
    }).catch(error => { if (current) setMessage(error.message); });
    return () => { current = false; };
  }, [block?.id, block?.preview_image_path, visual?.image_path]);
  useLayoutEffect(() => { if (reading.current) reading.current.scrollTop = 0; }, [block?.id, block?.version, visual?.version]);
  function refs(rows: any[], sources: any) {
    return <div className="reference-list">{rows.map((ref: any, index: number) => {
      const source = sources?.[ref.id];
      return <Button key={`${ref.id}-${index}`} variant="quiet" disabled={!source || active && source.kind === 'caption'} onClick={() => {
        if (source.kind === 'caption') onSeek(source.start || 0);
        else { setPage(ref.id.replace(/^block:/, '').replace(/:visual$/, '')); setTab('课件'); }
      }}>{source?.title || ref.id}{source?.page ? ` · 第 ${source.page} 页` : ''}</Button>;
    })}</div>;
  }
  return <section className="knowledge-window"><header><h2>课件辅助识别 · 有来源的课堂笔记</h2></header>
    <p role="status" className="knowledge-status">{message}</p>
    <div className="knowledge-tabs"><div className="knowledge-toolbar" role="tablist" aria-label="课程内容">{['课件', '识别术语', '课堂笔记'].map(name => <Button key={name} role="tab" id={`knowledge-tab-${name}`} aria-controls="knowledge-content" tabIndex={tab === name ? 0 : -1} aria-selected={tab === name} onKeyDown={event => {
        const names = ['课件', '识别术语', '课堂笔记'], index = names.indexOf(name);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : -1;
        if (next >= 0) { event.preventDefault(); setTab(names[next]); document.getElementById(`knowledge-tab-${names[next]}`)?.focus(); }
      }} onClick={() => setTab(name)}>{name}</Button>)}</div>
    <div className="knowledge-body" role="tabpanel" id="knowledge-content" aria-labelledby={`knowledge-tab-${tab}`}>{tab === '课件' && <>
      <div className="knowledge-row"><span>关联课程</span><Choice label="关联课程" value={association || '__none'} options={view.course_options?.length ? view.course_options.map((row: any) => ({ value: row.id, label: row.name })) : [{value:'__none',label:'尚未关联课程'}]} disabled={active || busy} onChange={setAssociation} /><Button disabled={active || busy || !association} onClick={() => command('associate', { folder_id: association })}>使用此课程</Button></div>
      <div className="knowledge-row"><Button disabled={active || busy} onClick={() => command('import')}>导入课件</Button><Button disabled={active || busy || !blocks.length} onClick={() => command('preview')}>准备本地原页</Button><Choice label="课件页" disabled={!blocks.length} value={block?.id || '__none'} options={blocks.length ? blocks.map((row: any) => ({ value: row.id, label: `${row.title} · 第 ${row.page} 页` })) : [{value:'__none',label:' '}]} onChange={setPage} /></div>
      <div className="material-reading" ref={reading}>{image && <img className="material-image" src={image} alt={`课件原页 ${block?.page || ''}`} />}
      {visual && <><h3>页面视觉解读（模型生成，需核对）</h3><div className="document-text">{visual.text}</div>{visual.preview_truncated && <p className="muted">文字预览；完整解读用于检索和笔记。</p>}</>}
      {block && <h3>原生文字</h3>}<div className="document-text">{block?.text || '先导入本课程课件。'}</div></div>
      <label className="knowledge-permission"><input type="checkbox" aria-label="允许云端读取课件图像" disabled={busy} checked={!!view.course?.material_images_cloud} onChange={event => command('permission', { materials: event.target.checked, notes: !!view.manifest?.notes_cloud })} />允许将本课程的页面图像和文字发送给 DeepSeek，完整阅读课件</label>
      <Button disabled={active || busy || !view.course?.material_images_cloud} onClick={() => command('extract')}>完整阅读并提取术语</Button>
    </>}
    {tab === '识别术语' && <><p>完整阅读会逐页查看课件，包括图表、公式和无文字页。模型解读仍需核对；候选术语勾选并保存后才用于 Qwen。</p>
      <div className="term-table"><table><thead><tr><th>使用</th><th>术语</th><th>别名（以 ; 分隔）</th></tr></thead><tbody>{terms.map((term, index) => <tr key={index} className={selectedTerms.includes(index) ? 'selected' : ''} onClick={event => {
          if (event.shiftKey) setSelectedTerms(terms.map((_, i) => i).filter(i => i >= Math.min(index, selectionAnchor.current) && i <= Math.max(index, selectionAnchor.current)));
          else if (event.metaKey || event.ctrlKey) { setSelectedTerms(old => old.includes(index) ? old.filter(i => i !== index) : [...old, index]); selectionAnchor.current = index; }
          else { setSelectedTerms([index]); selectionAnchor.current = index; }
        }}>
        <td title={term.origin === 'manual' ? '手动添加' : `课件来源：${term.evidence_ids.join('、')}`}><input type="checkbox" aria-label={`已审核 ${term.canonical}`} disabled={active || busy} checked={term.approved} onChange={event => { setTerms(terms.map((row,i) => i === index ? {...row,approved:event.target.checked} : row)); setDirty(true); }} /></td>
        <td><input aria-label={`术语 ${index + 1}`} disabled={active || busy} value={term.canonical} onChange={event => { setTerms(terms.map((row, i) => i === index ? { ...row, canonical: event.target.value } : row)); setDirty(true); }} /></td>
        <td><input aria-label={`别名 ${index + 1}`} disabled={active || busy} value={term.aliasesText ?? term.aliases.join('; ')} onChange={event => { setTerms(terms.map((row, i) => i === index ? { ...row, aliasesText: event.target.value } : row)); setDirty(true); }} /></td>
      </tr>)}</tbody></table></div>
      <div className="knowledge-row equal"><Button disabled={active || busy} onClick={() => setAddingTerm(true)}>添加术语</Button>
        <Button disabled={active || busy || !selectedTerms.length} onClick={() => { setTerms(terms.filter((_,i) => !selectedTerms.includes(i))); setSelectedTerms([]); setDirty(true); }}>移除选中</Button>
        <Button disabled={active || busy || savingTerms || !dirty} onClick={async () => {
          // A sent command is not a save receipt. Retain edits until matching confirmation.
          if (submittedTerms.current) return;
          submittedTerms.current = { course: course.current, rows: structuredClone(terms) }; setSavingTerms(true);
          if (!await command('terms', { terms: terms.map(({ aliasesText, ...term }) => ({ ...term, aliases: aliasesText === undefined ? term.aliases : aliasesText.split(';').map(value => value.trim()).filter(Boolean) })), course_id: course.current })) { submittedTerms.current = null; setSavingTerms(false); }
        }}>{savingTerms ? '正在保存…' : '保存审核结果'}</Button></div>
      <p>已审核 {view.manifest?.asr_context?.terms?.length || 0} 个术语/别名，用于下一次 Qwen 录音。录音开始后固定，不保证识别准确率提升。</p>
    </>}
    {tab === '课堂笔记' && <>{view.automatic_paused && <p className="error">自动笔记已暂停，请检查上方提示，处理后点击更新笔记重试。</p>}
      <label className="knowledge-permission"><input type="checkbox" aria-label="允许云端处理已保存文字" disabled={busy} checked={!!view.manifest?.notes_cloud} onChange={event => command('permission', { materials: !!view.course?.material_images_cloud, notes: event.target.checked })} />允许 DeepSeek 处理本段录音的文字，生成笔记与回答</label>
      <p>发送已保存定稿、相关课件和笔记文字；允许课件页面上传时，可重新查看相关页图像。不上传录音。关闭许可后停止后续请求；已发送内容无法撤回。</p>
      <div className="knowledge-row"><span>课后整理范围</span><Choice label="课后整理范围" value={section || '__all'} options={[{ value: '__all', label: '全课（过长时请选章节）' }, ...[...new Set<string>((view.notes || []).map((note: any) => note.section).filter(Boolean))].map(value => ({ value, label: value }))]} onChange={value => setSection(value === '__all' ? '' : value)} /></div>
      {!!view.notes?.length && <div className="note-list" role="listbox" aria-label="课堂笔记列表">{view.notes.map((row: any) => <button key={row.id} role="option" aria-selected={row.id === note?.id} className={row.id === note?.id ? 'selected' : ''} onClick={() => { setSelectedNote(row.id); setAnswer(null); }}>{row.section} · {{valid:'已核对',pending:'待核对新讲述',stale:'来源已变化'}[row.status as string]}{row.user_locked ? ' · 个人编辑' : ''}<br />{row.text.slice(0,75)}</button>)}</div>}
      <article className="note">{answer ? <><h3>模型回答（请结合引用核对）</h3><div className="document-text">{answer.answer}</div>{refs(answer.refs || [], answer.sources || view.sources)}</> : note ? <><h3>{note.section}</h3><p>{note.user_locked ? '个人编辑' : note.origin === 'material' ? '课件内容' : '课堂讲述'}</p>{note.status !== 'valid' && <p className="error">来源或后续讲述已变化，请重新核对。</p>}<div className="document-text">{note.text}</div>{refs(note.refs || [], view.sources)}</> : '暂无笔记。允许云端处理后，已保存的定稿原文会分批生成带引用笔记。'}</article>
      <div className="knowledge-row equal"><Button disabled={busy || !view.manifest?.notes_cloud} onClick={() => command('notes')}>更新笔记</Button><Button disabled={active || busy || !view.manifest?.notes_cloud} onClick={() => command('organize', { section })}>课后整理</Button><Button disabled={busy || !note || !!answer} onClick={() => { setEditing({ ...note, recording: view.manifest?.session_id }); setText(note.text); }}>个人编辑</Button><Button disabled={busy} onClick={() => command('export')}>保存笔记文件</Button></div>
      <div className="question"><input maxLength={800} aria-label="课程问题" value={question} onChange={event => setQuestion(event.target.value)} placeholder="针对本次课程提问…" /><Button disabled={active || busy || !view.manifest?.notes_cloud || !question.trim()} onClick={() => command('question', { question })}>提问</Button></div>
    </>}
    </div></div><footer className="knowledge-footer">{!connected && <Button onClick={() => request('knowledge.open').catch(error => setMessage(error.message))}>重新连接</Button>}<Button onClick={() => setCredential('')}>配置 DeepSeek 密钥</Button><span>{usage || '云端任务按输入与调用次数限额；不会上传录音。'}</span><Button disabled={!taskBusy} onClick={() => command('cancel')}>取消任务</Button></footer>
    {(dirty || drafts.current.size > 0) && <div className="knowledge-close"><Button onClick={async () => { drafts.current.clear(); setTerms(view.course?.terms || []); setDirty(false); await request('window.edited', { owner: 'knowledge', dirty: false }); onClose(); }}>放弃未保存的术语并关闭</Button></div>}
    {addingTerm && <EditDialog trackEdit={false} title="添加术语" onClose={() => setAddingTerm(false)} onSave={async canonical => {
      if (!canonical.trim()) throw new Error('请输入术语。');
      setTerms(old => [...old, { canonical: canonical.trim(), aliases: [], evidence_ids: [], approved: true, origin: 'manual' }]);
      setSelectedTerms([terms.length]); setDirty(true);
    }} />}
    {credential !== null && <Modal title="DeepSeek API 密钥" description="保存到系统凭据存储，不写入课程文件。" open onClose={() => setCredential(null)} actions={<><Button onClick={() => setCredential(null)}>取消</Button><Button onClick={async () => { if (credential.trim() && await command('credential', { value: credential.trim() })) setCredential(null); }}>保存</Button></>}><input type="password" aria-label="API 密钥" value={credential} onChange={event => setCredential(event.target.value)} autoComplete="off" /></Modal>}
    {editing && <Modal title="个人编辑" description="保存后，自动整理会保留你的内容。" open onClose={() => { if (!savingNote) setEditing(null); }} actions={<><Button disabled={savingNote} onClick={() => setEditing(null)}>取消</Button><Button disabled={savingNote || busy || editing.recording !== view.manifest?.session_id} onClick={async () => {
      const receipt = crypto.randomUUID(); submittedNote.current = receipt; setSavingNote(true);
      if (!await command('edit', { id: editing.id, text, request: receipt })) { submittedNote.current = null; setSavingNote(false); }
    }}>{savingNote ? '正在保存…' : '保存'}</Button></>}>{editing.recording !== view.manifest?.session_id && <p className="error">当前录音已变化。编辑内容仍保留，请返回原录音后保存，或取消编辑。</p>}<textarea aria-label="笔记内容" disabled={savingNote} value={text} onChange={event => setText(event.target.value)} rows={12} /></Modal>}
  </section>;
}


export function KnowledgeWindow() {
  const [active, setActive] = useState(false), [error, setError] = useState('');
  const generation = useRef<number | null>(null);
  useEffect(() => {
    function state(value: Bootstrap['state'], reopen: boolean) {
      setActive(value.state !== 'IDLE');
      if (generation.current !== value.generation && reopen && value.item) request('knowledge.open').catch(error => setError(error.message));
      generation.current = value.generation;
    }
    function settings(value: Bootstrap['settings']) {
      document.documentElement.dataset.theme = String(value.appearance);
      document.documentElement.dataset.reducedMotion = String(!!value.reduce_motion);
    }
    request<Bootstrap>('bootstrap').then(value => { settings(value.settings); state(value.state, false); }).catch(error => setError(error.message));
    return bridge?.subscribe(({ event, data }) => {
      if (event === 'settings') settings(data);
      if (event === 'state') state(data, true);
      if (event === 'knowledge' && data.type === 'view') setError('');
    });
  }, []);
  return <>{error && <p className="error" role="alert">{error}</p>}<Knowledge active={active} onClose={() => request('knowledge.dismiss').catch(error => setError(error.message))}
    onSeek={seconds => request('knowledge.locate', { seconds }).catch(error => setError(error.message))} /></>;
}
