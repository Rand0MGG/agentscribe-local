# 历史文档归档

这里保留选型、旧版本和阶段验证，不再追加当前规范。记录中的行为、门槛、命令和分支安排只适用于当时；有些试验产物已按授权清理，不能假定仍可复现。

日常使用看 [使用指南](../WORKSPACE.md)；开发看 [AGENTS](../../AGENTS.md) 与 [架构](../ARCHITECTURE.md)；打包和更新看 [发行流程](../RELEASING.md)。当前文档的完整入口见 [文档索引](../PROJECT_STRUCTURE.md)。

## 设计与版本

- [课程助手设计 v1.6](AgentScribe_软件开发设计文档_v1.6.md)：原始选型、任务拆分与规划。
- [v0.4.0](releases/RELEASE_v0.4.0.md)、[v0.5.0](releases/RELEASE_v0.5.0.md)：对应源码版本的发布说明，不代表当前安装包或两端验收。

## 阶段验证

- [课堂验证](testing/CLASSROOM_VALIDATION.md)、[字幕修订](testing/REVISION_PIPELINE.md)、[界面体验](testing/UI_EXPERIENCE.md)。
- [音频预设对比](testing/AUDIO_PRESET_BENCHMARK.md)、[语义分段基线](testing/SEGMENTATION_BASELINE.md)、[两阶段翻译](testing/TWO_PHASE_TRANSLATION.md)。
- [HY Metal 文件验证](testing/HY_METAL.md)、[Mac 主线同步记录](testing/MACOS_MAIN_SYNC.md)、[VAD Float32 修复](testing/VAD_DTYPE_FIX.md)。

这些记录保留测试环境、失败与限制，不能把其中的旧测试通过数当作当前版本结果。可持续使用的 AMI、评分和暂停测试协议仍在 [testing](../testing/)；平台文件推理证据仍见 [Mac 文件测试](../MACOS_FILE_TESTS.md)。
