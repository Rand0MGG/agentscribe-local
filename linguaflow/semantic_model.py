"""Local SaT boundary predictions; returns offsets, never generated text."""
from pathlib import Path

MODEL = "segment-any-text/sat-3l-sm"
TOKENIZER = "facebookAI/xlm-roberta-base"
MODEL_REVISION = "137da054051ad9f1eac42025f758db4ac9f22535"
TOKENIZER_REVISION = "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"


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
        from wtpsplit import SaT
        import onnxruntime as ort
        model, tokenizer = paths()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        provider = "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
        self.model = SaT(model, tokenizer_name_or_path=tokenizer, ort_providers=[provider],
                         ort_kwargs={"sess_options": options}, from_pretrained_kwargs={"local_files_only": True})
        if provider not in self.model.model.ort_session.get_providers():
            raise RuntimeError("所选 SaT 设备未成功初始化，没有静默切换设备。")

    def boundaries(self, text):
        # The model predicts each character's boundary probability using context.
        pieces = self.model.split(text, threshold=.5, strip_whitespace=False)
        if "".join(pieces) != text:
            raise ValueError("分句模型改变了输入文本，已拒绝该结果。")
        offset, boundaries = 0, []
        for piece in pieces[:-1]:
            offset += len(piece)
            boundaries.append(offset)
        return boundaries


if __name__ == "__main__":
    print("准备 SaT 分句模型与分词器…", flush=True)
    paths(prepare=True)
    model = SemanticModel()
    print(model.boundaries("这是第一段内容 我们接着看第二个例子"), flush=True)
    print("SaT 分句模型已准备好；下一次聆听自动使用。", flush=True)
