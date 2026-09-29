"""Session settings, captions and subtitle export (independent of Qt/models)."""

from dataclasses import dataclass, field

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
    backend: str = "wlk-whisper"
    qwen_model: str = "Qwen/Qwen3-ASR-0.6B"
    qwen_mode: str = "fast"
    qwen_window_seconds: float = 30.0
    update_seconds: float = 1.0
    draft_seconds: float = 0.5
    endpoint_seconds: float = 0.5
    translation_device: str = "cpu"
    translation_before: int = 3
    translation_after: int = 1
    input_sample_rate: int = 16000
    audio_processing: dict = field(default_factory=dict)
    semantic_device: str = "cpu"
    semantic_lookahead: float = 3.0


@dataclass
class Caption:
    id: int
    start: float
    end: float
    source: str
    language: str
    translation: str = ""
    error: str = ""
    final: bool = True
    revision: int = 1
    stable_source: str = ""
    ready: bool = False
    boundary_reason: str = ""
    translation_phase: str = ""  # initial / final; empty for older saved captions
    translation_source: str = ""


def translation_status(caption):
    if caption.error:
        return "最终翻译失败" if caption.final else "初译失败"
    if caption.translation_phase == "final" and caption.translation:
        return "译文已定稿"
    if not caption.translation_phase and caption.translation and caption.final:
        return "已保存译文"
    if caption.translation:
        if caption.final:
            return "初译 · 等待最终译文"
        if caption.translation_source and caption.translation_source != caption.source:
            return "初译 · 原文已更新"
        return "初译 · 待原文定稿"
    return "等待最终翻译" if caption.final else ("等待初译" if caption.ready else "等待原文提交")


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def export_srt(captions: list[Caption]) -> str:
    rows = []
    for index, caption in enumerate((c for c in captions if c.final and c.source.strip()), 1):
        text = caption.source.strip()
        if caption.translation:
            prefix = '[初译] ' if caption.translation_phase == 'initial' else ''
            text += "\n" + prefix + caption.translation.strip()
        rows.append(f"{index}\n{srt_time(caption.start)} --> {srt_time(caption.end)}\n{text}\n")
    return "\n".join(rows)
