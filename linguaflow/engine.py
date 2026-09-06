"""Three independent stages: capture -> ASR -> translation.

Stop drains already captured phrases; abort is used for fatal errors/close.
Only the coordinator owns model lifetime, so restart never overlaps models.
"""

import gc
import time
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Event, Thread

import numpy as np
from PySide6.QtCore import QThread, Signal

from .audio import capture
from .backends import NllbTranslator, WhisperRecognizer
from .core import Caption, Segmenter, offer_latest


class Session(QThread):
    status = Signal(str)
    caption = Signal(object)
    level = Signal(float)
    failure = Signal(str)
    ready = Signal()
    stage = Signal(str, str)

    def __init__(
        self,
        settings,
        parent=None,
        recognizer_factory=None,
        translator_factory=None,
        capture_fn=capture,
    ):
        super().__init__(parent)
        self.settings = settings
        self.stop_capture = Event()
        self.abort = Event()
        self.capture_done = Event()
        self.asr_done = Event()
        self.audio_queue = Queue(maxsize=3)
        self.text_queue = Queue(maxsize=12)
        self.recognizer_factory = recognizer_factory or (lambda s: WhisperRecognizer(s, self.report))
        self.translator_factory = translator_factory or (lambda s: NllbTranslator(s, self.report))
        self.prepare_translation_runtime = translator_factory is None
        self.capture_fn = capture_fn
        self.last_error = ""
        self.translation_error = ""
        self.recognized_count = 0
        self.dropped = 0

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
        segmenter = Segmenter(self.settings.phrase_seconds, self.settings.threshold)

        def enqueue(phrase):
            if not self.abort.is_set() and phrase is not None and offer_latest(self.audio_queue, phrase):
                self.dropped += 1
                self.report(
                    f"音频队列已满，跳过 {self.dropped} 段；已识别 {self.recognized_count} 条。请查看诊断记录。"
                )

        def block(samples):
            self.level.emit(float(np.sqrt(np.mean(samples * samples))))
            enqueue(segmenter.push(samples))

        try:
            self.stage.emit("音频", "采集中")
            self.capture_fn(self.settings, self.stop_capture, block)
            enqueue(segmenter.flush())
        except Exception as exc:
            self.fail(f"录音失败：{exc}")
        finally:
            self.capture_done.set()
            self.stage.emit("音频", "已停止")

    def _recognize(self, recognizer):
        counter = 0
        try:
            while not self.abort.is_set():
                try:
                    phrase = self.audio_queue.get(timeout=0.1)
                except Empty:
                    if self.capture_done.is_set():
                        break
                    continue
                started = time.monotonic()
                self.report(
                    f"正在识别 {phrase.end - phrase.start:.1f} 秒音频 · 等待 {self.audio_queue.qsize()} 段"
                )
                segments, language = recognizer.recognize(phrase.samples)
                self.report(f"识别完成 · {time.monotonic() - started:.1f} 秒 · {len(segments)} 条原文")
                for start, end, text in segments:
                    counter += 1
                    caption = Caption(
                        counter,
                        phrase.start + max(0, start),
                        min(phrase.end, phrase.start + end),
                        text,
                        language,
                    )
                    self.caption.emit(caption)
                    self.recognized_count = counter
                    if self.settings.translate:
                        if self.translation_error:
                            self.caption.emit(replace(caption, error=self.translation_error))
                            continue
                        # Keep all already displayed sources, mark skipped translations.
                        try:
                            self.text_queue.put_nowait(caption)
                        except Full:
                            self.caption.emit(replace(caption, error="翻译队列已满，已跳过"))
                            self.report("翻译等待队列已满，此条保留原文；翻译可能仍在加载，详见诊断记录。")
        except Exception as exc:
            self.fail(f"识别失败：{exc}")
        finally:
            self.asr_done.set()

    def run(self):
        workers = []
        recognizer = translator = None
        try:
            self.stage.emit("识别", "加载中")
            self.report("正在加载识别模型；首次使用可能需要下载…")
            recognizer = self.recognizer_factory(self.settings)
            if self.stop_capture.is_set():
                return
            self.report("识别模型已加载，正在预热验证推理；尚未录音…")
            self.stage.emit("识别", "预热中")
            if hasattr(recognizer, "warmup"):
                recognizer.warmup()
            if self.settings.translate and self.prepare_translation_runtime:
                # SciPy array API detection inspects sys.modules['torch'].Tensor.
                # Finish torch import before capture can call resample_poly.
                self.report("初始化翻译运行库；完成后开始录音…")
                NllbTranslator.prepare_runtime()
            if self.stop_capture.is_set():
                return
            workers = [Thread(target=self._record), Thread(target=self._recognize, args=(recognizer,))]
            self.ready.emit()
            self.stage.emit("识别", "就绪")
            self.report("识别已就绪，开始聆听；原文会先显示")
            for worker in workers:
                worker.start()
            if self.settings.translate and not self.abort.is_set():
                self.stage.emit("翻译", "加载中，原文继续")
                self.report("正在加载翻译模型（CPU）；原文识别继续运行…")
                try:
                    translator = self.translator_factory(self.settings)
                    self.stage.emit("翻译", "就绪 / CPU")
                    self.report("翻译模型已就绪")
                except Exception as exc:
                    self.translation_error = f"翻译模型加载失败：{exc}"
                    self.stage.emit("翻译", "加载失败，保留原文")
                    self.report(self.translation_error + "；继续显示原文")
            while not self.abort.is_set():
                try:
                    caption = self.text_queue.get(timeout=0.1)
                except Empty:
                    if self.asr_done.is_set():
                        break
                    continue
                try:
                    if self.translation_error:
                        self.caption.emit(replace(caption, error=self.translation_error))
                        continue
                    started = time.monotonic()
                    translated = translator.translate(caption.source, caption.language)
                    self.caption.emit(replace(caption, translation=translated))
                    self.report(f"译文已更新 · 翻译耗时 {time.monotonic() - started:.1f} 秒")
                except Exception as exc:
                    self.caption.emit(replace(caption, error=str(exc)))
                    self.report(f"翻译失败，原文已保留：{exc}")
        except Exception as exc:
            self.fail(f"启动失败（模型加载或推理预热）：{exc}")
        finally:
            self.stop_capture.set()
            for worker in workers:
                worker.join()
            recognizer = translator = None
            gc.collect()
