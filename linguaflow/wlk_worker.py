"""Isolated full WhisperLiveKit pipeline over local JSON-lines stdin/stdout.

The Qt process never imports the model runtime. PCM is s16le/16kHz/mono.
The application owns local model services and their ports.
"""
import asyncio
import base64
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from types import SimpleNamespace


async def serve(settings, emit, read_message):
    emit({"type": "status", "text": "正在导入 PyTorch 运行库…"})
    import torch
    if settings.get("asr_device") == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("推理环境没有可用 CUDA；请运行 scripts/install_runtime.py 安装 GPU 版本。")
    emit({"type": "status", "text": "正在导入 WhisperLiveKit 及语音检测组件…"})
    from whisperlivekit import TranscriptionEngine
    from whisperlivekit.config import WhisperLiveKitConfig

    mlx = settings["backend"] == "qwen3-mlx"
    qwen = settings["backend"] in ("qwen3-streaming", "qwen3-mlx")
    from .knowledge.glossary import context_text
    asr_context = context_text(settings.get('asr_context', {}))
    if mlx and (sys.platform != 'darwin' or settings.get('asr_device') != 'mlx'):
        raise ValueError('MLX 后端需要 macOS 和 Apple GPU 识别设备。')
    if not mlx and settings.get('asr_device') == 'mlx':
        raise ValueError('Apple GPU 设备需要选择 Qwen · MLX 4-bit 识别引擎。')
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
    )
    if qwen and config.lan == "auto":
        raise ValueError("Qwen 流式模式请选择原文语言。")
    if qwen:
        if not mlx:
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
        else:
            checkpoint = Path.home() / ".cache" / "whisper" / (model + ".pt")
            if checkpoint.is_file():
                config.model_path = str(checkpoint)
    def load_recognition(own):
        emit({"type": "status", "text": "正在加载 WhisperLiveKit / " + config.backend})
        if qwen:
            # The common engine supplies scheduling, not a second ASR model.
            config.transcription = False
            engine = TranscriptionEngine(config=config)
        else:
            from .runtime_compat import create_whisper_engine
            engine = create_whisper_engine(TranscriptionEngine, config, settings.get("asr_device", "cpu"))
            return engine, None
        if mlx:
            from .mlx_asr import build_mlx_online
            emit({"type": "status", "text": "加载 Qwen 4-bit · Apple GPU / Metal…"})
            online = build_mlx_online(config.model_path,
                settings.get('source'), draft_seconds,
                lambda text: emit({'type': 'status', 'text': text}),
                window_seconds=settings.get('qwen_window_seconds', 30.), own=own,
                **({'context': asr_context} if asr_context else {}))
        else:
            from .qwen_accurate import build_official_online
            emit({"type": "status", "text": "加载 Qwen 原始编码器；共享流式修订策略…"})
            online = build_official_online(config.model_path,
                settings.get("asr_device", "cpu"), settings.get("source"), draft_seconds,
                settings.get("qwen_window_seconds", 30.),
                **({'context': asr_context} if asr_context else {}))
        return engine, online

    def load_semantic():
        emit({"type": "status", "text": "加载本地字幕分句组件…"})
        try:
            from .semantic_model import SemanticModel
            semantic = SemanticModel()
        except Exception as exc:
            raise RuntimeError("字幕分句组件加载失败，请在‘识别模型’中下载 / 检查模型：" + str(exc)) from exc
        emit({"type": "status", "text": "字幕分句已就绪；近期原文和译文可修订"})
        return semantic

    from .inference_startup import load_components
    async with load_components(load_recognition, load_semantic) as (recognition, semantic):
        engine, online = recognition
        await _run_session(settings, emit, read_message, config, engine, online, semantic)


