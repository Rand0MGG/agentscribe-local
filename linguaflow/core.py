"""Audio segmentation, session data, and bounded queues (independent of Qt/models)."""

from collections import deque
from dataclasses import dataclass
from queue import Empty, Full, Queue

import numpy as np

SAMPLE_RATE = 16000
# UI label, Whisper code, NLLB language token
LANGUAGES = [
    ("简体中文", "zh", "zho_Hans"),
    ("English", "en", "eng_Latn"),
    ("日本語", "ja", "jpn_Jpan"),
    ("한국어", "ko", "kor_Hang"),
    ("Français", "fr", "fra_Latn"),
    ("Deutsch", "de", "deu_Latn"),
    ("Español", "es", "spa_Latn"),
    ("Русский", "ru", "rus_Cyrl"),
    ("العربية", "ar", "arb_Arab"),
    ("Português", "pt", "por_Latn"),
    ("Italiano", "it", "ita_Latn"),
    ("繁體中文", "zh", "zho_Hant"),
]
WHISPER_TO_NLLB = {code: token for _, code, token in reversed(LANGUAGES)}


@dataclass(frozen=True)
class Settings:
    device_id: str
    loopback: bool = False
    asr_model: str = "small"
    asr_device: str = "cpu"
    translation_model: str = "facebook/nllb-200-distilled-600M"
    source: str | None = None
    source_nllb: str | None = None
    target: str = "zho_Hans"
    translate: bool = True
    offline: bool = False
    phrase_seconds: float = 4.0
    threshold: float = 0.008


@dataclass
class AudioPhrase:
    samples: np.ndarray
    start: float
    end: float


@dataclass
class Caption:
    id: int
    start: float
    end: float
    source: str
    language: str
    translation: str = ""
    error: str = ""


def offer_latest(queue: Queue, item) -> bool:
    """Single-producer queue. Keep latency bounded; report a dropped oldest item."""
    dropped = False
    while True:
        try:
            queue.put_nowait(item)
            return dropped
        except Full:
            try:
                queue.get_nowait()
                dropped = True
            except Empty:
                pass


class Segmenter:
    """Energy gate with pre-roll, followed by Whisper's Silero VAD in the ASR stage.

    Input must be consecutive 100 ms mono blocks at 16 kHz. No overlapping
    phrases, so independent transcriptions cannot duplicate an overlap region.
    """

    def __init__(self, max_seconds=4.0, threshold=0.008):
        self.max_samples = int(max_seconds * SAMPLE_RATE)
        self.threshold = threshold
        self.position = 0
        self.pre = deque(maxlen=3)
        self.active = []
        self.start = 0
        self.size = 0
        self.silence = 0
        self.voiced = 0

    def push(self, block: np.ndarray) -> AudioPhrase | None:
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if len(block) != 1600:
            raise ValueError("Expected 100 ms / 1600 samples")
        loud = float(np.sqrt(np.mean(block * block))) >= self.threshold
        if not self.active:
            if not loud:
                self.pre.append(block.copy())
                self.position += len(block)
                return None
            self.active = list(self.pre)
            self.size = sum(len(x) for x in self.active)
            self.start = self.position - self.size
            self.pre.clear()
        self.active.append(block.copy())
        self.size += len(block)
        self.position += len(block)
        self.voiced += len(block) if loud else 0
        self.silence = 0 if loud else self.silence + len(block)
        if self.silence >= 8000 or self.size >= self.max_samples:
            return self.flush()
        return None

    def flush(self) -> AudioPhrase | None:
        result = None
        if self.active and self.voiced >= 3200:
            result = AudioPhrase(
                np.concatenate(self.active), self.start / SAMPLE_RATE, (self.start + self.size) / SAMPLE_RATE
            )
        self.active = []
        self.size = self.silence = self.voiced = 0
        return result


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def export_srt(captions: list[Caption]) -> str:
    rows = []
    for index, caption in enumerate(captions, 1):
        text = caption.source.strip()
        if caption.translation:
            text += "\n" + caption.translation.strip()
        rows.append(f"{index}\n{srt_time(caption.start)} --> {srt_time(caption.end)}\n{text}\n")
    return "\n".join(rows)
