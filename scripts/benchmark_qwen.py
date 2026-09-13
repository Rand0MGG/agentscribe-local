"""Local official Qwen inference baseline. Reference is read only after ASR."""
import argparse
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', default='.work/classroom.wav')
    parser.add_argument('--chunk-seconds', type=float, default=0)
    parser.add_argument('--natural-boundaries', action='store_true')
    parser.add_argument('--gain-db', type=float, default=0)
    parser.add_argument('--output', default='.work/qwen-official.json')
    args = parser.parse_args()
    import numpy as np
    import torch
    from linguaflow.runtime_compat import prepare_qwen_dependencies
    prepare_qwen_dependencies()
    from linguaflow.model_cache import resolve_qwen_cached
    from qwen_asr import Qwen3ASRModel
    torch.set_num_threads(4)
    torch.manual_seed(0)
    # Leave driver/runtime headroom within the 8 GiB deployment target.
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1., 7 * 1024**3 / total))
    with wave.open(args.audio) as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000
        audio = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').astype(np.float32) / 32768
    audio = np.clip(audio * 10 ** (args.gain_db / 20), -1, 1)
    model = Qwen3ASRModel.from_pretrained(resolve_qwen_cached('Qwen/Qwen3-ASR-1.7B'),
        dtype=torch.bfloat16, device_map='cuda', attn_implementation='sdpa', local_files_only=True,
        max_inference_batch_size=1, max_new_tokens=2048)
    model.model.generation_config.do_sample = False
    size = round(args.chunk_seconds * 16000) if args.chunk_seconds else len(audio)
    if args.natural_boundaries:
        from qwen_asr.inference.utils import split_audio_into_chunks
        parts = split_audio_into_chunks(audio, 16000, args.chunk_seconds)
    else:
        parts = [(audio[start:start+size], start/16000) for start in range(0, len(audio), size)]
    rows = []
    began = time.perf_counter()
    for chunk, offset in parts:
        stamp = time.perf_counter()
        result = model.transcribe((chunk, 16000), language='English', context='')[0]
        row = {'start': offset, 'end': offset + len(chunk)/16000, 'text': result.text,
               'compute_seconds': round(time.perf_counter() - stamp, 3)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'backend': 'official-qwen-asr-transformers', 'model': 'Qwen/Qwen3-ASR-1.7B',
              'context': '', 'dtype': 'bfloat16', 'audio_seconds': len(audio)/16000,
              'chunk_seconds': args.chunk_seconds, 'natural_boundaries': args.natural_boundaries,
              'gain_db': args.gain_db,
              'compute_seconds': time.perf_counter()-began,
              'torch_peak_gib': torch.cuda.max_memory_allocated()/1024**3,
              'rows': rows, 'text': ' '.join(row['text'] for row in rows)}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    Path(args.output).with_suffix('.txt').write_text(result['text'], encoding='utf-8')
    print('peak GiB', result['torch_peak_gib'], flush=True)


if __name__ == '__main__':
    main()
