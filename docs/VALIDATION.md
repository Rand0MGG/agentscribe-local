# 验证索引

本页记录已有什么证据及其限制；不是全平台支持声明。方法见 [TESTING](TESTING.md)，未完成验收统一在 [ROADMAP](ROADMAP.md)。历史记录中的“当前/本轮/未提交”只对应各自时点。

## 最近可核对的证据

2026-10-26 **成品退出占用根因修复**（基于 `22e979a`，尚未发行）：

- 该提交远程 13 项源码检查与两端候选构建均成功；进一步在本机以隔离无音频目录运行封存 Mac DMG，`lsof` 发现包内材质 Python 进程仍短暂占用只读映像。主进程现在取消并等待自有系统交互/材质辅助进程实际关闭，停止关闭期间的新材质工作，并等待后台进程的真实 `close`，保留保存失败与取消关闭路径。撤去上一轮临时强制卸载回退，成品映像必须正常卸载。
- 新的退出检查进一步复现原后台在解释器收尾时因守护线程持有 stdin 锁而 `SIGABRT`。后台发出持久化关闭回执后，Electron 结束输入管道，Python 等待读取线程释放后再完成解释器退出；不提前终止保存或录音后台。悬浮字幕关闭探针也改为等待实际窗口关闭事件后再枚举主窗口，避免访问已销毁的 WebContents。
- 真实无设备子进程检查覆盖完成、取消、取消后重用与最终关闭；原生 Electron 基础探针通过，后台退出码为 0。相关后台、打包、签名和更新无音频回归 **95 passed / 3.09s**，零原生音频导入尝试；日志 `.work/reports/release-011-owned-{base,python}.log`。后续两端最终包及原生升级另行验收，未建立发行标签或推进订阅。
- 同一工作区 **11 组全链路、26 组交互及 Electron→Qt→Electron 原生往返全部通过**，保留录音/字幕/库和关闭取消行为；日志 `.work/reports/release-011-owned-{chain,interaction,switch}.log`。Ruff 与差异检查通过，不访问真实设备或用户录音。

2026-10-26 **持续字幕积压下自动笔记调度修复与只读 CI 映像清理**（基于 `364b760`，候选尚未发行）：

- Code checks `40320061656` 的 Windows/Python 3.12 在自动笔记持续输入用例失败；追踪真实 worker 发现已有消息积压时，`Queue.get()` 和本地命令均可同步完成，主循环持续处理输入而不调度已建立的笔记 task。新增初始消息积压和慢持久化场景，两种管道编码修前 **2 failed、2 passed / 18.92s**；真实事件循环每条消息后 `await asyncio.sleep(0)` 让出调度，不增加固定处理延迟或更改自动笔记间隔/许可。测试先等待实际打开与许可回执，再保留 8 秒功能期限，避免将冷启动混入笔记调度断言。
- 修后课程 worker/API/适配相关 **60 passed / 8.07s**；最终相关课程、打包、签名与更新回归 **146 passed / 8.90s**，零原生音频导入尝试。证据 `.work/reports/release-011-notes-backlog-{before,after}.log`、`release-011-final-regressions.log`；Ruff 与差异检查通过。
- 候选构建 `40320069659` 的 Mac 成品 Electron 基础流程、正常进程退出与已记录自有辅助进程退出均成功，但 `hdiutil detach` 返回资源忙。只读探针映像在一次性 CI 中对该特定返回码使用清理回退，其他错误仍失败；用户机器不使用强制回退，且不强停应用进程。新增三项保护回归，不能把此处只读映像清理等同于生产升级或录音验收。
- 已封存的 `364b760` 两端候选仅留作诊断；自动笔记修复将纳入新的同源构建，未建立发行标签、上传 Release 或推进订阅。

2026-10-26 **成品双界面关闭验收统一**（基于 `3db2989`，未固定发行标签）：

