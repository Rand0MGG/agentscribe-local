import { Deleted } from './Deleted';
import { Transport } from './Transport';
import { LibraryTree, ResizableSidebar, SidebarToggle } from './LibraryTree';
import { useEffect, useRef, useState } from 'react';
import { Tooltip } from 'radix-ui';
import { ActionMenu, Button, Choice, ConfirmDialog, ControlPopover, EditDialog, Icon, IconMenu, InlineTitle, Modal, Tip, Toggle, type MenuAction } from './components';
import { Captions } from './Captions';
import { SettingsPage, progressText, prepareRecommended } from './Settings';
import { Playback } from './Playback';
import { LevelMeter, RecordingIsland } from './RecordingIsland';
import { useMaterial, usePageTransition } from './motion';
import { useNotifications } from './notifications';
import { bridge, clock, request, type Bootstrap, type Caption, type Item, type Page, type Settings, type State } from './types';

const blockingCommands = new Set(['recording.new', 'recording.open', 'recording.start', 'recording.stop', 'recording.pause', 'recording.save', 'recording.close_recovered', 'library.refresh', 'library.migrate', 'frontend.switch']);

const emptyPage: Page = { generation: 0, revision: 0, start: 0, total: 0, rows: [] };
type Editor = { title: string; initial?: string; save: (name: string) => Promise<unknown> };
type Confirmation = { title: string; description: string; label: string; run: () => Promise<unknown> };
const stateLabels: Record<string, string> = { IDLE: '开始聆听', STARTING: '正在启动…', LISTENING: '录音中', PAUSING: '正在暂停…', PAUSED: '已暂停', RESUMING: '正在继续…', STOPPING: '正在收尾…' };

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null), [error, setError] = useState('');
  const [page, setPage] = useState<Page>(emptyPage), [section, setSection] = useState('recording');
  const material = useMaterial(String(data?.settings.appearance || 'light')), pageTransition = usePageTransition(section, true);
  const { notice, post: setNotice, dismiss } = useNotifications();
  const [editor, setEditor] = useState<Editor | null>(null), [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false), [seconds, setSeconds] = useState(0), [level, setLevel] = useState(0);
  const [playback, setPlayback] = useState<{ position: number; duration: number; state: string; caption_id: number | null }>({ position: 0, duration: 0, state: 'StoppedState', caption_id: null }), [volume, setVolume] = useState(100);
  const scrubbing = useRef(false);
  const [deleted, setDeleted] = useState<any[] | null>(null), [moving, setMoving] = useState<Item | null>(null), [moveTo, setMoveTo] = useState('');
  const [search, setSearch] = useState<string | null>(null), [matches, setMatches] = useState<Caption[]>([]), [locate, setLocate] = useState<number | null>(null);
  const [searchPage, setSearchPage] = useState(0), [searchTotal, setSearchTotal] = useState(0);
  const [diagnostics, setDiagnostics] = useState<string[]>([]), [showDiagnostics, setShowDiagnostics] = useState(false);
  const [loadingModel, setLoadingModel] = useState(false), [loadingHidden, setLoadingHidden] = useState(false), [preparationHidden, setPreparationHidden] = useState(false);
  const modelLoading = data?.state.capture?.model_loading ?? loadingModel;
  const [guidance, setGuidance] = useState<string[] | null>(null), offeredGuidance = useRef(false);
  const [settingsCategory, setSettingsCategory] = useState('常规');
  const [folder, setFolder] = useState('');
  const [audioBusy, setAudioBusy] = useState(false), [audioMessage, setAudioMessage] = useState('');
  const dataRef = useRef(data), tail = useRef(true), searchGeneration = useRef(0), commands = useRef(new Set<string>());
  const stateGeneration = useRef(0);
  const [seekRevision, setSeekRevision] = useState(0);
  const [updatesBusy, setUpdatesBusy] = useState(false);
  dataRef.current = data;

  async function perform(method: string, params: Record<string, unknown> = {}) {
    if (commands.current.has(method)) return;
    commands.current.add(method); setBusy([...commands.current].some(command => blockingCommands.has(command)));
    try {
      const result = await request(method, params);
      if (method === 'audio.select') {
        setData(old => old ? { ...old, device: result } : old);
        setAudioMessage('已选择音频来源。'); setNotice(null, 'audio-discovery');
      }
      return result;
    }
    catch (e) { setNotice({ text: (e as Error).message, error: true }); }
    finally { commands.current.delete(method); setBusy([...commands.current].some(command => blockingCommands.has(command))); }
  }
  async function loadPage(start?: number, target?: number) {
    const generation = dataRef.current?.state.generation;
    tail.current = start === undefined && target === undefined;
    if (dataRef.current?.state.state === 'IDLE') {
      if (target !== undefined) setLocate(target);
      return;
    }
    try {
      const playbackTarget = start === undefined && target === undefined ? playback.caption_id : null;
      const result = await request<Page>('captions.page', { ...(start !== undefined ? { start } : {}), ...(target !== undefined || playbackTarget !== null ? { locate: target ?? playbackTarget } : {}) });
      if (result.generation === dataRef.current?.state.generation && generation === result.generation) {
        setPage(result); if (target !== undefined) setLocate(target);
      }
    } catch (e) { setNotice({ text: (e as Error).message, error: true }); }
  }
  useEffect(() => {
    let live = true;
    const unsubscribe = bridge?.subscribe(({ event, data: value }) => {
      if (!live) return;
      if (event === 'state') {
        if (stateGeneration.current !== value.generation) {
          stateGeneration.current = value.generation;
          tail.current = true; setLocate(null); setPage({ ...emptyPage, generation: value.generation });
          setPlayback({ position: 0, duration: value.playback?.duration || 0, state: 'StoppedState', caption_id: null }); setVolume(value.playback?.volume ?? 100); setSeconds(0);
        }
        if (value.state === 'IDLE' && value.has_audio && value.playback) setPlayback(old => ({ ...old, duration: value.playback.duration }));
        setData(old => old ? { ...old, state: value } : old);
      }
      if (event === 'library') setData(old => old ? { ...old, library: value } : old);
      if (event === 'library-root') setData(old => old ? { ...old, root: value } : old);
      if (event === 'updates') { setUpdatesBusy(!!value.busy); setNotice({ text: value.busy ? '正在检查更新…' : value.error || value.result?.message || '', error: !!value.error || value.result?.kind === 'error', busy: value.busy }, 'updates'); }
      if (event === 'settings') setData(old => old ? { ...old, settings: value } : old);
      if (event === 'devices') {
        const previous = dataRef.current?.device;
        const missing = previous && !value.some((row: Bootstrap['devices'][number]) => row.id === previous[0] && row.loopback === previous[1]);
        const message = !value.length ? '未发现音频来源，请连接设备并检查麦克风权限。' : missing ? '上次的音频来源不可用，请重新选择系统音频或外部输入。' : `已刷新 · 找到 ${value.length} 个音频来源`;
        setAudioMessage(message); setNotice({ text: message, error: !value.length || !!missing }, 'audio-discovery');
        setData(old => old ? { ...old, devices: value } : old);
      }
      if (event === 'device') setData(old => old ? { ...old, device: value } : old);
      if (event === 'audio-discovery') {
        setAudioBusy(!!value.busy);
        if (value.busy) setAudioMessage('正在检查音频来源…');
        else if (value.error) setAudioMessage(`刷新失败，原列表保留：${value.error}`);
      }
      if (event === 'captions' && value.generation === stateGeneration.current) setPage(value);
      if (event === 'caption') setPage(old => {
        if (old.generation !== value.generation) return old;
        let rows = old.rows.filter(row => row.id !== value.caption.id);
        if (value.caption.source && (tail.current || old.rows.some(row => row.id === value.caption.id))) rows.push(value.caption);
        rows.sort((a, b) => a.id - b.id);
        if (dataRef.current?.state.state !== 'IDLE' && rows.length > 200) rows = rows.slice(-200);
        return { ...old, rows, revision: value.revision, total: value.total, start: tail.current ? Math.max(0, value.total - rows.length) : old.start };
      });
      if (event === 'migration') setNotice({ text: typeof value.progress === 'number' ? `正在迁移录音… ${Math.round(value.progress)}%` : String(value.progress), busy: value.busy }, 'migration');
      if (event === 'notice') setNotice(value);
      if (event === 'diagnostic' || event === 'stage') setDiagnostics(old => [...old.slice(-499), `${new Date().toLocaleTimeString()}  ${event === 'stage' ? `${value.name}：${value.value}` : value}`]);
      if (event === 'model-loading') { setLoadingModel(value.busy); if (!value.busy) setLoadingHidden(false); }
      if (event === 'model-check' && value.missing && !offeredGuidance.current) {
        offeredGuidance.current = true;
        if (value.missing.some((row: string) => row.startsWith('识别模型：') || row.startsWith('翻译模型：'))) setGuidance(value.missing);
      }
      if (event === 'caption-location') { tail.current = false; setSection('recording'); setPage(value.page); setLocate(value.identifier); }
      if (event === 'clock') setSeconds(value.seconds);
      if (event === 'level') setLevel(value);
      if (event === 'playback') {
        if (value.seek) { tail.current = true; setLocate(null); setSeekRevision(old => old + 1); }
        setPlayback(old => ({ ...old, ...value, ...(scrubbing.current ? { position: old.position, caption_id: old.caption_id } : {}) }));
      }
    });
    request<Bootstrap>('bootstrap').then(result => {
      if (!live) return;
      stateGeneration.current = result.state.generation;
      setPlayback({ position: 0, duration: result.state.playback?.duration || 0, state: 'StoppedState', caption_id: null }); setVolume(result.state.playback?.volume ?? 100);
      setAudioBusy(!!result.audio_refreshing); setData(result); setPage(result.captions); setFolder(result.library.folders[0]?.id || '');
      if (result.fault) setNotice({ text: result.fault, error: true });
      if (!result.no_audio) { perform('audio.refresh'); perform('models.check'); }
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; unsubscribe?.(); };
  }, []);
  useEffect(() => { if (data) request('frontend.ready').catch(e => setNotice({ text: e.message, error: true })); }, [!!data]);
  useEffect(() => {
    document.documentElement.dataset.theme = String(data?.settings.appearance || 'light');
    document.documentElement.dataset.reducedMotion = String(!!data?.settings.reduce_motion);
  }, [data?.settings.appearance, data?.settings.reduce_motion]);
  const wasPreparing = useRef(false);
  useEffect(() => {
    if (!wasPreparing.current && data?.state.preparing) setNotice(null, 'preparation-result');
    if (wasPreparing.current && data && !data.state.preparing) setNotice({ text: data.state.preparation_status, error: data.state.preparation_recovery === '重试' }, 'preparation-result');
    wasPreparing.current = !!data?.state.preparing;
  }, [data?.state.preparing, data?.state.preparation_status, setNotice]);
  useEffect(() => { if (!data?.state.preparing) setPreparationHidden(false); }, [data?.state.preparing]);
  useEffect(() => { if (!modelLoading) setLoadingHidden(false); setNotice(modelLoading && !loadingHidden ? { text: '正在加载模型', busy: true } : null, 'model-loading'); }, [modelLoading, loadingHidden, setNotice]);
  useEffect(() => { setNotice(data?.state.preparing && !preparationHidden && !(section === 'settings' && ['模型管理', '运行环境'].includes(settingsCategory)) ? { text: data.state.preparation_status + (data.state.progress ? ` · ${progressText(data.state.progress)}` : ''), busy: true } : null, 'preparation'); }, [data?.state.preparing, data?.state.preparation_status, data?.state.progress, preparationHidden, section, settingsCategory, setNotice]);
  useEffect(() => {
    if (search === null) return;
    const ticket = ++searchGeneration.current;
    const timer = setTimeout(() => {
      request<{ rows: Caption[]; generation: number; total: number }>('captions.search', { query: search, start: searchPage * 100 }).then(result => {
        if (ticket === searchGeneration.current && result.generation === dataRef.current?.state.generation) { setMatches(result.rows); setSearchTotal(result.total); }
      }).catch(e => setNotice({ text: e.message, error: true }));
    }, 150);
    return () => clearTimeout(timer);
  }, [search, searchPage, data?.state.generation]);

  if (!data) return <div className="startup"><h1>AgentScribe</h1><p role={error ? 'alert' : 'status'}>{error || '正在打开本地工作区…'}</p>{error && <Button onClick={async () => { try { await request('library.recover'); } catch (error) { setError((error as Error).message); } }}>选择其他录音保存位置</Button>}</div>;
  const state = data.state, active = state.state !== 'IDLE';
  const canExport = !!state.item && !active && page.rows.some(row => row.final && row.asr_final !== false
    && row.boundary_final !== false && row.source.trim() && (!state.preview || state.preview.keep_ids.includes(row.id)));
  const blocked = active || busy || state.saving || state.dirty || state.closing || state.migrating;
  const languages = data.options.languages.map(row => ({ value: row[0], label: row[0] }));
  const setSettings = (values: Settings) => { perform('settings.set', { values }); };
  const sourceAvailable = !!data.device && data.devices.some(row => row.id === data.device![0] && row.loopback === data.device![1]);
  const open = async (item: Item) => {
    if (blocked) return false;
    const opened = await perform('recording.open', { identifier: item.id });
    if (!opened) return false;
    setFolder(item.folder || folder); setSection('recording');
    return true;
  };
  const newRecording = (folderId = folder) => { setSection('recording'); perform('recording.new', { folder_id: folderId || undefined }); };
  function actions(item: Item): MenuAction[] {
    let current = state.item?.folder;
    let containsCurrent = item.id === state.item?.id;
    const seen = new Set<string>();
    while (current && !seen.has(current)) {
      seen.add(current); if (current === item.id) containsCurrent = true;
      current = data!.library.folders.find(row => row.id === current)?.parent || undefined;
    }
    const commonBlocked = busy || state.migrating || state.closing;
    const manageBlocked = commonBlocked || (active ? containsCurrent : state.saving || state.dirty);
    const renameBlocked = active && item.id === state.item?.id ? commonBlocked || !!state.save_error : manageBlocked;
    return [
      { label: '重命名', disabled: renameBlocked, run: () => setEditor({ title: '重命名', initial: item.name, save: name => request('item.rename', { identifier: item.id, name }) }) },
      { label: '在资源管理器中打开', run: () => { perform('path.reveal', { identifier: item.id }); } },
      { label: '移动到…', disabled: manageBlocked, run: () => { setMoving(item); setMoveTo(data!.library.folders.find(row => row.id !== item.id)?.id || ''); } },
      { label: '移到最近删除', disabled: manageBlocked, danger: true, run: () => setConfirmation({ title: `删除“${item.name}”？`, description: '移到最近删除后可以恢复。', label: '移到最近删除', run: () => request('item.trash', { identifier: item.id }) }) },
    ];
  }
  function folderActions(item: Item): MenuAction[] {
    return [{ label: '新录音', disabled: blocked, run: () => newRecording(item.id) },
      { label: '新建子文件夹', disabled: blocked, run: () => setEditor({ title: '新建子文件夹', save: name => request('folder.create', { name, parent: item.id }) }) }, ...actions(item)];
  }
  return <Tooltip.Provider delayDuration={550}><div className={`app ${data.platform}`} style={material}>
    <header className="titlebar" aria-label="窗口拖动区域" />
    <div className="page-stack" ref={pageTransition}>{section === 'settings' && <SettingsPage audioBusy={audioBusy} audioMessage={audioMessage} updatesBusy={updatesBusy} switchDisabled={blocked || state.preparing} initialCategory={settingsCategory} data={data} values={data.settings} state={state} onClose={() => setSection('recording')} onDeleted={async () => { const result = await perform('trash.list'); if (result) setDeleted(result); }} perform={perform} onPatch={setSettings} onCategory={setSettingsCategory} />}<div className="workspace-layout" hidden={section !== 'recording'}>
      <ResizableSidebar preferred={data.layout?.sidebar_width} onCommit={async width => {
        try { const saved = await request<number>('layout.sidebar', { width }); setData(old => old ? { ...old, layout: { sidebar_width: saved } } : old); }
        catch (error) { setNotice({ text: (error as Error).message, error: true }); throw error; }
      }}><div className="brand">AgentScribe</div><Button className="navigation sidebar-action" variant="quiet" aria-label="新录音" title="新录音" disabled={blocked} onClick={() => newRecording()}><Icon name="new" /><span className="sidebar-label">新录音</span></Button>
        <SidebarToggle /><div className="folder-heading"><span className="sidebar-label">文件夹</span><Tip label="新建文件夹" side="right"><Button className="sidebar-action sidebar-icon-action" variant="quiet" aria-label="新建文件夹" disabled={blocked} onClick={() => setEditor({ title: '新建文件夹', save: name => request('folder.create', { name }) })}><Icon name="folder-add" /></Button></Tip></div>
        <LibraryTree library={data.library} current={state.item?.id} folder={folder} blocked={blocked} onOpen={open} onFolder={setFolder} actions={actions} folderActions={folderActions} /><div className="sidebar-bottom"><Button className="sidebar-action" variant="quiet" aria-label="最近删除" title="最近删除" onClick={async () => { const result = await perform('trash.list'); if (result) setDeleted(result); }}><Icon name="trash" /><span className="sidebar-label">最近删除</span></Button>
        <Button className="sidebar-action" variant="quiet" aria-label={updatesBusy ? '正在检查…' : data.installed ? '切换到 Qt 检查更新' : '检查更新'} title={data.installed ? '切换到 Qt 检查更新' : '检查更新'} disabled={updatesBusy} onClick={() => perform('updates.check')}><Icon name="download" /><span className="sidebar-label">{updatesBusy ? '正在检查…' : data.installed ? '切换到 Qt 检查更新' : '检查更新'}</span></Button><Button className="sidebar-action" variant="quiet" aria-label="设置" title="设置" onClick={() => setSection('settings')}><Icon name="settings" /><span className="sidebar-label">设置</span></Button></div>
      </ResizableSidebar><main className="workspace"><header className="workspace-header"><InlineTitle key={state.generation} value={state.item?.name || state.draft?.name || '新录音'} disabled={busy || state.migrating || state.closing || !!state.save_error} onSave={name => request('item.rename', { identifier: state.item?.id ?? null, name })} />
        <div className="header-actions">{data.settings.beta_features && <Button className="knowledge-header" variant="quiet" disabled={!state.item} onClick={() => perform('knowledge.window')}>课程资料与笔记 · Beta</Button>}
          <ActionMenu actions={[
            { label: '悬浮字幕', run: () => perform('overlay.toggle') },
            { label: '导出定稿', disabled: !canExport, run: () => perform('recording.export') },
            ...(data.settings.beta_features ? [{ label: '课程资料与笔记 · Beta', disabled: !state.item, run: () => perform('knowledge.window') }] : []),
            { label: '查找字幕', disabled: !state.item, run: () => { setSearchPage(0); setSearch(''); } },
            { label: '导出 TXT', disabled: !canExport, run: () => { perform('recording.export', { format: 'txt' }); } },
            { label: '导出 Markdown', disabled: !canExport, run: () => { perform('recording.export', { format: 'md' }); } },
            { label: '重试保存', disabled: !state.dirty || state.saving, run: () => { perform('recording.save'); } },
            { label: '备份全部文字', disabled: !state.item, run: () => { perform('recording.export', { recovery: true }); } },
            { label: '使用文字备份并关闭', disabled: !state.recovery_ready, run: () => setConfirmation({ title: '使用文字备份并关闭此录音？', description: '原录音仍未成功保存。备份不含音频；原目录及已有音频保留。请使用备份核对草稿和译文。', label: '使用备份并关闭', run: () => request('recording.close_recovered') }) },
            { label: '打开保存位置', run: () => { perform('path.reveal'); } },
            { label: '刷新录音列表', run: () => { perform('library.refresh'); } },
            { label: '复制最新字幕', disabled: !page.total && !state.preview, run: () => { perform('captions.copy'); } },
            { label: showDiagnostics ? '收起诊断记录' : '诊断记录', run: () => setShowDiagnostics(!showDiagnostics) },
            { label: '打开诊断日志文件夹', run: () => { perform('path.diagnostics'); } },
            { label: '取消模型检查', disabled: !state.checking_models, run: () => { perform('models.cancel_check'); } },
            { label: '取消录音库迁移', disabled: !state.migrating, run: () => { perform('library.cancel_migration'); } },
            ...(state.item ? actions(state.item) : []),
          ]} />
        </div></header>
        <Captions seekRevision={seekRevision} visible={section === 'recording'} interaction={data.interaction} page={page} state={state} position={playback.state === 'StoppedState' && playback.position === 0 ? -1 : playback.position} onPage={loadPage} onSeek={milliseconds => perform('playback.seek', { milliseconds, play: true })} locate={locate} onFollow={value => { tail.current = value; }} summary={state.draft ? <div className="pending-summary"><h2>准备开始录音</h2><p>点击下方开始按钮，即可聆听。</p><p>音频来源 · {data.devices.find(row => row.id === data.device?.[0] && row.loopback === data.device?.[1])?.name || '请选择音频来源'}</p><p>语言 · {String(data.settings.source)}{data.settings.translate ? ` → ${data.settings.target}` : ' · 仅识别原文'}</p><p>保存到 · {data.library.folders.find(row => row.id === state.draft?.folder)?.name}</p><small>下方图标调整设置 · 顶部标题修改名称</small></div> : undefined} />
        {showDiagnostics && <pre className="diagnostics" aria-label="诊断记录">{diagnostics.join('\n') || '暂无运行记录'}</pre>}
        <Transport active={active} playback={!active && state.has_audio}>{geometry => <>
          {!active && state.has_audio && <Playback maxVolume={state.playback?.supports_gain === false ? 100 : 300} geometry={geometry} position={playback.position} duration={playback.duration} playing={playback.state === 'PlayingState'} disabled={data.no_audio || busy} volume={volume}
            onToggle={() => perform('playback.toggle')} onPosition={position => { scrubbing.current = true; setPlayback(old => ({ ...old, position })); }}
            onSeek={async milliseconds => { await perform('playback.seek', { milliseconds }); scrubbing.current = false; }} onVolume={value => { setVolume(value); perform('playback.volume', { value }); }} />}
          {(active || !state.has_audio) && <RecordingIsland geometry={geometry} active={active} status={<><span>{state.capture?.label || stateLabels[state.state]}</span><span className="capture-time">{clock(seconds)}</span><span>{state.capture?.volume_label ?? '输入音量'}</span><LevelMeter rms={state.state === 'LISTENING' && !state.failure ? level : 0} /></>}>
            <IconMenu label="音频来源" icon={data.device && !data.device[1] ? 'microphone' : 'source'} disabled={data.no_audio || !['IDLE', 'LISTENING', 'PAUSED'].includes(state.state)} value={data.device ? JSON.stringify(data.device) : ''}
              options={data.devices.map(device => ({ value: JSON.stringify([device.id, device.loopback]), label: device.name }))} onChange={async value => {
                const [identifier, loopback] = JSON.parse(value); const selected = await perform('audio.select', { identifier, loopback }); if (selected) setData(old => old ? { ...old, device: selected } : old);
              }} refreshing={audioBusy} refreshStatus={audioMessage} refresh={() => { perform('audio.refresh'); }} />
              <ControlPopover label="语言设置" icon="language"><label>原文语言</label><Choice label="原文语言" value={String(data.settings.source)} options={[...(data.settings.backend === 'wlk-whisper' ? [{ value: '自动检测', label: '自动检测' }] : []), ...languages]} onChange={value => setSettings({ source: value })} /><label>翻译为</label><Choice label="翻译语言" value={String(data.settings.target)} options={languages} onChange={value => setSettings({ target: value })} /><label>启用翻译</label><Toggle label="启用翻译" disabled={!state.translation_available} value={!!data.settings.translate && state.translation_available} onChange={value => setSettings({ translate: value })} />{active && <p>语言变化在下次录音生效。</p>}</ControlPopover>
              {!active && <IconMenu label="保存文件夹" icon="folder" disabled={blocked} value={state.draft?.folder || folder} options={data.library.folders.map(row => ({ value: row.id, label: row.name }))} onChange={value => { setFolder(value); perform('recording.new', { folder_id: value, name: state.draft?.name }); }} />}
              {active ? <><Tip label={state.state === 'PAUSED' ? '继续录音' : '暂停'}><Button className="icon-button" aria-label={state.state === 'PAUSED' ? '继续录音' : '暂停'} disabled={!['LISTENING', 'PAUSED'].includes(state.state) || !!state.failure} onClick={() => perform('recording.pause')}><Icon name={state.state === 'PAUSED' ? 'play' : 'pause'} /></Button></Tip><Tip label="停止"><Button variant="primary" className="transport-button" aria-label="停止" disabled={state.state === 'STOPPING'} onClick={() => perform('recording.stop')}><Icon name="stop" /></Button></Tip></> :
                <Tip label="开始聆听"><Button variant="primary" className="transport-button" aria-label="开始聆听" disabled={busy || state.preparing || state.saving || state.closing || data.no_audio || !sourceAvailable} onClick={() => perform('recording.start')}><Icon name="play" /></Button></Tip>}
          </RecordingIsland>}
          {(state.failure || state.save_error || state.closing) && <p className="status error" role="alert">{state.save_error || state.failure || '正在保存并退出…'}</p>}
        </>}</Transport>
      </main></div></div>
    {notice && <aside className={`notification ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}><span>{notice.text}</span>{notice.busy && <span className="notice-progress" role="progressbar" aria-label="正在处理"><i /></span>}{['preparation', 'preparation-result'].includes(notice.key || '') && <><Button onClick={() => { setSettingsCategory('模型管理'); setSection('settings'); }}>查看准备</Button>{!state.preparing && state.preparation_recovery && <Button onClick={() => perform('models.retry')}>{state.preparation_recovery}</Button>}{state.preparing && <Button disabled={state.preparation_cancelling} onClick={() => perform('models.cancel')}>取消准备</Button>}</>}{notice.key === 'migration' && state.migrating && <Button onClick={() => perform('library.cancel_migration')}>取消迁移</Button>}<Button variant="quiet" aria-label="收起通知" onClick={() => { if (notice.key === 'preparation') setPreparationHidden(true); else if (notice.key === 'model-loading') setLoadingHidden(true); dismiss(notice.key!); }}>×</Button></aside>}
    {guidance && <Modal modal={false} title="准备本地模型" description="指定的模型尚未准备好。模型在本机运行，录音保存在你选择的位置。" open onClose={() => setGuidance(null)} actions={<>
      <Button onClick={() => setGuidance(null)}>稍后</Button><Button variant="primary" disabled={state.preparing || state.checking_models || !state.model_missing || state.model_missing.length > 0} onClick={() => setGuidance(null)}>开始使用</Button>
    </>}><h3>1  录音保存位置</h3><p>{data.root}</p><Button onClick={() => perform('library.migrate')}>更改保存位置…</Button>
      <h3>2  准备识别与翻译模型</h3><p>{data.options.downloads[0]?.[0]}{data.settings.translate ? ' · HY-MT2 1.8B Q4_K_M 翻译' : ''}</p>
      <p>{state.preparing ? '正在后台准备模型，可以先浏览应用。' : state.model_missing?.length === 0 ? '所需模型已就绪。' : '下载一次，之后可在本机使用。已有文件会复用。'}</p>
      <Button disabled={state.preparing || busy} onClick={async () => { try { await prepareRecommended(data); setGuidance(null); setSettingsCategory('模型管理'); setSection('settings'); } catch (error) { setNotice({text:(error as Error).message,error:true}); } }}>{data.settings.translate ? '下载并使用推荐组合' : '下载并使用推荐识别模型'}</Button>
    </Modal>}
    {state.save_error && <aside className="save-notification" role="alert"><span>保存失败，文字仍保留。</span><Button onClick={() => perform('recording.save')}>重试保存</Button><Button onClick={() => perform('recording.export', { recovery: true })}>备份全部文字</Button></aside>}
    {editor && <EditDialog title={editor.title} initial={editor.initial} onClose={() => setEditor(null)} onSave={editor.save} />}
    {confirmation && <ConfirmDialog title={confirmation.title} description={confirmation.description} confirm={confirmation.label} onClose={() => setConfirmation(null)} onConfirm={confirmation.run} />}
    {moving && <Modal title={`移动“${moving.name}”`} open onClose={() => setMoving(null)} actions={<><Button onClick={() => setMoving(null)}>取消</Button><Button variant="primary" disabled={!moveTo || busy} onClick={async () => {
      try { await request('item.move', { identifier: moving.id, folder_id: moveTo }); setMoving(null); } catch (e) { setNotice({ text: (e as Error).message, error: true }); }
    }}>移动</Button></>}><Choice label="目标文件夹" value={moveTo} options={data.library.folders.filter(row => row.id !== moving.id).map(row => ({ value: row.id, label: row.name }))} onChange={setMoveTo} /></Modal>}
    {deleted && <Deleted rows={deleted} disabled={blocked} onChange={setDeleted} onClose={() => setDeleted(null)} />}
    {search !== null && <Modal title="查找字幕" description="搜索原文或译文，选择结果定位，不会自动播放。" open onClose={() => { setSearch(null); searchGeneration.current++; }}><input aria-label="搜索当前录音字幕" placeholder="搜索原文或译文…" value={search} onChange={event => { setSearchPage(0); setSearch(event.target.value); }} autoFocus /><div className="search-results">{matches.map(row => <button key={row.id} onClick={async () => { await loadPage(undefined, row.id); setSearch(null); }}>{clock(row.start).slice(row.start >= 3600 ? 0 : 3)}　{row.source}<span>{row.translation}</span></button>)}{!matches.length && <p>没有匹配内容。</p>}</div><div className="settings-actions"><span>共 {searchTotal} 条，显示 {matches.length ? searchPage * 100 + 1 : 0}–{searchPage * 100 + matches.length}</span><Button disabled={searchPage === 0} onClick={() => setSearchPage(searchPage - 1)}>上一页</Button><Button disabled={(searchPage + 1) * 100 >= searchTotal} onClick={() => setSearchPage(searchPage + 1)}>下一页</Button></div></Modal>}

  </div></Tooltip.Provider>;
}
