import { useState } from 'react';
import { Button, Icon, Range, Tip } from './components';
import { clock } from './types';
import type { TransportGeometry } from './Transport';
import { useTween } from './motion';

/** Shared by the real recording view and the isolated workflow demo. */
export function Playback({ position, duration, playing, disabled, volume, onToggle, onPosition, onSeek, onVolume, geometry, maxVolume = 300 }: {
  maxVolume?: number; geometry?: TransportGeometry;
  position: number; duration: number; playing: boolean; disabled: boolean; volume: number;
  onToggle: () => void; onPosition: (position: number) => void; onSeek: (position: number) => void; onVolume: (volume: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const progress = useTween(Number(expanded), 200), extra = Math.round(112 * progress);
  const label = playing ? '暂停回听' : '播放录音';
  const timestamp = (milliseconds: number) => clock(milliseconds / 1000).slice(duration >= 3600000 ? 0 : 3);
  return <div className="playback-group" style={geometry ? { width: geometry.width + 68, height: geometry.height, transform: `translateX(${34 + geometry.offset}px)` } : undefined}><div className="playback" style={geometry ? { height: geometry.height } : undefined}><div className="playback-inner">
    <Tip label={label}><Button variant="quiet" className="transport-button" aria-label={label} disabled={disabled} onClick={onToggle}><Icon name={playing ? 'pause' : 'play'} /></Button></Tip>
    <Range label="播放位置" value={position} max={duration} onChange={onPosition} onCommit={onSeek} />
    <span className="playback-time">{timestamp(position)} / {timestamp(duration)}</span>
  </div></div><div className={`playback-volume ${expanded ? 'expanded' : ''}`} style={{ height: 58 + extra }}>
    <div className="volume-controls" style={{ height: Math.max(0, extra - 12), visibility: extra >= 64 ? 'visible' : 'hidden' }} aria-hidden={!expanded || extra < 64} inert={!expanded || extra < 64}>
      <Range label="回放音量百分比" orientation="vertical" value={volume} max={maxVolume} onChange={onVolume} /><span>{volume}%</span>
    </div>
    <Tip label={`回放音量 ${volume}% · 点击展开或收起`}><Button variant="quiet" className="volume-button icon-button" aria-label="回放音量" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}><Icon name="volume" /></Button></Tip>
  </div></div>;
}
