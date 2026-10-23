import { useEffect, useState } from 'react';
import { usePageTransition } from './motion';
import { Button, Choice, ConfirmDialog, Modal, SettingsRow, Toggle } from './components';
import { bridge, request, type Bootstrap, type Settings, type State } from './types';

const categories = ['常规', '聆听', '模型管理', '字幕与延迟', '运行环境', '使用指南'];
const backendNames: Record<string, string> = { 'wlk-whisper': 'WhisperLiveKit · Whisper / AlignAtt', 'qwen3-streaming': 'WhisperLiveKit · Qwen3-ASR 流式', 'qwen3-mlx': 'Qwen3-ASR · MLX（试验）' };
const deviceNames: Record<string, string> = { cpu: 'CPU（通用）', cuda: 'NVIDIA GPU · 半精度', mlx: 'Apple GPU · Metal / MLX', metal: 'Apple GPU · Metal' };

export function SettingsPage({ data, values, state, switchDisabled, updatesBusy, onClose, onDeleted, perform, onPatch, onCategory, initialCategory = '常规' }: {
  data: Bootstrap; values: Settings; state: State; switchDisabled: boolean; updatesBusy: boolean; onClose: () => void; onDeleted: () => void;
  perform: (method: string, params?: Record<string, unknown>) => Promise<any>;
  onPatch: (values: Settings) => void; onCategory?: (category: string) => void; initialCategory?: string;
}) {
  const [category, setCategory] = useState(initialCategory), [query, setQuery] = useState('');
  useEffect(() => { onCategory?.(category); }, [category, onCategory]);
  const [advanced, setAdvanced] = useState(false);
  const [inventory, setInventory] = useState<any[]>([]), [checking, setChecking] = useState(false), [loaded, setLoaded] = useState(false), [deleting, setDeleting] = useState<any>(null);
  const [selectedId, setSelectedId] = useState(''), [inventoryMessage, setInventoryMessage] = useState('');
  const [catalog, setCatalog] = useState(false), [modelEditor, setModelEditor] = useState<{ kind: 'asr' | 'translation'; entry?: any } | null>(null);
  const [modelCheck, setModelCheck] = useState(''), [updateAvailable, setUpdateAvailable] = useState(false);
  const pageTransition = usePageTransition(category);
  useEffect(() => bridge?.subscribe(({ event, data }) => {
    if (event === 'inventory') { setChecking(data.busy); if (data.result) { setInventory(data.result); setLoaded(true); setSelectedId(data.result[0]?.id || ''); } }
    if (event === 'updates' && data.result) setUpdateAvailable(!!data.result.url);
    if (event === 'model-check') setModelCheck(data.error || data.message || '');
  }), []);
  useEffect(() => { if (category === '模型管理') perform('models.inventory'); }, [category]);
  const active = state.state !== 'IDLE', selected = inventory.find(model => model.id === selectedId);
  function choices(label: string, key: string, options: { value: string; label: string }[]) {
    return <Choice label={label} value={String(values[key])} options={options} onChange={value => onPatch({ [key]: value })} />;
  }
  const languages = data.options.languages.map(row => ({ value: row[0], label: row[0] }));
  const aliases: Record<string, string> = { '模型管理': '下载 缓存 删除 ASR 翻译 Qwen HY-MT2 Whisper 本地 参数 前文 后文 GPU CPU MLX NLLB', '常规': '文件 存储 目录 路径 删除 恢复 跟随 动画 减少动态效果 外观 保存位置 Beta', '聆听': '设备 输入 语言 翻译', '字幕与延迟': '字幕 草稿 刷新 停顿', '运行环境': '安装 修复 更新 版本 GitHub 准备 取消 重试 界面 前端 切换 Qt Electron', '使用指南': '首次 使用 帮助 入门 导出 SRT 开始 说明' };
  const descriptions: Record<string, string> = { '常规': '管理本地录音、保存位置和使用习惯。', '聆听': '从哪里听、听什么语言，以及你想看到的译文。', '模型管理': '查看、设置或删除已下载的识别与翻译模型。', '字幕与延迟': '调整识别请求频率与计算量；实际草稿速度取决于模型，不直接控制字幕定稿。', '运行环境': '准备本地组件、修复运行环境和检查软件更新。', '使用指南': '从第一次聆听，到整理和分享你的录音。' };
  const visibleCategories = categories.filter(value => query.trim().toLowerCase().split(/\s+/).every(term => (value + ' ' + aliases[value]).toLowerCase().includes(term)));
  const firstMatch = visibleCategories[0], categoryVisible = visibleCategories.includes(category);
  useEffect(() => { if (firstMatch && !categoryVisible) setCategory(firstMatch); }, [firstMatch, categoryVisible]);
  function inspect(model: any) {
    const reason = model.kind === 'alignment' ? '此模型用于时间戳对齐，当前识别流程不加载它，不能选作识别模型。'
      : model.kind === 'asr' ? (data.options.backends.includes(model.engine) ? '' : '这个识别模型的引擎不适用于当前平台。')
      : model.kind === 'translation' && ['llama', 'pytorch'].includes(model.engine) ? '' : '此模型不能用于当前识别或翻译流程。';
    if (reason) setInventoryMessage(reason); else setModelEditor({ kind: model.kind, entry: model });
  }
  function role(kind: 'asr' | 'translation', label: string) {
    const engine = String(values[kind === 'asr' ? 'backend' : 'translation_engine']);
    const modelPath = String(values[kind === 'asr' ? engine === 'wlk-whisper' ? 'asr' : 'qwen_model' : engine === 'llama' ? 'llama_model' : 'translation']);
    const current = inventory.find(model => model.engine === engine && [model.path, model.selection].includes(modelPath));
    return <div className="model-role"><label>{label}</label><Choice label={`${label}模型`} disabled={active} value="current" options={[
      { value: 'current', label: current?.name || modelPath.replaceAll('\\', '/').split('/').pop() + (loaded ? ' · 已选择，未在本地找到' : ' · 当前选择') },
      ...inventory.filter(model => model.kind === kind && model.id !== current?.id && (kind !== 'asr' || data.options.backends.includes(model.engine))).map(model => ({ value: model.id, label: model.name })),
      { value: 'settings', label: '模型设置…' },
    ]} onChange={value => { if (value === 'settings') setModelEditor({ kind }); else { const model = inventory.find(row => row.id === value); if (model) onPatch({ [kind === 'asr' ? 'backend' : 'translation_engine']: model.engine, [kind === 'asr' ? model.engine === 'wlk-whisper' ? 'asr' : 'qwen_model' : model.engine === 'llama' ? 'llama_model' : 'translation']: model.path, ...(kind === 'asr' ? {compute: modelDevice(data,kind,model.engine,values.compute)} : {translation_device: modelDevice(data,kind,model.engine,values.translation_device)}) }); } }} /></div>;
  }
  return <div className="settings-page"><aside className="settings-nav"><Button variant="quiet" onClick={onClose}>←  返回录音</Button>
    <input aria-label="搜索设置" placeholder="搜索设置…" value={query} onChange={e => setQuery(e.target.value)} />
    <p className="settings-eyebrow">工作空间</p><nav>{visibleCategories.map(value => <Button key={value} variant="quiet" className={category === value ? 'selected' : ''} onClick={() => setCategory(value)}>{value}</Button>)}</nav>
    <p className="settings-footnote">更改将用于下一次录音</p>
  </aside><section className="settings-content"><header><h1>{visibleCategories.length ? category : '搜索设置'}</h1><p>{visibleCategories.length ? descriptions[category] : ''}</p></header>
    {!visibleCategories.length && <div className="settings-empty"><h2>没有找到这个设置</h2><p>试试「字幕」「GPU」「保存位置」或「翻译」。</p><Button onClick={() => setQuery('')}>清除搜索</Button></div>}
    <div className="settings-scroll" hidden={!visibleCategories.length}><div className={`settings-page-body ${category === '模型管理' ? 'models-page' : ''}`} ref={pageTransition}>
    {category === '常规' && <><h3>文件与存储</h3><div className="settings-group">
      <SettingsRow title="录音保存位置" hint={data.root}><Button onClick={() => perform('path.reveal')}>打开</Button><Button disabled={state.migrating} onClick={() => perform('library.migrate')}>更改…</Button>{state.migrating && <Button onClick={() => perform('library.cancel_migration')}>取消迁移</Button>}</SettingsRow>
      <SettingsRow title="最近删除" hint="删除的文件先保留在录音目录的「垃圾桶」文件夹，可随时恢复。"><Button onClick={onDeleted}>查看最近删除</Button></SettingsRow>
      </div><h3 className="section-spaced">使用习惯</h3><div className="settings-group">
      <SettingsRow title="外观" hint="白色或深色，切换后立即生效。">{choices('外观', 'appearance', [{ value: 'light', label: '白色' }, { value: 'dark', label: '深色' }])}</SettingsRow>
      <SettingsRow title="减少动态效果" hint="关闭平滑跟随、切页、弹窗和开关动画。"><Toggle label="减少动态效果" value={!!values.reduce_motion} onChange={value => onPatch({ reduce_motion: value })} /></SettingsRow>
      <SettingsRow title="体验 Beta 功能" hint="开启后显示课件解析、识别提示整理和课堂笔记入口。关闭会停止相关任务，已有资料保留。"><Toggle label="课程助手 Beta" value={!!values.beta_features} onChange={value => onPatch({ beta_features: value })} /></SettingsRow>
    </div></>}
    {category === '聆听' && <><h3>输入与语言</h3><div className="settings-group">
      <SettingsRow title="音频来源" hint={data.platform === 'darwin' ? '电脑声音选择“系统音频”。首次使用时需允许系统录制权限。' : '选择麦克风或正在播放声音的设备。'}><Choice label="音频来源" className="audio-device-choice" disabled={data.no_audio || !['IDLE', 'LISTENING', 'PAUSED'].includes(state.state)} value={data.device ? JSON.stringify(data.device) : ''} options={data.devices.map(device => ({ value: JSON.stringify([device.id, device.loopback]), label: device.name }))} onChange={value => { const [identifier, loopback] = JSON.parse(value); perform('audio.select', { identifier, loopback }); }} /></SettingsRow>
      <SettingsRow title="设备列表" hint="连接新设备后刷新。"><Button disabled={data.no_audio} onClick={() => perform('audio.refresh')}>刷新设备</Button></SettingsRow>
      <SettingsRow title="原文语言" hint="Qwen 需要明确选择原文语言。">{choices('原文语言', 'source', [...(values.backend === 'wlk-whisper' ? [{ value: '自动检测', label: '自动检测' }] : []), ...languages])}</SettingsRow>
      <SettingsRow title="翻译语言" hint="选择定稿与实时译文使用的语言。">{choices('翻译为', 'target', languages)}</SettingsRow>
      <SettingsRow title="启用翻译" hint="开启本地翻译并保存译文；关闭后仅识别和保存原文。"><Toggle label="启用翻译" disabled={!state.translation_available} value={!!values.translate && state.translation_available} onChange={value => onPatch({ translate: value })} /></SettingsRow>
    </div></>}
    {category === '模型管理' && <><div className="settings-actions"><Button disabled={active} onClick={() => setCatalog(true)}>下载模型…</Button></div>
      <div className="model-roles">{role('asr', '语音识别')}{role('translation', '翻译')}</div>
      {(checking || inventoryMessage || !inventory.length) && <p className="inventory-status" role="status">{checking ? '正在读取本地模型…' : inventoryMessage || (inventory.length ? '双击模型可查看引擎与参数；使用模型需在窗口中确认。' : '还没有下载模型。点击“下载模型”选择一个模型，或直接下载推荐组合。')}</p>}
      <div className="model-inventory" role="listbox" aria-label="本地模型">{inventory.map(model => <button key={model.id} role="option" aria-selected={selectedId === model.id} className={selectedId === model.id ? 'selected' : ''} title={model.path} onClick={() => setSelectedId(model.id)} onDoubleClick={() => inspect(model)} onKeyDown={event => { if (event.key === 'Enter') inspect(model); }}>
        <span>{{ asr: '识别', translation: '翻译', alignment: '时间对齐 · 当前流程未使用' }[model.kind as string] || '模型'}  ·  {model.name}</span><span>{backendNames[model.engine] || model.engine || '独立组件'} · {(model.size / 1024 ** 3).toFixed(2)} GB</span>
      </button>)}</div>
      <div className="settings-actions"><Button disabled={checking} onClick={() => perform('models.inventory')}>刷新</Button><Button variant="danger" disabled={!selected?.deletable || active || checking || state.preparing} onClick={() => setDeleting(selected)}>删除模型</Button></div>
      <Button className="fit-button" variant="primary" disabled={active || state.preparing} onClick={() => perform('models.prepare')}>检查 / 补齐当前模型</Button>
      {modelCheck && <p role="status">{modelCheck}</p>}
    </>}
    {category === '字幕与延迟' && <div className="settings-form"><p className="muted">沿用当前识别参数。以下时间是请求与停顿检测目标，不是动态窗口长度，也不保证实际刷新速度。</p><Button aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级参数' : '显示高级参数'}</Button>
      {advanced && [['update_seconds', '音频合并间隔'], ['draft_seconds', 'Qwen 原文草稿刷新目标'], ['endpoint_seconds', 'ASR 停顿检测（不直接定稿）']].map(([key, title]) => <div className="parameter-field" key={key}><label htmlFor={key}>{title}</label><div className="number-field"><input id={key} title={parameterHelp[key]} type="number" min={key === 'draft_seconds' ? .25 : .5} max={3} step={key === 'draft_seconds' ? .25 : .5} defaultValue={Number(values[key])} onBlur={event => { if (event.target.checkValidity()) onPatch({ [key]: Number(event.target.value) }); }} /><span>秒</span></div></div>)}
      {advanced && <p className="muted">默认保持流畅且不过度占用计算资源；更小的间隔可能增加负载，不保证实际刷新速度。</p>}
    </div>}
    {category === '运行环境' && <div className="settings-form"><h3>本地推理组件</h3><p>统一检查识别与翻译所需组件；缺失或损坏时自动修复。</p>
      <Button disabled={active || state.preparing} onClick={() => perform('models.prepare', { kind: 'runtime' })}>检查 / 修复运行环境</Button>
      {!!values.beta_features && <Button disabled={active || state.preparing} onClick={() => perform('models.prepare', { kind: 'documents' })}>安装 / 修复课件渲染组件</Button>}
      <p>桌面界面与模型推理使用独立环境。无需手动启动服务。统一检查所需组件，补齐或重建损坏环境，并清理未发布的残留环境。模型在模型管理中准备。</p>
      <h3>版本与更新</h3><p>当前版本：{data.version}</p><Button disabled={updatesBusy} onClick={() => perform('updates.check')}>{updatesBusy ? '正在检查…' : data.installed ? '切换到 Qt 检查更新' : '检查软件更新'}</Button>
      <p className="muted">{data.installed ? '检查适用于此平台的新版本；录音结束并保存后，再确认重启安装。' : '当前为源码运行，请到发行页查看对应源码；更新前保留本地修改。'}</p>{updateAvailable && <Button className="fit-button" variant="quiet" onClick={() => perform('app.releases')}>查看发行页</Button>}
      <h3>界面</h3><Button disabled={switchDisabled} onClick={() => perform('frontend.switch')}>切换到 Qt 界面</Button>
    </div>}
    {['运行环境', '模型管理'].includes(category) && (state.preparation_status || state.preparing) && <div className="preparation" role="status">
      <div className="settings-actions"><h3>准备本地模型</h3>{state.preparing && <Button disabled={state.preparation_cancelling} onClick={() => perform('models.cancel')}>取消准备</Button>}{state.preparation_recovery && <Button disabled={active || state.preparing} onClick={() => perform('models.retry')}>{state.preparation_recovery}</Button>}</div>
      <p>{state.preparation_status}</p>{state.preparing && <progress {...(Number(state.progress?.total) > 0 ? { value: Number(state.progress?.completed || 0), max: Number(state.progress?.total) } : {})} />}{state.progress && <p>{progressText(state.progress)}</p>}
    </div>}
    {category === '使用指南' && <><h3>第一次使用</h3><div className="settings-group">{[
      ['01  准备本地模型', '首次安装运行环境，再下载 / 检查识别模型；必要组件会一起准备。', '运行环境', '准备环境'],
      ['02  选择音频与语言', '选择麦克风或系统声音。使用 Qwen 时，指定原文语言。', '聆听', '设置聆听'],
      ['03  按需开启翻译', '选择翻译模型和目标语言；只需要原文时，可关闭翻译。', '模型管理', '设置翻译'],
    ].map(([title, hint, target, action]) => <SettingsRow key={title} title={title} hint={hint}><Button onClick={() => setCategory(target)}>{action}  →</Button></SettingsRow>)}</div>
      <h3>聆听中的文字会发生什么？</h3><p className="info-banner">识别到的原文会先显示出来，后续可能随上下文修订。<br /><br />标注“优化中”的内容仍可能变化；显示“已定稿”后，该段原文已确认。启用翻译时，译文会随后补充并更新，等待期间保留已有文字。<br /><br />暂停会停止收音，并继续处理已收到的内容；点击“继续录音”可接着录，暂停时间不计入录音。停止聆听后仍需处理剩余内容，请等待收尾完成。</p>
      <h3>录音结束以后</h3><p className="muted">从侧栏打开录音，可回听音频或导出双语 SRT、TXT 和 Markdown。使用「···」重命名、移动或打开保存位置；删除的录音先进入「最近删除」，可在那里恢复。</p><Button className="fit-button" variant="quiet" onClick={() => request('app.help')}>打开完整使用指南</Button>
    </>}
    </div></div>
    {catalog && <ModelCatalog data={data} values={values} disabled={active || state.preparing || checking} onClose={() => setCatalog(false)} onAdvanced={() => { setCatalog(false); setModelEditor({ kind: 'asr' }); }} />}
    {modelEditor && <ModelEditor key={`${modelEditor.kind}-${modelEditor.entry?.id || ''}`} kind={modelEditor.kind} entry={modelEditor.entry} data={data} values={values} disabled={active || state.preparing || checking} onClose={() => setModelEditor(null)} />}
    {deleting && <ConfirmDialog title={`删除“${deleting.name}”缓存？`} description="只删除应用管理的模型缓存，不删除录音。下次使用前需要重新下载。" confirm="删除缓存" onClose={() => setDeleting(null)} onConfirm={() => request('models.delete', { identifier: deleting.id })} />}
  </section></div>;
}

