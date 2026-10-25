"""SoundCard uses WASAPI on Windows and CoreAudio on macOS."""

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from platform import mac_ver

MAC_SYSTEM_AUDIO = "macos:system-audio"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    loopback: bool


def list_devices() -> list[Device]:
    import soundcard as sc

    # A virtual source needs no display enumeration or permission prompt here.
    result = ([Device(MAC_SYSTEM_AUDIO, "系统音频 · 电脑声音", True)]
              if sys.platform == "darwin" and int(mac_ver()[0].split('.')[0] or 0) >= 13 else [])
    for mic in sc.all_microphones(include_loopback=sys.platform == "win32"):
        loopback = bool(mic.isloopback)
        prefix = "系统音频" if loopback else "外部输入"
        result.append(Device(str(mic.id), f"{prefix} · {mic.name}", loopback))
    return result


def discover_devices() -> list[Device]:
    """Bound native discovery to an owned process; keep COM out of UI threads."""
    from .process_platform import close_process_pipes, start_worker, stop_worker
    from .runtime_paths import knowledge_python, python_environment, resource_root
    process, job = start_worker(knowledge_python(), 'linguaflow.audio', env=python_environment(),
                                cwd=resource_root(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        try:
            output, errors = process.communicate(timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('音频来源检查超时，请检查设备连接后重新刷新。') from exc
        if process.returncode:
            raise RuntimeError('无法刷新音频来源，请检查设备连接后重试：' + errors.decode('utf-8', errors='replace').strip())
        return [Device(**row) for row in json.loads(output.decode('utf-8'))]
    finally:
        stop_worker(process, job, (), force=True)
        close_process_pipes(process)


def capture(settings, stop, on_block):
    if stop.is_set():
        return
    if sys.platform == "darwin" and settings.device_id == MAC_SYSTEM_AUDIO:
        from .audio_macos import capture_system_audio
        capture_system_audio(settings, stop, on_block)
        return
    if sys.platform == "darwin" and settings.loopback:
        raise RuntimeError("macOS 不支持 Windows 系统回环配置，请在音频来源中重新选择“系统音频 · 电脑声音”；macOS 13 以下请选择已配置的音频输入。")
    import numpy as np
    import soundcard as sc

    # Both desktop frontends capture at 48kHz. Do not load SciPy/BLAS before
    # opening that stream when no resampling is needed (cold native DLL loads
    # can stall alongside concurrent model-cache imports on Windows).
    output_rate = getattr(settings, 'input_sample_rate', 16000)
    if output_rate != 48000:
        from scipy.signal import resample_poly

    # Resolve inside the capture thread; native audio handles stay thread-local.
    devices = sc.all_microphones(include_loopback=settings.loopback)
    mic = next(
        (m for m in devices if str(m.id) == settings.device_id and bool(m.isloopback) == settings.loopback),
        None,
    )
    if mic is None:
        raise RuntimeError("录音设备已断开，请刷新列表并重新选择。")
    # Record all native channels. WASAPI mono-channel recording has a known
    # SoundCard issue; downmix here rather than requesting a single channel.
    # WASAPI uses a one-second buffer. CoreAudio constrains hardware buffer
    # sizes, so keep its native default instead of requesting 48,000 frames.
    # Both backends still deliver 100 ms blocks to the application.
    options = {"samplerate": 48000}
    if sys.platform != "darwin":
        options["blocksize"] = 48000
    if stop.is_set():
        return
    from . import diagnostic_log as diag
    diag.event('capture_backend_open', output_rate=output_rate, loopback=bool(settings.loopback))
    with mic.recorder(**options) as recorder:
        diag.event('capture_backend_started')
        while not stop.is_set():
            data = recorder.record(numframes=4800)
            data = np.asarray(data, dtype=np.float32)
            if data.ndim != 2 or not data.shape[1] or not len(data):
                raise RuntimeError("录音设备没有返回有效音频帧，请重新选择设备。")
            if not np.isfinite(data).all():
                raise RuntimeError("录音设备返回了无效采样，请重新连接设备。")
            mono = np.asarray(data, dtype=np.float32).mean(axis=1)
            samples = (mono if output_rate == 48000
                       else resample_poly(mono, 1, 3).astype(np.float32))
            on_block(samples)


if __name__ == '__main__':
    print(json.dumps([asdict(device) for device in list_devices()], ensure_ascii=False))
