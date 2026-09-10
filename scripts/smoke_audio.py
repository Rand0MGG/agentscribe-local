"""Real optional engines: continuity, tail, alignment and fixture processing.

Run with .venv-wlk Python after install_audio.py; no microphone or playback.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import correlate, correlation_lags

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow.audio_processing.config import AudioConfig, PRESETS
from linguaflow.audio_processing.pipeline import AudioPipeline, DeepFilter, WPE
from linguaflow.audio_processing.preview import process_file


def stream(data, config, chunk):
    pipeline = AudioPipeline(config)
    result = np.concatenate([pipeline.process(data[i:i + chunk]) for i in range(0, len(data), chunk)]
                            + [pipeline.flush()])
    assert not len(pipeline.flush())
    assert len(result) == round(len(data) / 3), (len(result), len(data))
    assert np.isfinite(result).all()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    source = np.random.default_rng(123).normal(0, .08, 48017).astype(np.float32)
    # Overlap/add bypass must preserve every sample, including partial tail.
    wpe = WPE(AudioConfig(wpe=True, wpe_mix=0))
    reconstructed = np.concatenate([wpe.push(source[:811]), wpe.push(source[811:]), wpe.flush()])
    np.testing.assert_allclose(reconstructed, source, atol=1e-6)
    # Check the actual neural export's dry/wet alignment, not wrapper metadata.
    df = DeepFilter(AudioConfig(deepfilter=True, df_device=args.device, df_mix=1))
    complete = source[:len(source) // df.size * df.size]
    wet = np.concatenate([df.frame(complete[i:i + df.size]) for i in range(0, len(complete), df.size)])
    lag = correlation_lags(len(wet), len(complete))[np.argmax(correlate(wet, complete))]
    assert lag == df.delay, (lag, df.delay)
    if args.device == "cuda":
        # Numerical equivalence after unfusing the CPU export's node.
        cpu = DeepFilter(AudioConfig(deepfilter=True, df_mix=1))
        gpu = DeepFilter(AudioConfig(deepfilter=True, df_device="cuda", df_mix=1))
        for i in range(0, 512 * 20, 512):
            np.testing.assert_allclose(cpu.frame(complete[i:i+512]), gpu.frame(complete[i:i+512]),
                                       atol=2e-5, rtol=2e-3)
    results = []
    output = Path(".work/audio-validation")
    output.mkdir(parents=True, exist_ok=True)
    for index, (name, preset) in enumerate(PRESETS.items()):
        config = {**preset.to_dict(), "df_device": args.device}
        whole = stream(source, config, len(source))
        chopped = stream(source, config, 137)
        np.testing.assert_allclose(whole, chopped, atol=1e-6)
        stats = process_file("tests/fixtures/hello.wav", output / f"{args.device}-{index}.wav", config)
        stats["preset"] = name
        results.append(stats)
        print(name, f"{stats['elapsed']:.3f}s / {stats['seconds']:.2f}s audio", flush=True)
    Path(output / f"{args.device}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PASS: continuous state, sample count, tails, DF alignment, all presets", args.device)


if __name__ == "__main__":
    main()