- [40312490863](https://github.com/Rand0MGG/agentscribe-local/actions/runs/40312490863) 的 13 项源码检查全部成功。[40312494041](https://github.com/Rand0MGG/agentscribe-local/actions/runs/40312494041) 的 Windows 安装包完成完整回归、封装和实际安装后的 Qt/Electron 探针；Mac DMG 已通过封装和 Qt 成品探针，但 Electron 基础探针在最后等待关闭回执时触发与全链路相同的上下文销毁竞态，随后卸载映像报资源忙。未将该失败候选发布或推进订阅。
- 基础、全链路、交互及对照探针统一使用实际退出检查，保留关闭 IPC，精确接受正常销毁的传输结果，要求退出码 0、无信号和页面关闭；以 PID/创建时间限定范围等待自有辅助进程退出，不强停任何进程。基础探针正常及 250ms 回执延迟检查、11 组全链路、26 组交互及双向切换均通过；日志 `.work/reports/release-011-{base-exit,base-exit-delay,chain-exit,interaction-exit-final,switch-exit-final}.log`。
- 同次交互回归还暴露“打开目录”检查在实际 IPC 到达主进程前读取空记录，修为有期限等待真实目录打开调用，仍核对只调用一次、目标目录正确与录音身份保留；未删断言或添加固定通过延时。
- 新候选工作流即使后续探针失败也保留已封存文件用于诊断，失败运行仍不能进入发行验收。原生升级工作流支持读取同一成功构建的产物和公开签名，在建立不可变标签前完成候选验收；正式 HTTPS 验收仍要求已发布版本。

2026-10-26 **0.11.0 发行前关闭测试与本机双平台签名准备**（基于 `bd5a193`，尚未固定发行标签）：

- `40309719690` 的 Mac Electron job 在恢复录音目录成功后关闭窗口时，渲染上下文早于关闭 IPC 回执销毁，`chain-probe.cjs` 将正常关闭误判为测试失败。仅在测试中延迟回执 250ms 可复现相同错误；关闭检查改为等待实际应用退出，只接受该特定传输关闭结果，并额外断言进程退出码为 0、无终止信号及页面已关闭，其他异常仍失败。证据 `.work/reports/release-011-close-{before,after}.log`。
- 用户提示后确认两端原更新签名账户均在本机钥匙串，分别以官方工具读取公钥，匹配固定 Sparkle/WinSparkle 信任；未导出私钥。签名器扩展为在 Mac 上按目标平台选择清单字段与公钥，保留封存摘要/字节数、干净来源、目标身份、最终验签和签名期间防变更检查。26 项签名/更新与 Electron 包装回归通过，包含两端不同信任、错公钥拒绝、篡改拒绝；日志 `.work/reports/release-011-signing-tests.log`。
- 原候选构建 `40309839001` 在发行标签建立前中止，后续从补齐上述修改的同一固定提交重新构建两端，不复用旧源码候选。Ed25519 更新签名不等于 Apple Developer ID/公证或 Windows Authenticode；两端原生升级和订阅发布仍须实际验收。
- 正常及注入关闭回执延迟的 **11 组全链路**均通过；日志 `.work/reports/release-011-chain-final.log`、`release-011-close-after.log`。最终打包/签名/更新回归 **83 项通过**，含禁止在用户机器运行 Windows 原生升级探针的两项保护；日志 `.work/reports/release-011-final-tests.log`。新增两端原生升级工作流及 Windows WinSparkle/Inno 探针，静态检查通过，原生执行仍待候选包完成后进行；不得据此提前发布 Windows 订阅。
- 复核双界面构建入口时补齐解释器传递：前端调色板由打包进程的已准备 Python 生成，不依赖候选运行器上不存在的开发 `.venv`；复制回归同时核对传入的解释器。发行标签建立前重新固定此构建修正，旧候选不进入发行。

2026-10-26 **0.11.0 双平台安装包准备**（基于 `d646009`，本地 `mac`，构建/签名/发行/订阅尚未完成）：

- `d646009` 的远程 13 项 Code checks 全部成功。按用户要求将 `0.10.2` 升为次版本 `0.11.0`，同步 Python、Electron 元数据与 Mac 包内说明，不改旧标签或已发布附件。
- 包装器原先只复制三个固定 Electron 主进程文件，遗漏 `main.cjs` 引用的 `window-layout.cjs`。新增真实文件复制回归在修前因缺模块失败；改为复制 Git 跟踪的 `desktop/electron/*.cjs`，同时检查未跟踪本机文件不进入载荷、复制字节与前端清单一致。无音频打包/更新回归 **79 passed / 1.32s**，Ruff、版本一致性、工作流 YAML 与差异检查通过；日志 `.work/reports/release-011-packaging-{before,tests}.log`。
- 手动候选工作流新增双界面选项，两端仍使用同一固定提交。最终 DMG 或实际安装后的独立 Windows 目录需额外通过包内 Electron 基础流程；这一步不冒充真实旧版自动升级验收。
- 当前 GitHub 仓库及 `release-build` 环境均未配置更新签名 Secret；既有 Mac Sparkle 账户元数据可查，本机没有有效 Apple Developer ID 身份。Windows 需原 `WINDOWS_UPDATE_PRIVATE_KEY`，不能更换已固定公钥或把未签名包加入订阅。后续构建、签名和验收以对应实际证据为准。

2026-10-26 **Windows Electron CI 动画反向取样竞态修复**（基于 `9cfb2e4`，本地 `mac`，未提交/推送）：

- GitHub Actions [40304987421](https://github.com/Rand0MGG/agentscribe-local/actions/runs/40304987421) 为 12 项成功、1 项失败。Windows Electron job 的构建、基础探针与 11 组全链路均成功，交互脚本在 `parity-checks.cjs` 的 `assert(reversing>36&&reversing<180)` 失败，后续双向切换未执行；Mac Electron 与两端 Python 3.11–3.13 回归均成功。原始 Windows 日志 `.work/reports/windows-electron-ci-40304987421.log`。
- 原测试先检查历史帧中出现中间宽度，再跨进程读取当前宽度并点击展开。给测试端这两步之间注入 250ms 调度延迟，可在本机重现读取已完成的 36px 而误报；没有修改应用或增加动画时长。首轮本机探针在到达目标前遇到独立后台请求超时，日志 `sidebar-ci-delay-before-20261026.log` 保留；复跑命中目标断言，证据 `.work/reports/sidebar-ci-delay-before-repeat-20261026.log`。
- 改为在同一渲染帧读取真实中间宽度并激活反向动作；设置往返动画的同类读取与反向也一并放入渲染端。保留中间帧、36/180px 最终宽度、收起状态、连续返回及减少动态效果断言，未改应用逻辑、依赖或增加超时。测试方法同步 TESTING。
- 同样注入 250ms 测试端延迟后，完整 **26 组原生 Electron 交互检查通过**；再仅在隔离窗口中禁用侧栏 CSS 动画，新检查按预期以 `No intermediate sidebar width` 失败，连续读到 36px，确认没有把缺失动画判为通过。证据 `.work/reports/sidebar-ci-{delay-after,missing-animation}-20261026.log`，临时注入器仅保留于 `.work/reports/`，不进入 Git。
- 不带任何注入的正式 `npm run test:interaction` 同样 **26 组通过**，零原生音频访问；日志 `.work/reports/sidebar-ci-interaction-final-20261026.log`。两处 JavaScript 语法与差异检查通过；应用代码未变，未重复完整 Python 或安装包验证。
- 当前本机验证为 macOS 原生隔离窗口和无音频防护，不代表已复验 Windows。远程修复后 CI、安装包、真实设备/模型尚未验收；本条提交前的记录不等于推送或发行完成。

2026-10-26 **全面回归与四处边界缺陷修复**（`mac`，基于 `d184149` 加本地改动，未提交/推送）：

- 覆盖静态审查、完整无音频回归、Qt/Electron 关键工作区与本机原生基础/交互/全链路/前端切换探针。审查重点为当前侧栏、动画、跨文件夹导航和菜单调整，同时通过完整 Python 套件检查保存、取消、恢复、课程、模型编排、路径与进程释放。
- 已复现并修复四处缺陷：① Qt 收起后再展开，当前录音的选中高亮留在顶层文件夹；保存并恢复选择标识，收起期间显式选择其他文件夹则保留新选择。② 文件夹较多时纵向滚动条占用 36px 图标栏，导致图标位置与命中区挤窄；两端收起栏隐藏占宽滚动条，保留滚轮、键盘与程序滚动，新增 30 个文件夹检查最后一项可达。③ Qt 录音中的 final 字幕更新重新启用普通导出；集中复用空闲/定稿资格，导出入口也在打开文件对话框前校验。④ 仅有空白或未确认 ASR/分句的内容时，菜单可点但格式化器输出无正文；Qt 复用 `source_is_final`，Electron 按相同字段及有效预览范围判断，SRT/TXT/Markdown 一致禁用，全部文字备份仍可保留草稿。
- 三个首批新增回归修前 **3 failed / 3.44s**；定稿资格新增四组修前 **3 failed、1 passed / 4.53s**（原先已拒绝普通 draft，但遗漏另外三类）。修后相关侧栏、录音页、后台导出与格式回归 **34 passed / 18.60s**；未删断言、未增加超时。日志 `.work/reports/comprehensive-{boundaries-before,boundaries-after,export-eligibility-before,final-targeted}-20261026.log`。
- 最终工作区完整无音频回归 **1175 passed / 5 skipped / 374.41s**，零原生音频导入尝试。5 项跳过为 4 项原生 Windows 专项（venv redirector、8.3 临时路径、Job Object、安装器编译器）及本机未缓存的固定 Sparkle 构建依赖，非产品断言失败。该结果包含全部新增回归与最后的导出资格修复。
- Electron 最终构建、原生基础探针、**26 组交互**、**11 组全链路**与 Electron→Qt→Electron 往返均通过；包括真实临时 SRT 文件导出、保存/恢复、导出队列、准备取消/失败重试、删除批量恢复、启动目录失败恢复和跨前端保留录音/字幕/库。设备、模型和 HTTP 外部边界为现有离线夹具，应用/IPC/文件读写及进程生命周期走真实实现；零原生音频导入尝试。日志 `.work/reports/comprehensive-{build,base,interaction,chain,switch}-20261026.log`。
- Ruff、14 个 Electron/探针 JavaScript 脚本语法及差异检查通过。环境 macOS 26.6.2 arm64 / Python 3.12.14 / PySide6 6.11.2 / NumPy 2.5.3；完整测试原始记录 `.work/reports/comprehensive-final-full-20261026.log`，早期扫描记录 `comprehensive-full-20261026.log` 只代表当时快照。
- Qt 常规 UI 使用 offscreen，Electron 为独立本机原生窗口；未使用真实音频设备、实际 ASR/翻译模型、Windows 原生、安装包/升级或远程 CI。未提交、推送或发布，不能据此声称这些未执行范围已验收。

2026-10-26 **侧栏分组间距与新建入口区分**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- 用户反馈收起/展开按钮与下方新增文件夹入口之间空白过大，两个加号难以区分。根因是 Electron 文件夹分组的 12px margin 在收起后仍保留，Qt 还使用固定分组 spacer。两端改为展开时可见间距 8px、收起时 4px，移除收起状态额外留白，保留 36px 高/36×36px 尺寸契约。
- 新增文件夹由裸加号改为文件夹加号图标，与“新录音”的新建图标区分；保留“新建文件夹”辅助名称，Electron 复用共享 Tip 气泡，Qt 沿用提示管理器。创建入口及业务调用不变。
- Qt 侧栏定向无音频回归 **15 passed / 11.97s**，明确核对两种状态的实际间距及恢复后的 8px。Electron 构建及原生 **25 组交互检查通过**，核对展开/收起的 8/4px 位置差、原按钮尺寸、实际悬停提示及其离开隐藏。Ruff、脚本语法与差异检查通过；日志 `.work/reports/sidebar-folder-gap-{python,build,native}-20261026.log`。
- 已查看 Qt `.work/browser/sidebar-folder-gap/qt-sidebar-compact-dark.png` 及 Electron `output/playwright/interaction-fixes/sidebar-aligned-compact-light.png`，后者同批更新其他明暗/展开截图。Qt 为 offscreen，Electron 为本机隔离原生窗口，均未访问真实音频。未重跑全量 Python、原生 Windows、安装包或远程 CI，未提交或推送。

2026-10-26 **侧栏按钮固定尺寸边界**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- 按用户澄清，展开状态仅固定 36px 高，保留整行宽度及文字；收起状态才固定为 36×36px。Electron 为主动作、设置导航设置高度上限，并为收起动作同时固定宽高最小/最大值与 flex basis；Qt 收起时固定动作宽度为 36，展开时解除宽度限制，沿用已有固定高度，避免动画期间动作跟随侧栏横向拉大。
- 同时将文件夹/录音行尾的更多菜单按钮由 28px 改为 36px，高度、圆角与导航一致，名称区域保留对应空间。名称提示、分屏策略和设置过渡保持原有行为；规范中遗漏的旧 38px 说明同步改正。
- Qt 侧栏定向无音频回归 **15 passed / 11.95s**；检查展开动作的最小/最大高度均为 36，收起宽高均为 36，且展开后恢复保存宽度。Electron 构建、Ruff、脚本语法与差异检查通过。Electron 原生 **25 组交互检查通过**，补查所有可见侧栏按钮的高度与收起方形尺寸；日志 `.work/reports/sidebar-square-{python,build,native}-20261026.log`。
- 使用隔离库、无音频防护；没有真实设备访问。Qt 为 offscreen，未重跑全量 Python、原生 Windows、安装包或远程 CI。未提交或推送。

2026-10-26 **侧栏尺寸、图标与视觉对齐统一**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- 用户反馈侧边按钮大小、风格与视觉不齐。检查发现顶部/底部动作使用不同内边距与间距规则，新增文件夹是 28px 文字加号，收起文件夹行保留 38px 高度和文字渐隐遮罩，树图标使用不同的 16×20 坐标框。按统一导航规格收敛：36px 动作/文件夹行、20px 图标框、13px 常规文字、8px 圆角；顶部与底部复用同一个 `.sidebar-action`，根文件夹图标中心和文字起点对齐，收起时居中并取消文字遮罩。新增文件夹改为同套线条加号和 36px 方形命中区。
- Qt 复用 NavigationButton，包括新增文件夹；去掉展开/收起时另写尺寸样式，保留新建文件夹的键盘焦点资格。统一按钮/树行高度、图标笔画和悬停表面；设置文本导航与返回入口沿用相同行高、字重、圆角和左右留白，键盘焦点仍保留。业务、折叠策略、工具提示与动画契约不变。
- 定向 Qt 无音频回归 **21 passed / 16.47s**（侧栏、录音页和交互），包含动作行高、折叠恢复、提示、设置动画与跨文件夹点击。Electron 构建及原生 **25 组交互检查通过**；新增基于真实渲染位置的检查，逐个比较动作高度/宽度、20px 图标框、根文件夹与动作的图标中心及文字左边界、36px 收起命中区，以及设置按钮高度/字号/内边距。
- 已查看 Qt 与 Electron 展开/收起的明暗截图及设置页。Qt 图像 `.work/browser/sidebar-alignment/qt-{sidebar-expanded,sidebar-compact-light,sidebar-compact-dark,settings-light}.png`；Electron `output/playwright/interaction-fixes/sidebar-aligned-{expanded-light,expanded-dark,compact-light,compact-dark,settings-light}.png`。日志 `.work/reports/sidebar-alignment-{python,build,native}-20261026.log`；Ruff、脚本语法与差异检查通过。
- Qt 为 offscreen，Electron 为本机隔离原生窗口；零原生音频访问。未重跑全量 Python、原生 Windows、多屏缩放、安装包或远程 CI，未提交或推送。

2026-10-26 **悬浮字幕与导出定稿移入更多菜单**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- Qt 与 Electron 移除标题栏并排的“悬浮字幕”“导出定稿”按钮，入口放入旁边“··· / 更多操作”菜单。复用既有悬浮窗与导出调用，导出仍受原内容/录音状态条件限制；Qt 导出状态更新对象改为菜单 QAction，未改变后台导出或文件格式。
- 定向无音频回归 **16 passed / 32.34s**，覆盖录音页、真实后台导出、录音库切换和恢复流程；原导出可用性断言改为核对菜单 action，SRT/TXT/Markdown 通过 action 触发并核对真实输出，标题栏无重复按钮。
- Electron 构建及原生基础探针通过。探针从更多菜单执行真实 SRT 导出（仅文件保存选择器指向隔离库），核对文件中的原文；从同一菜单打开悬浮字幕并完成原有内容、权限、隐藏和退出检查。原外观取样脚本同步入口定位。Ruff、JavaScript 语法与差异检查通过；日志 `.work/reports/header-menu-{python,build,native}-20261026.log`。
- 使用隔离库与无音频防护，没有设备访问、采集或播放。未重跑全量 Python、24 组交互、Windows 原生、安装包或远程 CI；未提交或推送。

2026-10-26 **收起侧栏的文件夹提示与设置往返动画**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- Electron 文件夹名称改用现有 `Tip` 气泡，向右显示完整名称，移出后关闭，不依赖原生 title；Qt 沿用共享提示管理器，收起状态的文件夹提示只呈现名称。点击与键盘选择不展开侧栏的契约保持。
- 从收起栏进入设置，导航宽度以 220ms OutCubic 从当前宽度过渡到设置宽度；返回时反向恢复 36px，保留收起状态、录音和展开偏好。快速返回接续当前宽度并取消旧动画，减少动态效果开启时立即完成。Qt 复用现有 QVariantAnimation 与侧栏宽度更新，Electron 扩展现有页面过渡钩子，未新增依赖。
- Qt 侧栏、提示与交互定向无音频回归 **21 passed / 16.54s**。新增真实 QHelpEvent 检查气泡名称及离开隐藏，实际宽度采样验证中间帧、快速返回、减少动态效果中途完成和返回后的 36px 状态；原侧栏循环等待本次展开动画完成后再开始下一轮，保持恢复宽度断言。
- 构建、Ruff、JavaScript 语法和差异检查通过；证据 `.work/reports/sidebar-hints-motion-{python,build,interaction}-20261026.log`。Electron 原生 **24 组交互检查通过**，包含真实 hover 气泡、往返实际宽度采样与快速反向连续性检查；录音身份和收起状态保持。
- 本轮再次遇到既有 650 条字幕检查的取样竞态：等待条数与读取 ID 在两次调用间跨过异步打开时的清空，读到空列表。改为同一次 DOM 取样等待完整连续 ID，再核对保存的数组；未删条数/顺序断言、未增加超时。
- Qt 为 offscreen，Electron 为本机原生测试窗口，均使用隔离库与无音频防护；未访问设备或录音，未验收 Windows 原生、系统分屏菜单、安装包或远程 CI，未重跑全量 Python。未提交或推送。


2026-10-26 **侧栏自动收起限定为分屏**（基于 `d184149` 加此前本地修改，`mac`，未提交/推送）：

- 按用户最新要求移除普通窄窗的 800/840 自动切换，也不接入开始录音触发。Qt 与 Electron 仅在窗口进入左右贴边、占满屏幕可用高度且宽度不超过 80% 的几何布局时自动收起，允许 16px 系统边框误差；普通缩窗、录音状态变化和退出分屏均不改当前手动状态。分屏内手动展开不会被后续同状态事件再次收起。
- 点击收起栏的文件夹仅选择，不展开侧栏；双击和方向键也不揭开隐藏的子条目。通过专用按钮展开后恢复文件夹展开状态，220ms 动画、36px 图标栏与展开宽度继续保留。更新 UI 契约与工作区说明，旧批次中的阈值/文件夹点击展开描述仅代表当时版本。
- macOS 定向无音频回归 **51 passed / 11.20s**（侧栏、录音库及桌面服务），包括分屏状态边界、普通缩窗、手动控制、录音状态遍历、真实 QTest 文件夹点击/双击/方向键、文件夹状态和录音切换；Qt 分屏边界注入窗口布局判定，几何函数另测左右/不等宽/负坐标屏幕与非分屏反例。Electron 几何函数同组 10 个边界检查通过；原生基础探针及 **23 组交互检查通过**，通过调整独立测试窗口的真实屏幕位置和高度检查自动收起、重复事件不覆盖手动展开、普通缩窗及退出后保留选择。
- Electron 构建、Ruff、脚本语法与差异检查通过。日志 `.work/reports/sidebar-split-{python,build,base,interaction}-20261026.log`。原生交互首轮在既有字幕切换检查中读到过渡期空列表，原样复跑通过；未删除断言或延长等待。Qt 测试更新了刷新后重新取得树条目的操作，并按分屏前实际宽度核对恢复（允许 1px 布局取整），未放宽业务断言。
- 全程使用隔离库和无音频防护，无原生音频访问；录音状态由显示事件/状态函数注入，没有真实录音。未通过系统分屏菜单实测、未测 Windows 原生或多屏缩放，未重跑全量 Python、远程 CI 或安装包。分屏是跨端几何识别，并非系统分屏 API 的确证；普通窗口若手动摆成相同布局也会识别。未提交或推送。

2026-10-26 **跨文件夹录音行点击不响应修复**（基于 `d184149` 加此前侧栏修改，`mac`，未提交/推送）：

- 用户反馈“点不动，没反应，多点几次才行”。原生 Electron 独立库复现：A 录音已打开时，点击 B 的文件图标/右侧留白或 C 的左侧缩进，只改变树高亮，标题和字幕仍停在原录音；点击文字才打开。三类行区域均未触发打开请求，根因是 `LibraryTree` 只给名称按钮绑定打开，行本身只有焦点/键盘处理。修前新增原生回归在点击 B 文件图标后超时失败，日志 `.work/reports/cross-folder-{before,regression-before}-20261026.log`。
- 录音行非按钮区域统一复用选择入口；名称按钮、文件夹展开按钮和菜单不重复派发。App 仅在打开请求成功后应用目标文件夹，失败恢复原选择与内容；加载门禁保持，禁止在加载期间通过行留白误改变鼠标选择。业务后台和数据格式未改。
- 修后独立原生复验的文字、图标、留白和缩进 6 次操作均成功，标题/高亮一致；Electron 基础流程与 **22 组交互检查通过**。新增覆盖兄弟/嵌套文件夹一次点击切换、标题/字幕/选中项一致、单击名称只发送一个请求、右键/行菜单不切换录音，以及真实临时损坏文档加载失败后保留原选择和内容。损坏夹具在检查后恢复原始字节；`.work/reports/cross-folder-{after,base,regression-after}-20261026.log`。
- Qt 侧栏/录音库/桌面服务定向无音频回归 **40 passed / 13.35s**，包含跨文件夹图标/缩进/留白的真实 QTest 点击；Qt 未复现此次命中区域问题。Electron 构建、Ruff、脚本语法及差异检查通过，零音频访问；日志 `.work/reports/cross-folder-{build,python,qt}-20261026.log`。本轮未重跑全量 Python、Windows 原生、远程 CI 或安装包；下方完整回归是此前侧栏动画批次的证据。未提交或推送。

2026-10-26 **侧栏动画、36px 图标栏与手动展开**（基于 `d184149` 加本地修改，`mac`，未提交/推送）：

- 按用户补充要求，收起宽度改为顶部拖动栏高度（当前 36px），在“新录音”下增加收起/展开按钮；两端复用 220ms OutCubic 宽度过渡，快速反向从当前宽度接续，减少动态效果直接到位。自动阈值沿用 800/840；手动覆盖保留至自动模式下一次变化，不写入展开宽度偏好。
- 收起只呈现顶层文件夹，录音条目与子文件夹自动折叠；展开恢复原展开状态，点击文件夹也会展开侧栏及对应文件夹。当前录音和字幕不变，没有移动文件。Qt 用原 QVariantAnimation、录音树与 NavigationButton，Electron 用现有曲线、树和上下文；没有新增依赖。
- macOS / Python 3.12.14 / PySide6 6.11.2 完整无音频回归 **1155 passed / 5 skipped / 262.62s**；跳过仍为 Windows 专项与本地未缓存 Sparkle 构建依赖。相关 Qt/录音库/展示/恢复 **19 passed / 37.83s**。新增检查实际中间宽度采样、动画反向、减少动态效果中途完成、36px 对齐、按钮位置、文件夹折叠与点击恢复，以及当前录音/字幕与宽度保留。日志 `.work/reports/sidebar-motion-{full,python,qt}-20261026.log`。
- Electron 构建、基础流程、11 组全链路、**21 组交互**及双向切换探针通过；交互探针对真实渲染宽度逐帧采样，验证中间宽度、快速反向、最终 36/180px 与减少动态效果即时切换。检查 Qt/Electron 明暗图标栏及展开恢复截图：`.work/browser/sidebar-motion/`、`output/playwright/interaction-fixes/sidebar-compact-{light,dark}.png`；日志 `.work/reports/sidebar-motion-{build,base,chain,electron-final,switch}-20261026.log`。Ruff、脚本语法与差异检查通过。
- Qt 为 offscreen、Electron 为本机原生窗口，均零原生音频导入尝试；未测原生 Windows、多屏缩放或真实录音，未重跑远程 CI、提交、推送或发行。下方 64px 图标栏记录是本次补充前的阶段证据。

2026-10-26 **分屏窄窗口主侧栏图标模式**（基于 `d184149` 加本地修改，`mac`，未提交/推送）：

- Qt 与 Electron 复用现有侧栏/录音树，按工作区宽度自动切换图标模式；阈值、提示、导航与宽度恢复契约见 [窄布局规则](UI_DESIGN.md#窄布局与内容宽度)。展开宽度与自动模式分离，设置页隐藏或窗口变窄不写入 Electron 的展开宽度偏好；Qt 保留当前窗口手动调整的宽度。图标模式不展示文字、树缩进或行菜单按钮，保留名称、选中态与右键入口；已修正 Qt 树表头保留旧列宽导致图标裁切的问题。
- macOS / Python 3.12.14 / PySide6 6.11.2 完整无音频回归 **1154 passed / 5 skipped / 240.73s**；跳过 Windows venv、8.3 路径、Job Object、Windows 安装编译器及本地未缓存的 Sparkle 构建依赖。最终 Qt 定向用例通过，包含三次宽窄往返、选中录音与字幕保留、名称提示、图标命中范围、新建文件夹居中和展开宽度恢复。完整回归的统计不替代最终新建文件夹图标居中与截图补充的验证；这两项另由最终定向用例再次通过。日志 `.work/reports/sidebar-responsive-{full,qt-final}-20261026.log`。
- Electron 构建通过；原生隔离交互探针 **20 组通过**，涵盖 640/820/900 宽度往返、图标模式切换录音与右键操作、设置往返、窄窗口刷新、展开宽度偏好保留与边界缓冲。已查看 Qt 明暗图标栏、展开恢复，以及 Electron 明暗图标栏截图；`.work/browser/sidebar-responsive/`、`output/playwright/interaction-fixes/sidebar-compact-{light,dark}.png`。日志 `.work/reports/sidebar-responsive-{build,electron-final}-20261026.log`；Ruff、脚本语法和差异检查通过。
- Qt 为 offscreen 布局回归，Electron 为本机原生窗口；通过实际调整窗口内容尺寸触发适配，未操作系统分屏控制、未实测 Windows Snap/多屏缩放。均零原生音频导入尝试，不访问真实录音设备。保留此前长字幕测试修复与用户文件，未提交、推送、重跑远程 CI 或发布安装包。

2026-10-25 **Qt 长字幕定位测试等待修正**（基于 `d184149`，本地 `mac`，未提交/推送）：

- GitHub 运行 `40158778618` 的 macOS / Python 3.11 在 `test_cross_page_variable_heights` 的整窗 `settle_geometry` 前置等待超时，尚未执行字幕定位断言；本地原用例连续三次为 1 failed / 2 passed。仅移除该处整窗尺寸与 `sizeHint` 稳定等待，保留 450 条长短字幕、实际查找操作、目标卡片进入视口的 2 秒期限及最终位置断言；不修改通用等待器或业务代码。
- 修后 macOS / Python 3.12.14 / PySide6 6.11.2 下，该用例独立连续三次通过；同文件无音频回归 **13 passed / 30.07s**，Ruff 与差异检查通过。日志 `.work/qt-caption-wait-fix-repeat-20261025.log`、`.work/qt-ux-recovery-wait-fix-20261025.log`；零原生音频导入尝试。未重跑远程 CI、Python 3.11 或 Windows，不能据此声称 GitHub 已转绿。

2026-10-25 **真实录音冷启动与 Qt 反馈对齐修复**（本地 `windows`，未提交/推送）：

- 用户反馈揭示此前验收边界不足：原生交互、完整业务链路与截图均运行过，但采集/模型执行部分使用夹具，未覆盖真实冷启动。用户日志中 Electron 两次停止时 recorded_seconds=0（约等待 29s / 17s），随后 Qt 约 0.75s 收到首包并录得 7.6s；不能以之前的夹具通过声称这条真实路径正常。
- 经用户明确授权“最多 10 秒”，在当前 Windows 来源、独立临时库先复现 4s 首包始终为零；堆栈定位采集线程卡在 `audio.capture → scipy.signal → scipy.linalg.blas` 原生模块导入。桌面实际输出 48kHz，不需要重采样，却无条件加载 SciPy。改为仅 16kHz 转换路径导入原 `resample_poly`，48kHz 直接混音传递；没有换来源、吞异常、增加重试或改模型。
- 第二次 4s 真实复验，Session start→首包 **0.251s**，计时连续推进到 **3.8s**；已读 WAV 头核对 **182400 帧 / 48000Hz / 单声道 / 3.8s**。真实模型于会话开始约 13s 就绪，随后处理已采集内容，日志 `session_end complete=true, failed=false, recorded_seconds=3.8`。两次采集窗口合计约 8s，未播放/上传，也未操作已有 Qt 窗口。原始证据 `output/playwright/real-capture/probe-{wpp0Td,oHrbwM}/`，日志 `.work/reports/real-capture-{before,after}.log`；后者的 FINAL 行是中间 STOPPING 快照，最终完成另据 session_end 与 WAV 核对，诊断等待循环已修正但没有为重跑脚本追加录音。
- 按 Qt 原实现抽取 `recording_state.capture_feedback`，统一岛内状态/计时旁说明、正文等待文字、模型加载资格。模型进度与录音事实独立，并纳入 snapshot 防漏事件；切源回执更新等待状态，暂停/失败电平归零。活动按钮从均匀分散改为 40px、8px 间距整体居中，输入说明/计时按 Qt 层级呈现；连接和加载中的无字幕文字改为工作区居中，通知右侧间距 16px。
- 相关音频/桌面服务/Session/交互 **71 passed / 1 skipped / 17.46s**（跳过 Mac-only MLX helper）；末轮定向 **55 passed / 12.14s**，不与前批累加。构建、Ruff、JavaScript 语法与差异检查通过；基础原生及原有 **19 组**交互通过。补出 Qt **8** 个状态和独立工具通知，Electron **94** 个状态及原动效；新增连接→采集中加载→就绪→收尾的显示断言、48px 按钮中心距和等待文字居中检查，人工查看明暗主题及 Qt 对照。此组显示夹具与上面的真实音频证据分别成立。
- 对照与证据摘要 `.work/browser/recording-runtime-fix/index.html`、`real-evidence.json`；无音频日志 `.work/reports/capture-{feedback-final,lifecycle-regression,feedback-parity,feedback-native,feedback-interaction}.log`。Qt 浮动通知是独立工具窗口，主窗 grab 不包含它，另取控件截图，不据此误报 Qt 没有提示。短实录不能证明转写质量、所有设备、真实暂停/切源、多次长会话或 Mac 实机；未提交、推送或发布。

2026-10-25 **Windows Electron 窗口控制外观修复**（本地 `windows`，未提交/推送）：

- 原生窗口复现：深色偏好冷启动时右上三个按钮仍为白底/黑图标；运行中切主题虽更新颜色，但固定纯色背景与窗口材质之间形成色块。根因是 bootstrap 未同步 overlay，构造固定浅色且后续更新仍使用不透明色。原生最小化、最大化/还原及关闭的动作本身可响应，未将其误报为全部失效。
- 构造、bootstrap 与 settings 共用覆盖层选项：透明背景、对应主题的图标与 36px 高度；保留系统按钮、命中区及现有关闭保护。新增 `titlebar-checks.cjs` 先在旧实现失败，修后随 `npm test` 的完整基础原生回归通过；涵盖深浅设置、模拟构造初态后的真实 bootstrap 重载、可用覆盖层尺寸。JavaScript 语法及差异检查通过。日志 `.work/reports/titlebar-{before,after}.log`。
- Windows 150% 缩放下，修后使用独立无音频窗口实际查看深色冷启动、深色最大化及浅色 640×481 内容区；原生捕获可见按钮背景与材质衔接、图标清楚及关闭悬停警示色。实际点击最大化后 native `maximized=true`、覆盖层 36px；还原后显示最大化按钮；最小化后 native `minimized=true`；恢复并点击关闭后自有测试进程正常退出。此部分为原生窗口工具会话的观察，不把页面截图当作原生控制证据。
- 无设备访问、采集或播放，不操作用户录音或其他窗口；未实测系统 Snap 菜单、其他缩放/多屏、Mac 或远程 CI。未提交、推送或发布。

2026-10-25 **回放字幕全文与正序首屏修复**（本地 `windows`，未提交/推送）：

- 用户反馈长录音只显示一部分、需要从后向前加载。650 条隔离字幕复现：服务默认 start=450，Qt 仅保留 450–649，两个新增回归修前均失败。此前原生链路样本只有 120 条，未跨过 200 条边界；原 spec 也把有限窗口用于回听，本轮按用户要求修正该行为契约。
- Electron 的 IDLE 字幕改为完整返回，打开默认正序从头；搜索只定位已载入文本，播放位置不再请求/替换另一页，回听隐藏更早/较新入口。Qt 已保存加载及回放模式展示全部卡片，纯文字录音同样从开头定位；首卡定位保留请求的 24px 阅读偏移，避免尚未稳定的几何使最终首屏产生几像素偏移。实时录音仍保留原有窗口及手动历史保护。
- 相关服务/Qt/恢复/组件回归 **49 passed / 31.47秒**；补跑字幕反馈、文字选择/跟随及搜索 **7 passed / 11.44秒**，均零原生音频导入尝试。构建、Ruff、脚本语法及差异检查通过；Electron 基础原生流程、**19 组**交互、**11 组**全链路与双向切换通过。
- 原生交互使用 650 条字幕，检查载入时全部 DOM 已存在且首屏在开头、Home/End 的首末实际可见位置、跳转第 625 条再回第 1 条，以及搜索第 425 条后全文仍为 650 条。已查看开始/末尾截图，未以条数代替界面检查。证据 `output/playwright/interaction-fixes/{complete-transcript-start.png,complete-transcript-end.png,result.json}`；日志 `.work/reports/playback-transcript-{before,after,follow,build,test,test-interaction,test-chain,test-switch}.log`。
- 本机 Windows 隔离库、离线媒体适配验证，不访问用户录音或音频设备；没有验真实声音输出、Mac、多屏缩放或任意超大全文性能。全文增加内存和首次排版成本，不能用本次 650 条样本宣称所有长度均无卡顿。未提交、推送或发布。

2026-10-25 **以 Qt 为基准的 12 项界面修复**（本地 `windows`，保留此前未提交工作）：

- 原审查 U01–U12 已在本地实现：局部忙碌、设置分类滚动隔离、数值输入与保存值一致、弹窗单层滚动、树与模型键盘导航、可调整侧栏、行菜单打开目录、来源刷新反馈、参数帮助、待录音摘要、展开命中区及短目录高度。数值箭头步长不限制合法手输小数；后台只在首次无选择时选首个来源，失效旧来源要求重选。
- 相关无音频 Python **61 passed / 5.62秒**，覆盖桌面服务、音频、前端切换及打包；零原生音频导入尝试。构建、Ruff、脚本语法和差异检查通过。Electron 基础原生流程、**11 组**全链路、**16 组**交互及 **Electron → Qt → Electron** 切换通过；交互探针复用原有隔离库与音频保护，新增 Qt 对照检查。几何回归将小于一个设备像素的浮点测量归一为实际设备像素，仍断言位置及宽度完全相同。
- 修后重新生成 Qt **72**、Electron **86** 个界面状态，其中 **72** 个同名状态纳入三列对照；Electron 横向溢出与原有动效断言通过。人工复查工作区、待录音摘要、深色窄设置页、模型高级弹窗及下载目录。Qt 图片含系统边框/阴影，Electron 页面截图不含；Windows 150% 缩放使请求 640×480 偶得 640×481/482，实际尺寸保留在清单，临时截图适配允许 1px 系统舍入，交互探针允许 2px。
- 报告 `.work/browser/ui-fixes-20261025/index.html` 提供 Qt / 修前 / 修后三列切换及逐项说明；原审查保留在 `.work/browser/ui-audit-20261025/`。日志 `.work/reports/ui-fixes-{python,build,test,test-chain,test-switch,interaction,qt-capture,electron-capture}.log`，原生交互结果 `output/playwright/interaction-fixes/result.json`。
- 来源变化呈现使用事件夹具，首次选择/旧来源失效行为另由 Python 回归验证；目录解析走真实后台，仅系统目录打开由夹具拦截。离线媒体、HTTP、模型清单不证明真实录音、播放、下载、推理或云端可用。未验 Mac、多屏不同缩放、安装升级或远程 CI；未提交、推送或发布。

2026-10-24 **正常启动阻塞与切回 Qt 复查**（本地 `windows`，沿用未提交修改）：

- 用户正常模式日志中，`audio.refresh` 到后续请求之间分别停顿约 **10.46 / 13.23 秒**；切换失败仍为旧进程的归属校验。慢发现替身复现主线程阻塞，新增三分支修前均失败；正常协议后台的冷启动堆栈进一步定位到 `audio.py` 顶层导入 `scipy.signal → scipy.linalg.blas`。原无音频/预导入测试未覆盖这个条件，不能据此前通过结果宣称正常启动已验收。
- 来源刷新改为异步任务与受控发现子进程，超时回收自有进程树；合并重复刷新、失败保留原列表、关闭丢弃迟到结果。采集专用 NumPy/SciPy 延后至采集入口导入。最终相关无音频 **56 passed**（5.62秒），覆盖桌面服务、音频、切换、Electron 打包，零原生音频导入尝试；Ruff 与差异检查通过。双向切换隔离探针再次通过。
- 本机 Windows 正常来源检查返回 **5 个来源 / 1.015秒**（仅枚举，不采集或播放）。正式正常入口实际操作设置、运行环境并点击切回 Qt 成功，待录音草稿及库路径保持，Qt 窗口与来源/开始按钮正常显示；成功启动实例 `audio.refresh` 请求于 14:23:51.765，后续 `models.check` 于 51.766、`frontend.ready` 于 51.810，表明发现不再阻塞这些协议请求，不把该差值当成完整启动耗时。
- 证据 `.work/reports/device-refresh-before.log`、`startup-related-after.log`、`windows-device-discovery.log`、`startup-switch-after.log`、`startup-debug/` 及真实用户日志 `support-desktop-electron-20261024T062351-*.jsonl`。调试中只回收本轮自行启动、确认未录音且无编辑的空白实例；最终保留正常 Qt 窗口。未采集/播放、未验模型推理或 Mac 实机、未重跑远程 CI；未提交或推送。

2026-10-24 **GitHub 检查失败复现与本地修复**（基于 `1f8c140`，本地 `windows`，未提交/推送）：

- Windows / Python 3.12.8、PySide6 6.11.2、Node 24.13.0、Electron 45.0.0。明确设置 `PYTHONUTF8=0` 后，原前端切换测试 **2 failed / 3 passed**，中文 UTF-8 交接文件被默认 GBK 解码；GitHub Windows 3.11–3.13 日志为相同两例、默认 cp1252。两处测试读取显式指定 UTF-8 后 **5 passed**，不修改生产文件格式或全局编码设置。
- 原 `test:chain` 复现 `initial caption tail` 超时；实际 120 条已加载，`scrollTop=0`、`scrollHeight=13984`、`clientHeight=765`，处于已有音频的 IDLE 回听状态。测试错误期待自动跳到末尾；改为确认开头状态、用实际 End 键到达末尾，再按实际尾部位置验证原生滚动条拖动及设置往返锚点，保留原场景与后续断言。修复后 **11 组全链路检查通过**，`test:interaction` **5 组通过**。
- 补跑此前 CI 被跳过的 `test:switch`，复现 `frontend.prepare` 拒绝归属、随后切换超时。独立短进程及新增回归确认 Windows venv redirector 位于宿主与服务之间；新增用例修前 **1 failed / 7 passed**。归属判断仅额外允许通过同一解释器启动器验证的直接祖父宿主；无关可执行路径及非 Windows 祖父请求仍拒绝。修后真实 **Electron → Qt → Electron** 通过，同一录音、字幕、库路径及无音频约束保持。
- 最终 `test_desktop_service.py`、`test_frontend_switch.py`、`test_electron_packaging.py` 无音频回归 **37 passed**（4.33秒），零原生音频导入尝试；Ruff、JavaScript 语法及差异检查通过。复现与修复日志 `.work/reports/frontend-switch-{before,after}.log`、`frontend-owner-before.log`、`desktop-related-after.log`、`electron-chain-{before,diagnosis,after}.log`、`electron-interaction-after.log`、`electron-switch-{after,fixed}.log`。Electron 探针使用独立库/偏好及音频拦截，媒体、HTTP、安装下载和云执行为离线夹具；不影响既有用户窗口。
- 仅在本机 Windows/Python 3.12 复验，未重新运行全量 Python、其他 Python 版本、Mac 实机或远程 CI，未验真实设备/模型、安装升级。此次修复不能视为 GitHub 已转绿；没有提交、推送或发布。

2026-10-24 **用户反馈交互修复**：树行透明悬停、工具菜单互斥、圆形返回播放位置、首次回听异步定位，以及更新进度动画。保留用户确认的最近删除/弹窗效果；另修通知遮挡弹窗关闭按钮、主题切换短暂沿用旧材质、重复检查更新和更新失败语义。

- 本次定向无音频回归 **32 passed**，14.89秒；原有原生工作流及新增 `test:interaction` 五组原生流程通过，构建/Ruff/差异检查通过。首次回听保留真实IPC/服务/控制器/WAV读取，只有媒体硬件用延迟350ms的无设备适配器替换；更新使用离线HTTP响应，保留后台线程与解析。
- 约1.2秒更新动画采样73帧/73个transform，rAF P95与最大间隔17.7ms，字幕DOM变更0；仅本机短时采样，不是全平台帧率保证。截图含深色640×480弹窗，关闭按钮不被通知遮挡。
- 证据 `output/playwright/interaction-fixes/`、`.work/reports/user-interaction-fixes-20261024.md` 和 `interaction-fixes-*.log`。未进行真实音频或原生Windows测试；两平台CI已加入探针，未推送。未提交、打包或发布。



2026-10-24 **功能对照修复**：按 F01–F13 修复导出排队丢请求、推荐组合参数、准备后就绪检查、别名输入、跨录音回答、滚动条/设置导航阅读锚点，并补任务反馈、Beta 取消、运行时复用、回听元数据、批量最近删除、首次引导和启动目录恢复。实现/证据逐项记录于本地 `.work/reports/frontend-parity-fixes-20261024.md`。

- 全量无音频 **1130 passed / 3 skipped**，293.89 秒；3 项均为 Windows 专属。末轮元数据与共享悬浮窗几何等定向回归 **56 passed**，13.04 秒；不与全量累加。首次沙箱运行遭 `psutil/sysctl` 进程枚举权限限制，保留失败日志，在允许进程检查的环境重跑通过。两批均零音频导入尝试。
- 原有原生工作流探针通过；推荐组合测试已删除 `Service.request` 成功替身。新增 `test:chain` 保留前端→preload→IPC→JSONL→真实校验/共享后台，使用真实文件及工作进程；仅安装/下载和云端生成执行换为本地受控任务。覆盖成功、失败、取消、重试、持久化回执、库存设备适配、跨录音和坏库恢复。不能据此声称真实模型/云端已验收。
- 当前构建复拍 **86 个 Electron 页面状态**，与已保存的 v0.10.2 Qt 原生基准形成 **72 组配对**，人工核对工作区、窄运行环境、课程窗口及最近删除；最近删除恢复 560×440。小岛18组矩形尺寸/纵向差为0、横向最大0.5px；7组连续动画各41–42帧，含反向与减少动态效果。报告 `.work/browser/ui-parity/index.html`，不是新一轮真实音频会话或 Windows 渲染证明。
- 实际 Electron → Qt → Electron 往返通过，同一录音/字幕/录音库与无音频约束保留；属于源码环境。TypeScript/Vite、Ruff 和差异检查通过。当前源码未提交或推送，旧候选包未重新打包；Windows CI 已增加相同链路测试，未远程执行。

2026-10-23 **视觉与动效细节补齐**（晚于下述双前端候选 DMG）：仍在 `mac` / `e0d3c19` 加本地修改，未提交、推送、重打安装包或发布。

- 原生 Qt **72** 张参考图、原生 Electron **86** 个页面状态，整理为 **72 组同名配对**：工作区、六个设置页、模型目录/设置/高级、课程三页签、悬浮字幕；深浅主题及 1280×797 / 900×650 / 640×480。尺寸是实际窗口内容区；Qt Retina 图以平滑采样归一到逻辑像素。统一示例正文、模型清单与显示路径，实际库和偏好均隔离。`.work/browser/ui-parity/{qt,electron}/manifest.json`、`index.html`；对照页全部图片加载、叠加控件及动画图表检查通过（`report-check.json`）。
- 18 组待录音/录音/回听矩形比较：宽、高、纵向位置差为 **0px**，横向最大 **0.5px**（CSS 居中分数像素）。修复主侧栏最小宽度、标题栏、滚动条占位与小岛底部锚定。没有把这项几何检查称为全图逐像素相等。
- 共享动画逐帧采样覆盖小岛展开/收起/100ms 时反向、音量展开/中途反向、开关、减少动态效果；各轨迹 41 帧。小岛设置 280ms InOutCubic，本次点击到首次采到终值为 306.9 / 294.6ms（含提交及帧调度）；音量设置 200ms OutCubic，本次整数高度首次达到170px为198.2ms。进度条宽度/位置不随音量展开变化；切页150ms、弹窗140ms检查实际动画对象。`electron/motion.json`。这是原生渲染采样，不是实际录音/播放或屏幕录像。
- 壁纸材质直接复用 Qt 的采样、模糊、叠色和噪声实现，测试解码后像素相同，主题变化会使签名失效；原生截图等待页面背景实际加载并解码。连续移动时保留同一屏幕和主题下仍可用的已完成材质，避免连续刷新一直丢弃结果。相关无音频回归 **29 passed**，6.26秒，零原生音频导入尝试；包含服务、材质、切换边界和封装检查（`ui-parity-tests.log`）。本批未重跑上轮1123项全量，不把历史数量叠加成本轮结果。
- TypeScript/Vite、Ruff、差异检查通过；隔离原生工作流通过：中文编辑/IME、下拉键盘/关闭焦点、模型草稿取消、推荐组合应用（拦截真实下载，只核对请求与临时偏好）、跨平台模型禁用、课程保存回执/隐藏重开、悬浮字幕最新一段/字号/自动隐藏/手柄实际拖动缩放、字幕追加/修订和正常退出。`.work/reports/ui-parity-{build,workflows,electron,qt-matrix,report}.log` 与 `.work/browser/ui-parity/workflows/result.json`。
- 过程中修正截图夹具的异步读库/材质等待（使用有界异步轮询，避免 Promise 被当作已满足条件）、不同原生窗口识别、macOS内容高度限制及组件路由重载。一次焦点断言早于 Radix 的异步关闭回调；事件记录确认约10ms后已归还，改为有界等待同一焦点条件，保留原断言与失败记录。不是强制聚焦后宣称关闭正常。
- **旧候选 DMG 不含本轮视觉修改**。Windows原生、跨屏/不同缩放、所有异常状态组合、真实音频/模型/云端和安装升级仍未由本批证明；现有Qt入口与双向切换保留。字体栅格化、原生装饰和少量复杂弹窗间距不宣称完全等价。

以下为这次细节补齐之前的迁移与封装证据：

2026-10-23 Electron / Qt 双前端的 v0.10.2 对照：基准 `dd31363`，开发于 `e0d3c19` 加未提交修改；两提交之间仅有 Windows worker 测试隔离调整。已核对 `UI_DESIGN`、业务 specs、三套 UI Demo 与 Qt 组件/接线。两个界面增加明确切换按钮，第一次仍打开 Qt，随后记住成功打开的前端；未提交、推送或发布。尚待平台/设备验收的范围保留在 R27。

- macOS 26.6.2 arm64、Python 3.12.14：完整无音频回归 **1123 passed / 3 skipped**，301.86 秒，零原生音频导入尝试。跳过项仅为 Windows 8.3 临时路径、Job Object 生命周期及原生安装器编译器。证据 `.work/reports/electron-final-native-full.log` / `.xml`。首次受限沙箱批次出现图形会话/本机端口/进程读取受限，以及旧 UI 测试夹具未接受新参数；失败记录保留于 `electron-final-full.log` / `.xml`，没有以该失败批次冒充通过。
- 完整回归后补充启动就绪回执、取消切换及 Mac 封存兼容修复，相关定向回归 **68 passed**，5.90 秒，零原生音频导入尝试；包括服务、切换、Electron/原有封装、Qt 主入口与笔记持久化回执。`.work/reports/electron-final-targeted.log`。随后模型库存边界与设备草稿修复由 TypeScript 构建和下面的原生探针覆盖，没有把早期全量结果称为所有最后改动的全量运行。
- 包内原生探针发现 ICNS 不能传给 Electron Dock，已在可选双前端 Mac 构建中生成同源 PNG；Qt 单前端构建保持原行为。最后封装回归 **44 passed**，0.91 秒，零原生音频导入尝试（`electron-final-packaging.log`）；该数量与前述专项有重叠，不累加。启动失败及错误堆栈分别保留在 `electron-packaged-startup-failure.log`、`electron-packaged-icon-failure.log`。
- TypeScript/Vite 构建与 Ruff 通过；原生 Electron 探针覆盖临时录音库、中文名称、搜索、主题、模型草稿取消、对齐/跨平台模型禁止误用、MLX 设备草稿、下载目录、独立课程窗口与保存回执、受限悬浮窗口、IME/键盘焦点、音量展开不挤压进度条、字幕追加/修订与退出。独立录音库、偏好及浏览器 profile，零原生音频访问。`.work/reports/electron-build.log`、`electron-native.log` 和 `output/playwright/electron/result.json`。
- 原生 **Electron → Qt → Electron** 实际往返通过：同一录音 ID、标题、库路径、字幕恢复，无音频状态保留；未保存编辑阻止切换。Qt 观察器只注入临时测试环境，目标进程退出后才启动下一界面，没有靠强杀旧界面完成切换。`.work/reports/electron-switch-native.log`、`output/playwright/switch/result.json`。此项是源码环境验证。
- 最终 Mac 双前端候选包构建成功：`AgentScribe-0.10.2-dual-ui-macos-arm64.dmg`，430752946 字节，SHA-256 `8bea86777f02515d0a82f38deebfb36a7b80c5edf8d7cff19c3ca3df75a44b03`。原生签名完整性、启动器隔离、DMG 校验及只读挂载后的 Qt/worker/关闭探针通过；包内 Electron + Python 另跑上述原生交互流程通过，零音频访问（`electron-macos-build.log`、`electron-packaged-native.log`、`output/playwright/electron-packaged/result.json`）。运行后复核360个前端载荷文件、25个源码输入摘要及签名未变，见 `electron-sealed-verification.json`。产物在 `.work/packaging/dist/`，为 ad-hoc、未公证候选，未安装或发布；此处不声称安装包双向切换及真实旧版升级均已验收。
- 900×650 相同示例正文已人工对照 Qt 与 Electron 图片，校准侧栏宽度、字幕留白/段间距、小岛及标题；Qt 参考在 `.work/browser/electron-baseline/`，Electron 在 `output/playwright/electron/`。Qt 这批为离屏渲染，Electron 为原生窗口内容；窗口外框/字体栅格和所有状态尚非逐像素等价。Mac 截图不证明 Windows 或其他缩放通过。
- 没有真实采集/播放、模型下载/推理、供应商调用、Windows 原生或旧版升级验收。CI 已增加两端 Electron job，但本轮未推送触发远程运行；本机不能代替 Windows 验收。

原生探针曾发现课程部分视图导致重开术语不完整、弹窗下拉被遮罩挡住，均修复并复验；窗口隐藏使用操作系统可见状态核验，音量几何比较排除页面滚动位移。末轮组件键盘探针两次等待焦点/选择超时，保留 `electron-native-focus-failure*.log`；测试切换组件页面后显式激活自己的原生窗口，再复验通过。没有强制点击、放宽选择断言或跳过该检查。新增模型库存测试曾误跑旧构建而失败（`electron-inventory-stale-build.log`），重新构建后覆盖通过。

各行单独注明代码、环境及证据；测试通过数不跨批次累加。无音频回归和隔离界面探针不替代真实录音、GPU、云端质量或安装升级验收。

| 证据 | 已证明 | 范围与限制 |
| --- | --- | --- |
| 2026-10-23 v0.10.2 源码版本准备 | 在 `windows` 的 `775fb20` 与测试分级/审查改动上，将项目元数据、运行时版本、Mac 包内说明和源码指南同步为 `0.10.2`；远程最高标签为 `v0.10.1`。Windows / Python 3.12.8，Ruff 与差异检查通过；无音频收集 **1100 项**。版本/打包相关三文件回归 **71 passed / 1 failed / 1 skipped**（3.73 秒），零原生音频导入尝试 | 失败为打包夹具复制 Qt 许可时的 WinError 3：源文件与目标父目录均存在，目标完整路径 266 字符，单独执行相同 `shutil.copy2` 复现；没有缩短目录、跳过失败或修改实现。跳过项为 Windows 符号链接权限。保留此前迁移长路径和事件循环阻塞记录，未重复受阻全量回归；未验 Mac、设备/模型或最终安装升级，未发布安装包/更新订阅。本地 `.git` 只读，远程集成状态以 GitHub 提交为准；日志 `.work/reports/v0.10.2-{collection,version-tests}.log` |
| 2026-10-23 测试代码全面审查 | 静态扫描全部 121 个测试/支持 Python 文件、683 个测试函数，单独解析内嵌 UI/子进程代码，检查 15 个验收/评测脚本与 CI。记录 18 项问题/维护缺口和 7 组精简候选，逐项位置、保留边界见 [审查正文](testing/TEST_CODE_REVIEW_20261023.md)。受控替身退化后 6 个原测试项仍通过，分别证实无音频防护缺少真实拒绝自测、清理仅验目录存在、闲置回收在断言前手工关闭的检测缺口；另复用真实 LlamaTranslator.close，证实 check_llama 两处收尾属性访问产生 AttributeError | 没有加载模型、访问设备或启动真实推理进程；只修改独立合成夹具和进程内临时替身，未修改测试/业务实现。受控反例的“仍通过”是测试漏检证据，不能算产品验收通过。上轮事件循环阻塞和长路径失败仍保留，本轮未重复受阻全套或声明实际提速。原始清单/探针见 `.work/reports/test-code-review-*20261023.json` 及对应扫描/探针脚本。本地未提交/推送 |
| 2026-10-23 全仓库测试分级 | 在首批拆分的本地改动上，逐用例标注全部 **118 文件 / 683 函数**；最终全仓收集 **1100 项**，P0/P1/P2/P3 分别为 **284/627/184/5 项**（函数 **149/402/128/4**），逐项检查恰有一个标记，无漏标/重复。Windows / Python 3.12.8；Ruff 与差异检查通过。AST 对比确认 114 个文件仅增加标记/pytest 导入及导入排序，其余四个文件仅保留首批已验证拆分，没有业务变更。14 个不依赖事件循环的相关文件回归 **141 passed / 13 failed**（5.19 秒）；失败均在录音库迁移的长路径目录创建，WinError 206/3，`HEAD` 原版代表用例在同一临时根目录复现失败（0.48 秒）。两次专项运行均零原生音频导入尝试 | 完整无音频回归出现 Beta 开关 UI 等待超时，使用 `HEAD` 原版相同用例也复现（13.77 秒）；随后停滞于日志 worker 用例。最小标准库 `asyncio.run(asyncio.sleep(0))` 子进程 6 秒仍未结束，3 秒堆栈定位到 Windows `socket._fallback_socketpair` 的 `accept`，完整运行五分多钟无进展后停止，**未完成全量回归，不声明全套通过**。未改事件循环、套接字、临时路径长度策略或放宽断言；未验 Mac、真实设备/模型/GPU、线上 SDK 或安装升级。本地未提交/推送。分级快照/收集清单及 `full-test-priority-{20261023.log,unit-20261023.log,beta-baseline-20261023.log,migration-baseline-20261023.log,asyncio-probe-20261023.txt}` 均在 `.work/reports/`，分级不等于上述缺口已解决 |
| 2026-10-23 测试四级标准与跨等级拆分 | 基于 `775fb20` 的本地修改；6 个混合函数拆为 13 个独立函数并标注 P0–P3，参数展开由 9 项变为 19 项。Windows / Python 3.12.8、PySide6 6.11.2、NumPy 2.5.2、pytest 9.1.1；执行 `scripts/test_no_audio.py tests/test_recording_export.py tests/test_user_workflows.py tests/test_interaction_fixes.py tests/test_ui.py -q -rs --tb=short`，**47 passed**（77.69 秒），零原生音频导入尝试。全仓收集按 `-m "p0 or p1 or p2 or p3"` 筛选 **19/1100 项**；Ruff 与差异检查通过 | 首轮默认沙箱临时根目录不可写，**8 passed / 39 setup errors**，未进入相关用例主体；重跑仅在命令环境将 TEMP/TMP 指向获准的用户临时目录下新建唯一中文目录，保留 pytest 自动生成路径及中文文件名，未改测试入口或机器配置。仅验证四个受影响文件，未执行全量回归、真实模型/设备、Mac 或安装升级；标记尚未覆盖其余用例，不缩减默认 CI。本地完成，未提交/推送 |
| 2026-10-21 首句识别冷启动定位（未修复） | Windows Qwen3-ASR-1.7B / CUDA 的实际会话日志：开始后约 0.16 秒采到首块，5.41 秒模型 ready；VAD 检测讲话后约 0.49 秒启动首轮识别，处理 0.554 秒音频耗时 **16.822 秒**，完成后约 0.12 秒发布字幕修订；第二轮 **0.344 秒**。使用现有本地模型对已保存片段离线 GPU 复测，首次 **15.55 秒**、同进程再次 **0.22 秒**。主要等待位于首次模型计算，而非界面等待定稿；现有后台准备仅预导入运行库 | 按用户要求仅记录，预热/模型驻留策略未修改，R26 保持未解决。VAD 不是人工标注起点，字幕修订事件不是屏幕绘制完成；Python profiler 不能独立证明某个 CUDA 算子、库或编译器是唯一原因。离线输入由已保存 WAV 重采样，不等同完整实时前端；未新采集、播放或联网，未验长会话、质量和 Mac。本地原始日志与录音保留且不上传；摘要及复测证据在 `.work/reports/first-speech-latency.md`、`first-decode-profile.json`、`first-decode-profile-{0,1}.txt` |
| 2026-10-21 播放器信号修复与录音提示调整 | 用户报告的 `durationChanged(qlonglong)` → `duration_changed(int)` 连接异常在隔离 Qt 信号测试中修前复现，修后通过；转发时长/位置改为 64 位，播放器初始化完整成功后才保留引用，失败可重新打开重试，切换录音重置旧进度。最新 Windows 无音频相关回归 **31 passed**（41.76 秒），覆盖进度、重复打开、初始化失败重试、原文件不变及录音状态。按最新要求，小岛状态使用普通字重，加载只显示右上角通知，输入音量说明与可视化保持可用；就绪后收起通知 | 原测试替身误用 32 位信号，曾漏掉该缺陷，现使用 Qt `qlonglong` 信号；播放器仍为替身，WAV 为合成文件，不宣称实际设备出声或 Mac 验收。明暗/宽窄的 12 张主窗口截图与 4 张独立通知截图重新生成并检查代表性画面，布局探针通过；下方初版旁侧提示方案已被此次调整取代。日志 `.work/reports/playback-signal-before.log`、`playback-and-recording-targeted.log`、`recording-notice-preview.log`；截图 `.work/browser/quiet-recording/`。Ruff 与差异检查通过；本轮未提交/推送，运行中的旧进程需重启加载修复 |
| 2026-10-21 录音开始反馈收敛 | Windows 无音频相关流程 **39 passed**（59.07 秒），Ruff 与差异检查通过；采集确认前不谎报录音，确认后稳定显示录音与计时，模型加载使用旁侧弱提示，就绪且暂无字幕时显示“正在聆听”。覆盖模型先就绪、暂停中就绪、无声音警告保留、切源、停止及错误反馈；正式流程 Demo 补加载/就绪场景 | 使用模拟会话，不改变采集/推理实现，未访问真实设备或模型。明暗主题、900×650 与 640×480 的加载/聆听/暂停共 12 张离屏截图，几何检查通过并查看代表性画面；首次发现加载文字被固定小岛宽度截断，改为与音量说明共用旁侧位置后重新验证。日志 `.work/reports/quiet-recording-final.log` / `quiet-recording-preview.log`，截图 `.work/browser/quiet-recording/`。未验 Mac 原生、其他缩放及真实音频；本轮未提交/推送 |
| 2026-10-21 高频路径优化与桌面模块拆分 | 五项优化先经 **139 passed**；字幕/播放拆分流程 **61 passed**；Windows 完整无音频 **1064 passed / 25 skipped**（344.33 秒）。最后补充导出比较的读取权限边界并复验保存相关 **47 passed**（2.45 秒）；Ruff、差异检查通过。正式窗口 900×650、640×480 的明暗主题四张截图与原主窗口源码对照逐像素一致，组件 Demo 直接复用正式窗口按钮 | 跳过项为 Mac 专属、Windows 符号链接权限、原生更新/恢复组件条件；无原生音频导入尝试。未验真实音频/模型/GPU、Mac 实机和其他缩放。算法微基准不代表端到端提速。主窗口 3593→3098 行；主体源码 22775→23147 行，独立边界/索引/缓冲带来净增 372 行，不宣称整体减码。日志 `.work/reports/optimization-full.log`、`optimization-save-final.log`；微基准 `optimization-benchmark.json`，截图 `.work/browser/optimization-{before,after}-fonts/`。本地未提交/推送 |
| 2026-10-21 主体审查三项异常路径修复 | 预热池关闭/释放失败保留工作进程，异步关闭与同步重试串行；翻译日志线程未退出时管道关闭报错并保留资源，退出后再次清理成功；录音库线程启动失败通过已有完成信号恢复空闲、报告错误并允许重试/退出。新增 6 个回归项；Windows 针对性无音频 **100 passed / 5 skipped**（21.17 秒），Ruff、差异检查通过 | 真实 Python 父子进程覆盖继承日志管道；清理失败和线程启动失败为故障注入。跳过 3 个 Mac Metal 监督进程、1 个 Mac MLX、1 个 Windows 符号链接权限用例；无原生音频导入尝试。未验真实音频、模型/GPU 或 Mac 实机，未提交/推送。日志 `.work/reports/audit-fixes-targeted-final.log`；首轮新增 UI 用例漏导入辅助函数的失败日志保留为 `audit-fixes-targeted.log` |
| 2026-10-21 低优先级测试直接退役 | 按用户要求取消外观、动效、精细文案、演示页、辅助指标及重复便利性门禁，不迁移被删断言。相对上一轮 1135 项，删除 **47 个函数 / 57 个收集项 / 6 个文件**；测试 Python 从 19722 行降至 **17809 行**，净减 **1913 行（9.7%）**。最终 Windows 完整无音频 **1053 passed / 25 skipped**（339.91 秒）；Ruff 与差异检查通过，零原生音频导入尝试 | 保留核心结果、数据保护、取消/迟到结果、进程线程退出、许可与更新信任/恢复。明确取消的覆盖见 TESTING 当前取舍，不宣称覆盖等价。删除 Mac 版本菜单展示测试后平台跳过数由 26 降至 25；其余为平台专属、符号链接权限及原生更新/恢复组件条件。未验真实音频、GPU、Mac 实机；本轮未改业务。日志 `.work/reports/test-priority-full.log`，逐项删除清单/基线/统计为同目录 `test-priority-retired.json` / `test-priority-before.json` / `test-priority-summary.json`。本地完成，未提交/推送 |
| 2026-10-21 测试流程归并与共享入口 | 以本轮工作区 1140 项为基线，6 个重复正常路径检查归并到既有录音/设置/文件库/真实 PCM 流程；29 处 UI 子进程启动共用 `ui_support`，新增超时失败参数验证。最终 **1135 项：1109 passed / 26 skipped**（424.79 秒）；首轮专项 **58 passed / 1 skipped**，随后共享入口失败/超时检查由最终全量覆盖。41 个测试/支持文件变化，净减 127 行，84 个文件未改。Ruff 与差异检查通过，零原生音频导入尝试 | 本轮只改测试与测试文档，保留此前未提交的业务修复；映射和明确退役的一项历史菜单枚举见 TESTING。Windows 无音频、Qt offscreen；合成 PCM/替身模型不证明真实音频或 GPU 质量，未做 Mac 实机。26 项因平台、符号链接权限及原生更新/恢复组件条件跳过。日志 `.work/reports/test-journeys-full.log` / `test-journeys-targeted.log`；前后快照与统计在同目录 `test-journeys-before.json` / `test-journeys-change-summary.json`。本地完成，未提交/推送 |
| 2026-10-21 进程管理复用收敛 | 推理预热与课程后台共用启动、进程树停止及通信线程/管道回收；删除课程清理期间重复的进程/线程引用。Windows 完整无音频 **1114 passed / 26 skipped**（432.41 秒）；专项 **65 passed / 1 skipped**。覆盖真实 Windows 后代回收、重复关闭、清理失败后重试、迟到日志线程及 UI 响应；新增两端模拟启动失败释放归属、Mac 主进程退出后仍回收活跃通信所在进程组的回归。Ruff 与差异检查通过，零原生音频导入尝试 | 保留各调用方协议与超时，不改 MLX/翻译服务专用关闭协议。Mac 分支模拟不替代实机；26 项因平台专属、符号链接权限、原生更新/恢复组件条件跳过。未验真实音频、GPU 或原生 Mac。日志 `.work/reports/process-sharing-full.log` / `process-sharing-targeted.log`。本轮本地完成，未提交/推送 |
| 2026-10-21 稳定性复查与课程后台回收 | 检查启动、录音/保存/导出、模型租用、翻译取消、课程后台、日志及更新恢复的关键路径。真实隔离进程复现主进程存活/已退出但后代占用管道导致关闭超时，修复后两例通过；新增清理失败保留归属并重试的回归。Windows 全量首轮 **1110 passed / 26 skipped / 1 failed**（459.98 秒），唯一失败为旧界面测试替身仍使用单进程清理接口；修正后失败项复测 **1 passed**，相关专项 **6 passed / 1 skipped**。Ruff、差异检查通过，零原生音频导入尝试 | 全量与复测分别记账，不宣称一次全绿或所有缺陷已排除。跳过项为 Mac 专属、符号链接权限、原生更新/恢复组件条件；未做真实音频、长课堂 GPU、Mac 原生或供应商验收。日志 `.work/reports/stability-audit-full.log`、`stability-audit-recheck.log`、`stability-cleanup-targeted.log`；修复前后探针 `stability-knowledge-before.log` / `stability-knowledge-after2.log`。本轮本地完成，未提交/推送 |
| 2026-10-20 全测试体系精简复核 | Windows 完整无音频 **1108 passed / 26 skipped / 432.86s**；断言迁移定向 **141 passed / 1 Mac 专属跳过**，均零原生音频导入。Ruff、差异检查及 19 个本地文档链接通过。以 `188c99b` 的 122 文件/1190 收集项为基线，修改 36 个测试文件，删除或合并 26 个函数、缩减重复参数/布局循环，净减少 861 行；最终 121 文件/1134 收集项，净减少 56 项 | 方法、保留归属和明确退役范围见 TESTING。Python 3.12.8、PySide6 6.11.2；日志 `.work/reports/test-audit-full.log`、`test-audit-transfers.log`；收集清单 `test-audit-before.txt` / `test-audit-after.txt`，删减与改名审计 `test-audit-scope.json` / `test-audit-collection-diff.json`。26 项跳过仍为 Mac 专属、链接权限和缺原生恢复编译器。单次耗时不构成稳定加速比例；未验 Mac 实机、真实音频/GPU 或安装升级。本批仅改测试和文档，记录提交前验证 |
| 2026-10-20 测试精简与提交前回归 | Windows 完整无音频 **1164 passed / 26 skipped / 478.13s**，零原生音频导入；Ruff、暂存差异检查及 92 个修改文档本地链接通过。退役 6 项外观小项、删除 3 个测试文件，共减少 264 行；保留覆盖与减少的像素检查见 TESTING | 基于 `eb439b1` 加本会话日志、反馈、性能修复及测试精简；Python 3.12.8、PySide6 6.11.2。日志 `.work/reports/test-trim-full-normal.log`；首轮沙箱临时目录创建失败，诊断保留于 `test-trim-environment.log`，未改断言。26 项跳过涉及 Mac 专属、符号链接权限和缺原生恢复编译器。未验 Mac 实机、真实音频/GPU 或安装升级；本行记录提交前证据，不表示安装包发行 |
| 2026-10-20 底层性能审查修复 | Windows 完整无音频 **1168 passed / 26 skipped / 497.17s**；另补清理边界 **2 passed**，均零音频导入。确定性交接暂停、无变化分句缓存、空尾段复用通过；实际隔离进程覆盖主推理进程退出后后代持管道，以及 Windows 拥有者异常退出的 Job Object 回收。Ruff、差异检查通过 | `.work/reports/performance-fixes-full.log`、`performance-fixes-cleanup-boundaries.log`、`performance-fixes-probe.json`。300 秒合成 PCM 的 3000 次写读仅创建 1 个临时文件，读空后 0 字节、关闭后释放；20 次相同文字更新调用分句器 0 次；200 次 Job 创建/关闭后句柄增量 0。分句器计数使用确定性替身，不是 SaT 实际延迟；未验证 Mac 实机、真实设备、GPU 或安装包。本地未提交/推送 |
| 2026-10-20 控制锁、连续导出与 PCM 缓冲回收 | Windows 完整无音频 **1163 passed / 26 skipped / 496.40s**，零原生音频导入；阻塞写入时暂停/停止/切源请求返回、已接受块完成且迟到块拒绝；跨录音同路径导出按请求完成；已消费分段释放、暂停位置和 PCM 次序保留。会话测试独立运行 **17 passed / 1 skipped**；Ruff 与差异检查通过 | 日志 `.work/reports/audit-fixes-full.log`、`audit-fixes-session.log`。初次沙箱运行受临时目录权限阻断；正常目录的定向运行暴露测试替身提前替换 Popen 导致 asyncio 首次导入失败，已修复夹具初始化顺序。隔离写入阻塞与合成 PCM 不代表真实慢磁盘、Mac 实机或真实设备验收；未消费积压仍占磁盘。本地未提交/推送 |
| 2026-10-20 32 MiB 轮转、Mac GPU 采样与低开销日志 | 完整无音频 **1157 passed / 26 skipped / 510.20s**，零音频导入；验证每进程 8 MiB × 4 文件预算、空闲阻塞线程退出排空、UTF-8 与 INFO/ERROR、Mac 驱动利用率白名单/零值/缺值/越界/超大或无效 plist/超时退避及 CPU/RAM 保留。Windows 实际 31 秒 4 次资源采样：主进程 CPU 0.0625s、RSS 增量 159744 B，单次查询墙钟 0.110–0.125s；快照平均 904 B，约 0.31 MiB/h。空闲写盘线程 2 秒内 CPU 增量为计时精度下的 0；5000 条合成解码记录无缺失，入队 p50 9.2µs / p99 26.8µs、平均 367 B。Ruff、diff check、修改文档本地链接通过 | `.work/reports/log-compact-mac-full.log`；探针 `.work/reports/log_compact_probe.py`、`log-compact-probe/results.json`。主进程 CPU 不含 NVIDIA 查询子进程；快照体积取决于进程树大小，合成事件不代表完整课程增长率。Mac 使用系统 ioreg、无需提权或新依赖，当前仅原始源码口径核对与 Windows 协议夹具，未做 Mac 真机数值/开销验收；计数器缺失明确标不可用。首轮相关回归 79 passed / 1 skipped / 2 errors 为同一超大夹具自动测试名触发 Windows 环境变量长度限制（setup/teardown），改短 ID 后全量通过，原始报告保留在 `log-compact-mac-targeted.log`。目录 128 MiB 仍为启动清理目标；未验真实音频/长会话/安装包。本地 windows 未提交/推送 |
| 2026-10-20 全生命周期与资源诊断 | 完整无音频 **1146 passed / 26 skipped / 530.46s**；最终相关回归 **33 passed / 26.80s**（含全量收集后补充的目录容量用例及最终关键操作绑定），零原生音频导入。覆盖慢盘队列上限/省略计数/恢复/退出、坏字段/回传/控制台失败、活跃日志与目录保留、操作关联和进度合并、进程树 CPU/RAM、GPU 缺值/超时退避、采样失败恢复。Windows 原生 Qt 夹具验证新录音、准备、取消和关闭事件；本机 NVIDIA 整卡利用率与显存读取成功。Ruff、diff check 与修改文档本地链接检查通过 | `.work/reports/log-expansion-full.log`、`log-expansion-final-targeted.log`、`log-expansion-probe/{probe.py,results.json,output.log}`。500 条合成记录入队 p50 6.15µs / p99 11.4µs；两次资源查询耗时 0.485s / 0.134s，均在独立探针中，不是实时音频或长期性能验收。首次/新子进程 CPU 未知并标 partial；NVIDIA 未报告该探针的进程显存，不作零占用解释。新增桌面 psutil 7.2.2 及双端锁定哈希；模型环境不依赖它。未验 Mac 实机、真实音频/模型、长时间会话、安装包或断电尾部日志。26 项跳过为平台、符号链接权限或缺原生编译器。本地 windows 未提交/推送 |
| 2026-10-20 准备取消与检查反馈打磨 | 相关 50 项回归通过：综合运行 **49 passed / 1 failed / 104.12s**，失败为旧测试替身缺少真实任务已有的 `cancelled` 状态，补齐后该项 **1 passed / 2.30s**，未删减原断言。覆盖取消后迟到阶段/下载进度、离页持续反馈、继续准备、检查进程启动失败/超时/异常退出/无效 JSON、重新检查成功，以及现有通知、录音入口、保存保护、文件库与布局。正式流程 Demo 使用 Windows 原生 Qt，明暗及 900×650 / 640×480 取消状态截图已核对；Ruff 与 diff check 通过 | `.work/reports/ux-polish-final.log`、`ux-polish-fixture-final.log`；修复前复现见 `ux-cancel-before-normal-temp.log`、`ux-check-reasons-before.log`。截图 `.work/browser/ux-polish/`。全部经无音频 guard，零原生音频导入；其余 UI 用 offscreen，检查子进程用本地夹具。本轮为相关回归，未重跑完整套件；未验 Mac、真实下载/模型/音频、多屏或全部缩放。未提交、推送或发行 |
| 2026-10-19 持久化诊断日志 | Windows 完整无音频 **1131 passed / 26 skipped / 495.22s**，零原生音频导入。覆盖中文日志路径、轮转/过期保留、创建与写入失败、异常隐私过滤、独立进程文件、正常/异常退出解除诊断回调；合成 PCM 验证重叠不重复计为新增音频，真实协议子进程验证会话/解码序号及积压关联。Ruff、diff check 通过 | `.work/reports/diagnostics-full-complete.log` 为最终证据；`diagnostics-lifecycle-final.log` 8 项通过，`diagnostics-protocol.log` 16 项通过。首轮 `diagnostics-full.log` 的 26 项失败来自缺少可选版本字段的替身及连带超时、桌面测试替身缺少后台集合；同时补诊断回调退出清理回归。正常临时目录复测；沙箱临时目录创建失败及早期收集失败记录保留。26 项跳过涉及 Mac 专属、Windows 链接权限和缺恢复编译器。未访问真实设备/运行真实 GPU 模型，Mac 原生、长会话日志开销、驱动崩溃和断电未验；不是完整原生崩溃转储。本地未提交/推送 |
| 2026-10-18 立即录音与加载积压 | 真实 Session / 独立协议子进程配合合成 PCM：运行环境尚未 ready 时 WAV 已保存 32000 个采样；加载期间点击停止仍按序排空，输入输出 SHA256 一致。阻塞推理消费者时输入受到背压，恢复后 100 条音频逐条一致。Windows 原生 Qt 检查加载/追赶/实时文案；暂停中模型 ready 不恢复采集，加载中暂停再继续仍显示加载提示。最终完整无音频 **1122 passed / 26 skipped / 518.22s**，零原生音频导入；Ruff、diff check 通过 | 共享逻辑；真实设备、GPU 追赶速度与 Mac 原生未验，不能保证慢模型必能追上实时。首轮全量暴露 6 项旧前置检查/取消契约，已保留校验及资源释放断言并改为新执行边界；旧失败日志 `record-immediate-full.log` 保留。最终日志 `.work/reports/record-immediate-full-final.log`；26 项跳过为平台专属、符号链接权限和缺原生恢复编译器。定向日志 `.work/reports/record-immediate-*.log`，截图 `.work/browser/immediate-recording/`；离屏缺字截图单独保留，不计中文验收。本地未提交/推送 |
| 2026-10-18 崩溃恢复与停止提交修复 | Windows 真实 Session 写合成 48 kHz PCM，隔离子进程在整块/半块写入后强制终止：读取视图恢复 24000/26400 个采样，逐样本一致；最新原文预览恢复为草稿。新增独立 UI 子进程直接退出用例，验证未正常关闭的 WAV、原文及陈旧锁恢复，原音频字节不变。停止/取消竞态回归修前 **2 failed**，修后 **2 passed**。完整无音频 **1118 passed / 26 skipped / 519.31s**，零原生音频导入；Ruff、diff check 通过 | WAV 只读长度校正和原文保存为共享实现；Mac 原生解码/文件行为、真实设备、GPU 与断电未验。元数据替换前终止仍保留旧有效快照，不采用遗留临时文件；外部工具直接读原 WAV 可能仍受旧头长度限制。证据 `.work/reports/crash-fix-20261018/`（`probe.py`、`results.json`、`cancellation-before.log`、`cancellation-after.log`、`full-no-audio.log`）；26 项跳过为平台专属、符号链接权限及缺原生恢复编译器。本地未提交/推送 |
| 2026-10-18 UI 平台与崩溃恢复审查 | 当前本地源码完整无音频 **1110 passed / 26 skipped / 519.85s**，零原生音频导入；Ruff、diff check 通过。另用真实 Session 写盘、合成 48 kHz PCM、隔离子进程强制终止：完整 5 块后 24000 个采样逐字节一致，旧字幕/锁可恢复；元数据替换前终止保留旧 JSON | 写入第 6 块一半时终止：物理 26400 个采样、头部/读取 24000，应用 PlaybackStream 拒绝回放；最新 source preview 等待 2 秒及触发保存后仍未落盘，重开仅有旧字幕。R23 已改为已复现待修复，未修改恢复实现。日志与可复现探针 `.work/reports/crash-audit-20261018/`（`probe.py`、`results.json`、`full-no-audio.log`）。26 项跳过为 Mac 专属、符号链接权限及缺原生恢复编译器；非真实设备/模型、Mac Cocoa 或断电验收。共享 UI 在 main，远程 mac 仍为 `c23600c`；Windows 自绘边框受平台判断保护。本地审查记录未提交/推送 |
| 2026-10-18 main CI 排查与调度边界补验 | [运行 39124295352](https://github.com/Rand0MGG/agentscribe-local/actions/runs/39124295352) 固定 `0b541f2`；Windows 三版本、静态、两端 SDK/原生渲染通过，Mac 三版本失败于组件示例键盘焦点，3.11/3.12 另有流程动画宽度断言。该提交包含 `beab838` 的测试精简；不包含后续本地 Qwen 调度修复 | 本地为焦点测试补活动窗口前提，动画检查确定中间时刻及双向终态，不假定固定帧到达或变宽；未删用例。Windows offscreen **2 passed**；原生 UI 与识别/暂停/收尾定向 **87 passed / 1 Mac-only skipped**，空闲不重复解码、短尾停止排空通过，Ruff/diff check 通过。`.work/reports/ci-39124295352-failed.log`、`ci-ui-portability-offscreen.log`、`qwen-pacing-and-ci-ui.log`。Mac 修正后 CI、真实 GPU 负载及 HY 竞争未验；本地未提交/推送 |
| 2026-10-18 Qwen 慢首轮后的额外等待 | 新增回归修前 **3 failed**；修后共享 Qwen/MLX 修订、收尾、预览针对性无音频 **67 passed / 4.27s**。同一合成 PCM、模拟慢首轮空结果对照：修前运行时空、停止才出字；修后停止前出字且停止不重复解码。HY 加载受阻、未确认原文也能提前预览；Ruff、diff check 通过 | 移除基于上一轮计算耗时的新增语音门槛，保留刷新间隔、串行队列及定稿规则。仅替身解码器/模拟时钟与实际 worker 提交路径，不证明真实 GPU 首轮速度、质量或用户个案完全解决；R26 继续跟踪。日志 `.work/reports/qwen-pacing-targeted.log`、对照 `.work/reports/qwen-pacing-before-after.txt`；本地未提交/推送 |
| 2026-10-18 静默刷新、菜单对号与指南 | Windows 原生针对性无音频回归 **5 passed / 16.62s**；覆盖模型页进入、环境准备后刷新、手动刷新及删除反馈、指南状态、明暗选中菜单与已有流程。Ruff、diff check 通过，无音频导入尝试 | 截图 `.work/browser/menu-check/`；自动操作不再弹刷新进度/成功，对号独立抗锯齿绘制，指南采用“优化中/已定稿”。另一次包含原文预览的受限执行未产出 pytest 结果后终止，日志 `.work/reports/quiet-refresh-menu-preview.log`，不计通过。用户报告的 Qwen + HY 偶发停止后出字仍待定位（R26），未进行真实音频/GPU 验证；本地未提交/推送/发布 |
| 2026-10-18 正式流程缺陷与 Codex 按钮反馈 | 流程修复完整无音频 **1103 passed / 26 skipped**；随后最后按钮轻叠色调整的 Windows 原生针对性回归 **22 passed**，覆盖组件 Demo、正式流程、布局、录音页、安装 UI、明暗按钮正常/悬浮/按下/禁用像素与几何。Ruff、diff check 通过；无音频导入尝试 | 修复录音异步选择回跳、鼠标焦点残留、8 px 外框、小岛 280ms 双向过渡、窗口内滚动菜单及临时 QAction 生命周期、运行环境独立进度卡、失败原任务重试、已校验组件归档复用/Range 续传。参考本机 Codex 26.1013.4894.0 实际按钮角色，不外推另一套通用组件动画。日志 `.work/reports/workflow-fixes-full-final.log` / `workflow-button-final-targeted.log`；截图 `.work/browser/workflow-demo/`（按钮末次调整前）、`.work/browser/button-feedback/`（末次按钮状态）；参考 `.work/reports/codex-button-reference/REFERENCE.md`。原组件 Demo 未覆盖真实页面链路，新入口 `scripts/preview_workflows.py` 复用正式窗口、独立夹具。模拟下载与本地响应夹具不代表真实服务器续传；未验 Mac、其他缩放、多屏或真实音频/模型。本地未提交/推送/发行 |
| 2026-10-18 正式共享设计迁移 | 完整无音频回归 **1097 passed / 26 skipped**；随后新增的外壳最大化/还原回归与共享控件、悬停原生回归 **3 passed**。Windows 11、Qt Fusion、150% 下生成 **69 张**正式窗口示例截图，核对录音/回放、明暗、菜单、模型与设置 640×480 响应布局；角透明/阴影 alpha 与最大化归零、还原恢复验证通过。Ruff、diff check 通过，无音频导入尝试 | 单一语义主题替代反转/叠层；ChoiceBox、Switch、NameDialog、ResponsiveRow 与圆角阴影为正式共享实现。日志 `.work/reports/design-migration-full.log` / `design-native-tests.log`，截图 `.work/browser/design-migrated/`。原截图脚本错误期待整句 hover 背景，已按既有规范改为文字 hover 且句背景不变。26 项跳过涉及平台、编译器与符号链接权限；Mac 实机、100%/200%、多屏/Snap 人工操作、真实音频/模型未验；本地未提交/推送/发行 |
| 2026-10-18 展示圆角与轻阴影 | Windows 原生展示回归 **1 passed**；明暗截图核对，窗口角像素 alpha 0、外侧阴影采样 alpha 5，确认透明圆角与轻阴影实际绘制。最大化边距归零并停用阴影，还原恢复 12 px 边距与阴影；Ruff 通过 | 仅展示外壳，复用共享阴影参数；截图 `.work/browser/component-lab-frame/rounded-0.png` / `rounded-1.png`。未验 Mac，不代表正式窗口迁移；未提交/推送 |
| 2026-10-18 外框回退纠正与菜单对齐 | 撤掉导致旧式系统外框的 DWM 禁用方案，展示改为无系统标题栏；窗口控制矢量居中，原生最大化/还原检查通过。明暗主题菜单四边实际几何留白均为 **8 px**，反复切换断言通过；修正以已膨胀弹窗高度累加导致底部留白增长。深色次要按钮与菜单悬停实测为 `#424249`，正常按钮为 `#2b2b2e`；截图 `.work/browser/component-lab-frame/` 已核对。Windows 原生展示回归 **1 passed**，Ruff 通过 | 上一轮 DWM 状态成功不代表外框视觉正确，该方案已撤销；本轮仍只改候选展示。offscreen 用例在最后矢量按钮修改前通过，原生用例为最终代码。窗口拖拽与右下缩放未做人工验收，未验 Mac，未提交/推送 |
| 2026-10-18 截图缺陷修正 | 细进度条关闭内绘文字，取消后的百分比在状态行可见；原生展示测试 **1 passed**，覆盖 640×480 / 1100×780 下三个弹窗含阴影边距不越界、长列表滚动/End 选择、缩窗关闭、原有点击/键盘路径。DWM 查询确认当前展示 HWND 非客户区渲染关闭，Qt 无投影标记有效；Ruff 与差异检查通过 | 仅展示版；`.work/browser/component-lab-boundaries/` 保存取消进度与弹窗截图、已视觉核对。系统阴影通过本机 DWM 状态确认，完整桌面外框观感仍由用户评审。Qt 单独 setWindowFlag 未保留该标志，改为 setWindowFlags 后断言通过；Qt 提示本身未关闭 DWM，已补当前 HWND 适配。零音频导入尝试，未验 Mac，未提交/推送 |
| 2026-10-18 展示主题焦点与状态复查 | 修正主题下拉鼠标选择后的焦点边框；窗口路由连续切换主题，鼠标选择后图像与失焦图像一致，Tab 焦点图像有差异。补验保存名称再次编辑/取消、未开始及结束任务切换未知总量、完成与活动任务关闭；相关无音频 **6 passed**，Windows 原生展示测试 **1 passed**。独立原生探针验证菜单禁用/Escape、开关反向/减少动态效果、长值缩窗、切页停止追加 | 仅候选展示，正式页面不变；明暗/宽窄 16 张图在 `.work/browser/component-lab-audit/`，检查了窄窗口菜单页、字幕页、任务页。零原生音频导入尝试，Ruff 与差异检查通过；不代表所有 UI 缺陷已排除，未验 Mac、多屏、真实中文输入法、音频或模型；未提交/推送 |
| 2026-10-18 下拉点击路径纠正 | 原生 QWindow 事件复现旧实现关闭后重开；修复后 3 个下拉各连续 6 次点击按开/关交替，展开箭头像素变化断言通过。展示测试 Windows 原生与 offscreen 各 **1 passed**，零音频导入尝试；主要按钮明暗悬停实测背景从 `#29292d` 到 `#505057`、`#ededf0` 到 `#bebec8`，截图已核对 | 上一轮直接向 QWidget 发事件未覆盖 Qt 弹窗关闭后的点击回放，不能作为该问题已解决的证据。此次通过活动弹窗 QWindow 路由，并等待排队事件；仍不是人工鼠标或 Mac 验收。仅改候选展示组件，截图在 `.work/browser/component-lab-polished/`；未提交/推送 |
| 2026-10-18 展示组件交互打磨 | 最终无音频相关回归 **6 passed**；新增的下拉反复开关、外部点击关闭、方向键/Enter/Escape、明暗主题禁用文本区分、开关鼠标/键盘焦点及禁用操作断言通过，同一展示测试在 Windows 原生 Qt 下 **1 passed**。Ruff 与差异检查通过 | 仅展示脚本中的候选组件与样式，正式共享实现未迁移；无音频导入尝试。明暗主题与宽窄窗口 16 张截图在 `.work/browser/component-lab-polished/`。QTest 事件不等同人工全流程验收；未验 Mac、多屏、真实音频或模型。沙箱临时目录失败后，同一相关回归在正常权限下通过；未提交/推送 |
| 2026-10-18 独立 Qt 组件展示 | `test_component_lab.py`、`test_caption_view.py`、`test_ui_experience.py` 最终无音频回归 **6 passed**，零原生音频导入尝试；展示脚本/新增测试 Ruff、文档本地链接和差异检查通过。新增测试覆盖候选输入校验、合成 IME 事件、取消不提交、手动阅读锚点、任务收起/失败/重试、未知总量与活动任务关闭 | `windows`、`beab838` 上的本地展示脚本与文档修改，正式页面未改；Windows 原生 Qt/Fusion 150% 下生成明暗、1100×780 与 640×480 的 16 张客户端布局图，位于 `.work/browser/component-lab-native/`，另有 offscreen 图。沙箱默认临时目录曾报创建失败；最终 6 项在正常本机临时目录权限下执行。原生界面已生成供人工体验；合成 IME 不证明真实中文候选框操作。未验 Mac、多屏、真实设备/模型或正式业务流程；未提交/推送 |
| 2026-10-18 全仓库测试审查与精简 | 完整无音频 **1096 passed / 26 skipped**，零原生音频导入尝试；Ruff、差异检查通过。删除旧音频配置的 2 个无平台分支重复参数用例，保留读写兼容与 Mac 设置恢复覆盖；默认 beta 断言移出 13 组存储值参数，全部有效/损坏输入仍保留 | `windows`、`531622b` 加既有本地修改；Windows/Python 3.12，正常 pytest 临时路径及本机权限。全仓库测试盘点与候选对照见 `.work/reports/test-audit-20261018/audit.md`，完整日志 `full.log` / `full.xml`。26 项跳过为 Mac 专属、符号链接权限或缺原生恢复编译器；失败、取消、数据保护及原生平台用例未删改。此轮仅改测试和验证规范/记录，未验 Mac 实机、真实音频/模型或安装升级；未提交、推送或发布 |
| 2026-10-18 首次配置、翻译恢复与安装提示 | 相关回归 89 项分批验证：88 passed / 1 Mac 原生菜单跳过；首次推荐与旧语言重开覆盖 Windows/Mac 配置模拟，翻译缺失→仅识别→恢复及主动关闭通过；结构化阶段、真实子进程错误诊断和取消回收通过；Ruff/差异检查通过 | `531622b` 加本地修改，Windows/Python 3.12、无音频导入。初次批次 87 passed / 1 failed / 1 skipped：取消测试依赖已删除的原始进度信号，改为结构化启动事件后安装用例 29 项全过；最终反馈/界面及宽窄预览 11 passed / 1 skipped。合并本次新增的 3 个重复独立测试，保留关键失败/取消断言。截图 `.work/progress-preview-20261018/`；Mac 为配置模拟，未验 Cocoa 实机、真实下载/安装或音频；未提交发布 |
| 2026-10-17 v0.10.0 Mac 应用内更新 | 固定产物 `95fa8c3`，原更新公钥签名核验；真实 0.9.2→0.10.0 升级、取消、断网、篡改拒绝、启动失败恢复及数据保留均通过；stable/beta 订阅已部署，原始 0.9.2 包经生产 HTTPS 订阅升级通过 | [原生故障验收](https://github.com/Rand0MGG/agentscribe-local/actions/runs/39029582117)、[订阅部署](https://github.com/Rand0MGG/agentscribe-local/actions/runs/39030015716)、[生产升级](https://github.com/Rand0MGG/agentscribe-local/actions/runs/39030120035)。一次性 macOS 15 arm64 runner；本地签名/订阅回归 18 passed。证据 `.work/releases/v0.10.0/mac-update-acceptance/`；录音/保存门禁为模拟状态，未验真实采集或 Windows 原生升级；Mac ad-hoc、未公证 |
| 2026-10-17 0.10.0 构建前检查 | 源码、项目元数据及 Mac 包内说明统一为 0.10.0；封装/偏好/语言与导出搜索定向 70 passed / 1 skipped，完整 Ruff 与差异检查通过 | Windows Python 3.12；`.work/reports/v0100-preflight.xml`。跳过为链接权限；此前完整回归及后续定向证据见下方。两端候选构建须独立通过完整无音频回归及最终包探针，当前记录不代表安装包或 Release 已发布 |
| 2026-10-17 同语言自动关闭翻译 | 语言同步专项 1 passed，偏好与录音小岛相关 31 passed；覆盖全部语言、设置/弹层双向同步、自动检测、简繁区别、保持关闭、活动会话设置不变及偏好恢复；Ruff/差异检查通过 | Windows Qt offscreen，无音频导入；日志 `.work/reports/language-selection-20261017.xml`、`language-related-final-20261017.xml`。只更改共享界面设置联动，未验 Mac 原生或真实识别翻译，未提交发布 |
| 2026-10-17 文件夹行加号移除与侧栏对齐 | 文件夹行内加号、信号和点击热区移除，保留标题新建按钮及行菜单；导航图标按 20px 绘制，与根文件夹可见笔画和文字列对齐。Windows 原生明暗/宽窄窗口探针 1 passed，录音页回归最终 4 passed，Ruff/差异检查通过 | 初次新增用例按对象身份比较刷新后的文件夹行失败，改为稳定 ID 后通过；日志 `.work/reports/sidebar-row-plus-final-20261017.xml`、`sidebar-row-plus-recheck-20261017.xml`，截图 `.work/browser/sidebar-alignment-20261017/`。150% 缩放，无音频导入，未验 Mac 原生，未提交发布 |
| 2026-10-17 新录音按钮样式统一 | 移除独立 15px 字号，复用侧栏导航样式；Windows 原生 1280×840 / 640×480、150% 缩放、明暗主题及禁用状态视觉复核，字号/高度/对齐和点击返回待录音页探针 1 passed，已有字幕反馈回归 3 passed | 初版探针错误要求点击立即创建录音，按现有待录音契约纠正后通过；原始/最终日志 `.work/reports/new-recording-button-20261017.xml`、`new-recording-button-final-20261017.xml`，截图 `.work/browser/new-recording-button-20261017/`。无音频导入，未验 Mac 原生；只删局部样式，无平台逻辑变更，未提交发布 |
| 2026-10-17 导出/备份反馈与搜索分页修复 | 正常本机权限下定向 38 passed，覆盖队列持续进度、收起/新任务、失败/取消、备份恢复与跨页搜索；Windows 原生明暗主题截图补验 1 passed；Ruff、差异检查通过 | 初次受限运行 34 passed / 3 课程子进程超时，正常权限复查全过；日志 `.work/reports/export-search-20261017.xml`、`export-search-native-permissions-20261017.xml`、`export-search-visual-native-20261017.xml`。offscreen 字体缺失后另验原生截图 `.work/browser/export-search-20261017/`。零原生音频导入，未验 Mac 原生、真实音频或发行包；未提交发布 |
| 2026-10-17 回看悬停背景移除及体验续查 | 字幕反馈及用户流程 25 passed；字幕交互与体验缺口探针 4 passed。明暗主题悬停背景不变，按压/待触发反馈、播放高亮及文字选择边界保留；Ruff、差异检查通过 | Windows Qt offscreen，无原生音频导入。日志 `.work/reports/hover-20261017.xml`、`hover-audit-20261017.xml`；审查探针 `.work/test_hover_ux_audit.py` 用受控写入和模拟通知到期确认 R21，用 150 条合成字幕确认 R22，探针通过不代表缺口已修复。未验 Mac 原生或真实音频，未提交发行 |
| 2026-10-17 操作反馈与断线恢复修复 | Windows 完整无音频 **1093 passed / 26 skipped**，零音频导入；覆盖进度保留、收起后的取消入口、识别原因、模型检查重复/取消/迟到回执、新录音不扫描全库、真实课程子进程退出及重连保留草稿。最后的模型状态/关闭补验 1 passed，浅深主题及窄窗口视觉探针 1 passed；Ruff、差异检查通过 | `18c23fc` 加保留的本地改动；Python 3.12.8 / Qt 6.11.2。完整回归用正常本机权限及默认 pytest 临时路径；受限环境的 Python asyncio socketpair 初始化阻塞已独立定位，未改业务绕过。跳过为 Mac 专属、链接权限及缺原生编译器；汇总 `.work/reports/ui-feedback-20261017.json`，截图 `.work/browser/ui-feedback-20261017/`。Qt offscreen 仅验客户端布局，Mac 原生、真实音频/模型/供应商及安装升级未验；未提交发布 |
| 2026-10-17 P1 与用户流程修复 | Windows 完整无音频 1086 passed / 26 skipped；最终课程/视觉专项 40 passed；Python 3.11/3.13、Qt 6.12 各 21 项及来源缓存专项各 1 项通过。真实 PDF/PPTX 离线原页、文本分片、术语导航/退出、后台读库及浅深主题/窄窗口走查通过 | `windows`、`18c23fc` 加本地修改；全量为 Python 3.12.8/Qt 6.11.2，最后的任务内校验复用及新增用例由 40 项补验覆盖。原始失败、最终日志和截图：`.work/reports/ux-fixes-20261017/`，汇总 `validated-results.json`；初次保存回执/视图同步假设已纠正，未放宽截止时间。跳过为 Mac 专属、链接权限及缺原生编译器，零音频导入；未验 Mac 原生、真实音频/模型/供应商或安装升级，未提交发布 |
| 2026-10-17 用户流程审查 | 7 个探针复现跨录音术语丢失、浅色课程面板难读、具体错误被隐藏、窄设置页长路径溢出；核对 NLLB 截断、文本原生块与 PDF 离线预览缺口。101 条合成录音约 77 MB，库刷新/打开分别同步阻塞约 0.43/0.36 秒 | Windows，`18c23fc` 加 CI 修复，Python 3.12.8/PySide6 6.11.2；真实 Qt offscreen、临时库及适配器替身。`.work/reports/ux-review-20261017/audit-findings.json` 含源码定位、截图和分项证据。探针断言缺陷，执行通过不代表问题已修复；计时仅为本机单次观察，无设备、模型或供应商调用。待办归 ROADMAP |
| 2026-10-17 CI 测试修复与渲染排查 | Windows 无音频 1067 passed / 26 skipped；3.11/Qt 6.12 定向 57 passed / 2 skipped；3.13/Qt 6.12、cp1252 环境关键回归 6 passed。固定子进程 UTF-8、等待实际业务状态；渲染进程成功/失败/取消及安全退出码日志通过，Ruff/差异检查通过 | `windows`、`18c23fc` 加本地修改；全量为 Python 3.12.8/Qt 6.11.2，之后的取消等待调整由 3.11/3.12 各 3 项补验覆盖。跳过为 Mac 专属、链接权限或缺原生编译器；零音频导入。命令/环境及控制台摘要：`.work/reports/ci-fix-20261017/validated-results.json`，非完整日志。Mac 原生异常未关闭；当时未提交/推送/发布 |
| 2026-10-17 长录音、术语归属与保存恢复 | 完整桌面无音频 1087 passed / 2 Windows 专项跳过；长短字幕跨页定位及相关滚动/回听补验 5 passed，最终 Cocoa 专项 11 passed。覆盖 200 段分页、搜索/回听跨页、手动阅读位置、课程草稿隔离和旧回执、保存失败锁竞争、持久重试入口、草稿/即时原文 TXT 备份、取消/写失败/新文字/关闭确认边界，以及具体错误原因展示 | 基于 `c23600c` 加本地修改；macOS 26.6.2 arm64、Python 3.12.14、PySide6 6.11.2。完整收集未包含最后新增的长短字幕用例，该用例和最终滚动修改由 5 项补验及 Cocoa 11 项覆盖。初次受限运行有 19 项图形会话/本地端口权限失败，桌面会话完整复查通过；没有绕过检查。日志 `.work/reports/ux-audit-20261017/`，640×480 / 1280×840 示例窗口图 `.work/browser/ux-fixes-20261017/`。均使用临时数据及模拟会话，无原生音频导入尝试；未验真实录音、Windows 原生、安装升级。该批验证发生于版本号更新前；`0.9.3` 的源码/包内说明版本一致性检查、Ruff 与差异检查通过；版本、封装、更新及原生版本菜单补充回归 78 passed（`version-093-checks.log`）。源码集成不代表安装包发布 |
| 2026-10-16 通知/模型/更新检查复核 | 完整无音频 1073 passed / 2 Windows 专项跳过；最终状态保护 16 项补验、Cocoa 3 项通过。删除通知详情入口；更新安装操作不再自动消失；模型检查异常不冒充缺失，设置/文件复查不覆盖准备结果，取消不误报失败 | `64cb54c` 加本地修改；完整运行后增加的状态保护已包含在最终补验。日志 `.work/reports/followup-audit-*.log`、`preparation-feedback-*.log`、`remove-notification-details-*.log`。失败子进程为模拟故障，未重现用户此前首次下载失败，未执行真实下载/采集或 Windows 原生验收，未打包发布 |
| 2026-10-16 v0.9.2 Mac 应用内更新 | 固定来源 `13d2a33`；真实 0.9.0→0.9.2 下载、安装、正常重启及数据保留通过；中断、取消、篡改拒绝、启动失败自动恢复通过。原始旧包访问生产 HTTPS 订阅再次升级通过 | [构建](https://github.com/Rand0MGG/agentscribe-local/actions/runs/38882483285)：1039 passed / 24 平台或可选组件跳过、真实 Sparkle 回调与 DMG 探针通过；[故障验收](https://github.com/Rand0MGG/agentscribe-local/actions/runs/38886470827)、[生产升级](https://github.com/Rand0MGG/agentscribe-local/actions/runs/38887571571)。一次性 Mac runner；录音/保存门禁为模拟状态，未验真实采集或 Windows 原生升级。原钥匙串签名、订阅部署完成，仍为 ad-hoc、未公证 |
| 2026-10-16 更新状态修复阶段 | 本地完整无音频 1065 passed / 2 Windows 跳过；真实 Sparkle 的后台 404→手动重试→取消通过；渠道 18 项、更新/保存 43 项及最终 UI 9 项通过 | `.work/reports/update-e2e-20261016/`；完整运行后补了渠道与按钮反馈，定向补验通过。此行仅记录源码阶段，后续完整包与生产升级证据见上一行 |
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

2026-10-17 功能修复前的文档整理批次，修正安装/通知指引，补 R19 及 spec/验收；当日核对 GitHub Release。62 份 Markdown 的 327 个本地引用、39 个标题锚点及差异检查通过。当时仅改文档、未重跑应用验收；摘要：`.work/reports/docs-update-20261017/validation.json`。后续功能修复与验证见上表。

## 已发布产物

2026-10-16 [v0.9.2](https://github.com/Rand0MGG/agentscribe-local/releases/tag/v0.9.2) 已发布 Mac arm64 DMG、构建清单、SHA256 和原公钥 Ed25519 签名，四个附件均核对摘要。DMG 为 312067290 字节，SHA256 `1dcb9c7b33bfd2b76452c022c30b8b9363aa68e11cbd35a51fe87bd7598ca3e3`；[部署 38887341353](https://github.com/Rand0MGG/agentscribe-local/actions/runs/38887341353) 已完成，固定 stable/beta 地址无认证返回 200。证据保留于 `.work/reports/update-e2e-20261016/`。此前 v0.9.1 的“未推进订阅”仅指该历史批次；本轮未发布 Windows 包，Apple 公证未完成。
