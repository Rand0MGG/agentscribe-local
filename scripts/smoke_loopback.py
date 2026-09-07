"""Windows opt-in acceptance test: play a supplied WAV and capture default output.

Uses real audio capture, segmentation, models, Qt signal delivery and SRT export.
The Session uses a temporary PCM journal. Run with a known test WAV and other playback paused.
"""

import json
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import winsound

import soundcard as sc
from PySide6.QtCore import QCoreApplication, QTimer

from linguaflow.core import Settings, export_srt
from linguaflow.wlk_session import Session


def main():
    path = Path(sys.argv[1]).resolve()
    with wave.open(str(path)) as wav:
        duration = wav.getnframes() / wav.getframerate()
    app = QCoreApplication([])
    settings = Settings(
        str(sc.default_speaker().id),
        loopback=True,
        asr_model="large-v3",
        asr_device="cuda",
        translation_model="facebook/nllb-200-distilled-1.3B",
        source="en",
        source_nllb="eng_Latn",
        offline=True,
        translation_device="cuda",
    )
    session = Session(settings)
    captions, errors, events = {}, [], []

    def report(text):
        events.append(text)
        print(text, flush=True)

    session.status.connect(report)
    session.failure.connect(errors.append)
    session.caption.connect(lambda c: captions.update({c.id: c}))

    def play():
        # Let the native recorder open before starting the known test clip.
        QTimer.singleShot(
            500, lambda: winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        )
        QTimer.singleShot(int((duration + 1.5) * 1000), session.stop)

    session.ready.connect(play)
    session.finished.connect(app.quit)
    session.start()
    app.exec()
    session.wait()
    winsound.PlaySound(None, 0)
    finals = [c for c in captions.values() if c.final and c.source]
    source = " ".join(re.findall(r"\w+", " ".join(c.source for c in finals).lower()))
    expected = "hello welcome to our meeting today we are discussing a new project"
    if errors or not finals or source != expected or not all(c.translation and not c.error for c in finals):
        raise RuntimeError(f"Loopback test failed: {errors}, source={source!r}, captions={[vars(c) for c in finals]}")
    result = {"fixture": path.name, "events": events, "captions": [vars(c) for c in finals]}
    Path("docs/loopback-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path("docs/loopback-result.srt").write_text(export_srt(list(captions.values())), encoding="utf-8")
    print(json.dumps(result["captions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
