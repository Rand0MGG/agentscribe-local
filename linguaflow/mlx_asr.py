"""Adapt isolated MLX ASR to the shared Qwen streaming and caption contract."""
import atexit
import base64
import json
import subprocess
import sys
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread, current_thread

import numpy as np

from .asr_stability import choose_cut
from .qwen_accurate import LANGUAGE_NAMES, QwenAccurateOnline
from .runtime_paths import mlx_python

MLX_MODEL = 'mlx-community/Qwen3-ASR-1.7B-4bit'
MLX_REVISION = '78a389c776a5483b2d0d4ea5494e11012e0d6159'


class MLXClient:
    startup_timeout = 180.
    inference_timeout = 90.

    def __init__(self, model, language, report, background=False):
        python = mlx_python()
        if not python.is_file():
            raise RuntimeError('请在模型管理 → 运行环境安装 Apple GPU / MLX 识别环境。')
        self.report = report
        self.request_lock = Lock()
        self.close_lock = Lock()
        self.closed = False
        self.exchange = None
        self.loaded = Event()
        self.load_error = None
        self.process = subprocess.Popen([str(python), '-u', '-m', 'linguaflow.mlx_asr_worker'],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding='utf-8')
        atexit.register(self.close)
        self.loading = Thread(target=self.load, args=(model, language), daemon=True)
        self.loading.start()
        if not background:
            self.wait_ready()

    def load(self, model, language):
        """Initialize in the owned worker while CPU-only setup can proceed."""
        try:
            ready = self.request({'model': model, 'language': language}, self.startup_timeout)
            if ready.get('type') != 'ready' or 'gpu' not in ready.get('device', ''):
                raise RuntimeError('MLX 未确认 Apple GPU 已加载。')
            self.report(f"Qwen 4-bit · Apple GPU / Metal · 加载 {ready['load_seconds']:.1f}s")
        except BaseException as exc:
            self.load_error = exc
            self.close()
        finally:
            self.loaded.set()

    def wait_ready(self):
        # request() has its own deadline; allow its bounded close to finish too.
        if not self.loaded.wait(self.startup_timeout + 10):
            self.close()
            raise RuntimeError('MLX 模型加载超时，已结束识别进程。')
        if self.load_error is not None:
            raise self.load_error
        if self.closed:
            raise RuntimeError('MLX 识别进程已关闭，请重新开始聆听。')

    def request(self, message, timeout=None):
        """Bound both pipe writes and reads; close can interrupt stalled IO."""
        replies = Queue(maxsize=1)

        def exchange():
            try:
                self.process.stdin.write(json.dumps(message) + '\n')
                self.process.stdin.flush()
                replies.put(self.process.stdout.readline())
            except Exception as exc:
                replies.put(exc)

        with self.request_lock:
            with self.close_lock:
                if self.closed:
                    raise RuntimeError('MLX 识别进程已关闭，请重新开始聆听。')
                self.exchange = Thread(target=exchange, daemon=True)
                self.exchange.start()
            try:
                line = replies.get(timeout=self.inference_timeout if timeout is None else timeout)
            except Empty:
                self.close()
                operation = '模型加载' if 'model' in message else '识别请求'
                raise RuntimeError(f'MLX {operation}超时，已结束识别进程；请检查模型和可用内存。') from None
            if isinstance(line, Exception):
                raise RuntimeError('MLX 识别进程通信失败，请重新开始聆听。') from line
            if not line:
                raise RuntimeError('MLX 识别进程已退出；请查看诊断日志和可用内存。')
            result = json.loads(line)
            if result.get('type') == 'error':
                raise RuntimeError(result['text'])
            return result

    def decode(self, audio):
        result = self.request({'pcm': base64.b64encode(
            np.asarray(audio, dtype='<f4').tobytes()).decode('ascii')})
        self.report(f"Apple GPU · 识别 {result['compute_seconds']:.2f}s · "
                    f"MLX 分配峰值 {result['peak_bytes'] / 1024**3:.2f} GiB")
        return result['text']

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            atexit.unregister(self.close)
            if self.process.poll() is None:
                if self.exchange is not None and self.exchange.is_alive():
                    # A blocked writer owns the pipe lock: terminate before
                    # touching that pipe so cancellation cannot block on it.
                    self.process.terminate()
                else:
                    # Let MLX release resources normally after completed IO.
                    try:
                        self.process.stdin.write(json.dumps({'type': 'stop'}) + '\n')
                        self.process.stdin.flush()
                    except (OSError, ValueError):
                        pass
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=2)
            if self.exchange is not None:
                self.exchange.join(timeout=2)
            self.process.stdin.close()
            self.process.stdout.close()
        loading = getattr(self, 'loading', None)
        if loading is not None and loading is not current_thread():
            loading.join(timeout=2)


def begin_mlx_loading(settings, report):
    """Overlap only cached CPU SaT and isolated MLX; keep old paths serial."""
    if (sys.platform != 'darwin' or settings.get('asr_device') != 'mlx'
            or settings.get('semantic_device', 'cpu') != 'cpu'):
        return None
    from .semantic_cache import cached_cpu_model
    from .semantic_model import paths
    try:
        import onnxruntime as ort
        semantic, _ = paths()
        cached = cached_cpu_model(semantic, ort.__version__)
    except Exception as exc:
        raise RuntimeError('SaT 分句模型加载失败，请在‘字幕与延迟’中准备 / 检查模型：' + str(exc)) from exc
    if cached is None:
        return None
    canonical = LANGUAGE_NAMES.get(settings.get('source'))
    if canonical is None:
        raise ValueError('MLX 识别需要选择支持的原文语言。')
    from .model_cache import resolve_qwen_cached
    model = resolve_qwen_cached(settings.get('qwen_model', MLX_MODEL))
    report('并行准备 Qwen 4-bit · Apple GPU / Metal 与 SaT 分句模型…')
    return MLXClient(model, canonical, report, background=True)


def build_mlx_online(model, language, update_seconds, report, window_seconds=30., client=None):
    canonical = LANGUAGE_NAMES.get(language)
    if canonical is None:
        raise ValueError('MLX 识别需要选择支持的原文语言。')
    client = client if client is not None else MLXClient(model, canonical, report)
    # Honor the session's bounded window instead of silently forcing 12 s.
    try:
        client.wait_ready()
        online = QwenAccurateOnline(client.decode, choose_cut, language,
                                   update_seconds, window_seconds=window_seconds,
                                   pause_context_seconds=3.)
    except BaseException:
        client.close()
        raise
    online.close = client.close
    return online
