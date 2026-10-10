"""Model adapters. Imports and downloads only occur when a session is started."""

from .core import WHISPER_TO_NLLB, Settings
from .translation_models import (
    HY_GENERATION,
    NLLB_GENERATION,
    fit_translation_prompt,
    is_hy_model,
    translation_engine,
    translation_prompt,
)


def create_translator(settings, report=lambda text: None):
    engine = translation_engine(settings)
    if engine == 'llama':
        from .llama_translation import LlamaTranslator
        return LlamaTranslator(settings, report)
    if engine != 'pytorch' or settings.translation_device not in ('cpu', 'cuda'):
        raise ValueError('不支持的翻译引擎与设备组合')
    if not is_hy_model(settings.translation_model) and 'nllb' not in settings.translation_model.lower():
        from pathlib import Path
        if not Path(settings.translation_model).is_dir():
            raise ValueError('PyTorch 当前支持 HY-MT2、NLLB 及兼容模型目录。')
    cls = HyMtTranslator if is_hy_model(settings.translation_model) else NllbTranslator
    return cls(settings, report)


class HyMtTranslator:
    """Translate individual source strings with bounded context.

    Unconstrained HY generation cannot reliably map JSON subtitle IDs. The
    shared queue uses single requests here; llama.cpp owns constrained batching.
    """

    def __init__(self, settings, report=lambda text: None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        from .model_cache import resolve_translation

        self.torch, self.target, self.source = torch, settings.target, settings.source_nllb
        self.report = report
        torch.set_num_threads(4)
        path = resolve_translation(settings.translation_model, report)
        device = settings.translation_device
        dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_bf16_supported() else (
            torch.float16 if device == 'cuda' else torch.float32)
        report(f'正在加载 HY-MT2 到 {device.upper()}…')
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        if not self.tokenizer.chat_template:
            raise ValueError('HY-MT2 缺少 chat_template.jinja；请重新下载 / 检查模型，或选择完整模型目录。')
        self.model = AutoModelForCausalLM.from_pretrained(
            path, local_files_only=True, trust_remote_code=False, weights_only=True,
            dtype=dtype).to(device).eval()

    def translate(self, text, language, context=None):
        if (self.source or WHISPER_TO_NLLB.get(language)) == self.target:
            return text
        return self.complete(lambda background: translation_prompt(text, self.target, background), context)

    def complete(self, build_prompt, context):
        inputs = None
        def count_tokens(prompt):
            nonlocal inputs
            inputs = self.tokenizer.apply_chat_template(
                [{'role': 'user', 'content': prompt}], add_generation_prompt=True,
                tokenize=True, return_dict=True, return_tensors='pt')
            return inputs['input_ids'].shape[-1]
        _prompt, trimmed = fit_translation_prompt(build_prompt, context, count_tokens, 8192)
        if trimmed:
            self.report('翻译背景超出输入预算，已缩减较远上下文；待译原文完整保留。')
        inputs = inputs.to(self.model.device)
        # The generic fast tokenizer emits segment IDs; this causal model does
        # not accept them (unlike encoder/decoder translation tokenizers).
        inputs.pop('token_type_ids', None)
        length = inputs['input_ids'].shape[-1]
        if length > 8192:
            raise ValueError('本段翻译输入过长；已保留原文，不静默截断。')
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, **HY_GENERATION)
        tokens = output[0][length:]
        eos = self.model.generation_config.eos_token_id
        eos = eos if isinstance(eos, list) else [eos]
        if len(tokens) >= HY_GENERATION['max_new_tokens'] and int(tokens[-1]) not in eos:
            raise ValueError('译文达到长度上限，未将截断结果作为定稿。')
        result = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        if not result:
            raise ValueError('翻译模型未返回文字，原文已保留。')
        return result


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

        model_path = resolve_translation(settings.translation_model, report)
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
                **NLLB_GENERATION,
            )
        return self.tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()
