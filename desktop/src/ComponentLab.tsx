import { useState } from 'react';
import { Tooltip } from 'radix-ui';
import { CaptionText } from './CaptionText';
import { RecordingIsland } from './RecordingIsland';
import { Playback } from './Playback';
import { ActionMenu, Button, Choice, EditDialog, Range, SettingsRow, Toggle } from './components';

/** Manual reference uses the exact primitives imported by the real workspace. */
export function ComponentLab() {
  const [theme, setTheme] = useState('light'), [selected, setSelected] = useState('1');
  const [enabled, setEnabled] = useState(true), [volume, setVolume] = useState(100), [dialog, setDialog] = useState(false);
  const [caption, setCaption] = useState(''), [recording, setRecording] = useState(false);
  const [position, setPosition] = useState(7000);
  const [message, setMessage] = useState('示例组件；不连接设备或创建录音。');
  function appearance(value: string) { document.documentElement.dataset.theme = value; setTheme(value); }
  return <Tooltip.Provider><main className="component-lab"><h1>共享组件 · 示例</h1><p>{message}</p>
    <div className="settings-group"><SettingsRow title="外观"><Choice label="示例外观" value={theme} options={[{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }]} onChange={appearance} /></SettingsRow>
      <SettingsRow title="按钮"><Button>普通操作</Button><Button variant="primary">主要操作</Button><Button disabled>不可用</Button></SettingsRow>
      <SettingsRow title="长列表与键盘选择"><Choice label="示例选项" value={selected} onChange={setSelected} options={Array.from({ length: 16 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} · 长中文名称与 English text`, disabled: i === 2 }))} /></SettingsRow>
      <SettingsRow title="操作菜单"><ActionMenu actions={[{ label: '可用操作', run: () => setMessage('示例操作已触发') }, { label: '不可用操作', disabled: true, run: () => {} }, { label: '危险操作示例', danger: true, run: () => setMessage('只展示样式，不删除文件') }]} /></SettingsRow>
      <SettingsRow title="开关"><Toggle label="示例开关" value={enabled} onChange={setEnabled} /></SettingsRow>
      <SettingsRow title="输入与对话框" hint="测试中文输入、Escape、Tab 循环与关闭后焦点返回。"><Button onClick={() => setDialog(true)}>编辑示例名称</Button></SettingsRow>
      <SettingsRow title="回放音量" hint="示例滑块不连接音频输出。"><Range label="示例音量" value={volume} max={300} onChange={setVolume} /><span>{volume}%</span></SettingsRow>
    </div>
    <section><h2>实时字幕 · 模拟追加</h2><Button onClick={() => setCaption(value => value + '上下文 é 👩‍💻 ')}>追加示例文字</Button><Button onClick={() => setCaption('修订立即替换。')}>修订示例文字</Button><p aria-label="动态字幕示例"><CaptionText text={caption} animate /></p></section>
    <section><h2>录音小岛 · 模拟状态</h2><Button onClick={() => setRecording(!recording)}>切换模拟录音状态</Button><div style={{height:100,display:'flex',alignItems:'end'}}><RecordingIsland active={recording} status="正在聆听　00:12:34"><Button>来源</Button><Button>语言</Button><Button>开始</Button></RecordingIsland></div></section>
    <section className="playback-demo"><h2>回听小岛 · 模拟进度</h2><p>与正式回听共用控件；没有音频文件或播放操作。</p><Playback position={position} duration={94000} volume={volume} playing={false} disabled={false} onToggle={() => setMessage('模拟播放；不访问音频')} onPosition={setPosition} onSeek={setPosition} onVolume={setVolume} /></section>
    {dialog && <EditDialog title="编辑示例名称" initial="中文名称 · 示例" onClose={() => setDialog(false)} onSave={async name => { setMessage(`示例名称：${name}`); }} />}
  </main></Tooltip.Provider>;
}
