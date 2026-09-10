# AgentScribe v0.4.0 · 源码预览版

AgentScribe（原 LinguaFlow）是由 Agent 协作开发的本地语音识别与双语字幕桌面应用。本版提供源码包及 Windows/macOS 安装脚本，不包含模型权重或独立 EXE/DMG。

## 更新

- 音频实验室：WebRTC APM、WPE、DeepFilterNet3、均衡和响度控制，可调整预设、回听、导出音频并取消准备操作。
- 本地 SaT 上下文分句：听写、暂定分段、定稿分离；原文和翻译支持版本修订。
- Qwen 真实草稿与词语替换、分段合并提示，提供课堂快速配置。
- 修复停顿参数未应用到 Silero 检测器、短暂停顿导致 Qwen 上下文过早重置的问题。
- Codex 风格桌面界面、独立模型管理与诊断记录。

## 安装与验证

解压源码包后按照 README 安装 Python 环境与模型运行环境。建议 Python 3.12。旧版 `python -m linguaflow` 入口继续可用，新命令为 `agentscribe`。

41 项回归通过，Windows 实机 Whisper + GPU 翻译链路通过。约 4 分 50 秒课堂样本上，与用户提供的未核实参考文本的词级分歧从 32.7% 降至 11.3%；该指标不是人工真值错误率。参见 `docs/CLASSROOM_VALIDATION.md`。

macOS 和 8 GB 显存配置仍需独立实机验证。依赖和模型许可各自适用，详见 THIRD_PARTY_NOTICES.md。课堂录音、用户参考文本、虚拟环境、诊断日志和模型缓存不包含在发布包内。
