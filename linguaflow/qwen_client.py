"""Client for our stateful local Qwen bridge, NOT the file-transcription API."""
import base64
import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np

from .core import Caption


class LocalService:
    def __init__(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username:
            raise ValueError("本地流式服务只允许 http://127.0.0.1、localhost 或 ::1 地址。")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("请输入本地服务根地址，不包含路径。")
        self.url = url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, payload=None, timeout=120):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                detail = json.load(exc).get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"Qwen 流式服务拒绝请求：{detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"本地 Qwen 流式服务未就绪或连接中断：{exc}。请在模型管理中检查连接。") from exc

    def health(self):
        result = self.request("/health", timeout=5)
        if (result.get("protocol") != "linguaflow-stream-v1" or not result.get("continuous_audio")
                or not result.get("revisable_source")):
            raise RuntimeError("该服务没有持续音频输入能力，不能作为实时转写引擎。")
        return result


class QwenStream:
    def __init__(self, settings):
        self.service = LocalService(settings.service_url)
        info = self.service.health()
        if info.get("model") != settings.qwen_model:
            raise RuntimeError(f"服务加载的是 {info.get('model')}，与模型管理中的选择不一致。")
        self.settings = settings
        self.session_id = None
        self.row = 1
        self.offset = 0.0
        self.duration = 0.0
        self.revision = 0
        self.previous = None
        self.context = ""

    def update(self, samples, final=False):
        if self.session_id is None:
            if not len(samples):
                return []
            result = self.service.request("/start", {"language": self.settings.source,
                "context": self.context[-300:], "endpoint_seconds": self.settings.endpoint_seconds})
            self.session_id = result["id"]
        self.duration += len(samples) / 16000
        result = self.service.request("/audio", {"id": self.session_id, "final": final,
            "pcm": base64.b64encode(np.asarray(samples, dtype="<f4").tobytes()).decode()})
        text = result.get("text", "").strip()
        done = bool(result.get("final"))
        events = []
        if text != self.previous or done:
            if text or self.previous:
                self.revision += 1
                events.append(Caption(self.row, self.offset, self.offset + self.duration,
                    text, result.get("language", "auto"), final=done, revision=self.revision))
            self.previous = text
        if done:
            self.context = (self.context + " " + text)[-600:]
            self.session_id = None
            self.row += 1
            self.offset += self.duration
            self.duration = 0
            self.revision = 0
            self.previous = None
        return events

    def close(self):
        if self.session_id:
            self.service.request("/close", {"id": self.session_id}, timeout=5)
            self.session_id = None
