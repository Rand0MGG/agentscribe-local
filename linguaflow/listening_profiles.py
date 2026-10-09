"""User-facing listening presets; preserve ASR confirmation and sentence finalization."""
PROFILES = {
    'speed': ('减少计算', 1.5, '减少识别请求，适合电脑忙碌时；原文草稿可能更新较慢。'),
    'balanced': ('均衡', 1., '兼顾草稿请求频率与计算量，推荐先使用。'),
    'quality': ('更快请求草稿', .5, '更频繁请求原文草稿，计算量更高；实际速度取决于模型。'),
}