async def _run_session(settings, emit, read_message, config, engine, online, semantic):
    import numpy as np
    import torch
    from whisperlivekit import AudioProcessor

    from .audio_processing.pipeline import AudioPipeline
    qwen = online is not None
    audio_config = settings.get("audio_processing", {})
    emit({"type": "status", "text": "正在准备音频处理链…"})
    frontend = (AudioPipeline(audio_config, settings.get("input_sample_rate", 16000))
                if audio_config or settings.get("input_sample_rate", 16000) != 16000 else None)
    emit({"type": "status", "text": "识别模型已加载，正在创建流式解码任务…"})
    stream_events = asyncio.Queue()
    # All model loading has finished before VAD's tensor state is initialized.
    # Concurrent Transformers loading can temporarily change Torch's dtype.
    processor = AudioProcessor(transcription_engine=engine, stream_event_queue=stream_events)
    from .runtime_compat import configure_vad_float32
    configure_vad_float32(processor)
    if qwen:
        processor.transcription = online
        processor.args.transcription = True
        processor.transcription_queue = asyncio.Queue()
        processor.sep = " "

    async def process_pcm(pcm=None):
        if frontend is None:
            if pcm:
                await processor.process_audio(pcm)
            return
        audio = (await asyncio.to_thread(frontend.flush) if pcm is None else
                 await asyncio.to_thread(frontend.process, np.frombuffer(pcm, "<i2").astype(np.float32) / 32767))
        if len(audio):
            await processor.process_audio((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
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
    revisions = None
    revision_changed = asyncio.Event()
    event_loop = asyncio.get_running_loop()
    def revision_event(event):
        if os.environ.get("LINGUAFLOW_TRACE_REVISIONS") == "1":
            emit(event)
        event_loop.call_soon_threadsafe(revision_changed.set)
    if qwen:
        from .qwen_revisions import install_revision_bridge
        revisions = install_revision_bridge(processor.transcription,
            revision_event)
    results = await processor.create_tasks()
    from .wlk_captions import CaptionMapper, caption_snapshot
    mapper = CaptionMapper(config.lan, predictor=semantic.boundaries,
                           lookahead=3.)
    from .translation_queue import TranslationQueue
    from .translation_service import publish_translation_batch, publish_translation_result, run_translations
    translation_queue = TranslationQueue()
    from .translation_config import (
        DEFAULT_CONTEXT_AFTER,
        DEFAULT_CONTEXT_BEFORE,
        DEFAULT_INITIAL_CONTEXT_BEFORE,
    )
    from .translation_context import ContextPlanner
    from .translation_models import is_hy_model, translation_engine
    contextual_translation = (translation_engine(SimpleNamespace(**settings)) == 'llama'
                             or is_hy_model(settings.get('translation_model', '')))
    context_planner = ContextPlanner(
        settings.get('translation_before', DEFAULT_CONTEXT_BEFORE) if contextual_translation else 0,
        settings.get('translation_after', DEFAULT_CONTEXT_AFTER) if contextual_translation else 0,
        settings.get('translation_initial_before', DEFAULT_INITIAL_CONTEXT_BEFORE) if contextual_translation else 0)
    caption_lock = asyncio.Lock()
    latest = {}
    closed_audio_time = -1.

    async def publish(snapshot, done=False):
        async with caption_lock:
            # Only active SaT work blocks HY. Counting lock waiters can keep
            # the gate closed for an entire live recording under steady input.
            translation_queue.begin_source_update()
            try:
                if revisions is not None:
                    revisions.augment_snapshot(snapshot, config.lan)
                elif closed_audio_time >= 0:
                    snapshot['closed_audio_time'] = max(snapshot.get('closed_audio_time', -1), closed_audio_time)
                captions = await asyncio.to_thread(mapper.update, snapshot, done=done)
                for caption in captions:
                    emit({"type": "caption", "data": asdict(caption)})
                if settings.get('translate'):
                    for caption in captions:
                        if not caption.source:
                            translation_queue.discard(caption.id)
                    for caption in context_planner.update_changes(captions):
                        translation_queue.put_nowait(caption)
            finally:
                translation_queue.end_source_update()

    def apply_translation(current):
        mapper.previous[current.id] = current
        emit({'type': 'caption', 'data': asdict(current)})

    async def publish_translation(caption, context=None):
        await publish_translation_result(caption, mapper.previous.get, caption_lock,
            apply_translation, context, context_planner.get if contextual_translation else None, context_planner)

    async def publish_batch(captions, contexts):
        return await publish_translation_batch(captions, contexts, mapper.previous.get,
                                               caption_lock, apply_translation, context_planner)

    async def translate():
        if not settings.get("translate"):
            return
        from .backends import create_translator
        def report(text):
            emit({"type": "status", "text": text})
        await run_translations(translation_queue,
            lambda: create_translator(SimpleNamespace(**settings), report),
            mapper.previous.get, publish_translation, report,
            lambda values: emit({"type": "translation_metrics", **values}),
            context_planner.get if contextual_translation else None, context_planner, publish_batch)

    async def output():
        from .runtime_compat import results_with_final_snapshot
        async for snapshot in results_with_final_snapshot(processor, results):
            latest.clear()
            latest.update(caption_snapshot(snapshot))
            if os.environ.get("LINGUAFLOW_TRACE_SNAPSHOTS") == "1":
                emit({"type": "snapshot", "data": latest.copy()})
            await publish(latest)
            emit({"type": "metrics", "compute_lag": snapshot.remaining_time_transcription_processing,
                  "commit_lag": snapshot.remaining_time_transcription_policy})
            if snapshot.error:
                raise RuntimeError(snapshot.error)

    async def revision_output():
        # WLK can suppress unchanged append-only responses after a correction.
        # Wake from the authoritative store, independently of that formatter.
        while True:
            await revision_changed.wait()
            revision_changed.clear()
            await publish({})

    async def source_lifecycle():
        nonlocal closed_audio_time
        checked = event_loop.time()
        while True:
            ended = False
            try:
                event = await asyncio.wait_for(stream_events.get(), .25)
                if qwen:
                    processor.transcription.observe_capture_event(event.kind, event.timestamp)
                if event.kind == 'silence_transcription_ready':
                    # WLK emits this only after final decoding and its snapshot,
                    # unlike silence_started, which can precede pending inference.
                    closed_audio_time = max(closed_audio_time, event.timestamp)
                    ended = True
                stream_events.task_done()
            except asyncio.TimeoutError:
                pass
            if ended or event_loop.time() - checked >= .25:
                checked = event_loop.time()
                if latest or revisions is not None:
                    await publish(dict(latest))

    revision_task = asyncio.create_task(revision_output()) if revisions is not None else None
    lifecycle_task = asyncio.create_task(source_lifecycle())
    output_task = asyncio.create_task(output())
    def output_finished(task):
        if not task.cancelled() and task.exception():
            emit({"type": "error", "text": str(task.exception())})
    output_task.add_done_callback(output_finished)
    if revision_task:
        revision_task.add_done_callback(output_finished)
    lifecycle_task.add_done_callback(output_finished)
    translation_task = asyncio.create_task(translate())
    translation_task.add_done_callback(output_finished)
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
            elif message["type"] == "pause":
                from .runtime_compat import pause_audio_processor
                await process_pcm()
                await pause_audio_processor(processor)
                if frontend is not None:
                    frontend = await asyncio.to_thread(
                        AudioPipeline, audio_config, settings.get("input_sample_rate", 16000))
        await output_task
        lifecycle_task.cancel()
        await asyncio.gather(lifecycle_task, return_exceptions=True)
        if revision_task:
            revision_task.cancel()
            await asyncio.gather(revision_task, return_exceptions=True)
        await publish(latest, done=True)
        await translation_queue.join()
        translation_queue.put_nowait(None)
        await translation_task
        if torch.cuda.is_available():
            emit({"type": "status", "text": f"本次 PyTorch 显存分配峰值 {torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB（不含驱动等额外占用）"})
        emit({"type": "done"})
    finally:
        lifecycle_task.cancel()
        await asyncio.gather(lifecycle_task, return_exceptions=True)
        if revision_task:
            revision_task.cancel()
            await asyncio.gather(revision_task, return_exceptions=True)
        output_task.cancel()
        translation_task.cancel()
        await processor.cleanup()


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr  # Upstream prints must never corrupt the protocol.
    output_lock = Lock()
    def emit(message):
        with output_lock:
            protocol.write(json.dumps(message, ensure_ascii=False) + "\n")
            protocol.flush()

    async def read_message():
        line = await asyncio.to_thread(sys.stdin.readline)
        return json.loads(line) if line else None

    try:
        prepare_runtime()
        emit({'type': 'runtime_ready'})
        while first := sys.stdin.readline():
            settings = json.loads(first)
            os.environ['LINGUAFLOW_TRACE_REVISIONS'] = '1' if settings.pop('_diagnostic', False) else '0'
            asyncio.run(serve(settings, emit, read_message))
            release_runtime_models()
            emit({'type': 'runtime_ready'})
    except Exception as exc:
        import traceback
        traceback.print_exc()
        emit({"type": "error", "text": str(exc)})
        sys.exit(1)


def prepare_runtime():
    """Warm the shared CPU ONNX runtime without weights or network changes."""
    import importlib
    # SaT/skops must precede Transformers. ASR and translation still choose
    # their own PyTorch/Metal devices; SaT and VAD use CPU ONNX only.
    for module in ('onnxruntime', 'wtpsplit', 'torch', 'whisperlivekit'):
        importlib.import_module(module)


def release_runtime_models():
    """Release session model state while retaining compatible imports."""
    import gc

    import torch
    from whisperlivekit import TranscriptionEngine
    TranscriptionEngine.reset()
    gc.collect()
    if torch.cuda.is_initialized():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
