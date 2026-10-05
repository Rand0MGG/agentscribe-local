"""Internal gain and peak protection settings; no enhancement models or UI."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AudioConfig:
    output_db: float = 0.0
    limiter: bool = False
    peak_db: float = -1.0

    @classmethod
    def from_dict(cls, data=None):
        if data is not None and not isinstance(data, dict):
            raise ValueError("音频设置必须是参数对象。")
        # Ignore retired enhancement keys in historical snapshots; never restore
        # their dependencies or rewrite the original recording metadata.
        config = cls(**{key: value for key, value in (data or {}).items()
                        if key in cls.__dataclass_fields__})
        if not isinstance(config.limiter, bool):
            raise ValueError("峰值保护必须是布尔值。")
        for key, low, high in (("output_db", -12, 12), ("peak_db", -12, 0)):
            value = getattr(config, key)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not low <= value <= high):
                raise ValueError(f"音频参数 {key} 超出范围 {low}–{high}")
        return config

    def to_dict(self):
        return asdict(self)


def automatic_audio_config():
    """Return the user-selected +3 dB front end as a fresh session snapshot."""
    return AudioConfig(output_db=3, limiter=True).to_dict()
