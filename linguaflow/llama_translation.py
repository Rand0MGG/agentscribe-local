"""GGUF translation through an owned, authenticated llama.cpp service."""
import atexit
import json
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from threading import Lock, Thread

from .core import WHISPER_TO_NLLB
from .llama_assets import resolve_assets
from .process_platform import spawn_options, stop_tree
from .translation_models import llama_generation, translation_prompt


class LlamaTranslator:
    startup_timeout = 90

    def __init__(self, settings, report=lambda _: None):
        binary, weights = resolve_assets(settings)
        self.target, self.source = settings.target, settings.source_nllb
        self.process = None
        self.reader = None
        self.lock = Lock()
        self.closed = False
        self.recent = deque(maxlen=30)
        self.gpu_layers = None
        self.device = settings.translation_device
        self.device_id = {'metal': 'MTL0', 'cuda': 'CUDA0', 'vulkan': 'Vulkan0', 'cpu': 'none'}[self.device]
        self.device_confirmed = self.device == 'cpu'
        self.name = weights.stem
        self.api_key = secrets.token_urlsafe(32)
        # Ignore system proxies: text must stay on this process-owned loopback service.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.endpoint = f'http://127.0.0.1:{port}'
        command = [str(binary), '-m', str(weights), '--host', '127.0.0.1', '--port', str(port),
                   '--device', self.device_id, '-ngl', '0' if self.device == 'cpu' else '99', '--fit', 'off', '-c', '4096', '-np', '1',
                   '-t', '2', '-tb', '2', '--no-webui', '--no-context-shift', '-lv', '4',
                   '--api-key', self.api_key]
        try:
            report(f'正在加载 {self.name} · llama.cpp / {self.device.upper()}…')
            self.process = subprocess.Popen([sys.executable, '-u', '-m', 'linguaflow.managed_process', *command],
                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                errors='replace', **spawn_options())
            atexit.register(self.close)
            self.reader = Thread(target=self.read_logs, daemon=True)
            self.reader.start()
            began = time.monotonic()
            while time.monotonic()-began < self.startup_timeout:
                if self.process.poll() is not None:
                    raise RuntimeError('llama.cpp 启动失败：' + '\n'.join(self.recent)[-1500:])
                try:
                    ready = self.request('/health', timeout=1).get('status') == 'ok'
                    if ready and self.device_confirmed and (self.device == 'cpu' or self.gpu_layers):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('llama.cpp 未在 90 秒内确认所选设备加载：' + '\n'.join(self.recent)[-1000:])
            report(f'{self.name} · llama.cpp / {self.device.upper()} · '
                   + (f'{self.gpu_layers} 层已加载到 GPU' if self.gpu_layers else 'CPU 已就绪'))
        except BaseException:
            self.close()
            raise

    def read_logs(self):
        for line in self.process.stdout:
            self.recent.append(line.strip())
            if f'using device {self.device_id}' in line:
                self.device_confirmed = True
            match = re.search(r'offloaded (\d+)/(\d+) layers to GPU', line)
            if match and int(match[1]) > 0 and match[1] == match[2]:
                self.gpu_layers = int(match[1])

    def request(self, path, payload=None, timeout=90):
        request = urllib.request.Request(self.endpoint+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+self.api_key})
        with self.http.open(request, timeout=timeout) as response:
            return json.load(response)

    def translate(self, text, language, context=None):
        if self.closed or self.process.poll() is not None:
            raise RuntimeError('llama.cpp 翻译进程已结束，请停止后重新开始聆听。')
        if (self.source or WHISPER_TO_NLLB.get(language)) == self.target:
            return text
        payload = {'messages': [{'role': 'user', 'content': translation_prompt(text, self.target, context)}],
                   **llama_generation(), 'stream': False}
        try:
            result = self.request('/v1/chat/completions', payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode('utf-8', errors='replace')
            raise RuntimeError('llama.cpp 翻译请求失败：' + detail[:500]) from exc
        choice = result['choices'][0]
        output = choice['message'].get('content') or ''
        if choice['finish_reason'] != 'stop' or not output.strip():
            raise ValueError('llama.cpp 译文未完整生成；已保留原文和已有译文。')
        return output.strip()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            atexit.unregister(self.close)
            if self.process:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    for force in (False, True):
                        stop_tree(self.process, force=force)
                        try:
                            self.process.wait(timeout=4)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                if self.reader:
                    self.reader.join(timeout=2)
                self.process.stdout.close()
