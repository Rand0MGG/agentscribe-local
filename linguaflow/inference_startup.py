"""Load recognition and CPU segmentation together, with shared resource ownership."""
import asyncio
import sys
from contextlib import asynccontextmanager
from threading import Lock


@asynccontextmanager
async def load_components(load_recognition, load_semantic):
    """Yield both initialized components; join loaders and close owned resources.

    Both synchronous factories run outside the event loop. Recognition receives
    own(resource), which must be called before blocking initialization of an
    interruptible child. It must expose an idempotent close(). Loading failure
    or cancellation closes those resources before joining the remaining work.
    In-process model loading is bounded by the owning worker's existing deadline.
    """
    resources, lock, closing = [], Lock(), False

    def own(resource):
        with lock:
            if not closing:
                resources.append(resource)
                return
        resource.close()
        raise RuntimeError('识别会话已取消')

    tasks = [asyncio.create_task(asyncio.to_thread(load_recognition, own)),
             asyncio.create_task(asyncio.to_thread(load_semantic))]
    joined = asyncio.gather(*tasks, return_exceptions=True)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        yield tuple(task.result() for task in tasks)
    finally:
        active_error, cleanup_error = sys.exception(), None
        with lock:
            closing = True
            owned = list(reversed(resources))
        for resource in owned:
            try:
                await asyncio.to_thread(resource.close)
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        # Do not leave a loader running after another component failed. Shield
        # keeps cancellation from losing ownership of its eventual result.
        await asyncio.shield(joined)
        if cleanup_error is not None:
            if active_error is not None:
                active_error.add_note(f'识别资源清理失败：{cleanup_error}')
            else:
                raise cleanup_error


def start_problem(settings):
    """Return (title, actionable message) for invalid local startup input, otherwise None.

    Only inspect local assets here. Backend initialization retains its own final
    validation; this preflight never loads models or probes audio devices.
    """
    if settings.translate and settings.translation_engine == 'llama':
        from .llama_assets import resolve_assets
        try:
            resolve_assets(settings)
        except (ValueError, OSError) as exc:
            return '翻译模型尚未准备好', str(exc)
    if settings.backend in ('qwen3-streaming', 'qwen3-mlx'):
        if settings.source is None:
            return '请选择原文语言', 'Qwen 流式模式需要明确原文语言，例如 English 或简体中文。'
        from .model_cache import resolve_qwen_cached, validate_mlx_model
        try:
            path = resolve_qwen_cached(settings.qwen_model.strip())
            if settings.backend == 'qwen3-mlx':
                from .runtime_paths import mlx_python
                validate_mlx_model(path)
                if not mlx_python().is_file():
                    raise ValueError('请先到运行环境页检查 / 修复 Apple GPU / MLX 识别环境。')
        except ValueError as exc:
            return '模型尚未准备好', str(exc)
    if ((settings.backend == 'wlk-whisper' and not settings.asr_model)
            or (settings.translate and settings.translation_engine == 'pytorch' and not settings.translation_model)):
        return '模型为空', '请选择模型名称或本地模型目录。'
    return None
