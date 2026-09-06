"""Continuous capture -> revisable source -> translation of finalized source."""
import gc
import time
from dataclasses import replace
from queue import Empty, Queue
from threading import Event, Thread

import numpy as np
from PySide6.QtCore import QThread, Signal

from .audio import capture
from .backends import NllbTranslator, WhisperRecognizer
from .journal import AudioJournal
from .streaming import WhisperReviser


class Session(QThread):
    status = Signal(str)
    caption = Signal(object)
    level = Signal(float)
    failure = Signal(str)
    ready = Signal()
    stage = Signal(str, str)

    def __init__(self, settings, parent=None, recognizer_factory=None, translator_factory=None, capture_fn=capture):
        super().__init__(parent)
        self.settings = settings
        self.stop_capture = Event()
        self.abort = Event()
        self.capture_done = Event()
        self.asr_done = Event()
        self.text_queue = Queue()
        self.recognizer_factory = recognizer_factory or (lambda s: WhisperRecognizer(s, self.report))
        self.translator_factory = translator_factory or (lambda s: NllbTranslator(s, self.report))
        self.prepare_translation_runtime = translator_factory is None
        self.capture_fn = capture_fn
        self.last_error = ""
        self.translation_error = ""
        self.recognized_count = 0
        self.journal = None

    def report(self, text):
        if not self.abort.is_set():
            self.status.emit(text)

    def fail(self, text):
        self.last_error = text
        self.stop(discard=True)
        self.stage.emit("会话", "失败")
        self.failure.emit(text)

    def stop(self, discard=False):
        self.stop_capture.set()
        if discard:
            self.abort.set()

    def _record(self):
        def block(samples):
            self.journal.append(samples)
            self.level.emit(float(np.sqrt(np.mean(samples * samples))))
        try:
            self.stage.emit("音频", "完整采集")
            self.capture_fn(self.settings, self.stop_capture, block)
        except Exception as exc:
            self.last_error = f"录音失败：{exc}"
            self.failure.emit(self.last_error)
            self.stop_capture.set()
        finally:
            self.capture_done.set()
            self.stage.emit("音频", "已停止")

    def _publish(self, events):
        for caption in events:
            self.caption.emit(caption)
            if caption.final and caption.source:
                self.recognized_count += 1
                if self.settings.translate:
                    self.text_queue.put(caption)

    def _recognize(self, processor):
        interval = self.settings.update_seconds
        try:
            while not self.abort.is_set():
                pending = self.journal.pending_seconds
                if pending < interval and not self.capture_done.is_set():
                    self.abort.wait(0.05)
                    continue
                if pending == 0 and self.capture_done.is_set():
                    break
                samples = self.journal.read(int(16000 * interval))
                if not len(samples):
                    continue
                started = time.monotonic()
                self._publish(processor.update(samples))
                backlog = self.journal.pending_seconds
                self.stage.emit("识别", "更新原文" if backlog < 3 else f"延后 {backlog:.0f} 秒 · 音频保留")
                self.report(f"原文更新耗时 {time.monotonic() - started:.1f}s · 待处理 {backlog:.1f}s · 无音频丢弃")
            if not self.abort.is_set():
                self.stage.emit("识别", "确认最后一句")
                self._publish(processor.update(np.empty(0, np.float32), final=True))
        except Exception as exc:
            self.fail(f"实时识别失败：{exc}")
        finally:
            self.asr_done.set()

    def run(self):
        workers = []
        recognizer = translator = processor = None
        try:
            self.stage.emit("识别", "准备中")
            if self.settings.backend == "qwen-stream":
                from .qwen_client import QwenStream
                processor = QwenStream(self.settings)
            elif self.settings.backend == "whisper-live":
                self.report("正在加载 Whisper；近实时模式会反复回听并修订原文…")
                recognizer = self.recognizer_factory(self.settings)
                if self.stop_capture.is_set():
                    return
                self.stage.emit("识别", "预热中")
                if hasattr(recognizer, "warmup"):
                    recognizer.warmup()
                processor = WhisperReviser(recognizer, self.settings)
            else:
                raise ValueError("所选后端不支持持续音频输入。请在模型管理中选择实时或近实时引擎。")
            if self.settings.translate and self.prepare_translation_runtime:
                self.report("初始化本地翻译运行库…")
                NllbTranslator.prepare_runtime()
            if self.stop_capture.is_set():
                return
            self.journal = AudioJournal()
            workers = [Thread(target=self._record), Thread(target=self._recognize, args=(processor,))]
            self.ready.emit()
            self.stage.emit("识别", "等待语音")
            for worker in workers:
                worker.start()
            if self.settings.translate and not self.abort.is_set():
                self.stage.emit("翻译", "加载中 · 原文先行")
                try:
                    translator = self.translator_factory(self.settings)
                    self.stage.emit("翻译", "只翻译定稿原文")
                except Exception as exc:
                    self.translation_error = f"翻译加载失败：{exc}"
                    self.stage.emit("翻译", "不可用 · 原文继续")
                    self.report(self.translation_error)
            while not self.abort.is_set():
                try:
                    caption = self.text_queue.get(timeout=0.1)
                except Empty:
                    if self.asr_done.is_set():
                        break
                    continue
                try:
                    if self.translation_error:
                        raise RuntimeError(self.translation_error)
                    translated = translator.translate(caption.source, caption.language)
                    self.caption.emit(replace(caption, translation=translated))
                except Exception as exc:
                    self.caption.emit(replace(caption, error=str(exc)))
        except Exception as exc:
            self.fail(f"启动失败：{exc}")
        finally:
            self.stop_capture.set()
            for worker in workers:
                worker.join()
            if processor is not None:
                try:
                    processor.close()
                except Exception:
                    pass
            if self.journal is not None:
                self.journal.close()
            recognizer = translator = processor = None
            gc.collect()
