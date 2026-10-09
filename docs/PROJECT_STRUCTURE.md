# 项目目录与文档入口

模块职责、依赖方向与异步契约集中在 [ARCHITECTURE](ARCHITECTURE.md)；本文件只说明目录、数据位置和文档归属。

```text
linguaflow/            桌面、业务规则与平台/模型适配
linguaflow/knowledge/  按需启用的课程处理，不进入实时识别主链
scripts/              生产准备入口、构建/探针与验证工具
.github/workflows/    开发检查及后续发行自动化
packaging/            平台构建锁、启动器与许可（目前已有 Mac 构建）
tests/                回归与小型许可夹具
docs/                 当前使用、架构、发行和证据
docs/testing/         仍使用的测试协议与回归说明
docs/archive/         不再更新的设计、版本与阶段实测
.work/                忽略提交的临时产物、缓存与验证证据
.runtime/             源码模式的运行组件与已验证环境
requirements-*.txt    推理环境约束；桌面依赖见 pyproject.toml
```

## 环境与用户数据

`runtime_paths.py` 统一解释器、资源、运行组件和用户数据位置。桌面 `.venv` 与 WLK/MLX 环境隔离，兼容已有 `.venv-wlk`、`.venv-mlx`；新环境在最终独立路径创建，验证后才切换 `active.json`，不得搬动 venv。源码组件使用 `.runtime/`，安装态组件使用用户数据 `runtime/`。包内资源只读，不能把冻结 EXE 当 Python 解释器。当前实现及升级边界见 [架构](ARCHITECTURE.md) 和 [发行流程](RELEASING.md)。

默认录音位于 Windows `%LOCALAPPDATA%/AgentScribe/录音` 或 Mac `~/Library/Application Support/AgentScribe/录音`。已有偏好及非空旧库优先，不自动搬迁或删除；清理项目前保护其中的旧录音。具体文件结构、课程副本/快照、来源数据库、模型缓存和迁移说明由 [WORKSPACE](WORKSPACE.md) 维护。

模型权重、虚拟环境、个人录音、课程副本、密钥和本机配置不进 Git。安装包及其摘要/构建清单放 GitHub Release，生产构建结果留在 `.work/packaging/`。

## 工作产物与证据

源码工作产物留在项目普通目录，不建立外部目录映射。标准 `.app` 内部所需相对链接属于平台产物，不替代源码目录。

- `.work/cache/pytest`、`.work/cache/ruff`：测试与静态检查缓存。
- `.work/cache/`、`.work/browser/`：临时脚本、日志、浏览器记录和截图。
- `.work/ami`、`.work/macwhinney`、`.work/revisions-short`：原始评测证据，冻结清单依赖这些位置，不改名、不自动清理。
- 2026-10-05 经用户授权删除了放弃的音频增强试验与重复处理音频；书面结果及原录音保留，部分历史清单仍可能指向已删除产物。

保留原有 `media/`、`srt/` 和评测证据。清理前检查引用与授权，不将用户数据当缓存。基准协议见 [AMI](testing/AMI_BENCHMARK.md)、[音频处理](archive/testing/AUDIO_PRESET_BENCHMARK.md)、[评分](testing/SCORING_SYSTEM.md)。

## 文档索引

| 要解决的问题 | 正文位置 |
| --- | --- |
| 产品能力、下载入口 | [README](../README.md) |
| 安装、首次使用、录音与课程助手 | [WORKSPACE](WORKSPACE.md) |
| 开发约束与授权边界 | [AGENTS](../AGENTS.md) |
| 模块归属、状态与资源规则 | [ARCHITECTURE](ARCHITECTURE.md) |
| 两端集成、打包、发布、自动升级 | [RELEASING](RELEASING.md) |
| 当前平台的实测与限制 | [Windows 记录](VALIDATION.md)、[Mac 记录](MACOS_SUPPORT.md)及其专题链接 |
| 识别分段、翻译模型和后台音频规则 | [语义分段](SEMANTIC_SEGMENTATION.md)、[上下文翻译](CONTEXT_TRANSLATION.md)、[llama.cpp](LLAMA_CPP.md)、[音频处理](AUDIO_PROCESSING.md) |
| 可复用的测试协议 | [AMI](testing/AMI_BENCHMARK.md)、[评分](testing/SCORING_SYSTEM.md)、[暂停](testing/RECORDING_PAUSE.md) |
| 已发行版本内容 | [GitHub Releases](https://github.com/Rand0MGG/agentscribe-local/releases)；旧源码版本说明见归档 |
| 旧设计、实验、修复及阶段验证 | [历史归档索引](archive/README.md) |

每项事实只在上述正文维护，其他文件链接引用。历史证据保留但不继续承担当前规范；新增工作不再向旧设计稿或目录说明追加一份实现描述。

日常入口保持六份：README、AGENTS、本文、ARCHITECTURE、WORKSPACE、RELEASING。专题文档按任务读取；测试数量、旧实验与开发过程留在证据或归档，不要求每次开发全部加载。

旧 `STREAMING_DESIGN.md`、`QWEN_STREAMING.md`、`OPEN_SOURCE_REVIEW.md` 的有效内容已归入 README、ARCHITECTURE 与第三方说明，删除过时的重复入口；旧内容仍可从 Git 历史回溯。不要重建同名说明重复维护。
