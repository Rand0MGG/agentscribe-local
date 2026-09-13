"""Process the fixed recording through the live audio front end, without GUI limits."""
import argparse
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--input', default='media/test.m4a')
    parser.add_argument('--output', default='.work/classroom-enhanced.wav')
    args = parser.parse_args()
    import av
    import numpy as np
    from linguaflow.audio_processing.pipeline import AudioPipeline
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    began = time.perf_counter()
    print('Initializing audio pipeline', flush=True)
    pipeline = AudioPipeline(config, 48000)
    print(f'Pipeline ready in {time.perf_counter()-began:.1f}s', flush=True)
    with av.open(args.input) as source, wave.open(args.output, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
        total = 0
        last_report = 0
        def write(samples):
            nonlocal total, last_report
            output.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
            total += len(samples)
            if total - last_report >= 480000:
                print(f'Processed {total/16000:.1f}s audio in {time.perf_counter()-began:.1f}s', flush=True)
                last_report = total
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                write(pipeline.process(converted.to_ndarray().reshape(-1).astype(np.float32) / 32767))
        for converted in resampler.resample(None):
            write(pipeline.process(converted.to_ndarray().reshape(-1).astype(np.float32) / 32767))
        write(pipeline.flush())
    Path(args.output + '.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
