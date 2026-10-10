"""Adapt isolated MLX ASR to the shared Qwen streaming and caption contract."""
import atexit
import base64
import json
import subprocess
from queue import Empty, Queue
from threading import Lock, Thread

import numpy as np

from .asr_stability import choose_cut
from .model_options import MLX_MODEL as MLX_MODEL
from .process_platform import close_process_pipes
from .qwen_accurate import LANGUAGE_NAMES, QwenAccurateOnline
from .runtime_paths import mlx_python, python_environment, resource_root

MLX_REVISION = '78a389c776a5483b2d0d4ea5494e11012e0d6159'


class MLXClient:
    startup_timeout = 180.
    inference_timeout = 90.

    def __init__(self, model, language, report, own=lambda resource: None, context=''):
        from .knowledge.schemas import MAX_CONTEXT_BYTES
        if not isinstance(context, str) or len(context.encode('utf-8')) > MAX_CONTEXT_BYTES:
            raise ValueError('课程术语上下文无效或超长，请重新审核术语。')
        python = mlx_python()
        if not python.is_file():
            raise RuntimeError('请在模型管理 → 运行环境安装 Apple GPU / MLX 识别环境。')
        self.report = report
        self.request_lock = Lock()
        self.close_lock = Lock()
        self.closed = False
        self.exchange = None
        self.process = subprocess.Popen([str(python), '-u', '-m', 'linguaflow.mlx_asr_worker'],
            cwd=resource_root(), env=python_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding='utf-8')
        atexit.register(self.close)
        try:
            # Shared startup owns cancellation before this handshake can block.
            own(self)
            ready = self.request({'model': model, 'language': language,
                                  **({'context': context} if context else {})}, self.startup_timeout)
            if ready.get('type') != 'ready' or 'gpu' not in ready.get('device', ''):
                raise RuntimeError('MLX 未确认 Apple GPU 已加载。')
            precision = f" {ready['bits']}-bit" if ready.get('bits') in (4, 8) else ''
            self.report(f"Qwen{precision} · Apple GPU / Metal · 加载 {ready['load_seconds']:.1f}s")
        except BaseException:
            self.close()
            raise

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
            close_process_pipes(self.process)


def build_mlx_online(model, language, update_seconds, report, window_seconds=30.,
                     own=lambda resource: None, context=''):
    canonical = LANGUAGE_NAMES.get(language)
    if canonical is None:
        raise ValueError('MLX 识别需要选择支持的原文语言。')
    client = MLXClient(model, canonical, report, own=own, **({'context': context} if context else {}))
    # Honor the session's bounded window instead of silently forcing 12 s.
    try:
        online = QwenAccurateOnline(client.decode, choose_cut, language,
                                   update_seconds, window_seconds=window_seconds,
                                   pause_context_seconds=3.)
    except BaseException:
        client.close()
        raise
    online.close = client.close
    return online
