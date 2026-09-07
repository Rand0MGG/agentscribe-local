# 本地 Qwen3-ASR

0.3 已移除旧 HTTP/WSL 服务桥接及其配置。无需另开服务，模型管理选择 Qwen3-ASR 即可。

先按 README 安装 `.venv-wlk`，再在模型管理下载 0.6B 或 1.7B。请选择明确的原文语言；支持严格离线、CPU 和 Windows CUDA。桌面尚未开放 Mac MPS。

采用 WhisperLiveKit 的 HF windowed 适配，源模型来自 Qwen；不使用英语专用 causal 微调模型。词时间戳属于估计值。0.6B 已完成 Windows CUDA 真实音频验证，1.7B 尚未完成同等硬件验收。

运行 `scripts/smoke_session.py --backend qwen3-streaming` 可以验证与桌面相同的 Qt/进程/推理/翻译路径。测试音频为仓库中的固定合成英文语音，不采集用户麦克风。
