"""Exercise the same worker used by Qt with paced real PCM and real models."""
import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
import wave
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow.core import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["wlk-whisper", "qwen3-streaming"], default="wlk-whisper")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--audio", default="tests/fixtures/hello.wav")
    parser.add_argument("--translate", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--gap", type=float, default=1.0, help="Silence between fixture repetitions")
    parser.add_argument("--expect", default="Hello welcome to our meeting Today we are discussing a new project")
    parser.add_argument("--reference", help="Reference text for a non-repeated long fixture")
    parser.add_argument("--max-wer", type=float, default=0.05)
    parser.add_argument("--output", default=".work/wlk-smoke.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings("fixture", backend=args.backend, asr_model=args.model, asr_device="cuda",
                        source="en", source_nllb="eng_Latn", translate=args.translate,
                        translation_device="cuda", translation_model="facebook/nllb-200-distilled-1.3B")
    with wave.open(args.audio) as wav:
        assert wav.getsampwidth() == 2
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, wav.getnchannels()).mean(axis=1)
        samples = resample_poly(samples, 16000, wav.getframerate())
    samples = np.tile(np.concatenate((samples, np.zeros(round(16000 * args.gap)))), args.repeat)
    pcm = np.clip(samples, -32768, 32767).astype("<i2").tobytes()
    python = root / ".venv-wlk" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    errors = Path(args.output).with_suffix(".log")
    errors.parent.mkdir(parents=True, exist_ok=True)
    events = []
    with errors.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(python), "-u", "-m", "linguaflow.wlk_worker"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                   text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        def send(data):
            process.stdin.write(json.dumps(data) + "\n")
            process.stdin.flush()
        send(asdict(settings))
        def feed():
            for offset in range(0, len(pcm), 3200):
                send({"type": "audio", "pcm": base64.b64encode(pcm[offset:offset+3200]).decode()})
                time.sleep(0.1)
            send({"type": "stop"})
        feeder = None
        for line in process.stdout:
            event = json.loads(line)
            events.append(event)
            if event["type"] == "ready":
                feeder = threading.Thread(target=feed)
                feeder.start()
            if event["type"] not in ("metrics", "snapshot"):
                print(json.dumps(event, ensure_ascii=False), flush=True)
        if feeder:
            feeder.join()
        code = process.wait()
    Path(args.output).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    finals = [e["data"] for e in events if e["type"] == "caption" and e["data"]["final"]]
    assert code == 0 and events[-1]["type"] == "done", f"Worker failed; see {errors}"
    import re
    # Validate all fixture words, not merely one greeting from a truncated row.
    rows = {c["id"]: c for c in finals if c["source"]}
    actual = " ".join(c["source"] for c in rows.values())
    def normalize(text):
        return " ".join(re.findall(r"\w+", text.lower()))
    if args.reference:
        reference = normalize(Path(args.reference).read_text(encoding="utf-8-sig")).split()
        hypothesis = normalize(actual).split()
        previous = list(range(len(hypothesis) + 1))
        for index, word in enumerate(reference, 1):
            current = [index]
            for column, candidate in enumerate(hypothesis, 1):
                current.append(min(current[-1] + 1, previous[column] + 1,
                                   previous[column-1] + (word != candidate)))
            previous = current
        wer = previous[-1] / max(1, len(reference))
        print(f"WER {wer:.3%}; reference {len(reference)} words; hypothesis {len(hypothesis)} words")
        assert wer <= args.max_wer, (wer, args.max_wer, actual)
    else:
        expected = normalize(args.expect)
        assert normalize(actual).count(expected) == args.repeat, (actual, args.expect, args.repeat)
    if args.translate:
        assert rows and all(c["translation"] and not c["error"] for c in rows.values()), rows
    print("PASS", args.backend, len(pcm)/32000, "audio seconds")


if __name__ == "__main__":
    main()
