import { useEffect, useState } from 'react';
import { Button, ConfirmDialog, Modal } from './components';
import { request } from './types';

export function Deleted({ rows, disabled, onChange, onClose }: { rows: any[]; disabled: boolean; onChange: (rows: any[]) => void; onClose: () => void }) {
  const [selected, setSelected] = useState<string[]>([]), [purging, setPurging] = useState<any[] | null>(null);
  useEffect(() => { setSelected(old => { const kept = old.filter(token => rows.some(row => row.token === token)); return kept.length ? kept : rows.length ? [rows[0].token] : []; }); }, [rows]);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function apply(method: string, targets: any[]) {
    setBusy(true); setError('');
    const failures: string[] = [];
    try {
      for (const row of targets) {
        try { onChange(await request(method, { token: row.token })); }
        catch (error) { failures.push(`${row.name}：${(error as Error).message}`); }
      }
      setSelected([]); setError(failures.join('；'));
    } finally { setBusy(false); setPurging(null); }
  }
  return <Modal width={560} height={440} title="最近删除" description="恢复时保留同名文件；永久删除无法撤销。" open onClose={() => { if (!busy) onClose(); }} actions={<>
    <Button variant="danger" disabled={disabled || busy || !selected.length} onClick={() => setPurging(rows.filter(row => selected.includes(row.token)))}>永久删除选中</Button>
    <Button variant="danger" disabled={disabled || busy || !rows.length} onClick={() => setPurging([...rows])}>清空最近删除</Button>
    <Button variant="primary" style={{marginLeft:'auto'}} disabled={disabled || busy || !selected.length} onClick={() => apply('trash.restore', rows.filter(row => selected.includes(row.token)))}>恢复选中</Button>
  </>}><div className="deleted-list">{!rows.length && <p>最近删除为空。</p>}{rows.map(row => <div className="deleted-row" key={row.token}>
    <input type="checkbox" aria-label={`选择 ${row.name}`} disabled={disabled || busy} checked={selected.includes(row.token)} onChange={event => setSelected(old => event.target.checked ? [...old, row.token] : old.filter(token => token !== row.token))} />
    <span>{row.name}<small className="muted">{String(row.deleted).slice(0, 10)}</small></span>
    <Button disabled={disabled || busy} onClick={() => apply('trash.restore', [row])}>恢复</Button>
    <Button variant="danger" disabled={disabled || busy} onClick={() => setPurging([row])}>永久删除</Button>
  </div>)}</div>{error && <p role="alert" className="error">{error}</p>}
    {purging && <ConfirmDialog title={`永久删除 ${purging.length} 项？`} description={purging.map(row => row.name).join('、') + '。录音及关联文件将永久删除，此操作无法撤销。'} confirm="永久删除" onClose={() => { if (!busy) setPurging(null); }} onConfirm={() => apply('trash.purge', purging)} />}
  </Modal>;
}
