"""Qt session owns a disposable local WLK process and continuous audio capture."""
import base64
import json
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread

import numpy as np
from PySide6.QtCore import QThread, Signal

from .audio import capture
from .core import Caption
from .journal import AudioJournal


def runtime_python():
    root = Path(__file__).resolve().parents[1]
    return root / ".venv-wlk" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


class Session(QThread):
    startup_idle_timeout = 300
    status = Signal(str)
    caption = Signal(object)
    level = Signal(float)
    failure = Signal(str)
    ready = Signal()
    stage = Signal(str, str)

    def __init__(self, settings, parent=None, capture_fn=capture):
        super().__init__(parent)
        self.settings = settings
        self.capture_fn = capture_fn
        self.stop_capture = Event()
        self.capture_done = Event()
        self.abort = Event()
        self.process = None
        self.model_ready = Event()
        self.last_error = ""

    def stop(self, discard=False):
        self.stop_capture.set()
        if discard or (self.process is not None and not self.model_ready.is_set()):
            self.abort.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def fail(self, text):
        self.last_error = text
        self.failure.emit(text)
        self.stop(discard=True)

    def run(self):
        workers = []
        journal = None
        try:
            python = runtime_python()
            if not python.is_file():
                raise RuntimeError("请先运行 scripts/install_runtime.py 安装 WhisperLiveKit 推理环境。")
            self.stage.emit("识别", "加载 WhisperLiveKit")
            self.status.emit("正在启动本地推理进程…首次导入运行库可能需要较长时间，可点击停止取消。")
            self.process = subprocess.Popen(
                [str(python), "-u", "-m", "linguaflow.wlk_worker"],
                cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            def send(message):
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()

            last_progress = [time.monotonic()]
            recent_errors = deque(maxlen=12)

            def diagnostics():
                for line in self.process.stderr:
                    if line.strip():
                        last_progress[0] = time.monotonic()
                        recent_errors.append(line.strip())
                        self.status.emit(line.strip())

            def watch_startup():
                while not self.abort.wait(1):
                    if self.model_ready.is_set() or self.process.poll() is not None:
                        return
                    if time.monotonic() - last_progress[0] > self.startup_idle_timeout:
                        self.fail("模型启动长时间没有进展，已结束推理进程。请在模型管理中检查模型文件和运行环境。\n"
                                  + "\n".join(recent_errors)[-1200:])
                        return

            watchdog = Thread(target=watch_startup)
            watchdog.start()
            workers.append(watchdog)

            diagnostics_thread = Thread(target=diagnostics)
            diagnostics_thread.start()
            workers.append(diagnostics_thread)
            send(asdict(self.settings))
            journal = AudioJournal()

            def record():
                def block(samples):
                    journal.append(samples)
                    self.level.emit(float(np.sqrt(np.mean(samples * samples))))
                try:
                    self.capture_fn(self.settings, self.stop_capture, block)
                except Exception as exc:
                    self.fail(f"录音失败：{exc}")
                finally:
                    self.capture_done.set()
                    self.stage.emit("音频", "已停止")

            def feed():
                try:
                    while not self.abort.is_set():
                        samples = journal.read(16000)
                        if len(samples):
                            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                            send({"type": "audio", "pcm": base64.b64encode(pcm).decode()})
                        elif self.capture_done.is_set():
                            send({"type": "stop"})
                            break
                        else:
                            self.abort.wait(0.02)
                except Exception as exc:
                    if not self.abort.is_set():
                        self.fail(f"音频传递失败：{exc}")

            completed = False
            for line in self.process.stdout:
                last_progress[0] = time.monotonic()
                event = json.loads(line)
                kind = event["type"]
                if kind == "ready":
                    self.model_ready.set()
                    if self.stop_capture.is_set():
                        send({"type": "stop"})
                        continue
                    for action in [record, feed]:
                        thread = Thread(target=action)
                        thread.start()
                        workers.append(thread)
                    self.ready.emit()
                    self.stage.emit("音频", "连续采集")
                elif kind == "caption":
                    self.caption.emit(Caption(**event["data"]))
                elif kind == "metrics":
                    self.stage.emit("识别", f"计算延后 {event['compute_lag']:.1f}s · 待确认 {event['commit_lag']:.1f}s")
                elif kind == "status":
                    self.status.emit(event["text"])
                    if not self.model_ready.is_set():
                        self.stage.emit("识别", event["text"])
                elif kind == "translation_metrics":
                    if event["error"]:
                        self.stage.emit("翻译", "失败 · 原文保留")
                    else:
                        self.stage.emit("翻译", f"待处理 {event['pending']} 条 · 最近耗时 {event['compute_seconds']:.1f}s")
                    self.status.emit(f"翻译等待 {event['wait_seconds']:.1f}s · 推理 {event['compute_seconds']:.1f}s · 待处理 {event['pending']} 条")
                elif kind == "error":
                    self.fail(event["text"])
                elif kind == "done":
                    completed = True
            code = self.process.wait()
            if not completed and not self.abort.is_set():
                raise RuntimeError(f"推理进程提前退出（{code}）。\n" + "\n".join(recent_errors)[-1200:])
        except Exception as exc:
            self.fail(str(exc))
        finally:
            self.abort.set()
            self.stop_capture.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait()
            for thread in workers:
                thread.join()
            if journal:
                journal.close()
