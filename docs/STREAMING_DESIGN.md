# 连续音频与原文修订（0.2）

本次不对已被用户判断不可用的旧路径继续做效果基准。改动针对音频完整性、上下文和字幕生命周期；功能测试通过不代表识别效果已获验收。

## 三种“流式”不能混用

| 能力 | 输入 | 是否适用于边说边显示 |
| --- | --- | --- |
| 文件转录、逐 token / 逐段输出 | 已录好的完整音频 | 仅输出渐进，不证明能接收持续音频 |
| 离线模型近实时适配 | 滚动音频窗口，反复识别 | 可以，但须重叠、去重、上下文、草稿修订和定稿策略 |
| 持续音频会话接口 | 不断送入新音频并保留会话状态 | 可以；仍须检查内部是否重算、延迟、停顿和内存边界 |

[MacWhisper 官方 CLI 文档](https://docs.macwhisper.com/article/57-macwhisper-command-line-tool)把 `--stream` 定义为文件处理过程逐段输出。该列表包含 WhisperKit，不能拿它反驳用户所见的“Live Captions 只允许 Parakeet”。本次没有 MacWhisper GUI 的直接访问条件，未独立核实所有版本 Live Captions 的模型菜单；不声称 Whisper 在该功能中可选。

同名 large-v3 不保证相同效果：录完音频再处理有更完整的右侧上下文；固定短段可能切词；能量门限及重复 VAD 可能漏语音；积压丢弃会直接丢内容。旧工程存在这些链路因素，不能归咎于翻译速度。也不能从 Parakeet 品牌名称推断其所有变体均为原生流式。

## 本次接入

1. `AudioJournal` 连续保存采集到的 16kHz PCM；识别落后时只显示积压，不覆盖旧片段。正常停止会处理剩余内容，异常或关闭取消后删除临时文件。
2. Whisper 使用滚动窗口、词时间戳和最近已定稿文本提示。整行草稿可被下一次识别替换，也可撤回；停顿时定稿。
3. 长句使用 [UFAL Whisper-Streaming](https://github.com/ufal/whisper_streaming) 的实际 `HypothesisBuffer` 代码比较连续识别的一致部分。到约 20 秒尝试提交稳定前缀，保留至少 2 秒尾部待确认；裁剪后保留 1 秒声学重叠。不是移植整个上游系统，不沿用上游性能指标。
4. Qwen 使用官方 `init_streaming_state / streaming_transcribe / finish_streaming_transcribe`。检查服务支持连续输入和原文修订；禁止把文件 API 当实时引擎。官方实现累积音频并回退尾部 token，不能宣传为每次仅计算新音频。
5. Caption 有 `id / revision / final`。界面按版本更新原文，旧版本不能覆盖新版本。翻译只接收 final，避免翻译先前错误草稿；导出只包含定稿。

## 选择与限制

[Whisper-Streaming](https://github.com/ufal/whisper_streaming) 上游已推荐后继 [SimulStreaming](https://github.com/ufal/SimulStreaming)。本次选取其独立 MIT 一致性缓冲组件，复用现有 faster-whisper Windows GPU 环境；并未宣称这是最新或效果最佳整套方案。

[Qwen3-ASR 官方说明](https://github.com/QwenLM/Qwen3-ASR#streaming-inference)明确流式当前依赖 vLLM，不提供流式时间戳或批处理。此项目接入的是可选本机服务；0.6B 为 8GB 优先候选，未实测其总显存和延迟。1.7B 参数量不等于运行显存预算。

macOS 当前仍为 Whisper CPU 适配；没有接入 Parakeet、MLX 或 Metal。Windows 桌面可连接同机 WSL 服务，需先独立完成服务安装。Qwen 当前连续 60 秒无停顿会停止报错，避免无限累积状态；时间戳是本地会话范围估计，不是词级精确对齐。

定稿历史暂不回写，修订只限当前尚未确认的原文。VAD 对停顿的判断仍可能不准，用户可延长定稿停顿。后续效果评估应针对新方案的长句、轻声、中英混合和跨边界重复；本次未进行效果验收。