const modelHints: Record<string, string> = {
  llama: 'Q4_K_M 是 4-bit 量化。可选目录中的版本，或输入 hf://作者/仓库/文件.gguf 下载。自选 GGUF 需要兼容当前 llama.cpp 和翻译提示词；下载完成不等于推理已验收。',
  'qwen3-mlx': 'MLX 识别需要 Apple Silicon Mac；8-bit 尚待实机验收。',
  'qwen3-streaming': '使用 Qwen3-ASR 原始权重、兼容仓库 ID 或本地目录。当前 Windows 识别后端不支持 MLX 4-bit 权重。',
  'wlk-whisper': '选择 Whisper 模型大小，或导入兼容的原始 .pt 权重。',
  pytorch: '选择 HY-MT2 / NLLB 模型，也可输入兼容仓库 ID 或本地目录。量化 GGUF 请切换到 llama.cpp。',
};
const parameterHelp: Record<string, string> = {
  update_seconds: '请求识别前合并新音频的目标；当草稿刷新目标更短时优先采用草稿目标。不是上下文窗口长度，也不是承诺的字幕刷新频率。',
  draft_seconds: '更小值更早请求原文草稿，也会增加计算量。实际更新受模型速度限制；逐字显示只影响呈现，不改变识别、翻译和保存时机。草稿优先于较长的音频合并间隔。',
  endpoint_seconds: 'Qwen：连续静音达到该时间后才结束语音段，保留犹豫和短停顿的上下文。Whisper 保留原有检测节奏，此值仅辅助上游分段。两者都不直接决定字幕定稿。',
};

