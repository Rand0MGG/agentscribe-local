"""Backend session owns capture and an exclusive lease of a local WLK process."""
import base64
import json
import time
import wave
from collections import deque
from dataclasses import asdict, replace
from threading import Event, Thread
from uuid import uuid4

import numpy as np

from . import diagnostic_log as diag
from .audio import capture
from .capture_control import CaptureControl
from .capture_diagnostics import CaptureTrace
from .core import Caption
from .events import Signal, Worker
from .journal import AudioJournal
from .process_platform import stop_tree
from .runtime_paths import runtime_python
from .runtime_preparation import RuntimePreparation


class Session(Worker):
    startup_idle_timeout = 300
    stop_timeout = 180.
    status = Signal(str)
    caption = Signal(object)
    source_preview = Signal(object)
    model_result = Signal(object)
    level = Signal(float)
    source_changed = Signal(int)
    failure = Signal(str)
    ready = Signal()
    paused = Signal(bool)
    stage = Signal(str, str)

    def __init__(self, settings, parent=None, capture_fn=capture, diagnostic=False, recording_path=None,
                 runtime=None):
        super().__init__(parent)
        self.log_session = uuid4().hex
        self.settings = settings
        self.diagnostic = diagnostic
        self.capture_fn = capture_fn
        self.stop_capture = Event()
        self.capture_done = Event()
        self.abort = Event()
        self.process = None
        self.process_owned = Event()
        self.model_ready = Event()
        self.capture_started = Event()
        self.stop_started = None
        self.last_error = ""
        self.recording_path = recording_path
        self.recorded_seconds = 0.
        self.capture_control = CaptureControl()
        self.capture_settings = settings
        self.source_revision = 0
        self.owns_runtime = runtime is None
        self.runtime = runtime if runtime is not None else RuntimePreparation()

    def pause(self):
        if not self.capture_started.is_set() or self.stop_capture.is_set():
            return False
        return self.capture_control.pause()

    def resume(self):
        return self.capture_control.resume()

    def switch_source(self, device_id, loopback):
        """Queue a capture-only change; return its revision or None after stop.

        The capture thread releases the old device first. The model configuration,
        recording file and caption clock remain those of the current session.
        """
        with self.capture_control.condition:
            if self.stop_capture.is_set() or not self.capture_control.restart():
                return None
            self.capture_settings = replace(self.settings, device_id=device_id, loopback=loopback)
            self.source_revision += 1
            return self.source_revision

    def stop(self, discard=False):
        if self.stop_started is None:
            self.stop_started = time.monotonic()
        diag.event('stop_requested', session=self.log_session, discard=discard, recorded_seconds=self.recorded_seconds)
        self.stop_capture.set()
        self.capture_control.stop()
        if discard or not self.capture_started.is_set():
            self.abort.set()
            if self.process and self.process_owned.is_set() and self.process.poll() is None:
                self.process_owned.clear()  # Repeated cancellation must not spawn more cleanup tasks.
                # Cancel the owned launcher and Python child off the UI thread.
                Thread(target=stop_tree, args=(self.process,), kwargs={'force': True}).start()

    def fail(self, text):
        diag.event('session_failure', session=self.log_session)
        self.last_error = text
        self.failure.emit(text)
        self.stop(discard=True)

    def run(self):
        diag.set_session(self.log_session)
        diag.event('session_start', backend=self.settings.backend, device=self.settings.asr_device,
                   sample_rate=self.settings.input_sample_rate, draft_seconds=self.settings.draft_seconds,
                   window_seconds=self.settings.qwen_window_seconds, translate=self.settings.translate)
        workers = []
        journal = None
        prepared = None
        completed = False
        try:
            if self.abort.is_set() or self.stop_capture.is_set():
                return
            journal = AudioJournal(self.settings.input_sample_rate)

            def record():
                silent_samples = 0
                warned = False
                recording = None
                recording_file = None
                signal_trace = None
                def write_block(samples):
                    nonlocal silent_samples, warned
                    signal_trace.observe(samples)
                    if recording is not None:
                        recording.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                        recording_file.flush()
                    journal.append(samples)
                    if not self.capture_started.is_set():
                        diag.event('capture_first_block', session=self.log_session, samples=len(samples))
                    self.capture_started.set()
                    self.recorded_seconds = journal.written / (self.settings.input_sample_rate * 4)
                    self.level.emit(float(np.sqrt(np.mean(samples * samples))))
                    silent_samples = silent_samples + len(samples) if not np.any(samples) else 0
                    if silent_samples >= self.settings.input_sample_rate * 3 and not warned:
                        warned = True
                        self.stage.emit("音频", "输入持续为零，请检查来源 / 静音")
                        self.status.emit("连续 3 秒未采集到有效声音。请检查所选设备；系统音频来源需要正在播放音频。")
                    elif warned and silent_samples == 0:
                        warned = False
                        self.stage.emit("音频", "已收到声音 · 连续采集")

                def paused():
                    nonlocal silent_samples, warned
                    silent_samples, warned = 0, False
                    diag.event('capture_pause', session=self.log_session, recorded_seconds=self.recorded_seconds)
                    journal.mark_pause()
                    self.level.emit(0.)
                    self.stage.emit("音频", "已暂停 · 不采集声音")
                    self.paused.emit(True)

                def resumed():
                    diag.event('capture_resume', session=self.log_session, recorded_seconds=self.recorded_seconds)
                    self.stage.emit("音频", "连续采集")
                    self.paused.emit(False)
                try:
                    if self.recording_path:
                        recording_file = open(self.recording_path, 'wb')
                        recording = wave.open(recording_file, "wb")
                        recording.setnchannels(1)
                        recording.setsampwidth(2)
                        recording.setframerate(self.settings.input_sample_rate)
                        recording.writeframes(b'')
                        recording_file.flush()
                    previous_revision = 0
                    while (segment := self.capture_control.next_segment(paused, resumed)) is not None:
                        with self.capture_control.condition:
                            if segment.is_set():
                                continue
                            source_settings = self.capture_settings
                            revision = self.source_revision
                        if revision != previous_revision:
                            diag.event('source_switch', session=self.log_session, revision=revision, recorded_seconds=self.recorded_seconds)
                            journal.mark_pause()  # Flush old-source speech before new PCM.
                            silent_samples, warned = 0, False
                            self.level.emit(0.)
                        previous_revision = revision
                        acknowledged = [False]

                        def block(samples, segment=segment, revision=revision, acknowledged=acknowledged):
                            def write():
                                write_block(samples)
                                if not acknowledged[0]:
                                    acknowledged[0] = True
                                    self.source_changed.emit(revision)
                            return self.capture_control.accept(write, segment)

                        with diag.trace_scope(capture_id=uuid4().hex[:16], source_revision=revision,
                                              recording_start_seconds=self.recorded_seconds):
                            signal_trace = CaptureTrace('recording_input', self.settings.input_sample_rate)
                            try:
                                self.capture_fn(source_settings, segment, block)
                            finally:
                                signal_trace.finish()
                        if not segment.is_set():
                            break
                except Exception as exc:
                    diag.exception('capture_exception', exc)
                    self.fail(f"录音失败：{exc}")
                finally:
                    if recording is not None:
                        try:
                            recording.close()
                        except (OSError, wave.Error) as exc:
                            diag.exception('recording_wav_finalize_exception', exc)
                            self.fail(f"录音保存失败：{exc}")
                    if recording_file is not None:
                        try:
                            recording_file.close()
                        except (OSError, wave.Error) as exc:
                            diag.exception('recording_file_close_exception', exc)
                            self.fail(f"录音保存失败：{exc}")
                    self.capture_done.set()
                    if self.stop_started is None:
                        self.stop_started = time.monotonic()
                    self.stage.emit("音频", "已停止")

            capture_thread = Thread(target=record)
            capture_thread.start()
            workers.append(capture_thread)
            last_progress = [time.monotonic()]
            recent_errors = deque(maxlen=12)

            def diagnostics():
                cursor = 0
                while not self.abort.wait(.05):
                    for serial, text in prepared.recent_logs(cursor):
                        cursor = serial
                        last_progress[0] = time.monotonic()
                        recent_errors.append(text)
                        self.status.emit(text)

            def watch_progress():
                while not self.abort.wait(.1):
                    if self.process is not None and self.process.poll() is not None:
                        return
                    now = time.monotonic()
                    # Stopping during loading still drains accepted audio, but
                    # cannot wait forever even while the loader reports progress.
                    if self.stop_started is not None and now - self.stop_started > self.stop_timeout:
                        self.fail('录音收尾超时，已有录音和字幕保留，本次录音将标记为未完整结束。')
                        return
                    elif not self.model_ready.is_set() and now - last_progress[0] > self.startup_idle_timeout:
                        self.fail("模型启动长时间没有进展，已结束推理进程。请在模型管理中检查模型文件和运行环境。\n"
                                  + "\n".join(recent_errors)[-1200:])
                        return

            watchdog = Thread(target=watch_progress)
            watchdog.start()
            workers.append(watchdog)

            from .inference_startup import start_problem
            if problem := start_problem(self.settings):
                raise RuntimeError('：'.join(problem))
            python = runtime_python()
            if not python.is_file():
                raise RuntimeError("请先运行 scripts/install_runtime.py 安装 WhisperLiveKit 推理环境。")
            self.stage.emit("识别", "加载 WhisperLiveKit")
            self.status.emit("录音与模型加载并行；正在启动本地推理进程…")
            self.status.emit('正在等待后台准备的运行环境…')
            prepared = self.runtime.acquire(self.abort)
            self.process = prepared.process
            self.process_owned.set()
            if self.abort.is_set():
                raise RuntimeError('启动已取消。')

            def send(message):
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()

            diagnostics_thread = Thread(target=diagnostics)
            diagnostics_thread.start()
            workers.append(diagnostics_thread)
            settings = asdict(self.settings)
            settings['_diagnostic'] = self.diagnostic
            settings['_log_session'] = self.log_session
            diag.event('worker_attached', worker_pid=getattr(self.process, 'pid', None))
            self.status.emit('运行环境已准备；正在加载本次会话模型…')
            send(settings)
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
                    diag.exception('audio_transport_exception', exc)
                    if not self.abort.is_set():
                        self.fail(f"音频传递失败：{exc}")

            completed = False
            for line in self.process.stdout:
                last_progress[0] = time.monotonic()
                event = json.loads(line)
                kind = event["type"]
                if kind == "ready":
                    if self.model_ready.is_set():
                        continue
                    diag.event('model_ready', session=self.log_session, journal_pending_seconds=journal.pending_seconds)
                    self.model_ready.set()
                    if self.abort.is_set():
                        break
                    thread = Thread(target=feed)
                    thread.start()
                    workers.append(thread)
                    self.ready.emit()
                    self.stage.emit("识别", "模型已就绪，正在处理积压音频")
                elif kind == "caption":
                    self.caption.emit(Caption(**event["data"]))
                elif kind == 'source_preview':
                    self.source_preview.emit(event['data'])
                elif kind == 'source_preview_done':
                    self.source_preview.emit(dict(sequence=event['sequence'], done=True))
                elif kind == "model_result" and self.diagnostic:
                    self.model_result.emit(event["data"])
                elif kind == 'asr_timing':
                    diag.event('asr_capture_lag', session=self.log_session, decode_id=event['decode_id'],
                               recorded_seconds=self.recorded_seconds, decoded_end=event['window_end'],
                               lag_seconds_estimate=max(0., self.recorded_seconds - event['window_end']),
                               journal_pending_seconds=journal.pending_seconds)
                elif kind == "metrics":
                    processed = event.get('processed_audio_seconds')
                    lag = (max(0., self.recorded_seconds - processed) if processed is not None
                           else max(float(event['compute_lag']), journal.pending_seconds))
                    diag.periodic('pipeline_progress', key=self.log_session, session=self.log_session, recorded_seconds=self.recorded_seconds,
                               processed_seconds=processed, lag_seconds=lag, journal_pending_seconds=journal.pending_seconds,
                               compute_lag=event['compute_lag'], commit_lag=event['commit_lag'])
                    state = f"正在追赶识别 · 延后 {lag:.1f}s" if lag > 1 else "实时识别"
                    self.stage.emit("识别", state + f" · 待确认 {event['commit_lag']:.1f}s")
                elif kind == "status":
                    self.status.emit(event["text"])
                    if not self.model_ready.is_set():
                        self.stage.emit("识别", event["text"])
                elif kind == "translation_metrics":
                    diag.periodic('translation_progress', key=self.log_session, session=self.log_session, pending=event['pending'],
                               compute_seconds=event['compute_seconds'], wait_seconds=event['wait_seconds'],
                               failed=bool(event['error']))
                    if event["error"]:
                        self.stage.emit("翻译", "失败 · 原文保留")
                    else:
                        self.stage.emit("翻译", f"待处理 {event['pending']} 条 · 最近耗时 {event['compute_seconds']:.1f}s")
                    self.status.emit(f"翻译等待 {event['wait_seconds']:.1f}s · 推理 {event['compute_seconds']:.1f}s · 待处理 {event['pending']} 条")
                elif kind == "error":
                    self.fail(event["text"])
                elif kind == "done":
                    completed = True
                    break
            code = self.process.poll()
            if not completed and not self.abort.is_set() and code is None:
                code = self.process.wait(timeout=2)
            if not completed and not self.abort.is_set():
                raise RuntimeError(f"推理进程提前退出（{code}）。\n" + "\n".join(recent_errors)[-1200:])
        except Exception as exc:
            diag.exception('session_exception', exc)
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
                    self.runtime.release(prepared, reusable and not self.owns_runtime)
                except Exception as exc:
                    diag.exception('worker_release_exception', exc)
                    self.fail('会话模型释放失败：' + str(exc))
            if self.owns_runtime:
                self.runtime.close()
            for thread in workers:
                thread.join()
            if journal:
                journal.close()
            diag.event('session_end', session=self.log_session, complete=completed, failed=bool(self.last_error),
                       recorded_seconds=self.recorded_seconds, worker_exit=self.process.poll() if self.process else None)
            diag.clear_session(self.log_session)
