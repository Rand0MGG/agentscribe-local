# 验证索引

本页记录已有什么证据及其限制；不是全平台支持声明。方法见 [TESTING](TESTING.md)，未完成验收统一在 [ROADMAP](ROADMAP.md)。历史记录中的“当前/本轮/未提交”只对应各自时点。

## 最近可核对的证据

2026-10-16 此前 Mac UI 批次基于 `e82b957`，本次 Windows 补验基于 `92b8ed2` 加本地修改；源码同步与安装包发行分别进行。验证使用模拟设备/媒体，零音频访问尝试，只覆盖注明的平台与输入，不替代真实音频、GPU 或安装升级验收。历史轮次通过数不累加。

| 证据 | 已证明 | 范围与限制 |
| --- | --- | --- |
| 2026-10-16 更新状态修复阶段 | 本地完整无音频 1065 passed / 2 Windows 跳过；真实 Sparkle 的后台 404→手动重试→取消通过；渠道 18 项、更新/保存 43 项及最终 UI 9 项通过 | `.work/reports/update-e2e-20261016/`；完整运行后补了渠道与按钮反馈，定向补验通过。真实旧包→0.9.2、原密钥签名及生产订阅仍待本轮后续验收，未据此声明应用内更新可用 |
| 2026-10-16 v0.9.1 Mac DMG | 固定来源 `2ce4be5`；GitHub Mac 回归 1033 passed / 23 可选组件或平台跳过，Ruff、最终 DMG 校验及只读挂载包探针通过；上传后三个附件摘要核对一致 | [运行 38872564024](https://github.com/Rand0MGG/agentscribe-local/actions/runs/38872564024)，预览版已发布。312126171 字节，SHA256 以发行清单为准；ad-hoc、未公证，未验真实录音/旧包升级，未推进自动更新。保留本地完整回归及上传故障记录 `.work/reports/startup-polish-20261016/` |
| 2026-10-16 Mac 首次下载与界面边界 | 完整无音频 1060 passed / 2 Windows 专项跳过；原生相关 36 项经修复/补验覆盖通过，63 张预览与明暗弹层像素检查通过，Ruff/差异与本地文档链接检查通过 | `b7a6248` 加本地修改；下载用模拟准备线程，验证引导跳转、通知关闭不取消/重弹、顶部渐隐、菜单阴影及目录失效恢复。失败与补验日志保留于 `.work/reports/startup-polish-20261016/`；零音频访问，未验真实下载、Windows 原生或正式安装升级，未构建/推送/发布 |
| 2026-10-16 Windows 长许可证路径封装 | Inno 6.7.1 对 300 字符许可证源路径可复现失败，扩展路径前缀同样不支持；固定便携 Inno 7.1.0 用真实安装脚本编译通过，封装/更新回归 57 passed / 1 符号链接权限跳过 | 编译夹具未执行；完整 Windows 6fc4308 载荷已通过包探针，旧编译器随后失败。构建入口改用官方 SHA256 固定的便携 Inno 7；日志 `.work/reports/inno-long-source-probe/`、`v090-inno7-tests.xml`。最终完整安装包以新 Actions 运行及清单为准 |
| 2026-10-16 Windows 临时渲染短名称 | 真实 8.3 临时路径回归修前失败、修后通过；课件格式/视觉/UI 定向 60 passed，Ruff/差异检查通过 | Windows 11/x64、Python 3.12.8；CI `c2a5419` 的 Windows SDK/渲染失败源于 `RUNNER~1` 与展开用户名比较不一致。仅在 Windows 临时渲染入口展开路径，归属校验与 Mac 分支未改；证据 `.work/reports/v090-temp-path-before.xml`、`v090-temp-path-after.xml`。0.9.0 最终构建结果以对应 Actions/安装包清单为准 |
| 2026-10-16 空库默认文件夹与弹层统一 | Windows 完整无音频 1031 passed / 1 failed / 25 skipped；新增 5 项全过，Ruff/差异检查通过。原生定向 20 passed / 1 悬停失败，该悬停用例单独复跑通过；12 张明暗弹层截图检查 | `92b8ed2` 加本地修改；Windows 11/x64、Python 3.12.8、PySide6 6.11.2。全量唯一失败与改前一致：offscreen 回放条宽 385，断言 ≥400；原生悬停批次鼠标进入事件未到达，根因未确认。日志 `.work/reports/default-folders-popups-*.xml`，截图 `.work/browser/popup-after/`。Cocoa 外围玻璃反馈待 Mac 实机复核，未提交/推送/发布 |
| 2026-10-16 提交前回归 | 1052 个用例已覆盖：完整运行 1034 passed，18 项因图形会话/本机端口受限失败后补验全过；Ruff 与文档引用检查通过 | Mac arm64 / Python 3.12.14；两次运行均保留，证据 `.work/reports/github-submit-20261016/`。未构建或发布安装包 |
| 2026-10-15—16 Mac 界面与即时原文 | 阶段完整无音频回归最高 1045 passed，后续界面、预览、状态专项通过；原生截图覆盖明暗主题及窄窗口 | `e82b957` 加本地修改；后续更改未重跑全量。阶段明细见 [归档](archive/testing/MAC_UI_20261016.md)，日志/截图在其中列出的 `.work/reports/` |
| 2026-10-16 聆听中改名与库管理 | 68 项定向、2 项截图补验通过；持续写入、删除恢复、目录保护和冲突保留通过 | 模拟会话、真实临时文件；证据 `.work/reports/live-library-20261016/`；聆听空态随后修正，见下一行 |
| 2026-10-16 状态提示与全部删除 | 状态/预览定向 13 项、删除定向 27 项通过；确认取消、范围及共享资料保护通过 | 证据 `.work/reports/listening-state-20261016/`、`delete-all-20261016/`；原生 Cocoa 与隔离库，非真实采集 |
| 2026-10-15 主界面与小岛 | Windows 完整无音频 988 passed / 25 skipped；补充空来源刷新、键盘顺序与文字尺寸后，Python 3.11/3.12/3.13 定向各 51 passed / 1 skipped，3.12 另补键盘断言 1 passed；零音频导入尝试，Ruff 通过 | `046f30f` 上本地 UI 修改；PySide6 分别 6.12.0/6.11.2/6.12.0。原生 Windows 150% 示例图覆盖浅深主题、空状态、录音/回放、长名称和窄窗口；不是 Mac Cocoa、真实录音或模型验收 |
| 2026-10-14 Windows 退出/深路径修复 | Python 3.11.15、3.12.8、3.13.9 的完整无音频各 984 passed / 25 skipped，零音频导入尝试；深 PNG/HTML/DOCX、绘制中关闭及资源日志检查 | Windows 11/x64；PySide6 分别 6.12.0、6.11.2、6.12.0。25 跳过涉及 Mac 专属、符号链接权限和未配置的原生编译器；非 Mac/设备/GPU/安装升级验收 |
| 2026-10-14 打包修复 | 完整无音频 943/23，Inno 以文本假载荷原生编译，模拟两端封存探针/清理边界 | 不执行假安装器，不证明真实 Windows 载荷可安装；后来被上一行源码回归补充 |
| Mac GPU 文件链路 | MLX 识别、SaT CPU、HY Q4_K_M/Metal 真实输出与保存审计；包含 101 秒合成英文及短课堂片段 | 历史 M2/8GB/macOS 26.6.2/Python 3.12.14，具体配置以记录为准；不是中文、完整长课堂、真实采集或当前源码重新验收 |
| Mac 系统声音与 UI | 历史短系统采集、暂停/继续、切源和 WAV 保存，以及原生界面检查 | 采集探针使用模拟推理，不能推出 GPU 联动或安装态权限通过 |
| Mac 隔离更新/恢复 | 隔离应用的实际 Sparkle 下载、安装、重启及故障旧版恢复 | 非正式系统签名包，不替代 Windows 原生或生产旧包升级 |

小岛修改日志位于 `.work/reports/ui-implementation-20261015/`：`full-final312.log`、`final-target311.log`、`final-target312.log`、`final-target313.log` 和 `empty-picker-final312.log`。完整回归后只补了设备为空时的恢复入口、键盘顺序和语言按钮尺寸，并完成上述定向检查；完整回归的跳过原因保留在日志。原生图位于 `.work/browser/ui-final-20261015/`，使用隔离库、示例字幕/设备/音量，不采集或播放。

2026-10-14 退出/深路径修复的命令为各解释器执行 `scripts/test_no_audio.py -v -rs --tb=short`；本地日志 `.work/reports/runtime-integrity-fixes-20261014/final311.log`、`final312.log`、`final313.log`，结构化摘要为同目录 `validated-results.json`。文档整理时重新核对了日志，不是重新运行模型或全量测试。该轮源码基线是 `08fe5d6` 加本地修复，代码随后提交为 `f84b388`；推送/合并不增加平台验收或发行证据。

## 详细证据

- [Windows/共享验证记录](archive/testing/VALIDATION_20261015.md)：各轮命令、失败与修复、平台边界及本地证据路径；末节保留三 Python 最终回归。
- [Mac 适配记录](archive/testing/MACOS_SUPPORT_20261011.md)：原生 UI、系统声音、短探针及资源限制。
- [Mac 文件推理](archive/testing/MACOS_FILE_TESTS_20261006.md)：CPU/MPS/MLX 的失败与成功、授权/资源边界、101 秒与课堂片段。
- [历史专题与发行](archive/README.md)：分句/翻译/DSP、基准方法的旧结果、版本说明。

原始 `.work/` 证据通常只在执行机器，不随 Git 同步；链接记录存在不保证另一台机器保有原始音频或日志。数据集或机器转写的参考可信度由 [评分协议](testing/SCORING_SYSTEM.md) 分别声明，不把 WER、词差异、句界或人工可读性混为一个指标。

上述回归和历史实测只覆盖各自断言与输入，不能证明全部 spec 已实现。文档与源码核对发现的保存锁、翻译截断、课程来源、模型检查及原生更新等实现差距，统一在 [ROADMAP](ROADMAP.md#实现缺口) 跟踪。

## 文档核对

2026-10-15 在 Windows、源码 `f37e351` 上完成文档修订与交叉审查：精简 AGENTS 并核对细则承接，区分 spec 目标、当前策略、实现缺口和待验证范围。61 份 Markdown 的 320 个本地引用（含 41 个标题锚点）、5 段 PowerShell 示例语法与 `git diff --check` 通过；示例未执行。历史正文、许可、业务代码、依赖与版本均未修改，没有重新运行应用、模型、音频、云端或生产升级验收。

本地检查摘要在 `.work/reports/docs-improvement-20261015/validation.json`，示例语法结果在同目录 `powershell-examples.json`；与其他 `.work/` 证据一样不随 Git 同步。检查只证明可见文件、标题引用、修改范围与示例语法，不证明示例已在相应设备执行。

## 已发布产物

2026-10-16 已核对 [v0.9.1 预览版](https://github.com/Rand0MGG/agentscribe-local/releases/tag/v0.9.1)：提供 Mac arm64 DMG、构建清单和 SHA256，三个附件均已上传并核对摘要；临时签名、未公证，本次未提供 Windows 包或推进自动更新。其他历史版本及具体产物以 [发行页](https://github.com/Rand0MGG/agentscribe-local/releases) 为准。
