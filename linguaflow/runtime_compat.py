"""Compatibility for native dependencies in Unicode Windows checkouts."""
import atexit
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


def configure_vad_pause(processor, seconds):
    """Apply the UI pause to Silero itself, not only WLK line segmentation."""
    import math
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("语音停顿阈值必须是有限正数")
    if processor.vac is not None:
        processor.vac.min_silence_samples = round(processor.sample_rate * seconds)


def prepare_qwen_dependencies():
    # Qwen imports its optional Japanese aligner even for streaming English.
    # DyNet's model loader cannot open Unicode Windows paths. Keep the real
    # nagisa package and assets together under an ASCII temporary import root.
    if os.name != "nt" or "nagisa" in sys.modules:
        return
    spec = importlib.util.find_spec("nagisa")
    if spec is None or str(spec.origin).isascii():
        return
    temporary = tempfile.TemporaryDirectory(prefix="linguaflow-nagisa-")
    if not temporary.name.isascii():
        temporary.cleanup()
        raise RuntimeError("Qwen 的日语分词依赖需要 ASCII 临时路径，请将 TEMP 指向仅含英文字母的目录。")
    shutil.copytree(Path(spec.origin).parent, Path(temporary.name) / "nagisa",
                    ignore=shutil.ignore_patterns("__pycache__"))
    sys.path.insert(0, temporary.name)
    try:
        importlib.import_module("nagisa")
    except Exception:
        temporary.cleanup()
        raise
    finally:
        sys.path.remove(temporary.name)
    atexit.register(temporary.cleanup)


def create_whisper_engine(engine_type, config, device):
    """Set the native Whisper device/dtype before upstream warmup.

    The pinned backend does not forward an explicit device to load_model and
    its AlignAtt encoder normally receives FP32 mel. Load on CPU first to
    avoid a temporary full-precision CUDA model, then apply the selected
    device/precision. No changes are made to installed package files.
    """
    from whisperlivekit.simul_whisper import backend
    # Upstream otherwise waits five seconds before resetting an ended
    # utterance. Honor the same pause threshold selected in the desktop UI;
    # carrying repeated completed sentences into a growing decoder context
    # can trigger its repetition guard. This worker owns exactly one session.
    backend.MIN_DURATION_REAL_SILENCE = config.pause_segmentation_seconds
    original = backend.load_model

    def load(*args, **kwargs):
        kwargs["device"] = "cpu"
        model = original(*args, **kwargs)
        if device == "cuda":
            import torch
            model = model.half()
            # Whisper's LayerNorm explicitly normalizes x.float(), so its
            # small scale/bias tensors must remain FP32 in a mixed model.
            for module in model.modules():
                if isinstance(module, torch.nn.LayerNorm):
                    module.float()
            model = model.to(device)

            def encoder_dtype(module, inputs):
                return (inputs[0].to(dtype=module.conv1.weight.dtype), *inputs[1:])
            model.encoder.register_forward_pre_hook(encoder_dtype)
        return model

    backend.load_model = load
    try:
        return engine_type(config=config)
    finally:
        backend.load_model = original


def finalize_whisper_once(processor):
    """Do not decode the same ended utterance again at stream shutdown.

    WLK calls start_silence at the VAD boundary, then falls back to calling it
    again at EOF for this backend. Silence padding is not new speech. Repeated
    final decoding can invent a trailing word; new PCM resets the generation.
    """
    insert_audio = processor.insert_audio_chunk
    start_silence = processor.start_silence
    generation, finalized = 0, -1

    def insert(*args, **kwargs):
        nonlocal generation
        result = insert_audio(*args, **kwargs)
        generation += 1
        return result

    def finish():
        nonlocal finalized
        if finalized == generation:
            return [], processor.end
        result = start_silence()
        finalized = generation
        return result

    processor.insert_audio_chunk = insert
    processor.start_silence = finish
    processor.finish = finish
    end_silence = getattr(processor, "end_silence", None)
    if end_silence:
        def advance_silence(duration, last_word_end):
            # The last recognized word can end before the actual audio cut.
            # Using its timestamp as the next segment origin accumulates
            # drift after repeated pauses. The processor owns the PCM clock.
            return end_silence(duration, processor.end)
        processor.end_silence = advance_silence
