"""Compare audio front ends with identical official Qwen decoding; no reference prompts.

Run with the inference environment. Each front end runs in a separate process so
its GPU allocation is released before ASR. Results are checkpointed after each case.
The reference is another recognizer's output, not a verified accuracy ground truth.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from linguaflow.audio_processing.config import AudioConfig


def candidates():
    return {
        'raw': {},
        'gain6': {'output_db': 6, 'limiter': True},
        'highpass_gain6': {'highpass': True, 'output_db': 6, 'limiter': True},
        'agc': {'gain': True, 'limiter': True},
        'apm_mild': {'apm': True, 'apm_level': 0, 'gain': True, 'limiter': True},
        'apm_medium': {'apm': True, 'apm_level': 2, 'gain': True, 'limiter': True},
        'wpe_mild': {'wpe': True, 'wpe_mix': .25, 'output_db': 6, 'limiter': True},
        'eq_mild': {'eq': True, 'presence_db': 2, 'output_db': 6, 'limiter': True},
        'df25': {'deepfilter': True, 'df_mix': .25, 'df_device': 'cuda'},
        'df50': {'deepfilter': True, 'df_mix': .5, 'df_device': 'cuda'},
        'df75': {'deepfilter': True, 'df_mix': .75, 'df_device': 'cuda'},
        'df50_gain6': {'deepfilter': True, 'df_mix': .5, 'df_device': 'cuda', 'output_db': 6, 'limiter': True},
        'df50_agc': {'deepfilter': True, 'df_mix': .5, 'df_device': 'cuda', 'gain': True, 'limiter': True},
        'df50_wpe': {'deepfilter': True, 'df_mix': .5, 'df_device': 'cuda', 'wpe': True, 'wpe_mix': .25},
    }


def words(text):
    return re.findall(r'\w+', text.lower())


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j-1] + 1,
                               previous[j-1] + (word != other)))
        previous = current
    return previous[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='media/test.m4a')
    parser.add_argument('--reference', default='media/test.txt')
    parser.add_argument('--saved-config', default='.work/user-audio.json')
    parser.add_argument('--output', default='.work/audio-presets')
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--chunk-seconds', type=float, default=30)
    parser.add_argument('--df-device', choices=['cpu', 'cuda'], default='cuda')
    parser.add_argument('--reuse-audio-from', help='Completed run directory; verifies input hash and exact settings')
    args = parser.parse_args()
    if args.chunk_seconds <= 0:
        parser.error('--chunk-seconds must be positive')
    args.input = str(Path(args.input).resolve())
    args.reference = str(Path(args.reference).resolve())
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    configs = candidates()
    if Path(args.saved_config).is_file():
        configs['user_saved'] = json.loads(Path(args.saved_config).read_text(encoding='utf-8'))
    if args.only:
        configs = {name: configs[name] for name in args.only}
    rows = []
    cached = {}
    audio_dir = Path(args.reuse_audio_from).resolve() if args.reuse_audio_from else out
    if args.reuse_audio_from:
        previous = json.loads((audio_dir / 'results.json').read_text(encoding='utf-8'))
        if previous['input_sha256'] != hashlib.sha256(Path(args.input).read_bytes()).hexdigest():
            raise ValueError('Cached audio belongs to a different input')
        cached = {r['name']: r for r in previous['results']}
    for name, data in configs.items():
        if data.get('deepfilter'):
            data = {**data, 'df_device': args.df_device}
        config = AudioConfig.from_dict(data).to_dict()
        config_path = out / f'{name}.config.json'
        config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        if args.reuse_audio_from:
            if name not in cached or cached[name]['config'] != config:
                raise ValueError(f'{name}: cached settings do not match')
            rows.append({'name': name, 'config': config,
                         'processing_seconds': cached[name]['processing_seconds']})
            continue
        began = time.perf_counter()
        with (out / f'{name}.processing.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/enhance_classroom.py'),
                            '--input', args.input, '--config', str(config_path),
                            '--output', str(out / f'{name}.wav')],
                           stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        rows.append({'name': name, 'config': config, 'processing_seconds': time.perf_counter()-began})
        print(f'Prepared {name}: {rows[-1]["processing_seconds"]:.1f}s', flush=True)
    import numpy as np
    import torch
    from linguaflow.runtime_compat import prepare_qwen_dependencies
    prepare_qwen_dependencies()
    from linguaflow.model_cache import resolve_qwen_cached
    from qwen_asr import Qwen3ASRModel
    torch.set_num_threads(4)
    torch.manual_seed(0)
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1., 7 * 1024**3 / total))
    model = Qwen3ASRModel.from_pretrained(resolve_qwen_cached('Qwen/Qwen3-ASR-1.7B'),
        dtype=torch.bfloat16, device_map='cuda', attn_implementation='sdpa', local_files_only=True,
        max_inference_batch_size=1, max_new_tokens=2048)
    model.model.generation_config.do_sample = False
    manifest = {'input_sha256': hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                'model': 'Qwen/Qwen3-ASR-1.7B', 'context': '', 'language': 'English',
                'chunk_seconds': args.chunk_seconds, 'reference_verified': False, 'results': []}
    expected_samples = None
    for row in rows:
        row['audio_path'] = str(audio_dir / f'{row["name"]}.wav')
        with wave.open(row['audio_path']) as wav:
            assert wav.getframerate() == 16000 and wav.getnchannels() == 1
            audio = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').astype(np.float32) / 32768
        if expected_samples is None:
            expected_samples = len(audio)
        if not len(audio) or len(audio) != expected_samples:
            raise RuntimeError(f'{row["name"]}: audio length changed ({len(audio)} vs {expected_samples})')
        row.update(samples=len(audio), seconds=len(audio)/16000,
                   rms_dbfs=float(20*np.log10(max(1e-12, np.sqrt(np.mean(audio**2))))),
                   peak=float(np.max(np.abs(audio))), clipped_fraction=float(np.mean(np.abs(audio) >= .999)))
        began = time.perf_counter()
        size = round(args.chunk_seconds * 16000)
        row['segments'] = []
        for start in range(0, len(audio), size):
            text = model.transcribe((audio[start:start+size], 16000), language='English', context='')[0].text
            row['segments'].append({'start': start/16000, 'text': text})
        row['asr_seconds'] = time.perf_counter() - began
        row['text'] = ' '.join(s['text'] for s in row['segments'])
        # Reference is deliberately first accessed after inference, never used as context.
        reference = words(Path(args.reference).read_text(encoding='utf-8-sig'))
        hypothesis = words(row['text'])
        row['reference_words'] = len(reference)
        row['word_edits'] = distance(reference, hypothesis)
        row['unverified_word_disagreement'] = row['word_edits'] / max(1, len(reference))
        (out / f'{row["name"]}.txt').write_text(row['text'], encoding='utf-8')
        manifest['results'].append(row)
        (out / 'results.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{row["name"]}: disagreement={row["unverified_word_disagreement"]:.3%}; ASR={row["asr_seconds"]:.1f}s', flush=True)


if __name__ == '__main__':
    main()
