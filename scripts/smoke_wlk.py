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
    parser.add_argument("--qwen-model", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--update-seconds", type=float, default=1.0)
    parser.add_argument("--draft-seconds", type=float, default=.5)
    parser.add_argument("--endpoint-seconds", type=float, default=.5)
    parser.add_argument("--comparison", action="store_true", help="Reference is unverified: report disagreement, not accuracy")
    parser.add_argument("--audio", default="tests/fixtures/hello.wav")
    parser.add_argument("--translate", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--gap", type=float, default=1.0, help="Silence between fixture repetitions")
    parser.add_argument("--expect", default="Hello welcome to our meeting Today we are discussing a new project")
    parser.add_argument("--reference", help="Reference text for a non-repeated long fixture")
    parser.add_argument("--max-wer", type=float, default=0.05)
    parser.add_argument("--output", default=".work/wlk-smoke.json")
    parser.add_argument("--audio-preset", help="Enable the 48 kHz desktop enhancement route using this preset name")
    parser.add_argument("--audio-device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    from linguaflow.audio_processing.config import PRESETS
    audio_config = ({**PRESETS[args.audio_preset].to_dict(), "df_device": args.audio_device} if args.audio_preset else {})
    rate = 48000 if args.audio_preset else 16000
    settings = Settings("fixture", backend=args.backend, asr_model=args.model, asr_device="cuda",
                        qwen_model=args.qwen_model, update_seconds=args.update_seconds, draft_seconds=args.draft_seconds,
                        endpoint_seconds=args.endpoint_seconds,
                        input_sample_rate=rate, audio_processing=audio_config,
                        source="en", source_nllb="eng_Latn", translate=args.translate,
                        translation_device="cuda", translation_model="facebook/nllb-200-distilled-1.3B")
    with wave.open(args.audio) as wav:
        assert wav.getsampwidth() == 2
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, wav.getnchannels()).mean(axis=1)
        samples = resample_poly(samples, rate, wav.getframerate())
    samples = np.tile(np.concatenate((samples, np.zeros(round(rate * args.gap)))), args.repeat)
    pcm = np.clip(samples, -32768, 32767).astype("<i2").tobytes()
    python = root / ".venv-wlk" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    errors = Path(args.output).with_suffix(".log")
    errors.parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).with_suffix(".settings.json").write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
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
            chunk = rate // 5  # 100 ms PCM16
            for offset in range(0, len(pcm), chunk):
                send({"type": "audio", "pcm": base64.b64encode(pcm[offset:offset+chunk]).decode()})
                time.sleep(0.1)
            send({"type": "stop"})
        feeder = None
        for line in process.stdout:
            event = json.loads(line)
            event["received_monotonic"] = time.monotonic()
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
    finals = [e["data"] for e in events if e["type"] == "caption"]
    assert code == 0 and events[-1]["type"] == "done", f"Worker failed; see {errors}"
    import re
    # Validate all fixture words, not merely one greeting from a truncated row.
    rows = {}
    for caption in finals:
        if caption["source"]:
            rows[caption["id"]] = caption
        else:
            rows.pop(caption["id"], None)
    rows = dict(sorted(rows.items(), key=lambda item: item[1]["start"]))
    assert rows and all(c["final"] for c in rows.values()), "Unfinalized captions remain after stopping"
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
        label = "Unverified reference word disagreement" if args.comparison else "WER"
        print(f"{label} {wer:.3%}; reference {len(reference)} words; hypothesis {len(hypothesis)} words")
        if not args.comparison:
            assert wer <= args.max_wer, (wer, args.max_wer, actual)
    else:
        expected = normalize(args.expect)
        assert normalize(actual).count(expected) == args.repeat, (actual, args.expect, args.repeat)
    if args.translate:
        assert rows and all(c["translation"] and not c["error"] for c in rows.values()), rows
    print("PASS", args.backend, len(pcm)/(rate * 2), "audio seconds")
    Path(args.output).with_suffix(".txt").write_text(actual, encoding="utf-8")


if __name__ == "__main__":
    main()
