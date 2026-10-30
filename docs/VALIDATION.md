# 验证索引

仅记录当前可核对的证据与限制；测试规则见 [TESTING](TESTING.md)，功能缺口见 [ROADMAP](ROADMAP.md)。历史逐轮记录已移至 [验证归档](archive/testing/VALIDATION_THROUGH_20261030.md)，不把旧通过数或“本地未提交”当作当前状态。

## 2026-10-31 Mac v0.12.1 安装包

- 固定来源 `b808577`，最终 DMG **232,120,686 字节**，SHA256 `77d3029d1cb8462794d68615b0a60009717b70c5e784bcb421ebcafffde84a2e`；仅发布 Apple Silicon/macOS 15+，Windows 安装包保持 v0.11.0。应用 ad-hoc、未公证，DMG 使用原 Sparkle Ed25519 身份签署并复验。
- 99 项打包/更新回归、前端构建、最终映像校验及隔离无音频包探针通过。[原生升级验收](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41087381972) 用实际 v0.11.0 包验证篡改拒绝、断流、取消、正常升级和启动失败恢复，五项均通过，录音/模型/运行组件/偏好保留。录音及保存门禁采用模拟状态，不替代真实采集和长会话验收。
- [订阅部署](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41088689344) 成功，Mac stable/beta 均为 0.12.1；部署前后对比确认 Windows 两份 XML 及索引条目完全不变。
- [真实 HTTPS 订阅升级](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41089054072) 通过：未修改的 v0.11.0 客户端安装同一封存包并报告健康，测试数据保留。相同产品源码的 [CI](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41087326557) 12 项通过（包含全部 Mac 项目）；Windows Python 3.11 的双进程日志归档用例等待 ready 超时，另行排查；此前一轮还出现旧锁并发回收失败，不宣称全矩阵通过。

## 2026-10-30 Mac 回听初始化阻塞

