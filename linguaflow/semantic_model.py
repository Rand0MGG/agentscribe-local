"""Local SaT boundary predictions; returns original-text offsets, never rewritten text."""
import re
import unicodedata
from pathlib import Path

MODEL = "segment-any-text/sat-3l-sm"
TOKENIZER = "facebookAI/xlm-roberta-base"
MODEL_REVISION = "137da054051ad9f1eac42025f758db4ac9f22535"
TOKENIZER_REVISION = "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"

_STRUCTURED_TEXT = re.compile(
    r"(?:https?://|www\.)[^\s<>\"“”。！？；：，、（）【】]+"
    r"|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"
    r"|\b(?:[A-Za-z]\.){2,}"
    r"|\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr)\.",
)
_OPENING = '“‘「『（([{《〈【'


def _cjk(char):
    return ('\u3400' <= char <= '\u9fff' or '\u3040' <= char <= '\u30ff'
            or '\uac00' <= char <= '\ud7af' or '\U00020000' <= char <= '\U0003134f')


def _sat_input(text):
    """Clean a predictor-only copy and retain each character's original index."""
    protected = set()
    for match in _STRUCTURED_TEXT.finditer(text):
        value = match.group()
        if value.startswith(('http://', 'https://', 'www.')):
            value = value.rstrip('.,!?;:。！？；：，)]}）')
        protected.update(range(match.start(), match.start() + len(value)))
    remove = []
    for i, char in enumerate(text):
        inside = 0 < i < len(text)-1 and text[i-1].isalnum() and text[i+1].isalnum()
        word_symbol = inside and char in "'-’‐‑_"
        decimal = inside and char == '.' and text[i-1].isdigit() and text[i+1].isdigit()
        negative = char == '-' and i+1 < len(text) and text[i+1].isdigit()
        remove.append(unicodedata.category(char).startswith('P')
                      and i not in protected and not word_symbol and not decimal and not negative)
    chars, owners = [], []
    i = 0
    while i < len(text):
        if not remove[i]:
            chars.append(text[i])
            owners.append(i)
            i += 1
            continue
        end = i + 1
        while end < len(text) and remove[end]:
            end += 1
        # Removing punctuation must not turn "hello,world" into "helloworld".
        # CJK writing does not need an artificial space between adjacent words.
        if (chars and end < len(text) and chars[-1].isalnum() and text[end].isalnum()
                and not (_cjk(chars[-1]) and _cjk(text[end]))):
            chars.append(' ')
            owners.append(i)
        i = end
    return ''.join(chars), owners


def _original_boundary(text, cleaned, owners, offset):
    """Keep opening quotation/bracket characters with the following sentence."""
    left, right = offset - 1, offset
    while left >= 0 and cleaned[left].isspace():
        left -= 1
    while right < len(cleaned) and cleaned[right].isspace():
        right += 1
    if left < 0:
        return 0
    if right == len(cleaned):
        return len(text)
    boundary = owners[right]
    for i in range(owners[left] + 1, owners[right]):
        if text[i] in _OPENING or (text[i] in '\"\'' and i > 0 and text[i-1].isspace()):
            boundary = min(boundary, i)
            break
    return boundary


def paths(prepare=False):
    from huggingface_hub import snapshot_download
    model = snapshot_download(MODEL, allow_patterns=["config.json", "model_optimized.onnx"],
                              local_files_only=not prepare, revision=MODEL_REVISION)
    tokenizer = snapshot_download(TOKENIZER, allow_patterns=["config.json", "tokenizer.json",
        "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model"],
        local_files_only=not prepare, revision=TOKENIZER_REVISION)
    if not (Path(model) / "model_optimized.onnx").is_file():
        raise ValueError("SaT 权重不完整，请在模型管理的‘字幕与延迟’中准备分句模型。")
    return model, tokenizer


class SemanticModel:
    def __init__(self, device="cpu"):
        if device == "cuda":
            from .audio_processing.pipeline import select_backend
            select_backend(device)
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("SaT CUDA 不可用")
        import onnxruntime as ort
        from wtpsplit import SaT
        model, tokenizer = paths()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        provider = "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
        if device == 'cpu':
            from .semantic_cache import cached_cpu_model
            cached = cached_cpu_model(model, ort.__version__)
            if cached is not None:
                model = cached
                options.add_session_config_entry('session.load_model_format', 'ORT')
                options.add_session_config_entry('session.use_memory_mapped_ort_model', '1')
                options.add_session_config_entry('session.use_ort_model_bytes_for_initializers', '1')
        self.model = SaT(model, tokenizer_name_or_path=tokenizer, ort_providers=[provider],
                         ort_kwargs={"sess_options": options}, from_pretrained_kwargs={"local_files_only": True})
        if provider not in self.model.model.ort_session.get_providers():
            raise RuntimeError("所选 SaT 设备未成功初始化，没有静默切换设备。")

    def boundaries(self, text):
        # The model predicts each character's boundary probability using context.
        cleaned, owners = _sat_input(text)
        if not cleaned.strip():
            return []
        try:
            pieces = list(self.model.split(cleaned, threshold=.5, strip_whitespace=False,
                                           split_on_input_newlines=False))
        except Exception as exc:
            raise RuntimeError("SaT 分句推理失败：" + str(exc)) from exc
        if "".join(pieces) != cleaned:
            raise ValueError("分句模型改变了输入文本，已拒绝该结果。")
        offset, boundaries = 0, []
        for piece in pieces[:-1]:
            offset += len(piece)
            if 0 < offset < len(cleaned):
                original = _original_boundary(text, cleaned, owners, offset)
                if 0 < original < len(text) and (not boundaries or original > boundaries[-1]):
                    boundaries.append(original)
        return boundaries


if __name__ == "__main__":
    print("准备 SaT 分句模型与分词器…", flush=True)
    source, _ = paths(prepare=True)
    import onnxruntime as ort

    from .semantic_cache import prepare_cpu_model
    if prepare_cpu_model(source, ort, force=True) is not None:
        print("SaT CPU 启动优化缓存已准备；载入时直接映射权重。", flush=True)
    model = SemanticModel()
    print(model.boundaries("这是第一段内容 我们接着看第二个例子"), flush=True)
    print("SaT 分句模型已准备好；下一次聆听自动使用。", flush=True)
