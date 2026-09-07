"""Real desktop Session, Qt signals, PCM, models, translation and SRT export."""
import argparse
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linguaflow.core import Settings, export_srt
from linguaflow.wlk_session import Session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["wlk-whisper", "qwen3-streaming"], default="wlk-whisper")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = parser.parse_args()
    with wave.open("tests/fixtures/hello.wav") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, wav.getnchannels()).mean(axis=1) / 32768
        samples = resample_poly(samples, 16000, wav.getframerate()).astype(np.float32)
    samples = np.concatenate((samples, np.zeros(24000, np.float32)))

    def capture(settings, stop, block):
        for offset in range(0, len(samples), 1600):
            if stop.is_set():
                break
            block(samples[offset:offset + 1600])
            stop.wait(.1)

    app = QCoreApplication([])
    session = Session(Settings("fixture", backend=args.backend, asr_model=args.model,
                               asr_device=args.device, translation_device="cuda", source="en",
                               source_nllb="eng_Latn", offline=True), capture_fn=capture)
    # Use the already cached model rather than download a second NLLB variant.
    from dataclasses import replace
    session.settings = replace(session.settings, translation_model="facebook/nllb-200-distilled-1.3B")
    rows, errors = {}, []
    session.caption.connect(lambda caption: rows.update({caption.id: caption}))
    session.failure.connect(errors.append)
    session.status.connect(lambda message: print(message, flush=True))
    session.finished.connect(app.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (errors.append("timeout"), session.stop(discard=True)))
    timer.start(180000)
    session.start()
    app.exec()
    session.wait()
    assert not errors, errors
    finals = [c for c in rows.values() if c.final and c.source]
    source = " ".join(re.findall(r"\w+", " ".join(c.source for c in finals).lower()))
    assert source == "hello welcome to our meeting today we are discussing a new project", source
    assert all(c.translation and not c.error for c in finals), finals
    output = Path(".work") / (args.backend + "-session")
    output.with_suffix(".json").write_text(json.dumps([vars(c) for c in finals], ensure_ascii=False, indent=2), encoding="utf8")
    output.with_suffix(".srt").write_text(export_srt(finals), encoding="utf8")
    print("PASS desktop Session", args.backend)


if __name__ == "__main__":
    main()
