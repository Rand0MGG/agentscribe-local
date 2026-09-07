"""Model adapters. Imports and downloads only occur when a session is started."""

from .core import WHISPER_TO_NLLB, Settings


class NllbTranslator:
    """Independent CPU or CUDA translation for NLLB-family models."""

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
        report(f"翻译权重已就绪，正在加载到 {getattr(settings, 'translation_device', 'cpu').upper()}…")
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
            .to(device=getattr(settings, "translation_device", "cpu"),
                dtype=torch.float16 if getattr(settings, "translation_device", "cpu") == "cuda" else torch.float32)
            .eval()
        )

    def translate(self, text: str, language: str) -> str:
        source = self.source or WHISPER_TO_NLLB.get(language)
        if source is None:
            raise ValueError(f"自动检测到 {language}，当前语言映射不支持；请手动选择源语言。")
        if source == self.target:
            return text
        self.tokenizer.src_lang = source
        inputs = self.tokenizer(text, return_tensors="pt", truncation=False)
        if inputs.input_ids.shape[1] > 512:
            raise ValueError("原文超出翻译模型单段长度限制；已保留完整原文，不静默截断。")
        inputs = inputs.to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                forced_bos_token_id=self.tokenizer.convert_tokens_to_ids(self.target),
                max_new_tokens=256,
                num_beams=1,
            )
        return self.tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()
