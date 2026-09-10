"""Serializable settings; no Qt or model imports."""
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class AudioConfig:
    apm: bool = False
    apm_level: int = 0
    highpass: bool = False
    wpe: bool = False
    wpe_mix: float = 0.35
    wpe_taps: int = 10
    wpe_delay: int = 3
    wpe_alpha: float = 0.9999
    deepfilter: bool = False
    df_device: str = "cpu"
    df_mix: float = 0.65
    gain: bool = False
    max_gain_db: float = 12.0
    gain_speed: float = 3.0
    headroom_db: float = 6.0
    noise_ceiling_db: float = -45.0
    eq: bool = False
    presence_db: float = 2.0
    output_db: float = 0.0
    limiter: bool = False
    peak_db: float = -1.0

    @classmethod
    def from_dict(cls, data=None):
        if data is not None and not isinstance(data, dict):
            raise ValueError("音频设置必须是参数对象。")
        known = {f.name for f in fields(cls)}
        config = cls(**{k: v for k, v in (data or {}).items() if k in known})
        for key in ["apm", "highpass", "wpe", "deepfilter", "gain", "eq", "limiter"]:
            if not isinstance(getattr(config, key), bool):
                raise ValueError(f"音频开关 {key} 必须是布尔值。")
        for key in ["apm_level", "wpe_taps", "wpe_delay"]:
            if type(getattr(config, key)) is not int:
                raise ValueError(f"音频参数 {key} 必须是整数。")
        ranges = {"apm_level": (0, 3), "wpe_mix": (0, 1), "wpe_taps": (3, 30),
                  "wpe_delay": (1, 10), "wpe_alpha": (.9, .99999), "df_mix": (0, 1),
                  "max_gain_db": (0, 30), "gain_speed": (.1, 12), "headroom_db": (1, 15),
                  "noise_ceiling_db": (-70, -20), "presence_db": (-6, 6),
                  "output_db": (-12, 12), "peak_db": (-12, 0)}
        for key, (low, high) in ranges.items():
            value = getattr(config, key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"音频参数 {key} 超出范围 {low}–{high}")
        if config.df_device not in ("cpu", "cuda"):
            raise ValueError("音频增强设备必须是 cpu 或 cuda")
        return config

    def to_dict(self):
        return asdict(self)


PRESETS = {
    "原声直通 · 系统音频": AudioConfig(),
    "轻度降噪 · 普通麦克风": AudioConfig(apm=True, gain=True, limiter=True),
    "温和增强 · 嘈杂环境": AudioConfig(deepfilter=True, gain=True, limiter=True),
    "课堂远场 · 去混响": AudioConfig(wpe=True, deepfilter=True, gain=True, limiter=True),
    "组合增强 · 谨慎使用": AudioConfig(apm=True, wpe=True, deepfilter=True,
                                        df_mix=.5, gain=True, limiter=True),
}