function ModelField({ value, options, label, onChange }: { value: string; options: [string, string][]; label: string; onChange: (value: string) => void }) {
  const [custom, setCustom] = useState(false), [draft, setDraft] = useState(value);
  return <div className="model-field">{custom ? <><input aria-label={label} value={draft} onChange={event => setDraft(event.target.value)} /><Button onClick={() => { if (draft.trim()) { onChange(draft.trim()); setCustom(false); } }}>应用</Button><Button onClick={() => setCustom(false)}>取消</Button></> : <>
    <Choice label={label} value={value} options={[...options.map(([label, value]) => ({ value, label })), ...(!options.some(row => row[1] === value) && value ? [{ value, label: value }] : [])]} onChange={onChange} />
    <Button variant="quiet" onClick={() => { setDraft(value); setCustom(true); }}>自定义</Button></>}</div>;
}


function selection(values: Settings) {
  return { backend: String(values.backend), asr_model: String(values[values.backend === 'wlk-whisper' ? 'asr' : 'qwen_model']), translation_engine: String(values.translation_engine), translation_model: String(values[values.translation_engine === 'llama' ? 'llama_model' : 'translation']), translation_device: String(values.translation_device) };
}

function ModelCatalog({ data, values, disabled, onClose, onAdvanced }: { data: Bootstrap; values: Settings; disabled: boolean; onClose: () => void; onAdvanced: () => void }) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  // Opening the catalogue freezes its original selection; retry uses the same backend snapshot.
  const [original] = useState(() => selection(values));
  async function download(kind: string, engine: string, model: string, bundle = false) {
    setBusy(true); setError('');
    try {
      const snapshot = { ...original, ...(kind === 'asr' ? { backend: engine, asr_model: model } : { translation_engine: engine, translation_model: model }) };
      snapshot.translation_device = modelDevice(data, 'translation', snapshot.translation_engine, snapshot.translation_device);
      if (bundle) {
        snapshot.backend = data.options.recommended.backend; snapshot.asr_model = data.options.recommended.asr_model;
        await request('settings.set', { values: { compute: modelDevice(data, 'asr', snapshot.backend, values.compute), backend: snapshot.backend, [snapshot.backend === 'wlk-whisper' ? 'asr' : 'qwen_model']: snapshot.asr_model, translation_device: snapshot.translation_device, translation_engine: snapshot.translation_engine, [snapshot.translation_engine === 'llama' ? 'llama_model' : 'translation']: snapshot.translation_model } });
      }
      await request('models.prepare', { selection: snapshot, only: bundle ? 'all' : kind }); onClose();
    } catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  return <Modal width={588} title="下载模型" description="选择模型即可下载，无需设置运行参数。已下载的模型会自动复用。" open onClose={() => { if (!busy) onClose(); }} actions={<><Button className="catalog-advanced" variant="quiet" disabled={busy} onClick={onAdvanced}>高级…</Button><Button variant="primary" disabled={disabled || busy} onClick={() => download('translation', data.options.recommended.translation_engine, data.options.recommended.translation_model, true)}>下载并使用推荐组合</Button></>}>
    <div className="catalog-items">{data.options.downloads.map(([title, hint, kind, engine, model]) => <SettingsRow key={`${engine}-${model}`} title={title} hint={hint}><Button disabled={disabled || busy} onClick={() => download(kind,engine,model)}>下载</Button></SettingsRow>)}</div>
    {data.platform !== 'darwin' && <p className="muted">Windows 的 Qwen 4-bit / 8-bit 识别尚未接入，当前提供原始版本。</p>}
    <div className="catalog-recommended"><h3>推荐组合</h3><p>{data.options.downloads[0]?.[0]}  +  {data.options.downloads.at(-1)?.[0]}</p><p className="muted">一次备齐识别和翻译，并设为下一次聆听使用的模型。</p></div>
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}

