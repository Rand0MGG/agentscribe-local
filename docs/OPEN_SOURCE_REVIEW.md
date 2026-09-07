# 上游方案与集成范围

0.3 使用以下完整运行时，不再仅复制 LocalAgreement 的缓冲类。

- [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit)：AudioProcessor、连续 VAC/VAD、SimulStreaming/AlignAtt、Qwen backend。
- [SimulStreaming](https://github.com/ufal/SimulStreaming)：Whisper 的流式提交策略；通过 WhisperLiveKit 消费实现。
- [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)：原始模型与 Transformers 实现。
- [Qwen3-ASR-causal](https://github.com/QuentinFuxa/Qwen3-ASR-causal)：采用 windowed 适配，未开启英语专用 causal 权重。

具体提交固定于 requirements-runtime.txt，许可证见 THIRD_PARTY_NOTICES.md。
桌面代码负责音频来源、进程生命周期、短字幕/原文草稿展示及独立 GPU 翻译；不再维护自己的音频回听和稳定前缀算法。

Whisper、窗口式流式适配、原生因果流式模型并非同一种计算方式。上游吞吐基准不能直接当作本应用端到端延迟，真实验证范围见 VALIDATION.md。
