"""Adapt isolated MLX ASR to the shared Qwen streaming and caption contract."""
import atexit
import base64
import json
import subprocess
from pathlib import Path

import numpy as np

from .qwen_accurate import LANGUAGE_NAMES, QwenAccurateOnline
from .runtime_paths import mlx_python

MLX_MODEL = 'mlx-community/Qwen3-ASR-1.7B-4bit'
MLX_REVISION = '78a389c776a5483b2d0d4ea5494e11012e0d6159'


def choose_cut(audio, seconds):
    """Cut at quiet 100 ms near the window end, with bounded linear work."""
    target = round(seconds * 16000)
    lo, hi = max(16000, target - 16000), min(len(audio), target + 16000)
    frame = 1600
    candidates = range(lo, max(lo + 1, hi - frame + 1), frame)
    return min(candidates, key=lambda i: float(np.mean(audio[i:i+frame] ** 2)))


class MLXClient:
    def __init__(self, model, language, report):
        python = mlx_python()
        if not python.is_file():
            raise RuntimeError('请在模型管理 → 运行环境安装 Apple GPU / MLX 识别环境。')
        self.report = report
        self.process = subprocess.Popen([str(python), '-u', '-m', 'linguaflow.mlx_asr_worker'],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding='utf-8')
        atexit.register(self.close)
        try:
            ready = self.request({'model': model, 'language': language})
            if ready.get('type') != 'ready' or 'gpu' not in ready.get('device', ''):
                raise RuntimeError('MLX 未确认 Apple GPU 已加载。')
            report(f"Qwen 4-bit · Apple GPU / Metal · 加载 {ready['load_seconds']:.1f}s")
        except BaseException:
            self.close()
            raise

    def request(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
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
        atexit.unregister(self.close)
        if self.process.poll() is None:
            # Let Python/MLX release resources normally after a completed session.
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
                    self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def build_mlx_online(model, language, update_seconds, report):
    canonical = LANGUAGE_NAMES.get(language)
    if canonical is None:
        raise ValueError('MLX 识别需要选择支持的原文语言。')
    client = MLXClient(model, canonical, report)
    # Short windows bound encoder activations on unified-memory Macs.
    online = QwenAccurateOnline(client.decode, choose_cut, language,
                               max(1., update_seconds), window_seconds=12.)
    online.close = client.close
    return online
