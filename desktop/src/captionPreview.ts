import type { Caption, Preview, PreviewRow } from './types';

/** Display projection only: semantic rows and translation ownership stay intact. */
export function projectCaptionRows(rows: Caption[], preview: Preview | null | undefined) {
  const patches = new Map(preview?.rows?.filter(row => row.id !== null).map(row => [row.id, row]));
  const keep = new Set(preview?.keep_ids);
  const ids = new Set(rows.map(row => row.id));
  const views = rows.map(row => {
    const patch = patches.get(row.id);
    const drafting = !!patch && patch.source !== row.source;
    const hidden = !!preview && (patch ? !patch.source : !keep.has(row.id));
    const caption = drafting ? {...row, source:patch.source, start:patch.start, end:patch.end,
      final:false, asr_final:false, boundary_final:false,
      translation_source:row.translation_source || row.source, translation_phase:'initial',
      translation_status:row.translation ? '原文更新中 · 译文待更新' : ''} : row;
    return {caption, hidden, drafting};
  });
  const extra: PreviewRow[] = preview?.rows
    ? preview.rows.filter(row => row.source && (row.id === null || !ids.has(row.id)))
    : preview?.source ? [{id:null, index:0, source:preview.source, start:preview.start, end:preview.end ?? preview.start}] : [];
  return {views, extra};
}