function modelDevices(data: Bootstrap, kind: 'asr' | 'translation', engine: string) {
  return kind === 'asr' ? engine === 'qwen3-mlx' ? ['mlx'] : data.options.devices : data.options.translation_devices[engine];
}

function modelDevice(data: Bootstrap, kind: 'asr' | 'translation', engine: string, current: unknown) {
  const choices = modelDevices(data, kind, engine).map(device => kind === 'asr' ? deviceNames[device] : device);
  return choices.includes(String(current)) ? String(current) : choices[0];
}

function ModelEditor({ kind, entry, data, values, disabled, onClose }: { kind: 'asr' | 'translation'; entry?: any; data: Bootstrap; values: Settings; disabled: boolean; onClose: () => void }) {
  const [draft, setDraft] = useState<Settings>(() => {
    const initial: Settings = { ...values, ...(entry ? kind === 'asr' ? { backend: entry.engine, [entry.engine === 'wlk-whisper' ? 'asr' : 'qwen_model']: entry.path } : { translation_engine: entry.engine, [entry.engine === 'llama' ? 'llama_model' : 'translation']: entry.path } : {}) };
    const engine = String(initial[kind === 'asr' ? 'backend' : 'translation_engine']);
    const deviceKey = kind === 'asr' ? 'compute' : 'translation_device';
    initial[deviceKey] = modelDevice(data, kind, engine, initial[deviceKey]);
    return initial;
  });
  const [advanced, setAdvanced] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const engine = String(draft[kind === 'asr' ? 'backend' : 'translation_engine']);
  const modelKey = kind === 'asr' ? engine === 'wlk-whisper' ? 'asr' : 'qwen_model' : engine === 'llama' ? 'llama_model' : 'translation';
  const deviceKey = kind === 'asr' ? 'compute' : 'translation_device';
  const devices = modelDevices(data, kind, engine);
  const patch = (value: Settings) => setDraft(old => ({ ...old, ...value }));
  async function submit(download: boolean) {
    setBusy(true); setError('');
    try {
      if (download) await request('models.prepare', { only: kind, selection: selection(draft) });
      else {
        const keys = kind === 'asr' ? ['backend', modelKey, 'compute', 'draft_seconds', 'update_seconds', 'endpoint_seconds'] : ['translation_engine', modelKey, 'translation_device'];
        await request('settings.set', { values: Object.fromEntries(keys.map(key => [key, draft[key]])) });
      }
      onClose();
    } catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  return <Modal width={588} title={entry?.name || '模型设置'} description="点击使用后，用于下一次聆听。" open onClose={() => { if (!busy) onClose(); }} actions={<><Button disabled={busy} onClick={onClose}>取消</Button><Button variant="primary" disabled={busy} onClick={() => submit(false)}>使用此模型</Button></>}>
    <div className={`model-editor-body ${advanced ? 'advanced' : ''}`}>{entry && <p className="muted">本地文件 · {(entry.size / 1024 ** 3).toFixed(2)} GB · {entry.path}</p>}
    <p>{kind === 'asr' ? '语音识别' : '翻译'} · {backendNames[engine] || engine} · {String(draft[modelKey])}</p>
    <Button variant="quiet" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级设置' : '高级设置…'}</Button>
    {advanced && <><SettingsRow title="对应引擎"><Choice label="对应引擎" value={engine} options={(kind === 'asr' ? data.options.backends : ['llama', 'pytorch']).map(value => ({ value, label: backendNames[value] || value }))} onChange={value => {
      const key = kind === 'asr' ? value === 'wlk-whisper' ? 'asr' : 'qwen_model' : value === 'llama' ? 'llama_model' : 'translation';
      patch({ [kind === 'asr' ? 'backend' : 'translation_engine']: value, [key]: data.options.models[value][0][1], [deviceKey]: modelDevice(data, kind, value, values[deviceKey]) });
    }} /></SettingsRow>
    <p className="muted">{modelHints[engine]}</p>{kind === 'translation' && <p className="document-text muted">{data.options.generation?.[engine === 'llama' || String(draft[modelKey]).toLowerCase().includes('hy-mt2') ? 'hy' : 'nllb']}</p>}
    <SettingsRow title="模型 / 下载地址"><ModelField label="模型 / 下载地址" value={String(draft[modelKey])} options={data.options.models[engine]} onChange={value => patch({ [modelKey]: value })} /></SettingsRow>
    <SettingsRow title="计算设备"><Choice label="计算设备" value={String(draft[deviceKey])} options={devices.map(value => ({ value: kind === 'asr' ? deviceNames[value] : value, label: deviceNames[value] }))} onChange={value => patch({ [deviceKey]: value })} /></SettingsRow>
    {kind === 'asr' && [['draft_seconds', '草稿刷新目标'], ['update_seconds', '音频合并间隔'], ['endpoint_seconds', '停顿检测阈值']].filter(([key]) => engine !== 'wlk-whisper' || key !== 'draft_seconds').map(([key, label]) => <SettingsRow key={key} title={label} hint={parameterHelp[key]}><input aria-label={label} type="number" min={key === 'draft_seconds' ? .25 : .5} max={3} step={key === 'draft_seconds' ? .25 : .5} value={Number(draft[key])} onChange={event => patch({ [key]: Number(event.target.value) })} />秒</SettingsRow>)}
    <div className="settings-actions"><Button disabled={busy} onClick={async () => { try { const result = await request('models.choose', { key: modelKey, apply: false }); if (result.path) patch({ [modelKey]: result.path }); } catch (error) { setError((error as Error).message); } }}>导入本地模型…</Button><Button disabled={disabled || busy} onClick={() => submit(true)}>下载模型</Button></div></>}
    {error && <p className="error" role="alert">{error}</p>}</div>
  </Modal>;
}

export function progressText(value: Record<string, unknown>) {
  const done = Number(value.completed || 0), total = Number(value.total || 0);
  const amount = (n: number) => value.unit === 'B' ? `${(n / 1024 ** 2).toFixed(1)} MB` : String(n);
  return [value.label, total > 0 ? `${Math.min(100, Math.round(done / total * 100))}% · ${amount(done)} / ${amount(total)}` : amount(done),
    Number(value.rate) > 0 ? `${amount(Number(value.rate))}/s` : '', Number(value.rate) > 0 && total > done ? `剩余 ${Math.ceil((total - done) / Number(value.rate))} 秒` : ''].filter(Boolean).join(' · ');
}

export async function prepareRecommended(data: Bootstrap) {
  const snapshot = { ...data.options.recommended };
  snapshot.translation_device = modelDevice(data, 'translation', snapshot.translation_engine, data.settings.translation_device);
  await request('settings.set', { values: {
    backend: snapshot.backend, [snapshot.backend === 'wlk-whisper' ? 'asr' : 'qwen_model']: snapshot.asr_model,
    compute: modelDevice(data, 'asr', snapshot.backend, data.settings.compute),
    translation_engine: snapshot.translation_engine, [snapshot.translation_engine === 'llama' ? 'llama_model' : 'translation']: snapshot.translation_model,
    translation_device: snapshot.translation_device,
  } });
  await request('models.prepare', { selection: snapshot, only: data.settings.translate ? 'all' : 'asr' });
}
