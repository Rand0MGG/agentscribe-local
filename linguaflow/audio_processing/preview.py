"""Offline audition of the exact stateful front end used by wlk_worker."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .pipeline import AudioPipeline
from .health import signal_stats, input_warning


def process_file(source, destination, config):
    info = sf.info(source)
    if info.duration > 60:
        raise ValueError("回听样本最长 60 秒，请截取有代表性的一段。")
    pcm16 = info.subtype == "PCM_16"
    samples, rate = sf.read(source, dtype="int16" if pcm16 else "float32", always_2d=True)
    if len(samples) > rate * 60:
        raise ValueError("回听样本最长 60 秒，请截取有代表性的一段。")
    x = samples.astype(np.float32).mean(axis=1) / (32767 if pcm16 else 1)
    # Live transport is PCM16 before enhancement; audition uses the same range
    # and quantization so gain/threshold comparisons are meaningful.
    if not (pcm16 and samples.shape[1] == 1):
        x = (np.clip(x, -1, 1) * 32767).astype("<i2").astype(np.float32) / 32767
    health = signal_stats(x)
    if not health["nonzero"]:
        raise ValueError(input_warning(health))
    start = time.perf_counter()
    pipeline = AudioPipeline(config, rate)
    output = [pipeline.process(x[i:i + 4800]) for i in range(0, len(x), 4800)]
    output.append(pipeline.flush())
    y = np.concatenate(output)
    elapsed = time.perf_counter() - start
    if not len(y):
        raise ValueError("样本没有音频。")
    processed_health = signal_stats(y)
    if not processed_health["nonzero"]:
        raise RuntimeError("原声有信号，但处理输出完全为零。请关闭降噪逐项检查；本次结果不作为成功输出。")
    # Explicit PCM16 conversion, identical to the live worker.
    sf.write(destination, (np.clip(y, -1, 1) * 32767).astype(np.int16), 16000, subtype="PCM_16")
    rms = lambda a: float(20 * np.log10(max(float(np.sqrt(np.mean(a ** 2))), 1e-9)))
    return {"seconds": len(x) / rate, "elapsed": elapsed, "input_dbfs": rms(x),
            "output_dbfs": rms(y), "clip_percent": float(np.mean(np.abs(y) > 1) * 100),
            "wpe_protected_bins": sum(getattr(s, "protected_bins", 0) for s in pipeline.stages),
            "samples": len(y), "config": config}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    stats = process_file(args.input, args.output, config)
    Path(args.output + ".json").write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
