# 项目与文档地图

## 从哪里读

| 要解决的问题 | 唯一正文 |
| --- | --- |
| 产品用途与下载 | [README](../README.md) |
| 安装、录音、课程助手与故障处理 | [WORKSPACE](WORKSPACE.md) |
| 开发/分支约定、文档更新规则 | [AGENTS](../AGENTS.md) |
| 产品边界与功能要求 | [specs](specs/README.md)；视觉交互见 [UI_DESIGN](UI_DESIGN.md) |
| 模块、执行流、数据与资源归属 | [ARCHITECTURE](ARCHITECTURE.md) |
| 如何选择和运行测试 | [TESTING](TESTING.md)；[AMI](testing/AMI_BENCHMARK.md)、[评分](testing/SCORING_SYSTEM.md) 是复用协议 |
| 当前优先级、未完成与已完成 | [ROADMAP](ROADMAP.md) |
| 哪些已有证据、证据的适用范围 | [VALIDATION](VALIDATION.md) |
| 构建、签名、发布和升级 | [RELEASING](RELEASING.md) |
| 历史方案、实验、版本及迁移去向 | [archive](archive/README.md) |
| 来源与许可 | [第三方说明](../THIRD_PARTY_NOTICES.md)、[Mac 发行许可](../packaging/macos/THIRD_PARTY.md)、[测试夹具](../tests/fixtures/course_formats/NOTICE.md) |

开工读 README、本文、架构和任务对应 spec；其余按需，不默认加载历史记录。当前要求、计划和实测分别维护，跨文件只引用，不重复施工经过。

## 源码与数据

```text
linguaflow/            桌面、业务、模型及系统适配
  knowledge/          可选课程处理，独立于实时音频
scripts/              安装、构建、探针、文件回放和评测
tests/                回归与小型许可夹具
packaging/            平台锁、启动器、安装器、更新身份和许可
.github/workflows/    开发检查、发行草稿和更新订阅
docs/                 当前指南、规范、计划与证据入口
  specs/              长期行为约定
  testing/            可复用测试协议
  archive/            冻结历史记录
.runtime/             源码运行组件；不提交
.work/                缓存、临时工具、截图与本地原始证据；不提交
```

`runtime_paths.py` 统一桌面/WLK/MLX 解释器、资源及数据路径。默认录音在 Windows `%LOCALAPPDATA%/AgentScribe/录音`、Mac `~/Library/Application Support/AgentScribe/录音`；已有非空旧库/自选位置优先，不自动迁移或删除。安装态运行组件在用户数据 `runtime/`，源码态使用 `.runtime/` 并兼容旧 venv。

`.work/cache/` 放缓存，`.work/browser/` 放截图，`.work/reports/` 放临时验证摘要。既有 `.work/ami`、`.work/macwhinney`、`.work/revisions-short`、`.work/mac-file-tests` 等冻结证据按原路径保留，不当作普通缓存清理。私人 `media/` / `srt/`、录音、材料和模型不进 Git；安装包/摘要/构建清单进 Release。

具体模块位置只在架构维护，操作步骤只在指南维护。旧专题已提炼入 spec，其原始实验和决定可从归档检索，不再创建平行规范。
