export type Item = { id: string; name: string; folder?: string; parent?: string | null; state?: string; created?: string };
export type Caption = { id: number; start: number; end: number; source: string; translation: string;
  final: boolean; revision: number; language: string; error: string; translation_phase: string;
  translation_status: string; translation_source: string; asr_final?: boolean; boundary_final?: boolean };
export type Preview = { source: string; start: number; keep_ids: number[]; sequence: number };
export type RecordingState = 'IDLE' | 'STARTING' | 'LISTENING' | 'PAUSING' | 'PAUSED' | 'RESUMING' | 'STOPPING';
export type State = { item: Item | null; draft: { name: string; folder: string } | null; state: RecordingState; status: string; failure: string; save_error: string;
  model_missing?: string[] | null; playback?: { duration: number; supports_gain: boolean; volume: number }; translating?: boolean; saving: boolean; dirty: boolean; generation: number; revision: number; count: number; preview: Preview | null;
  preparing: boolean; preparation_cancelling: boolean; preparation_recovery: string; preparation_status: string; checking_models: boolean; translation_available: boolean; progress: Record<string, unknown> | null; closing: boolean; has_audio: boolean; migrating: boolean; recovery_ready: boolean };
export type Settings = Record<string, string | number | boolean>;
export type Device = { id: string; name: string; loopback: boolean };
export type Library = { folders: Item[]; sessions: Item[] };
export type Page = { generation: number; revision: number; start: number; total: number; rows: Caption[] };
export type Options = { generation?: Record<string, string>; downloads: [string, string, string, string, string][]; languages: [string, string, string][]; backends: string[]; devices: string[];
  models: Record<string, [string, string][]>; translation_devices: Record<string, string[]>;
  recommended: { backend: string; asr_model: string; translation_engine: string; translation_model: string; translation_device: string } };
export type Interaction = { doubleClickInterval: number; dragDistance: number };
export type Bootstrap = { version: string; platform: string; installed?: boolean; interaction?: Interaction; no_audio: boolean; settings: Settings; library: Library; root: string;
  state: State; captions: Page; devices: Device[]; device: [string, boolean] | null; options: Options; fault?: string };
export type DesktopEvent = { event: string; data: any };
export type Bridge = { request: <T = any>(method: string, params?: Record<string, unknown>) => Promise<T>;
  subscribe: (listener: (event: DesktopEvent) => void) => () => void };
declare global { interface Window { agentScribe?: Bridge } }

export const bridge = window.agentScribe;
export function request<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  if (!bridge) return Promise.reject(new Error('请从 Electron 桌面入口启动；浏览器预览不连接个人录音或设备。'));
  return bridge.request<T>(method, params).catch(error => { throw new Error(error.message.replace(/^Error invoking remote method '[^']+': (?:Error: )?/, '')); });
}
export function clock(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}
