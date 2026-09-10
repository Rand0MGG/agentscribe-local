"""Small signal checks shared by recording, audition and validation."""
import numpy as np


def signal_stats(samples):
    x = np.asarray(samples, np.float64)
    if not x.size:
        return {"samples": 0, "peak": 0., "rms_dbfs": -180., "nonzero": 0}
    if not np.isfinite(x).all():
        raise ValueError("音频包含 NaN 或无穷大，请检查采集设备或关闭异常处理模块。")
    return {"samples": int(x.size), "peak": float(np.max(np.abs(x))),
            "rms_dbfs": float(20 * np.log10(max(float(np.sqrt(np.mean(x * x))), 1e-9))),
            "nonzero": int(np.count_nonzero(x))}


def input_warning(stats):
    if not stats["nonzero"]:
        return "原声没有有效声音（全部为零）。请检查录音来源、麦克风静音及系统权限；系统声音需要正在播放音频。"
    if stats["rms_dbfs"] < -65:
        return "原声电平很低，请先检查麦克风距离、输入音量和设备选择。"
    return ""
