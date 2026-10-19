# 项目与文档地图

## 从哪里读

| 要解决的问题 | 唯一正文 |
| --- | --- |
| 产品用途与下载 | [README](../README.md) |
| 安装、录音、课程助手与故障处理 | [WORKSPACE](WORKSPACE.md) |
| 基本开发规范、分支与授权边界 | [AGENTS](../AGENTS.md) |
| 文档归属、状态表达与维护方法 | [本文文档维护](#文档维护) |
| 产品边界与功能要求 | [specs](specs/README.md)；视觉交互见 [UI_DESIGN](UI_DESIGN.md) |
| 模块、执行流、数据与资源归属 | [ARCHITECTURE](ARCHITECTURE.md) |
| 诊断日志目录、隐私与问题反馈 | [WORKSPACE：诊断日志](WORKSPACE.md#诊断日志与问题反馈) |
| 诊断事件与延迟口径 | [ARCHITECTURE：诊断日志](ARCHITECTURE.md#诊断日志) |
| 如何选择和运行测试 | [TESTING](TESTING.md)；[AMI](testing/AMI_BENCHMARK.md)、[评分](testing/SCORING_SYSTEM.md) 是复用协议 |
| 当前优先级、未完成与已完成 | [ROADMAP](ROADMAP.md) |
| 哪些已有证据、证据的适用范围 | [VALIDATION](VALIDATION.md) |
| 构建、签名、发布和升级 | [RELEASING](RELEASING.md) |
| 历史方案、实验、版本及迁移去向 | [archive](archive/README.md) |
| 来源与许可 | [第三方说明](../THIRD_PARTY_NOTICES.md)、[Mac 发行许可](../packaging/macos/THIRD_PARTY.md)、[测试夹具](../tests/fixtures/course_formats/NOTICE.md) |

开工读 README 和本文，再按任务读取架构、对应 spec、测试或发行指南；不默认加载历史记录。AGENTS 只保留基本规范，专题细则在上表对应正文维护，不再建立平行开发手册。

## 文档维护

- 需求与行为进 spec，操作进 WORKSPACE，实现职责与当前方案进 ARCHITECTURE，测试方法进 TESTING，工作状态进 ROADMAP，实测结果进验证记录；其他位置只作必要摘要和链接。
- spec 是已接受的目标，不是全部当前能力的清单。当前策略与默认参数标明适用范围，精确值尽量引用代码、配置或锁；参数调整须有相关验证，迁移文字本身不改变功能、默认值或支持范围。
- 审查分别判断要求是否合理、代码是否符合、证据是否充分。合理但未实现的要求在 ROADMAP 列为待实现或缺陷并写验收条件；已有实现但缺实测才标已实现待验证；需要取舍或证据不足的建议标待评估。过时要求说明理由后修订，不能按代码现状掩盖缺陷，也不把全部历史设想变成承诺。
- 行为变化同批更新 spec 和相关验收，仅实现细节变化更新对应实现说明；没有信息变化不制造修改。保留异常路径、兼容约束和关键取舍，压缩重复解释与施工经过。
- 已实现、已验证、已发布分别表达。验证注明系统、代码范围及证据，记录方法见 TESTING；不能用静态检查、替身或旧测试结果替代当前实机验收。
- 移动、合并或改标题时修复文件与锚点引用。历史记录保留原时点的环境、失败、授权和适用范围，不改写成当前规范；临时授权不能泛化，仍有效的限制不能因整理丢失。

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

具体模块位置在架构维护，操作步骤在指南维护。旧专题的现行要求进入 spec，原始实验和决定可从归档检索；许可和固定测试协议保留各自正文，不因压缩文档而删减来源或条款。
