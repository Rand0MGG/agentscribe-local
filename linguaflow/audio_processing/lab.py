"""Audio presets, advanced controls and a local record/process/listen workspace."""
import json
import os
import signal
import time
import shutil
import tempfile
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QUrl, Qt, Signal, QTimer
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QProgressBar,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..audio import capture, list_devices
from ..wlk_session import runtime_python
from .config import AudioConfig, PRESETS
from .health import signal_stats, input_warning


class Recorder(QThread):
    progress = Signal(float)
    failure = Signal(str)
    level = Signal(float, bool)

    def __init__(self, device, path, seconds, parent):
        super().__init__(parent)
        self.device, self.path, self.seconds = device, path, seconds
        self.stop = threading.Event()
        self.health = {"samples": 0, "nonzero": 0, "peak": 0., "rms_dbfs": -180.}

    def run(self):
        try:
            settings = SimpleNamespace(device_id=self.device[0], loopback=self.device[1], input_sample_rate=48000)
            with wave.open(str(self.path), "wb") as output:
                output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                count = 0

                def write(samples):
                    nonlocal count
                    samples = samples[:max(0, int(self.seconds * 48000) - count)]
                    health = signal_stats(samples)
                    self.health["nonzero"] += health["nonzero"]
                    self.health["samples"] += len(samples)
                    self.health["peak"] = max(self.health["peak"], health["peak"])
                    self.level.emit(health["rms_dbfs"], bool(self.health["nonzero"]))
                    output.writeframesraw((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
                    count += len(samples)
                    self.progress.emit(count / 48000)
                    if count >= self.seconds * 48000:
                        self.stop.set()

                capture(settings, self.stop, write)
        except Exception as exc:
            self.failure.emit(str(exc))


class AudioLab(QDialog):
    def __init__(self, config=None, device=None, parent=None, discover=False):
        super().__init__(parent)
        self.setWindowTitle("音频实验室 · 试听后再应用")
        self.resize(920, 760)
        self.setStyleSheet("QDialog {background:#202020;} QGroupBox {border:1px solid #454545; border-radius:8px; margin-top:14px; padding:16px 10px 10px;} QGroupBox::title {subcontrol-origin:margin; left:12px;} QGroupBox::indicator {width:14px;height:14px;border:1px solid #888;border-radius:3px;background:#202020;} QGroupBox::indicator:checked {background:#dddddd;border-color:#dddddd;} QTabWidget::pane {border:0;}")
        self.temp = tempfile.TemporaryDirectory(prefix="linguaflow-audition-")
        self.root = Path(self.temp.name)
        self.device = device
        self.original = None
        self.processed = None
        self.job = None
        self.record_job = None
        self.busy = False
        self.cancelled = False
        self.close_requested = False
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self.check_timeout)
        self.record_failed = False
        self.controls = {}
        self.result_config = AudioConfig.from_dict(config).to_dict()
        outer = QVBoxLayout(self)
        title = QLabel("音频实验室")
        title.setStyleSheet("font-size:22px;font-weight:600")
        outer.addWidget(title)
        hint = QLabel("选择预设 → 录一小段或导入 WAV → 处理并对比回听 → 应用到下一次聆听")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        top = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(["自定义"] + list(PRESETS))
        top.addWidget(QLabel("场景预设"))
        top.addWidget(self.preset, 1)
        self.prepare = QPushButton("准备增强组件")
        self.prepare.setToolTip("首次使用时下载可选运行库和约 13 MB 的 DF3 模型；设备跟随高级设置。")
        top.addWidget(self.prepare)
        outer.addLayout(top)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        audition = QWidget()
        listen = QVBoxLayout(audition)
        source_row = QHBoxLayout()
        self.source = QComboBox()
        self.source.setMinimumContentsLength(25)
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        if device is not None:
            self.source.addItem("当前主界面录音来源（刷新可查看名称）", device)
        self.refresh_sources = QPushButton("刷新音频来源")
        source_row.addWidget(QLabel("录制来源"))
        source_row.addWidget(self.source, 1)
        source_row.addWidget(self.refresh_sources)
        listen.addLayout(source_row)
        self.source_hint = QLabel("录自己的讲话请选择“输入 / 麦克风”；“系统声音”只录电脑正在播放的声音。")
        self.source_hint.setWordWrap(True)
        listen.addWidget(self.source_hint)
        self.input_meter = QProgressBar()
        self.input_level = QLabel("等待录制 · 输入电平")
        listen.addWidget(self.input_level)
        self.input_meter.setRange(0, 80)
        self.input_meter.setValue(0)
        self.input_meter.setTextVisible(False)
        listen.addWidget(self.input_meter)
        self.sample_label = QLabel("还没有样本。建议录下包含轻声、停顿和背景噪音的 15 秒。")
        self.sample_label.setWordWrap(True)
        listen.addWidget(self.sample_label)
        row = QHBoxLayout()
        self.record = QPushButton("录制样本")
        self.record.setEnabled(device is not None)
        self.duration = QSpinBox()
        self.duration.setRange(3, 60)
        self.duration.setValue(15)
        self.duration.setSuffix(" 秒")
        self.stop_record = QPushButton("结束录制")
        self.stop_record.setEnabled(False)
        self.import_button = QPushButton("导入 WAV")
        for w in [self.record, self.duration, self.stop_record, self.import_button]:
            row.addWidget(w)
        listen.addLayout(row)
        self.process_button = QPushButton("用当前参数处理样本")
        self.process_button.setEnabled(False)
        listen.addWidget(self.process_button)
        self.chain = QLabel()
        self.chain.setWordWrap(True)
        listen.addWidget(self.chain)
        row = QHBoxLayout()
        self.play_original = QPushButton("回听原声")
        self.play_processed = QPushButton("回听处理后 · ASR 输入")
        self.stop_play = QPushButton("停止播放")
        self.export = QPushButton("导出处理后 WAV")
        for w in [self.play_original, self.play_processed, self.stop_play, self.export]:
            row.addWidget(w)
        listen.addLayout(row)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        listen.addWidget(self.seek)
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("回听音量（不影响 ASR）"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        volume_row.addWidget(self.volume)
        listen.addLayout(volume_row)
        self.stats = QLabel("处理后的回听为 16 kHz 单声道，与 ASR 实际收到的音频一致。")
        self.stats.setWordWrap(True)
        listen.addWidget(self.stats)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        listen.addWidget(self.log, 1)
        privacy = QLabel("录制与处理样本仅存本机临时目录，关闭后删除；导入的原文件、导出文件会保留。录音时暂停回听。")
        privacy.setWordWrap(True)
        listen.addWidget(privacy)
        self.tabs.addTab(audition, "回听对比")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        advanced = QWidget()
        self.advanced_layout = QVBoxLayout(advanced)
        self.group("apm", "1 · WebRTC 轻度降噪 · CPU", [
            ("apm_level", "抑制级别（0 最保守）", 0, 3, 1, 0)])
        self.group("highpass", "低频清理 · 减少隆隆声（默认关闭）", [])
        self.group("wpe", "2 · NARA-WPE 在线去混响 · CPU", [
            ("wpe_mix", "去混响混合比例", 0, 1, .05, 2),
            ("wpe_taps", "预测长度（帧）", 3, 30, 1, 0),
            ("wpe_delay", "预测延迟（帧，每帧 10 ms）", 1, 10, 1, 0),
            ("wpe_alpha", "记忆系数（越大适应越慢）", .9, .99999, .0001, 5)])
        df = self.group("deepfilter", "3 · DeepFilterNet3 人声增强", [
            ("df_mix", "增强混合比例（0 原声 / 1 全增强）", 0, 1, .05, 2)])
        self.df_device = QComboBox()
        self.df_device.addItem("CPU", "cpu")
        self.df_device.addItem("NVIDIA CUDA", "cuda")
        df.addRow("计算设备", self.df_device)
        self.controls["df_device"] = self.df_device
        self.df_device.currentIndexChanged.connect(self.changed)
        self.group("gain", "4 · 自适应响度 · CPU", [
            ("max_gain_db", "最大增益（dB）", 0, 30, 1, 1),
            ("gain_speed", "增益变化速度（dB/s）", .1, 12, .5, 1),
            ("headroom_db", "预留峰值空间（dB）", 1, 15, 1, 1),
            ("noise_ceiling_db", "噪声增益上限（dBFS）", -70, -20, 1, 1)])
        self.group("eq", "可选人声频段均衡 · 2.5 kHz（默认关闭）", [
            ("presence_db", "存在感增益（dB）", -6, 6, .5, 1)])
        self.group("limiter", "峰值保护", [("peak_db", "峰值上限（dBFS）", -12, 0, .5, 1)])
        gain_form = QFormLayout()
        self.add_number(gain_form, "output_db", "最终输出增益（dB）", -12, 12, .5, 1)
        self.advanced_layout.addLayout(gain_form)
        note = QLabel("顺序：低频清理 / APM → WPE → DF3 → 均衡 / 响度 / 峰值保护 → 16 kHz ASR。\n"
                      "WPE 使用单声道在线估计；不做声道质量选择。多重降噪可能损伤轻声，建议逐项试听。\n"
                      "CUDA 仅用于 DF3；APM 和 NARA-WPE 使用各项目现有的 CPU 实现。")
        note.setWordWrap(True)
        self.advanced_layout.addWidget(note)
        self.advanced_layout.addStretch()
        scroll.setWidget(advanced)
        self.tabs.addTab(scroll, "高级参数")
        buttons = QHBoxLayout()
        self.status = QLabel("参数尚未应用")
        self.status.setWordWrap(True)
        buttons.addWidget(self.status, 1)
        self.apply_button = QPushButton("应用到聆听")
        self.apply_button.setToolTip("将当前处理参数和录制来源用于下一次聆听。")
        self.cancel_button = QPushButton("取消当前操作")
        self.cancel_button.setEnabled(False)
        self.close_button = QPushButton("关闭")
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.close_button)
        outer.addLayout(buttons)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(.7)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(lambda p: self.seek.setValue(p) if not self.seek.isSliderDown() else None)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, int(d)))
        self.player.errorOccurred.connect(lambda *_: self.status.setText(self.player.errorString()))
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100))
        self.play_original.clicked.connect(lambda: self.play(self.original))
        self.play_processed.clicked.connect(lambda: self.play(self.processed))
        self.stop_play.clicked.connect(self.player.stop)
        self.record.clicked.connect(self.record_sample)
        self.refresh_sources.clicked.connect(self.discover_sources)
        self.source.currentIndexChanged.connect(self.source_changed)
        self.stop_record.clicked.connect(lambda: self.record_job.stop.set() if self.record_job else None)
        self.import_button.clicked.connect(self.import_sample)
        self.process_button.clicked.connect(self.process_sample)
        self.prepare.clicked.connect(self.prepare_components)
        self.export.clicked.connect(self.export_sample)
        self.apply_button.clicked.connect(self.apply_config)
        self.close_button.clicked.connect(self.reject)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.preset.currentTextChanged.connect(self.choose_preset)
        self.load_config(self.result_config)
        for name, preset in PRESETS.items():
            if {**preset.to_dict(), "df_device": self.result_config["df_device"]} == self.result_config:
                self.preset.blockSignals(True)
                self.preset.setCurrentText(name)
                self.preset.blockSignals(False)
                break
        self.status.setText("已载入当前聆听参数；可先试听再调整")
        self.refresh()
        if discover:
            QTimer.singleShot(0, self.discover_sources)

    def discover_sources(self):
        try:
            devices = list_devices()
            current = self.source.currentData()
            self.source.blockSignals(True)
            self.source.clear()
            for device in devices:
                self.source.addItem(device.name, (device.id, device.loopback))
            index = self.source.findData(current)
            if index >= 0:
                self.source.setCurrentIndex(index)
            self.source.blockSignals(False)
            self.source_changed()
        except Exception as exc:
            self.source.blockSignals(False)
            self.status.setText("无法读取音频来源：" + str(exc))

    def source_changed(self, *_):
        self.device = self.source.currentData()
        self.source_hint.setText("当前是系统声音：请播放音频；对着麦克风讲话不会被这一路录入。"
                                 if self.device and self.device[1] else
                                 "当前是麦克风输入：请讲话并观察电平。回听时使用系统默认输出设备。")
        self.refresh()

    def recording_level(self, db, nonzero):
        self.input_meter.setValue(round(max(0, min(80, db + 80))))
        self.input_level.setText(f"输入 {db:.1f} dBFS" if nonzero else "未收到声音 · 检查来源、静音与权限")

    def group(self, key, title, fields):
        group = QGroupBox("启用 · " + title)
        group.setCheckable(True)
        self.controls[key] = group
        group.toggled.connect(self.changed)
        form = QFormLayout(group)
        for field in fields:
            self.add_number(form, *field)
        self.advanced_layout.addWidget(group)
        return form

    def add_number(self, form, key, label, low, high, step, decimals):
        control = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            control.setDecimals(decimals)
        control.setRange(low, high)
        control.setSingleStep(step)
        control.valueChanged.connect(self.changed)
        self.controls[key] = control
        form.addRow(label, control)

    def config(self):
        return AudioConfig.from_dict({key: (w.isChecked() if isinstance(w, QGroupBox) else
                                           w.currentData() if isinstance(w, QComboBox) else w.value())
                                      for key, w in self.controls.items()}).to_dict()

    def load_config(self, data):
        for key, value in data.items():
            w = self.controls[key]
            w.blockSignals(True)
            if isinstance(w, QGroupBox):
                w.setChecked(value)
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(w.findData(value))
            else:
                w.setValue(value)
            w.blockSignals(False)
        self.changed(reset_preset=False)

    def choose_preset(self, name):
        if name in PRESETS:
            data = PRESETS[name].to_dict()
            data["df_device"] = self.df_device.currentData()
            self.load_config(data)

    def changed(self, *_, reset_preset=True):
        if not hasattr(self, "status"):
            return
        if reset_preset:
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(0)
            self.preset.blockSignals(False)
        self.processed = None
        if hasattr(self, "player"):
            self.player.stop()
        self.status.setText("参数已更改；重新处理样本后可回听")
        cfg = self.config()
        names = [name for key, name in [("apm", "APM"), ("highpass", "低频清理"), ("wpe", "WPE"),
                                       ("deepfilter", "DF3"), ("eq", "均衡"), ("gain", "响度"), ("limiter", "峰值保护")] if cfg[key]]
        self.chain.setText("当前处理：" + " → ".join(names + ["16 kHz ASR 输入"]))
        self.refresh()

    def refresh(self):
        self.play_original.setEnabled(bool(self.original) and not self.busy)
        self.play_processed.setEnabled(bool(self.processed) and not self.busy)
        self.export.setEnabled(bool(self.processed) and not self.busy)
        self.process_button.setEnabled(bool(self.original) and not self.busy)
        self.record.setEnabled(self.device is not None and not self.busy)
        for w in [self.import_button, self.prepare, self.preset, self.apply_button, self.duration, self.source, self.refresh_sources]:
            w.setEnabled(not self.busy)
        self.tabs.widget(1).setEnabled(not self.busy)
        self.cancel_button.setEnabled(self.busy)

    def play(self, path):
        if path and not self.busy:
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()

    def record_sample(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.original = self.processed = None
        self.busy, self.record_failed = True, False
        self.record_job = Recorder(self.device, self.root / "recorded.wav", self.duration.value(), self)
        self.record_job.progress.connect(lambda n: self.status.setText(f"正在录制 {n:.1f} 秒；回听已暂停"))
        self.record_job.failure.connect(self.record_error)
        self.record_job.level.connect(self.recording_level)
        self.record_job.finished.connect(self.record_done)
        self.stop_record.setEnabled(True)
        self.refresh()
        self.record_job.start()

    def record_error(self, text):
        self.record_failed = True
        self.status.setText("录制失败：" + text)

    def record_done(self):
        self.busy = False
        self.stop_record.setEnabled(False)
        if not self.record_failed:
            self.original = self.root / "recorded.wav"
            self.sample_label.setText("已录制样本。可以反复更改参数并处理同一段原声。")
            self.status.setText("录制结束，点击处理样本")
            if not self.record_job.health["nonzero"]:
                self.status.setText(input_warning(self.record_job.health))
                self.sample_label.setText("此次录制完全无声，请修正上方录音来源后重新录制。")
        self.record_job.deleteLater()
        self.record_job = None
        self.refresh()
        if self.close_requested:
            QTimer.singleShot(0, self.reject)

    def import_sample(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择最多 60 秒的样本", "", "WAV 音频 (*.wav)")
        if path:
            self.player.stop()
            self.player.setSource(QUrl())
            self.original = Path(path)
            self.processed = None
            self.sample_label.setText("样本：" + Path(path).name)
            self.refresh()

    def launch(self, args, operation):
        python = runtime_python()
        if not python.is_file():
            self.status.setText("请先在模型管理中安装推理环境。")
            return
        self.busy = True
        self.cancelled = False
        self.player.stop()
        self.player.setSource(QUrl())
        self.operation = operation
        self.started_at = time.monotonic()
        self.refresh()
        self.log.clear()
        self.status.setText("正在准备组件…" if operation == "install" else "正在处理样本…")
        self.job = QProcess(self)
        self.job.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        self.job.setProcessEnvironment(env)
        self.job.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.job.readyReadStandardOutput.connect(self.read_log)
        self.job.finished.connect(self.process_done)
        self.job.errorOccurred.connect(self.process_error)
        self.job.start(str(python), args)
        self.watchdog.start()

    def read_log(self):
        data = bytes(self.job.readAllStandardOutput())
        # ORT's Windows native logger may interleave UTF-16LE with Python UTF-8.
        text = data.decode("utf-8", "replace").replace("\x00", "").strip()
        self.log.appendPlainText(text)

    def check_timeout(self):
        elapsed = time.monotonic() - self.started_at
        if elapsed > (900 if self.operation == "install" else 180):
            self.log.appendPlainText("操作超时，正在停止处理进程。")
            self.cancel_operation()
        elif not self.cancelled:
            self.status.setText(f"{'准备组件' if self.operation == 'install' else '处理样本'}已运行 {int(elapsed)} 秒 · 可以取消")

    def cancel_operation(self):
        if self.record_job:
            self.record_job.stop.set()
            self.status.setText("正在结束录制…")
            return
        if not self.job or self.job.state() == QProcess.ProcessState.NotRunning:
            return
        self.cancelled = True
        self.cancel_button.setEnabled(False)
        self.status.setText("正在取消；已下载文件与原声保留")
        pid = int(self.job.processId())
        if os.name == "nt":
            self.killer = QProcess(self)
            self.killer.start("taskkill", ["/PID", str(pid), "/T", "/F"])
        elif self.operation == "install":
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            self.job.kill()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.watchdog.stop()
            self.busy = False
            self.status.setText("无法启动处理进程：" + self.job.errorString())
            self.refresh()

    def process_sample(self):
        self.processed = None
        self.pending_config = self.config()
        path = self.root / "settings.json"
        path.write_text(json.dumps(self.pending_config), encoding="utf-8")
        self.launch(["-m", "linguaflow.audio_processing.preview", "--input", str(self.original),
                     "--output", str(self.root / "processed.wav"), "--config", str(path)], "process")

    def prepare_components(self):
        script = Path(__file__).resolve().parents[2] / "scripts" / "install_audio.py"
        self.launch([str(script), "--device", self.df_device.currentData()], "install")

    def process_done(self, code, _status):
        self.watchdog.stop()
        self.busy = False
        if self.cancelled:
            self.status.setText("已取消；原声和已下载组件保留，可重试")
        elif code == 0 and self.operation == "process":
            try:
                self.processed = self.root / "processed.wav"
                stats = json.loads(Path(str(self.processed) + ".json").read_text(encoding="utf-8"))
                ratio = stats["elapsed"] / max(stats["seconds"], .001)
                self.stats.setText(f"样本 {stats['seconds']:.1f}s · 处理 {stats['elapsed']:.2f}s（耗时/时长 {ratio:.2f}）\n"
                                   f"平均电平 {stats['input_dbfs']:.1f} → {stats['output_dbfs']:.1f} dBFS · 超幅采样 {stats['clip_percent']:.2f}%\n"
                                   "数值用于检查音量和性能，识别效果仍需结合原文判断。")
                self.status.setText("可回听原声 / 处理后；满意后应用到聆听")
            except Exception as exc:
                self.processed = None
                self.status.setText("无法读取处理结果：" + str(exc))
        elif code == 0:
            self.status.setText("增强组件准备完成，可以处理样本")
        else:
            lines = [line.strip() for line in self.log.toPlainText().splitlines() if line.strip()]
            self.status.setText("操作失败：" + (lines[-1][-250:] if lines else f"进程退出码 {code}") + "；原声仍保留")
            self.tabs.setCurrentIndex(0)
        self.job.deleteLater()
        self.job = None
        self.refresh()
        if self.close_requested:
            QTimer.singleShot(0, self.reject)

    def export_sample(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存 ASR 输入音频", "enhanced.wav", "WAV (*.wav)")
        if path:
            try:
                shutil.copyfile(self.processed, path)
                self.status.setText("已导出：" + path)
            except OSError as exc:
                self.status.setText(str(exc))

    def apply_config(self):
        self.result_config = self.config()
        self.accept()

    def done(self, result):
        if self.busy:
            self.close_requested = True
            self.cancel_operation()
            return
        self.player.stop()
        self.player.setSource(QUrl())
        # Multimedia may release a file asynchronously on Windows. QDialog's
        # owner retains this object until playback has stopped; cleanup is best effort.
        try:
            self.temp.cleanup()
        except OSError:
            pass
        super().done(result)
