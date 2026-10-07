"""File/PCM-only MLX inference service; no audio device or desktop imports."""
import base64
import json
import os
import sys
import threading
import time
from pathlib import Path


def watch_parent(parent):
    # Also release Metal memory when WLK is cancelled during model generation.
    while os.getppid() == parent:
        time.sleep(.5)
    os._exit(0)


def serve(read, emit):
    import mlx.core as mx
    import numpy as np
    from mlx_audio.stt.utils import load_model

    if not mx.metal.is_available():
        raise RuntimeError('Apple GPU / Metal 不可用；MLX 识别不会回退 CPU。')
    mx.set_default_device(mx.gpu)
    mx.set_cache_limit(128 * 1024**2)
    mx.set_memory_limit(3 * 1024**3)
    settings = read()
    from .knowledge.schemas import MAX_CONTEXT_BYTES
    context = settings.get('context', '')
    if not isinstance(context, str) or len(context.encode('utf-8')) > MAX_CONTEXT_BYTES:
        raise ValueError('课程术语上下文无效或超长。')
    path = Path(settings['model'])
    from .model_cache import validate_mlx_model
    validate_mlx_model(path)
    started = time.perf_counter()
    model = load_model(str(path))
    emit({'type': 'ready', 'device': str(mx.default_device()),
          'load_seconds': time.perf_counter() - started,
          'active_bytes': mx.get_active_memory()})
    while (message := read()) is not None and message.get('type') != 'stop':
        pcm = np.frombuffer(base64.b64decode(message['pcm'], validate=True), '<f4')
        # The shared adapter permits a 40 s window plus at most 5 s lookahead.
        if not 0 < len(pcm) <= 45 * 16000 or not np.isfinite(pcm).all():
            raise ValueError('MLX 识别音频必须是 0–45 秒的有限值 16 kHz 单声道 PCM。')
        started = time.perf_counter()
        result = model.generate(pcm, language=settings['language'], temperature=0.,
                                max_tokens=512, prefill_step_size=256, verbose=False,
                                **({'system_prompt': context} if context else {}))
        mx.synchronize()
        emit({'type': 'result', 'text': result.text.strip(),
              'compute_seconds': time.perf_counter() - started,
              'peak_bytes': mx.get_peak_memory(), 'active_bytes': mx.get_active_memory(),
              'device': str(mx.default_device())})
        mx.clear_cache()


def main():
    protocol = sys.stdout
    sys.stdout = sys.stderr
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    threading.Thread(target=watch_parent, args=(os.getppid(),), daemon=True).start()

    def read():
        line = sys.stdin.readline()
        return json.loads(line) if line else None

    def emit(value):
        protocol.write(json.dumps(value, ensure_ascii=False) + '\n')
        protocol.flush()

    try:
        serve(read, emit)
    except Exception as exc:
        emit({'type': 'error', 'text': str(exc)})
        raise


if __name__ == '__main__':
    main()
