"""Decode the local classroom fixture reproducibly; run with .venv-wlk Python."""
import hashlib
import json
import wave
from pathlib import Path

import av


def main():
    root = Path(__file__).resolve().parents[1]
    source, reference = root / 'media/test.m4a', root / 'media/test.txt'
    output = root / '.work/classroom.wav'
    output.parent.mkdir(exist_ok=True)
    with av.open(str(source)) as container, wave.open(str(output), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        for frame in container.decode(audio=0):
            for decoded in resampler.resample(frame):
                wav.writeframes(decoded.to_ndarray().tobytes())
        for decoded in resampler.resample(None):
            wav.writeframes(decoded.to_ndarray().tobytes())
    manifest = {'audio_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
                'reference_status': 'Unverified Qwen Scribe + 1.7B output, not ground truth',
                'decoder': f'PyAV {av.__version__}; standard mono rematrix; PCM16 16000 Hz'}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
