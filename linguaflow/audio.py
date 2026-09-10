"""SoundCard uses WASAPI on Windows and CoreAudio on macOS."""

import sys
from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    loopback: bool


def list_devices() -> list[Device]:
    import soundcard as sc

    result = []
    for mic in sc.all_microphones(include_loopback=sys.platform == "win32"):
        loopback = bool(mic.isloopback)
        prefix = "系统声音" if loopback else "输入"
        result.append(Device(str(mic.id), f"{prefix} · {mic.name}", loopback))
    return result


def capture(settings, stop, on_block):
    import soundcard as sc

    # Resolve inside the capture thread; native audio handles stay thread-local.
    devices = sc.all_microphones(include_loopback=settings.loopback)
    mic = next(
        (m for m in devices if str(m.id) == settings.device_id and bool(m.isloopback) == settings.loopback),
        None,
    )
    if mic is None:
        raise RuntimeError("录音设备已断开，请停止后刷新设备列表。")
    # Record all native channels. WASAPI mono-channel recording has a known
    # SoundCard issue; downmix here rather than requesting a single channel.
    # One second of native buffering absorbs model-loading scheduling stalls.
    # Still read 100 ms at a time; buffer capacity is not the subtitle interval.
    with mic.recorder(samplerate=48000, blocksize=48000) as recorder:
        while not stop.is_set():
            data = recorder.record(numframes=4800)
            data = np.asarray(data, dtype=np.float32)
            if data.ndim != 2 or not data.shape[1] or not len(data):
                raise RuntimeError("录音设备没有返回有效音频帧，请重新选择设备。")
            if not np.isfinite(data).all():
                raise RuntimeError("录音设备返回了无效采样，请重新连接设备。")
            mono = np.asarray(data, dtype=np.float32).mean(axis=1)
            samples = (mono if getattr(settings, "input_sample_rate", 16000) == 48000
                       else resample_poly(mono, 1, 3).astype(np.float32))
            on_block(samples)
