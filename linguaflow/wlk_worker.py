"""Isolated full WhisperLiveKit pipeline over local JSON-lines stdin/stdout.

The Qt process never imports the model runtime. PCM is s16le/16kHz/mono.
No HTTP service, WSL or user-managed port is required.
"""
import asyncio
import base64
import json
import math
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock
from types import SimpleNamespace


async def serve(settings, emit, read_message):
    import numpy as np
    from .audio_processing.pipeline import AudioPipeline, select_backend
    audio_config = settings.get("audio_processing", {})
    if audio_config.get("deepfilter"):
        select_backend(audio_config.get("df_device", "cpu"))
    if settings.get("semantic_mode", "auto") != "rules" and settings.get("semantic_device") == "cuda":
        try:
            select_backend("cuda")
        except RuntimeError:
            pass  # Optional semantic-model initialization below reports fallback.
    emit({"type": "status", "text": "正在准备音频处理链…"})
    # Legacy 16 kHz clients keep their original PCM route. Desktop captures 48 kHz.
    frontend = (AudioPipeline(audio_config, settings.get("input_sample_rate", 16000))
                if audio_config or settings.get("input_sample_rate", 16000) != 16000 else None)

    async def process_pcm(pcm=None):
        if frontend is None:
            if pcm:
                await processor.process_audio(pcm)
            return
        audio = (await asyncio.to_thread(frontend.flush) if pcm is None else
                 await asyncio.to_thread(frontend.process, np.frombuffer(pcm, "<i2").astype(np.float32) / 32767))
        if len(audio):
            await processor.process_audio((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())

    emit({"type": "status", "text": "正在导入 PyTorch 运行库…"})
    import torch
    if settings.get("asr_device") == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("推理环境没有可用 CUDA；请运行 scripts/install_runtime.py 安装 GPU 版本。")
    emit({"type": "status", "text": "正在导入 WhisperLiveKit 及语音检测组件…"})
    from whisperlivekit import AudioProcessor, TranscriptionEngine
    from whisperlivekit.config import WhisperLiveKitConfig

    qwen = settings["backend"] == "qwen3-streaming"
    # Request fresh hypotheses independently of semantic readiness. Upstream
    # still paces decoding against actual compute time; no audio is discarded.
    draft_seconds = max(0.25, min(3., float(settings.get("draft_seconds", .5))))
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
        asr_coalesce_min_s=(min(settings.get("update_seconds", 1.0), draft_seconds)
                            if qwen else settings.get("update_seconds", 1.0)),
        pause_segmentation_seconds=settings.get("endpoint_seconds", 0.5),
        beams=1,
        decoder_type="greedy",
        disable_fast_encoder=True,
        vllm_model=settings.get("qwen_model", "Qwen/Qwen3-ASR-0.6B"),
        qwen3_streaming_device=settings.get("asr_device", "cuda"),
        qwen3_streaming_audio_backend="windowed",
        qwen3_streaming_chunk_sec=draft_seconds,
        # Keep at least the original 2 x 2-second observation horizon when
        # requesting faster drafts; more UI updates must not imply early commit.
        qwen3_streaming_stable_iterations=max(2, math.ceil(4. / draft_seconds)),
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
    # WLK's pause_segmentation_seconds only marks presentation boundaries.
    # Its Silero iterator otherwise ends speech after just 100 ms, invoking
    # Qwen start_silence(), which flushes and resets the decoder. Configure
    # the detector itself so a short hesitation retains acoustic context.
    from .runtime_compat import configure_vad_pause
    if qwen:
        configure_vad_pause(processor, settings.get("endpoint_seconds", .5))
    if not qwen:
        # AlignAtt otherwise chooses CUDA from global availability even when
        # the user selected a CPU model. Translation can still use that GPU.
        processor.transcription.model.device = settings.get("asr_device", "cpu")
        from .runtime_compat import finalize_whisper_once
        finalize_whisper_once(processor.transcription)
    results = await processor.create_tasks()
    from .wlk_captions import CaptionMapper, caption_snapshot
    predictor = None
    if settings.get("semantic_mode", "auto") != "rules":
        emit({"type": "status", "text": "加载本地 SaT 上下文分句模型…"})
        try:
            from .semantic_model import SemanticModel
            semantic = await asyncio.to_thread(SemanticModel, settings.get("semantic_device", "cpu"))
            predictor = semantic.boundaries
            emit({"type": "status", "text": "SaT 上下文分句已启用；近期原文和译文可修订"})
        except Exception as exc:
            emit({"type": "status", "text": "SaT 暂不可用，使用上下文规则；可在模型管理准备分句模型：" + str(exc)})
    mapper = CaptionMapper(config.lan, predictor=predictor,
                           lookahead=settings.get("semantic_lookahead", 3.),
                           max_seconds=settings.get("caption_max_seconds", 12.))
    from .translation_queue import TranslationQueue
    translation_queue = TranslationQueue()
    caption_lock = asyncio.Lock()
    latest = {}

    async def publish(snapshot, done=False):
        async with caption_lock:
            try:
                captions = await asyncio.to_thread(mapper.update, snapshot, done=done)
            except Exception:
                if mapper.policy.predictor is None:
                    raise
                mapper.policy.predictor = None
                mapper.policy.cache = None
                emit({"type": "status", "text": "分句模型推理异常，已切换上下文规则；原文继续保留"})
                captions = mapper.update(snapshot, done=done)
            for caption in captions:
                emit({"type": "caption", "data": asdict(caption)})
                if (caption.ready or caption.final) and caption.source and settings.get("translate"):
                    translation_queue.put_nowait(caption)

    async def translate():
        if not settings.get("translate"):
            return
        from .backends import NllbTranslator
        translator = None
        from collections import OrderedDict
        cache = OrderedDict()
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
            current = mapper.previous.get(caption.id)
            if current is None or current.revision != caption.revision:
                translation_queue.task_done()
                continue
            started = time.monotonic()
            try:
                if error:
                    raise RuntimeError(error)
                key = (caption.source, caption.language)
                if key in cache:
                    text = cache[key]
                    cache.move_to_end(key)
                else:
                    text = await asyncio.to_thread(translator.translate, caption.source, caption.language)
                    cache[key] = text
                    if len(cache) > 512:
                        cache.popitem(last=False)
                caption = replace(caption, translation=text)
            except Exception as exc:
                caption = replace(caption, error=str(exc))
            async with caption_lock:
                current = mapper.previous.get(caption.id)
                if current is not None and current.source == caption.source and (current.ready or current.final):
                    emit({"type": "caption", "data": asdict(replace(current, translation=caption.translation, error=caption.error))})
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
            await publish(latest)
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
                await process_pcm()
                await processor.process_audio(b"")
                break
            if message["type"] == "audio":
                await process_pcm(base64.b64decode(message["pcm"], validate=True))
        await output_task
        await publish(latest, done=True)
        await translation_queue.join()
        translation_queue.put_nowait(None)
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
