# 历史文档与迁移索引

历史记录保留当时的失败、环境、授权、配置与证据路径，停止承担当前规范；不把旧建议自动加入现行待办。私人原始证据通常仅在执行机器 `.work/`，有些旧实验文件已按授权删除，不能假定可重跑。

当前入口：[文档地图](../PROJECT_STRUCTURE.md)、[spec](../specs/README.md)、[验证索引](../VALIDATION.md)、[计划](../ROADMAP.md)。

近期阶段记录：[Mac UI 验证（2026-10-15—16）](testing/MAC_UI_20261016.md)。

## 归档分组

- `releases/`：各版本源码/安装包说明；未发布源码版本不等于已有安装包。
- `testing/`：阶段实测、平台适配、旧评分结果与原架构验证节。原始正文保留，只修正移动后的文件引用，并添加历史范围提示。
- `topics/`：本轮提炼前的分句、翻译、DSP、引擎与发行专题，保存选型/性能实验依据；当前契约分别进入 spec 和操作文档。
- [课程助手 v1.6](AgentScribe_软件开发设计文档_v1.6.md)：早期设计和候选方案，不再维护逐文件计划。

## 2026-10-15 文档核对与去向

以下保留首次整理（后提交为 `f37e351`）的迁移记录；其核对基线是 windows/08fe5d6 加当时既有修复，“本轮/非 main/未提交”等只对应记录时点，不是后续源码状态。下表覆盖原 39 篇项目 Markdown 和 1 份随包安装文本；技能、依赖锁和许可证原文不计入篇数。规范/操作核对调用入口、配置和相关测试；历史记录只核对范围、来源/引用，不声称重新运行历史 GPU、设备或云端测试。后续文档归属与维护规则以 [文档地图](../PROJECT_STRUCTURE.md#文档维护) 为准。

| 原文档 | 现行正文/保留位置 | 处理 |
| --- | --- | --- |
| `AGENTS.md` | [正文](../../AGENTS.md) | 重写/压缩，按职责分流；未变部分保留 |
| `README.md` | [正文](../../README.md) | 重写/压缩，按职责分流；未变部分保留 |
| `THIRD_PARTY_NOTICES.md` | [正文](../../THIRD_PARTY_NOTICES.md) | 更正退休组件和旧版本表述，完整保留许可正文 |
| `docs/ARCHITECTURE.md` | [正文](../ARCHITECTURE.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/AUDIO_PROCESSING.md` | [正文](../specs/recording.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/AgentScribe_软件开发设计文档.md` | [正文](../specs/course-materials.md) | 移除重复跳转，课程约定归入 spec |
| `docs/CONTEXT_TRANSLATION.md` | [正文](../specs/captions-translation.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/LLAMA_CPP.md` | [正文](../specs/models-runtime.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/MACOS_FILE_TESTS.md` | [正文](../VALIDATION.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/MACOS_SUPPORT.md` | [正文](../VALIDATION.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/PROJECT_STRUCTURE.md` | [正文](../PROJECT_STRUCTURE.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/RELEASE_v0.6.0-beta.1.md` | [正文](releases/RELEASE_v0.6.0-beta.1.md) | 冻结版本说明归档，发行列表另行只读核对 |
| `docs/RELEASE_v0.6.0-beta.2.md` | [正文](releases/RELEASE_v0.6.0-beta.2.md) | 冻结版本说明归档，发行列表另行只读核对 |
| `docs/RELEASE_v0.7.0.md` | [正文](releases/RELEASE_v0.7.0.md) | 冻结版本说明归档，发行列表另行只读核对 |
| `docs/RELEASE_v0.8.0.md` | [正文](releases/RELEASE_v0.8.0.md) | 冻结版本说明归档，发行列表另行只读核对 |
| `docs/RELEASING.md` | [正文](../RELEASING.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/SEMANTIC_SEGMENTATION.md` | [正文](../specs/captions-translation.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/UI_DESIGN.md` | [正文](../UI_DESIGN.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/VALIDATION.md` | [正文](../VALIDATION.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/WORKSPACE.md` | [正文](../WORKSPACE.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/archive/AgentScribe_软件开发设计文档_v1.6.md` | [正文](AgentScribe_软件开发设计文档_v1.6.md) | 保留历史内容，仅修正引用 |
| `docs/archive/README.md` | [正文](README.md) | 保留历史内容，仅修正引用 |
| `docs/archive/releases/RELEASE_v0.4.0.md` | [正文](releases/RELEASE_v0.4.0.md) | 保留历史内容，仅修正引用 |
| `docs/archive/releases/RELEASE_v0.5.0.md` | [正文](releases/RELEASE_v0.5.0.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/AUDIO_PRESET_BENCHMARK.md` | [正文](testing/AUDIO_PRESET_BENCHMARK.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/CLASSROOM_VALIDATION.md` | [正文](testing/CLASSROOM_VALIDATION.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/HY_METAL.md` | [正文](testing/HY_METAL.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/MACOS_MAIN_SYNC.md` | [正文](testing/MACOS_MAIN_SYNC.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/REVISION_PIPELINE.md` | [正文](testing/REVISION_PIPELINE.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/SEGMENTATION_BASELINE.md` | [正文](testing/SEGMENTATION_BASELINE.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/TWO_PHASE_TRANSLATION.md` | [正文](testing/TWO_PHASE_TRANSLATION.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/UI_EXPERIENCE.md` | [正文](testing/UI_EXPERIENCE.md) | 保留历史内容，仅修正引用 |
| `docs/archive/testing/VAD_DTYPE_FIX.md` | [正文](testing/VAD_DTYPE_FIX.md) | 保留历史内容，仅修正引用 |
| `docs/testing/AMI_BENCHMARK.md` | [正文](../testing/AMI_BENCHMARK.md) | 重写/压缩，按职责分流；未变部分保留 |
| `docs/testing/RECORDING_PAUSE.md` | [正文](../specs/recording.md) | 提炼当前要求/操作，历史证据归档 |
| `docs/testing/SCORING_SYSTEM.md` | [正文](../testing/SCORING_SYSTEM.md) | 重写/压缩，按职责分流；未变部分保留 |
| `media/README.md` | [正文](../../media/README.md) | 核对用途与来源后保留；不压缩许可/固定协议 |
| `packaging/macos/THIRD_PARTY.md` | [正文](../../packaging/macos/THIRD_PARTY.md) | 核对用途与来源后保留；不压缩许可/固定协议 |
| `packaging/macos/安装说明.txt` | [正文](../../packaging/macos/安装说明.txt) | 保留随包操作，更正历史测试与当前包验收的区别 |
| `tests/fixtures/course_formats/NOTICE.md` | [正文](../../tests/fixtures/course_formats/NOTICE.md) | 核对用途与来源后保留；不压缩许可/固定协议 |

原文 SHA256、逐篇去向、未改业务文件校验和本轮文档验证结果保存在执行机 `.work/docs-restructure-20261015/`；目录不随 Git 同步。
