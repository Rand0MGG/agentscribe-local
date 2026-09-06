"""Model adapters. Imports and downloads only occur when a session is started."""

from .core import WHISPER_TO_NLLB, Settings


class WhisperRecognizer:
    def __init__(self, settings: Settings, report=lambda text: None):
        if settings.asr_device == "cuda":
            from .runtime import prepare_cuda

            report("检查 GPU 运行库…")
            prepare_cuda()
        from faster_whisper import WhisperModel

        self.source = settings.source
        report(f"加载识别模型 {settings.asr_model} · {settings.asr_device}；首次下载进度见终端")
        self.model = WhisperModel(
            settings.asr_model,
            device=settings.asr_device,
            compute_type="int8_float16" if settings.asr_device == "cuda" else "int8",
            local_files_only=settings.offline,
            cpu_threads=4,
            num_workers=1,
        )

    def warmup(self):
        import numpy as np

        # Do not use VAD here: silence would skip GPU kernels and miss missing DLLs.
        segments, _ = self.model.transcribe(
            np.zeros(16000, dtype=np.float32),
            language="en",
            vad_filter=False,
            beam_size=1,
            max_new_tokens=1,
            condition_on_previous_text=False,
        )
        list(segments)  # faster-whisper inference is lazy; consume the generator.

    def recognize(self, samples):
        segments, info = self.model.transcribe(
            samples,
            language=self.source,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350},
            condition_on_previous_text=False,
            temperature=0.0,
        )
        return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()], info.language

    def recognize_words(self, samples, prompt=""):
        # Whole rolling window, with word boundaries and no amplitude/VAD removal.
        segments, info = self.model.transcribe(
            samples, language=self.source, beam_size=5, word_timestamps=True,
            vad_filter=False, initial_prompt=prompt or None,
            condition_on_previous_text=True, temperature=0.0,
        )
        words = []
        for segment in segments:
            if segment.no_speech_prob > 0.8 and segment.avg_logprob < -0.5:
                continue
            words.extend((w.start, w.end, w.word) for w in (segment.words or []))
        return words, info.language

    def endpoint(self, samples, seconds):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        tail = samples[-16000 * 8:]
        speech = get_speech_timestamps(tail, VadOptions(min_silence_duration_ms=500, speech_pad_ms=0))
        return (len(tail) - speech[-1]["end"]) / 16000 >= seconds if speech else len(tail) >= seconds * 16000


class NllbTranslator:
    """CPU-only translation preserves VRAM for ASR; NLLB-family models only."""

    @staticmethod
    def prepare_runtime():
        import torch
        from transformers import M2M100ForConditionalGeneration, NllbTokenizerFast

        torch.set_num_threads(4)
        return torch.Tensor, M2M100ForConditionalGeneration, NllbTokenizerFast

    def __init__(self, settings: Settings, report=lambda text: None):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        torch.set_num_threads(4)
        self.target = settings.target
        self.source = settings.source_nllb
        from .model_cache import resolve_translation

        model_path = resolve_translation(settings.translation_model, settings.offline, report)
        report("翻译权重已就绪，正在加载到 CPU 内存…")
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
        )
        if "Nllb" not in type(self.tokenizer).__name__:
            raise ValueError("翻译模型必须是 NLLB 系列，或其完整本地模型目录。")
        self.model = (
            AutoModelForSeq2SeqLM.from_pretrained(
                model_path,
                local_files_only=True,
                trust_remote_code=False,
                weights_only=True,
            )
            .to("cpu")
            .eval()
        )

    def translate(self, text: str, language: str) -> str:
        source = self.source or WHISPER_TO_NLLB.get(language)
        if source is None:
            raise ValueError(f"自动检测到 {language}，当前语言映射不支持；请手动选择源语言。")
        if source == self.target:
            return text
        self.tokenizer.src_lang = source
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.convert_tokens_to_ids(self.target),
                max_new_tokens=256,
                num_beams=1,
            )
        return self.tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()
