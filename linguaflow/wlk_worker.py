"""Isolated full WhisperLiveKit pipeline over local JSON-lines stdin/stdout.

The Qt process never imports the model runtime. PCM is s16le/16kHz/mono.
No HTTP service, WSL or user-managed port is required.
"""
import asyncio
import base64
import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock
from types import SimpleNamespace


async def serve(settings, emit, read_message):
    emit({"type": "status", "text": "正在导入 PyTorch 运行库…"})
    import torch
    if settings.get("asr_device") == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("推理环境没有可用 CUDA；请运行 scripts/install_runtime.py 安装 GPU 版本。")
    emit({"type": "status", "text": "正在导入 WhisperLiveKit 及语音检测组件…"})
    from whisperlivekit import AudioProcessor, TranscriptionEngine
    from whisperlivekit.config import WhisperLiveKitConfig

    qwen = settings["backend"] == "qwen3-streaming"
    config = WhisperLiveKitConfig(
        backend="qwen3-streaming" if qwen else "whisper",
        backend_policy="simulstreaming",
        model_size=settings.get("qwen_model", "Qwen/Qwen3-ASR-0.6B") if qwen else settings.get("asr_model", "large-v3"),
        lan=settings.get("source") or "auto",
        pcm_input=True,
        diarization=False,
        target_language="",
        vac=True,
        vad=True,
        asr_coalesce_min_s=settings.get("update_seconds", 1.0),
        pause_segmentation_seconds=settings.get("endpoint_seconds", 0.5),
        beams=1,
        decoder_type="greedy",
        disable_fast_encoder=True,
        vllm_model=settings.get("qwen_model", "Qwen/Qwen3-ASR-0.6B"),
        qwen3_streaming_device=settings.get("asr_device", "cuda"),
        qwen3_streaming_audio_backend="windowed",
    )
    if qwen and config.lan == "auto":
        raise ValueError("Qwen 流式模式请选择原文语言。")
    if qwen:
        from .runtime_compat import prepare_qwen_dependencies
        prepare_qwen_dependencies()
        from .model_cache import resolve_qwen_cached
        model = config.model_size
        emit({"type": "status", "text": "检查 Qwen 模型文件；已缓存权重复用"})
        config.model_path = resolve_qwen_cached(model)
    if not qwen:
        model = settings.get("asr_model", "large-v3")
        if Path(model).exists():
            config.model_path = str(Path(model).resolve())
        elif settings.get("offline"):
            checkpoint = Path.home() / ".cache" / "whisper" / (model + ".pt")
            if not checkpoint.is_file():
                raise ValueError("离线 Whisper 权重不存在，请先在模型管理中下载。")
            config.model_path = str(checkpoint)
    emit({"type": "status", "text": "正在加载 WhisperLiveKit / " + config.backend})
    if qwen:
        engine = TranscriptionEngine(config=config)
    else:
        from .runtime_compat import create_whisper_engine
        engine = create_whisper_engine(TranscriptionEngine, config, settings.get("asr_device", "cpu"))
    emit({"type": "status", "text": "识别模型已加载，正在创建流式解码任务…"})
    processor = AudioProcessor(transcription_engine=engine)
    if not qwen:
        # AlignAtt otherwise chooses CUDA from global availability even when
        # the user selected a CPU model. Translation can still use that GPU.
        processor.transcription.model.device = settings.get("asr_device", "cpu")
        from .runtime_compat import finalize_whisper_once
        finalize_whisper_once(processor.transcription)
    results = await processor.create_tasks()
    from .wlk_captions import CaptionMapper, caption_snapshot
    mapper = CaptionMapper(config.lan)
    translation_queue = asyncio.Queue()
    latest = {}

    def publish(snapshot, done=False):
        for caption in mapper.update(snapshot, done=done):
            emit({"type": "caption", "data": asdict(caption)})
            if caption.final and caption.source and settings.get("translate"):
                translation_queue.put_nowait((caption, time.monotonic()))

    async def translate():
        if not settings.get("translate"):
            return
        from .backends import NllbTranslator
        translator = None
        error = None
        try:
            translator = await asyncio.to_thread(NllbTranslator, SimpleNamespace(**settings),
                                                lambda text: emit({"type": "status", "text": text}))
        except Exception as exc:
            error = str(exc)
            emit({"type": "status", "text": "翻译加载失败，原文继续：" + error})
        while True:
            item = await translation_queue.get()
            if item is None:
                translation_queue.task_done()
                return
            caption, queued_at = item
            started = time.monotonic()
            try:
                if error:
                    raise RuntimeError(error)
                text = await asyncio.to_thread(translator.translate, caption.source, caption.language)
                caption = replace(caption, translation=text)
            except Exception as exc:
                caption = replace(caption, error=str(exc))
            emit({"type": "caption", "data": asdict(caption)})
            emit({"type": "translation_metrics", "pending": translation_queue.qsize(),
                  "wait_seconds": started - queued_at, "compute_seconds": time.monotonic() - started,
                  "error": caption.error})
            translation_queue.task_done()

    async def output():
        async for snapshot in results:
            latest.clear()
            latest.update(caption_snapshot(snapshot))
            if os.environ.get("LINGUAFLOW_TRACE_SNAPSHOTS") == "1":
                emit({"type": "snapshot", "data": latest.copy()})
            publish(latest)
            emit({"type": "metrics", "compute_lag": snapshot.remaining_time_transcription_processing,
                  "commit_lag": snapshot.remaining_time_transcription_policy})
            if snapshot.error:
                raise RuntimeError(snapshot.error)

    output_task = asyncio.create_task(output())
    def output_finished(task):
        if not task.cancelled() and task.exception():
            emit({"type": "error", "text": str(task.exception())})
    output_task.add_done_callback(output_finished)
    translation_task = asyncio.create_task(translate())
    emit({"type": "ready", "backend": config.backend})
    try:
        while True:
            message = await read_message()
            if message is None or message.get("type") == "stop":
                await processor.process_audio(b"")
                break
            if message["type"] == "audio":
                await processor.process_audio(base64.b64decode(message["pcm"], validate=True))
        await output_task
        publish(latest, done=True)
        await translation_queue.join()
        await translation_queue.put(None)
        await translation_task
        if torch.cuda.is_available():
            emit({"type": "status", "text": f"本次 PyTorch 显存分配峰值 {torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB（不含驱动等额外占用）"})
        emit({"type": "done"})
    finally:
        output_task.cancel()
        translation_task.cancel()
        await processor.cleanup()


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Upstream prints must never corrupt the protocol.
    first = sys.stdin.readline()
    settings = json.loads(first)
    if settings.get("offline"):
        os.environ["HF_HUB_OFFLINE"] = "1"

    output_lock = Lock()
    def emit(message):
        with output_lock:
            protocol.write(json.dumps(message, ensure_ascii=False) + "\n")
            protocol.flush()

    async def read_message():
        line = await asyncio.to_thread(sys.stdin.readline)
        return json.loads(line) if line else None

    try:
        asyncio.run(serve(settings, emit, read_message))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        emit({"type": "error", "text": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
