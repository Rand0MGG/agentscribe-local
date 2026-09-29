"""Compatibility for native dependencies in Unicode Windows checkouts."""
import atexit
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


async def pause_audio_processor(processor):
    """Drain accepted PCM and end the utterance without ending the session."""
    await processor._flush_remaining_pcm()
    await processor._begin_silence(at_sample=processor.total_pcm_samples)
    if processor.vac is not None:
        processor.vac.reset_states()
        processor.vac.current_sample = processor.total_pcm_samples


async def results_with_final_snapshot(processor, results):
    """Refresh after EOF: ASR can finish while the consumer handles a snapshot.

    The pinned formatter checks task completion after yielding. If final tokens
    arrive during that yield, it can return without publishing those tokens.
    A fresh formatter pass reads the completed state before it checks EOF.
    """
    async for snapshot in results:
        yield snapshot
    if processor.is_stopping:
        async for snapshot in processor.results_formatter():
            yield snapshot


def configure_vad_float32(processor):
    """Install before processing PCM; keep VAD independent of model load dtype.

    Transformers temporarily changes torch's process-wide default dtype while
    loading HY-MT2 in another thread. WLK's FixedVADIterator uses torch.Tensor
    on each NumPy frame, which then becomes BF16/FP16. ONNX requires FP32.
    Keep upstream VAD decisions/reset behavior and only replace frame conversion.
    """
    if processor.vac is None:
        return
    import numpy as np
    import torch
    from whisperlivekit.silero_vad_iterator import FixedVADIterator, VADIterator

    class Float32VADIterator(FixedVADIterator):
        def __call__(self, x, return_seconds=False):
            self.buffer = np.append(self.buffer, np.asarray(x, dtype=np.float32))
            events = []
            while len(self.buffer) >= 512:
                # from_numpy preserves FP32 without consulting global defaults.
                # It also keeps ONNX's concatenated context FP32 when its initial
                # zeros were allocated during a half-precision model load.
                frame = torch.from_numpy(self.buffer[:512])
                event = VADIterator.__call__(self, frame, return_seconds=return_seconds)
                self.buffer = self.buffer[512:]
                if event is not None:
                    events.append(event)
            return events

    vad = processor.vac
    processor.vac = Float32VADIterator(
        vad.model, threshold=vad.threshold, sampling_rate=vad.sampling_rate,
        min_silence_duration_ms=vad.min_silence_samples * 1000 / vad.sampling_rate,
        speech_pad_ms=vad.speech_pad_samples * 1000 / vad.sampling_rate,
    )


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