- 远程诊断确认点击命中且 `playback.seek` 已发出，但初始化未返回、媒体未加载。[Mac 调用栈](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41080209950/job/124149709266) 明确停在 `PlaybackController.load → HTTPServer.server_bind → socket.getfqdn`；这是产品后台线程被反向主机名查询阻塞，与此前修复的点击计时问题独立。
- 本地回环媒体服务改为直接绑定数字地址，取消不必要的反向查询。新增 P2 回归在解析器不可用时验证实际 HTTP 文件读取、定位与释放；修复前失败，修复后通过，原随机令牌、范围读取和旧回执拒绝保持不变。没有延长交互测试的 10 秒等待或绕过播放流程。
- macOS 回听控制器、媒体流、桌面服务与 Qt-free 后台回归 **59 passed**，完整 Electron `test:interaction`、`test:audio-adapter`、Ruff 和差异格式检查通过。`f4787a2` 的 [13 项远程 CI](https://github.com/Rand0MGG/agentscribe-local/actions/runs/41081727663) 全部通过；Mac 后台播放请求 24ms 返回，随后收到模拟媒体播放回执。隔离合成录音与设备替身，无原生音频导入；证据位于 `.work/reports/ci-analysis-20261030/`，不替代真实音频设备验收。

## 2026-10-30 回听点击计时与侧栏动画测试

- 基于 `e6da89e`：原文和译文的短按时长改用输入事件时间，排除界面处理延迟。正式交互探针加入真实浏览器单击及 500ms 主线程阻塞；修复前在等待回听开始处超时，修复后通过，长按、拖选、双击不定位的保护仍有效。
- 旧 Qt 动画测试改为同步推进中间帧，验证收拢、当前位置反向展开及减少动态效果；最终状态仍等待真实事件循环完成。该纯动画用例按 P3 分级，不再用采样次数推断动画尚未结束，产品动画未修改。
- macOS：侧栏回归 **17 passed**；Electron 构建、完整 `test:interaction`、Ruff 与差异格式检查通过。使用隔离库和模拟媒体，无原生音频导入尝试，未播放、采集或改音量。证据在 `.work/reports/ci-analysis-20261030/` 和 `output/playwright/interaction-fixes/`。
- 以上证明点击计时缺陷与本地修复；后续 CI 的独立回听初始化阻塞见上节。双进程日志归档的远程失败根因仍未确定，本轮未改归档实现或其测试。

## 2026-10-30 课程客户端测试的 PID 发布竞态

- `d7e210b` 的 Windows Python 3.12 CI 在测试准备阶段读到空 PID；测试此前仅等待文件存在。测试辅助进程改为同目录临时文件写完并关闭后原子发布 PID，等待阶段检查辅助进程退出及超时，失败清理覆盖 PID 尚未取得的阶段；产品进程清理代码未修改。
- 在原测试四种关闭/取消及启动器退出组合中，以握手明确暂停在文件已创建但内容未写入的阶段，断言此时最终 PID 文件不可见。旧直接写入方式在该断言失败；原子发布后 `tests/test_knowledge_client.py` **5 passed**（Windows 11 / Python 3.12.8），包括原有后代退出、通信线程/管道回收、重复关闭和失败重试检查。无原生音频导入尝试，Ruff 与差异格式检查通过。
- 这是本地测试修复验证，未证明远程 CI 已通过；macOS 的 Electron 回听交互超时仍是独立待查问题。

## 2026-10-30 Windows 首次打开录音的 IPC 阻塞修复

- 基于 `43cdf1f`：共享后台在 stdin 协议读线程启动前初始化 NumPy。新增真实管道子进程回归保持输入打开且空闲，验证首次打开合成 WAV 的时长、正常关闭和原件不变；修复前在打开回执处 15 秒超时，修复后通过。
- Windows 11 / Python 3.12.8：后台、Qt-free、回听控制器与启动相关回归 **51 passed、1 skipped**，跳过项为 macOS Cocoa 事件循环；无原生音频导入尝试。Ruff 与差异格式检查通过。
- 现有 `npm test`、`test:chain`、`test:interaction`、`test:audio-adapter` 均通过，包括首次 WAV 时长、650 条字幕定位与模拟播放状态。使用隔离库及设备替身，未访问用户录音或真实音频设备。
- 证据由探针保存在 `output/playwright/`；此前最小诊断脚本在 `.work/reports/ci-timeout/`。本记录仅证明本地 Windows 修复验证，macOS、远程 CI 和安装包未由本轮验证，不能据此宣布 Mac 交互超时已修复。

## 2026-10-30 Qwen 原声窗口与分批输入

- 连续原声、参考点释放、窗口缓冲带、每轮新增 1～10 秒及长静音等待规则见 [字幕 spec](specs/captions-translation.md)。多轮文字确认、SaT 和翻译策略不变。
- 行为改动后 macOS 完整无音频回归 **1307 passed、4 skipped，302.72 秒**；跳过项仅 Windows 专属。随后同步源码版本 `0.12.0`，版本一致性检查及打包/更新相关 63 项通过。Ruff、差异格式与文档链接通过，无原生音频导入尝试。
- 合成 PCM 逐样本验证百秒积压、8/25/30/40 秒窗口、25/30 秒长静音阈值、保护音、异常恢复和尾音；实际安装的 WLK 队列验证 4/100 秒输入、暂停/恢复、EOF 与修订发布。ASR 使用替身，不能代表模型质量或追赶速度。
- 分批修改前，问题录音 325–378 秒、389–436.1 秒经真实 Silero 和 Qwen 1.7B 4-bit/MLX 完成 89 次文件解码，未复现整屏重复单词或循环报数，仍有可疑错词。三份录音的既有 VAD 标注另用于窗口调度模拟；这些历史结果不替代新策略的真实模型、并行翻译或长会话验收。
- 本地证据：`.work/reports/qwen-admission-20261030/`、`.work/reports/qwen-window-implementation-20261030/`。未播放、采集、改音量或修改原录音；Windows 实机及新安装包仍需独立验收。

## 2026-10-30 测试审计与日志归档

- 全仓核对 pytest 收集、等级标记和 CI 入口。补齐新测试的函数级分级，撤去混合文件统一 P1；数据/隐私保护保留 P0，纯日志归档功能按 P2。收集阶段拒绝漏标、重复及统一继承标记，默认 P0→P1→P2→P3 全量执行，`-m` 不能绕过检查。
- 去掉 Python 对同一 Node 音频适配器脚本的重复包装；保留独立 Node 入口和实际 WAV/HTTP/原件保护。活跃日志保护合入实际轮转测试；UI 只保留代表格式的快照接线，三格式 Unicode/草稿过滤集中到底层；防覆盖独立 P0，模型检查等待真实状态。
- 补强清理前后文件字节、自动闲置释放、真实无音频拒绝及后代继承；修复文本模型探针在关闭后读取已清空 owner 的过时写法。下载测试仅补齐进度条模拟，产品下载及识别/翻译逻辑不变。
- 日志保留 ASR 确认、SaT 边界、翻译任务与发布关联；去除无变化轮询及重复字段。每约 8 MiB 无损归档，压缩历史共用 128 MiB，不限每进程文件数/14 天，活跃文件不计入；失败保留原件，详见 [使用指南](WORKSPACE.md#诊断日志与问题反馈)。
- macOS 完整无音频回归 **1278 passed、4 skipped，280.06 秒**；跳过项仅限 Windows venv 重定向、Job Object、安装器编译和 8.3 临时路径。1282 个收集项均有唯一函数级标记并按等级排序：P0 333、P1 713、P2 230、P3 6。无原生音频导入尝试。首轮暴露的两项临时 CI 夹具漏标已修复，最终回归包含该门禁。
- Ruff、差异格式、文档相对路径及 Electron 构建通过；Electron `npm test`、`test:chain`、`test:interaction`、`test:audio-adapter` 均通过。旧 Qt 完成/释放用例改为实际工作流归属检查和有期限的终态等待，未更改产品接线。
- 本地证据位于 `.work/reports/test-audit-*20261030*`；不操作现有录音/日志，不访问音频设备，原生窗口仅使用隔离库和自有测试进程。Windows 与本次提交的远程 CI 结果需独立核对。

## 日志行为与容量证据

此前相关回归 222 项通过，最终存储/下载 44 项复测通过。默认 8 MiB 轮转探针写入 35,365 条元数据、21,668,020 字节，三个归档解压拼接的 SHA-256 与输入一致；两次轮转约 81/64 ms。启用日志的同输入模拟对照中，4 份源快照、6 条字幕变化、2 次翻译调用及发布结果与 `d5cb5ac` 一致。它们不证明真实模型质量或 Windows 性能；旧 32 MiB / 92 分钟保留估算已失效。

## 已合入基线与独立验收边界

`main` 的 `cee7b86` 修复 CI Python 路径与 Electron 前置准备，`d5cb5ac` 修复 Windows GUI 子进程 stdin 提前 EOF 导致启动即退出。本轮在这些提交之上保留日志与测试改动；先前 Windows 本地证据及其失败项见 [归档](archive/testing/VALIDATION_THROUGH_20261030.md)。

本地源码测试、GitHub CI、真实设备/GPU、签名安装包及原生升级分别验收。上传源码不等于发行，不创建安装包、标签、Release 或更新订阅。
