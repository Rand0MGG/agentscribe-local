"""Re-score completed preset runs and write a compact, inspectable Markdown table."""
import argparse
import json
from pathlib import Path

from benchmark_audio_presets import distance, words


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('results')
    parser.add_argument('--reference', default='media/test.txt')
    args = parser.parse_args()
    path = Path(args.results)
    data = json.loads(path.read_text(encoding='utf-8'))
    reference = words(Path(args.reference).read_text(encoding='utf-8-sig'))
    for row in data['results']:
        row['reference_words'] = len(reference)
        row['word_edits'] = distance(reference, words(row['text']))
        row['unverified_word_disagreement'] = row['word_edits'] / max(1, len(reference))
    data['normalization'] = 'lowercase Unicode word tokens; punctuation separates words'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 音频处理对比', '',
             '参考文本来自另一识别器，未经人工校对。下表是词差异率，不能称为真实错误率或准确率。', '',
             f'同一录音 SHA256：`{data["input_sha256"]}`。模型 `{data["model"]}`；固定 '
             f'{data["chunk_seconds"]:g} 秒切分；英文；无提示词。', '',
             '处理耗时包含子进程启动和组件初始化；识别耗时不包含模型加载。', '',
             '| 方案 | 词差异率 | 编辑数 | 处理秒 | 识别秒 | RMS dBFS | 峰值 | 削波比例 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in sorted(data['results'], key=lambda r: r['unverified_word_disagreement']):
        lines.append(f'| {row["name"]} | {row["unverified_word_disagreement"]:.2%} | '
                     f'{row["word_edits"]} | {row["processing_seconds"]:.1f} | {row["asr_seconds"]:.1f} | '
                     f'{row["rms_dbfs"]:.1f} | {row["peak"]:.3f} | {row["clipped_fraction"]:.4%} |')
    lines.extend(['', 'JSON 含完整参数和分段识别文本。音频保存在首轮目录；复测 JSON 的 audio_path 指向复用音频。', ''])
    path.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
