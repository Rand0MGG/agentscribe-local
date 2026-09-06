"""Opt-in real-model check. Downloads weights unless --offline is provided."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linguaflow.backends import NllbTranslator, WhisperRecognizer
from linguaflow.core import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", help="Optional audio file to recognize")
    parser.add_argument("--asr-model", default="tiny")
    parser.add_argument("--asr-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--translation-model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    settings = Settings(
        "",
        asr_model=args.asr_model,
        asr_device=args.asr_device,
        translation_model=args.translation_model,
        offline=args.offline,
        source="en",
        source_nllb="eng_Latn",
    )
    result = {}
    text = "Hello, welcome to our meeting. Today we are discussing a new project."
    if args.audio:
        from faster_whisper.audio import decode_audio

        print("Loading ASR model…", flush=True)
        recognizer = WhisperRecognizer(settings)
        recognizer.warmup()
        started = time.monotonic()
        segments, language = recognizer.recognize(decode_audio(args.audio, sampling_rate=16000))
        text = " ".join(item[2] for item in segments)
        result.update(source=text, detected_language=language, asr_seconds=time.monotonic() - started)
        if not text:
            raise RuntimeError("No speech recognized")
    print("Loading translation model…", flush=True)
    translator = NllbTranslator(settings)
    started = time.monotonic()
    result.update(
        source=text,
        translation=translator.translate(text, "en"),
        translation_seconds=time.monotonic() - started,
    )
    if not result["translation"]:
        raise RuntimeError("Empty translation")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
