import type { Method, RequestArgs, RequestResults } from './protocol.generated';
export type { Method, RequestArgs, RequestResults } from './protocol.generated';
export type Item = { id: string; name: string; folder?: string; parent?: string | null; state?: string; created?: string };
export type Caption = { id: number; start: number; end: number; source: string; translation: string;
  final: boolean; revision: number; language: string; error: string; translation_phase: string;
  translation_status: string; translation_source: string; asr_final?: boolean; boundary_final?: boolean };
export type PreviewRow = { id: number | null; index: number; source: string; start: number; end: number };
export type Preview = { source: string; start: number; end?: number; keep_ids: number[]; sequence: number; rows?: PreviewRow[] };
export type RecordingState = 'IDLE' | 'STARTING' | 'LISTENING' | 'PAUSING' | 'PAUSED' | 'RESUMING' | 'STOPPING';
export type State = { item: Item | null; draft: { name: string; folder: string } | null; state: RecordingState; status: string; failure: string; save_error: string;
  update_fenced?: boolean; capture?: { label: string; volume_label: string; waiting: string; model_loading: boolean };
  model_missing?: string[] | null; playback?: { duration: number; supports_gain: boolean; volume: number }; translating?: boolean; saving: boolean; dirty: boolean; generation: number; revision: number; count: number; preview: Preview | null;
  preparing: boolean; preparation_blocks_recording?: boolean; preparation_kind?: string | null; preparation_cancelling: boolean; preparation_recovery: string; preparation_status: string; checking_models: boolean; translation_available: boolean; progress: Record<string, unknown> | null; closing: boolean; has_audio: boolean; migrating: boolean; recovery_ready: boolean };
export type Settings = Record<string, string | number | boolean>;
export type Device = { id: string; name: string; loopback: boolean };
export type Library = { folders: Item[]; sessions: Item[] };
export type Page = { generation: number; revision: number; start: number; total: number; rows: Caption[] };
export type Options = { generation?: Record<string, string>; downloads: [string, string, string, string, string][]; languages: [string, string, string][]; backends: string[]; devices: string[];
  models: Record<string, [string, string][]>; translation_devices: Record<string, string[]>;
  recommended: { backend: string; asr_model: string; translation_engine: string; translation_model: string; translation_device: string } };
export type Interaction = { doubleClickInterval: number; dragDistance: number };
export type Bootstrap = { version: string; platform: string; installed?: boolean; interaction?: Interaction; no_audio: boolean; audio_refreshing?: boolean; layout?: { sidebar_width: number | null }; settings: Settings; library: Library; root: string;
  state: State; captions: Page; devices: Device[]; device: [string, boolean] | null; options: Options; fault?: string };
export type DeletedItem = { token: string; name: string; deleted: string };
export type CaptionLocation = { page: Page; identifier: number | null };
export type OverlayOptions = { font: number; opacity: number; bounds?: { x: number; y: number; width: number; height: number } };
export type Material = { appearance: string; image: string; width: number; height: number; x: number; y: number };
export type Term = { canonical: string; aliases: string[]; aliasesText?: string; evidence_ids: string[]; approved: boolean; origin: string };
export type ModelEntry = { id: string; name: string; kind: string; engine: string; path: string; selection: string; [key: string]: unknown };
export type UpdateEvent = { stage?: string; text?: string; releasing?: boolean; busy?: boolean; error?: string; result?: { url?: string; message?: string; kind?: string }; [key: string]: unknown };
// Knowledge views are extensible documents; fields read at the transport boundary
// are explicit, while additional document content remains unknown.
export type KnowledgeEvent = { type: string; course_folder_id?: string; course?: { id: string; terms?: Term[]; documents?: unknown[] };
  manifest?: { session_id?: string }; reading_coverage?: Record<string, { read: number; total: number }>;
  material_error?: string; pending?: unknown[]; busy?: boolean; event_seq?: number; notes_version?: number;
  course_id: string; request?: string; requests?: number; uncertain?: boolean; tokens_or_reserved?: number; message?: string; [key: string]: unknown };
export type EventData = {
  state: State; library: Library; 'library-root': string; settings: Settings; devices: Device[]; device: [string, boolean] | null;
  captions: Page; caption: { generation: number; revision: number; total: number; caption: Caption };
  'caption-location': CaptionLocation; 'audio-discovery': { busy: boolean; error?: string };
  notice: { text: string; error?: boolean; busy?: boolean; persistent?: boolean; key?: string };
  migration: { busy: boolean; progress?: number | string }; diagnostic: string; stage: { name: string; value: string };
  'model-loading': { busy: boolean }; 'model-check': { busy: boolean; missing?: string[]; error?: string; message?: string };
  clock: { seconds: number }; level: number;
  playback: { position?: number; duration?: number; state?: string; caption_id?: number | null; seek?: boolean };
  inventory: { busy: boolean; result?: ModelEntry[]; error?: string }; updates: UpdateEvent; 'updates-reveal': unknown;
  'settings-page': string; 'window-layout': { split: boolean }; material: Material | null;
  knowledge: KnowledgeEvent; 'knowledge-close': unknown; closed: unknown;
};
export type DesktopEvent = { [K in keyof EventData]: { event: K; data: EventData[K] } }[keyof EventData];
export type Bridge = { request: <M extends Method>(method: M, ...args: RequestArgs<M>) => Promise<RequestResults[M]>;
  subscribe: (listener: (event: DesktopEvent) => void) => () => void };
declare global { interface Window { agentScribe?: Bridge } }

export const bridge = window.agentScribe;
export function request<M extends Method>(method: M, ...args: RequestArgs<M>): Promise<RequestResults[M]> {
  if (!bridge) return Promise.reject(new Error('请从 Electron 桌面入口启动；浏览器预览不连接个人录音或设备。'));
  return bridge.request(method, ...args).catch(error => { throw new Error(error.message.replace(/^Error invoking remote method '[^']+': (?:Error: )?/, '')); });
}
export function clock(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}
