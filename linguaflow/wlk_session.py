"""Qt session owns capture and an exclusive lease of a local WLK process."""
import base64
import json
import os
import subprocess
import time
import wave
from collections import deque
from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread

import numpy as np
from PySide6.QtCore import QThread, Signal

from .audio import capture
from .capture_control import CaptureControl
from .core import Caption
from .journal import AudioJournal
from .runtime_paths import runtime_python


class Session(QThread):
    startup_idle_timeout = 300
    status = Signal(str)
    caption = Signal(object)
    model_result = Signal(object)
    level = Signal(float)
    failure = Signal(str)
    ready = Signal()
    paused = Signal(bool)
    stage = Signal(str, str)

    def __init__(self, settings, parent=None, capture_fn=capture, diagnostic=False, recording_path=None,
                 runtime=None):
        super().__init__(parent)
        self.settings = settings
        self.diagnostic = diagnostic
        self.capture_fn = capture_fn
        self.stop_capture = Event()
        self.capture_done = Event()
        self.abort = Event()
        self.process = None
        self.process_owned = Event()
        self.model_ready = Event()
        self.last_error = ""
        self.recording_path = recording_path
        self.capture_control = CaptureControl()
        self.runtime = runtime

    def pause(self):
        if not self.model_ready.is_set() or self.stop_capture.is_set():
            return False
        return self.capture_control.pause()

    def resume(self):
        return self.capture_control.resume()

    def stop(self, discard=False):
        self.stop_capture.set()
        self.capture_control.stop()
        if discard or ((self.process is not None or self.runtime is not None) and not self.model_ready.is_set()):
            self.abort.set()
            if self.process and self.process_owned.is_set() and self.process.poll() is None:
                self.process.terminate()

    def fail(self, text):
        self.last_error = text
        self.failure.emit(text)
        self.stop(discard=True)

    def run(self):
        workers = []
        journal = None
        prepared = None
        completed = False
        try:
            python = runtime_python()
            if not python.is_file():
                raise RuntimeError("请先运行 scripts/install_runtime.py 安装 WhisperLiveKit 推理环境。")
            self.stage.emit("识别", "加载 WhisperLiveKit")
            self.status.emit("正在启动本地推理进程…首次导入运行库可能需要较长时间，可点击停止取消。")
            if self.runtime is not None:
                self.status.emit('正在等待后台准备的运行环境…')
                prepared = self.runtime.acquire(self.abort)
            self.process = prepared.process if prepared else subprocess.Popen(
                [str(python), "-u", "-m", "linguaflow.wlk_worker"],
                cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8",
                     "LINGUAFLOW_TRACE_REVISIONS": "1" if self.diagnostic else "0"},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.process_owned.set()
            if self.abort.is_set():
                raise RuntimeError('启动已取消。')

            def send(message):
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()

            last_progress = [time.monotonic()]
            recent_errors = deque(maxlen=12)

            def diagnostics():
                if prepared:
                    cursor = 0
                    while not self.abort.wait(.05):
                        for serial, text in prepared.recent_logs(cursor):
                            cursor = serial
                            last_progress[0] = time.monotonic()
                            recent_errors.append(text)
                            self.status.emit(text)
                    return
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
            settings = asdict(self.settings)
            if prepared:
                settings['_diagnostic'] = self.diagnostic
                self.status.emit('运行环境已准备；正在加载本次会话模型…')
            send(settings)
            journal = AudioJournal(self.settings.input_sample_rate)

            def record():
                silent_samples = 0
                warned = False
                recording = None
                def write_block(samples):
                    nonlocal silent_samples, warned
                    if recording is not None:
                        recording.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                    journal.append(samples)
                    self.level.emit(float(np.sqrt(np.mean(samples * samples))))
                    silent_samples = silent_samples + len(samples) if not np.any(samples) else 0
                    if silent_samples >= self.settings.input_sample_rate * 3 and not warned:
                        warned = True
                        self.stage.emit("音频", "输入持续为零，请检查来源 / 静音")
                        self.status.emit("连续 3 秒未采集到有效声音。请检查所选设备；系统声音来源需要正在播放音频。")
                    elif warned and silent_samples == 0:
                        warned = False
                        self.stage.emit("音频", "已收到声音 · 连续采集")

                def block(samples):
                    return self.capture_control.accept(lambda: write_block(samples))

                def paused():
                    nonlocal silent_samples, warned
                    silent_samples, warned = 0, False
                    journal.mark_pause()
                    self.level.emit(0.)
                    self.stage.emit("音频", "已暂停 · 不采集声音")
                    self.paused.emit(True)

                def resumed():
                    self.stage.emit("音频", "连续采集")
                    self.paused.emit(False)
                try:
                    if self.recording_path:
                        recording = wave.open(str(self.recording_path), "wb")
                        recording.setnchannels(1)
                        recording.setsampwidth(2)
                        recording.setframerate(self.settings.input_sample_rate)
                    while (segment := self.capture_control.next_segment(paused, resumed)) is not None:
                        self.capture_fn(self.settings, segment, block)
                        if not segment.is_set():
                            break
                except Exception as exc:
                    self.fail(f"录音失败：{exc}")
                finally:
                    if recording is not None:
                        try:
                            recording.close()
                        except OSError as exc:
                            self.fail(f"录音保存失败：{exc}")
                    self.capture_done.set()
                    self.stage.emit("音频", "已停止")

            def feed():
                try:
                    while not self.abort.is_set():
                        samples = journal.read(self.settings.input_sample_rate)
                        if len(samples):
                            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                            send({"type": "audio", "pcm": base64.b64encode(pcm).decode()})
                        elif journal.take_pause():
                            send({"type": "pause"})
                        elif self.capture_done.is_set() and journal.pending_seconds == 0:
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
                elif kind == "model_result" and self.diagnostic:
                    self.model_result.emit(event["data"])
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
                    if prepared:
                        break
            code = self.process.poll() if prepared else self.process.wait()
            if not completed and not self.abort.is_set():
                raise RuntimeError(f"推理进程提前退出（{code}）。\n" + "\n".join(recent_errors)[-1200:])
        except Exception as exc:
            if not self.abort.is_set():
                self.fail(str(exc))
        finally:
            reusable = completed and not self.abort.is_set() and not self.last_error
            self.abort.set()
            self.stop_capture.set()
            self.capture_control.stop()
            # Old Session objects must never terminate a worker leased again.
            self.process_owned.clear()
            if prepared:
                try:
                    self.runtime.release(prepared, reusable)
                except Exception as exc:
                    self.fail('会话模型释放失败：' + str(exc))
            elif self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            for thread in workers:
                thread.join()
            if journal:
                journal.close()
