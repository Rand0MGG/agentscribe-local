"""Optional Linux/WSL Qwen streaming bridge. No changes to the desktop environment.

Install requirements-qwen.txt in an isolated environment; bind localhost only.
Uses Qwen's init_streaming_state/streaming_transcribe/finish_streaming_transcribe.
"""
import argparse
import base64
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

LANGUAGES = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "ru": "Russian", "ar": "Arabic",
    "pt": "Portuguese", "it": "Italian"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["Qwen/Qwen3-ASR-0.6B", "Qwen/Qwen3-ASR-1.7B"], default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.65)
    args = parser.parse_args()
    import numpy as np
    import torch
    from qwen_asr import Qwen3ASRModel
    from silero_vad import get_speech_timestamps, load_silero_vad

    asr = Qwen3ASRModel.LLM(model=args.model, gpu_memory_utilization=args.gpu_memory_utilization,
                            max_model_len=4096, max_new_tokens=256)
    vad = load_silero_vad(onnx=True)
    active = {"id": None, "state": None, "updated": 0, "samples": 0, "tail": np.empty(0, np.float32)}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, result):
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"protocol": "linguaflow-stream-v1", "model": args.model,
                                 "continuous_audio": True, "revisable_source": True, "timestamps": False})
            else:
                self.reply(404, {"error": "unknown route"})

        def do_POST(self):
            # Browser origins are not accepted; desktop requests never carry Origin.
            if self.headers.get("Origin") or self.headers.get("Content-Type") != "application/json":
                self.reply(403, {"error": "desktop JSON client required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 2_000_000:
                    raise ValueError("invalid payload length")
                payload = json.loads(self.rfile.read(length))
                if active["id"] and time.monotonic() - active["updated"] > 600:
                    active.update(id=None, state=None)
                if self.path == "/start":
                    if active["id"]:
                        self.reply(409, {"error": "another session is active"})
                        return
                    language = payload.get("language")
                    if language and language not in LANGUAGES:
                        raise ValueError("unsupported language")
                    active.update(id=uuid.uuid4().hex, samples=0, tail=np.empty(0, np.float32),
                        endpoint=max(0.5, min(3.0, float(payload.get("endpoint_seconds", 1.0)))),
                        state=asr.init_streaming_state(context=str(payload.get("context", ""))[-300:],
                            language=LANGUAGES.get(language), unfixed_chunk_num=2, unfixed_token_num=5,
                            chunk_size_sec=2.0), updated=time.monotonic())
                    self.reply(200, {"id": active["id"]})
                    return
                if not active["id"] or payload.get("id") != active["id"]:
                    raise ValueError("unknown session")
                if self.path == "/close":
                    active.update(id=None, state=None)
                    self.reply(200, {"closed": True})
                    return
                if self.path != "/audio":
                    raise ValueError("unknown route")
                samples = np.frombuffer(base64.b64decode(payload.get("pcm", ""), validate=True), dtype="<f4").copy()
                if not np.isfinite(samples).all() or len(samples) > 16000 * 10:
                    raise ValueError("invalid audio")
                active["samples"] += len(samples)
                if active["samples"] > 16000 * 60:
                    raise ValueError("60 seconds without endpoint; stop and restart to bound model memory")
                active["tail"] = np.concatenate((active["tail"], samples))[-16000 * 8:]
                asr.streaming_transcribe(samples, active["state"])
                speech = get_speech_timestamps(torch.from_numpy(active["tail"]), vad,
                                               sampling_rate=16000, speech_pad_ms=0)
                quiet = (len(active["tail"]) - speech[-1]["end"]) / 16000 if speech else len(active["tail"]) / 16000
                done = bool(payload.get("final")) or quiet >= active["endpoint"]
                if done:
                    asr.finish_streaming_transcribe(active["state"])
                state = active["state"]
                language = next((code for code, name in LANGUAGES.items() if name.lower() == state.language.lower()), state.language)
                self.reply(200, {"text": state.text, "language": language, "final": done})
                active["updated"] = time.monotonic()
                if done:
                    active.update(id=None, state=None)
            except Exception as exc:
                # Don't retry an uncertain audio operation and duplicate its samples.
                active.update(id=None, state=None)
                self.reply(400, {"error": str(exc)})

    print(f"Qwen ready: http://127.0.0.1:{args.port} ({args.model})", flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
