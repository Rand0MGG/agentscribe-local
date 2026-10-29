# 测试规范

测试验证用户可观察的结果和 [spec](specs/README.md) 的约束；代码与测试一致仍不等于行为合理。纯文档修改检查事实、引用和差异，不必启动应用、安装依赖或运行模型。

## 测试重要程度

按测试保护的实际后果分四级，数字越小越重要；测试层次、是否使用替身、运行耗时和执行环境不决定等级。

| 等级 | 判断标准 | 示例 |
| --- | --- | --- |
| P0：安全与重大损失 | 损害系统、其他程序、用户数据或隐私，或产生未授权费用 | 路径越界写入、误删文件、误杀进程、不可信更新执行、未授权上传或付费调用、已有录音不可恢复地丢失 |
| P1：核心流程 | 录音→识别→分句→翻译→保存主流程无法完成，或核心结果明显错误；不涉及 P0 后果 | 无法开始/停止、音频遗漏、字幕修订错误、翻译错配、保存失败但结果仍可恢复、启动/退出卡死 |
| P2：独立功能 | 具体功能失效，但核心流程仍可正常使用 | 搜索、可选导出格式、课件解析、回放定位、可选模型管理 |
| P3：使用体验 | 功能与结果正确，主要影响展示、便利性或流畅度 | 排版、动画、提示位置、非关键文案、轻微卡顿 |

等级依据明确的失败路径：已有文件被破坏属于 P0，导出格式错误通常属于 P2；模型准备失败若阻断首次识别属于 P1，仅某个可选模型不可用通常属于 P2。不能因极端假设任意升级，也不能把文件名含 UI、feedback 或 appearance 当作低等级依据。

现有 `tests/test_*.py` 用例均使用 `@pytest.mark.p0` 至 `@pytest.mark.p3` 标注，一个用例一个等级，不在整个混合文件上统一打标。新增或实质修改用例时同步评估，不能按名称批量推断或将漏标当成 P3。可通过无音频入口追加 `-m p0` 或 `-m "p0 or p1"` 筛选；默认回归仍运行全部测试，CI 不因分级缩减范围。标记与参数化顺序不改变原有平台、组件或权限跳过条件。

拆分以独立失败原因和可独立运行的场景为边界：更新身份/渠道与信任拒绝、导出内容与写失败保护、错误恢复与提示几何等应分别验证。拆分后保留原断言及参数边界，共享必要准备，不复制整套业务流程。正常流程中的数据保护、资源释放和退出检查若是该场景结果的一部分，应保留在原流程中，按实际主要风险定级；不能为了凑出单一等级移除这些检查。P2/P3 不自动等于可删，是否精简还要检查重复覆盖与维护收益。

P0/P1 优先作为相关改动的验证门禁，P2 按受影响功能选择，P3 按相关体验改动选择。等级不授予设备、模型、网络或付费调用权限，也不替代目标平台和发布验收。

### 2026-10-23 全仓库评估

已按用例核对 118 个文件、683 个测试函数；实际 pytest 收集 1100 项，每项恰有一个等级，无漏标或重复标记。源码标记为维护依据；参数化会增加执行项数，不代表新增测试函数。

| 等级 | 测试函数 | 参数展开后的收集项 |
| --- | ---: | ---: |
| P0：安全与重大损失 | 149 | 284 |
| P1：核心流程 | 402 | 627 |
| P2：独立功能 | 128 | 184 |
| P3：使用体验 | 4 | 5 |
| 合计 | 683 | 1100 |

本表反映当前源码标记分布；后续复核确认的分级遗漏、测试漏检及精简候选见 [测试代码审查](testing/TEST_CODE_REVIEW_20261023.md)。其中混合导出/防覆盖和术语草稿保护的分级尚待修正，不能把“全量有标记”当成分级判断已经没有缺口。

本次边界处理：

- 活跃录音的 PCM/字幕遗漏、修订错配和停止卡死为 P1；已有录音/资料/用户编辑被覆盖或误删、跨目录写入为 P0。迁移、回放和模型处理流程中实际验证原件不变的用例保留完整操作上下文，不抽出空泛的“文件仍在”断言。
- 未授权设备初始化、云端许可、付费预算、日志中的用户内容、安装包信任和进程停止归属为 P0；受控后台任务关闭、超时和失败恢复通常为 P1。课程结果正确性通常为 P2，涉及上传许可或用户笔记保护时为 P0。
- 搜索、回放定位、独立导出格式、课程文档渲染和更新检查通常为 P2；模型准备或页面操作若阻断首次识别、录音/保存/退出，则为 P1。通知的恢复入口按所保护的流程评估，不能统一降为体验级。
- 默认中文录音名的 locale 格式化用例会复现创建录音时的异常，属于 P1，不因名称文案降为 P3。已知可重新准备的内置模型缓存/转换失败属于 P1；不能仅因断言含“原文件保留”就假设为不可恢复的个人资料损失，涉及自定义文件、越界删除等明确风险时才升为 P0。
- 评测计分器正确性与架构约束为 P2；测试基础设施按其保护的风险评估，例如无音频防护为 P0，不能忽略的 Qt/子进程失败和集成跳过门禁为 P1。P3 数量少，与此前已退役大量外观/动效专用门禁有关，不意味着其余未执行的体验检查已验收。

独立脚本不由 pytest 收集，也不计入上表；其验收职责如下，不能通过 `-m` 筛选：

| 脚本入口 | 风险等级与范围 |
| --- | --- |
| `smoke_session.py`、`smoke_wlk.py`、`smoke_loopback.py` | P1：真实会话/模型/设备主流程；设备与播放仍须单独授权 |
| `check_hy_translation.py`、`check_llama.py` | P1：实际翻译后端生成与退出 |
| `replay_streaming.py`、`benchmark_qwen.py`、`benchmark_ami.py` | P1：识别主链路质量、延迟与资源；报告格式/计分辅助职责为 P2 |
| `evaluate_streaming.py`、`compare_classroom.py` | P2：参考文本审计、评分与比较，不证明实时录音链路 |
| `probe_package.py`、`probe_macos_package.py`、`probe_packaged_launcher.py` | P0：设备防护与启动隔离；P1：封存包启动、通信与退出 |
| `probe_macos_update.py` | P0：封存包信任与替换边界；P1：真实升级/重启/故障恢复，仅在一次性 Mac runner 运行 |

本轮只新增等级标记和必要的 pytest 导入，未继续拆分、删除测试或修改业务；上一节拆分原则及下节首批拆分记录继续有效。复核快照为 `.work/reports/full-test-priority-assessment-20261023.json`，逐收集项清单为同目录 `full-test-priority-collection-20261023.json`。运行证据与限制见 [VALIDATION](VALIDATION.md)。

### 2026-10-23 首批跨等级用例拆分

本轮将四个测试文件内的 6 个混合函数拆为 13 个独立函数，分别标注等级；参数展开后由 9 项变为 19 项。没有删除断言或产品功能，也没有为其余测试批量推断等级。

| 文件与原场景 | 拆分后的独立职责 |
| --- | --- |
| `test_recording_export.py` 普通导出 | Unicode 内容写出 P2；发布失败保留已有文件及清理临时文件 P0，均保留全部格式参数 |
| `test_recording_export.py` 恢复备份 | 草稿/过期译文恢复内容 P1；发布失败保护旧备份 P0 |
| `test_user_workflows.py` 更新身份 | 平台/渠道 P2；缺失信任公钥拒绝 P0，均保留两端参数 |
| `test_user_workflows.py` 通知 | 保存错误的重试入口及跨页保留 P1；进度/优先级 P2；不挤动工作区 P3 |
| `test_interaction_fixes.py` 浮窗 | 当前/修订/隐藏期间字幕同步 P2；隐藏控件释放阅读空间 P3 |
| `test_ui.py` 重译与损坏录音 | 失败重译保留可用结果并重试完成 P1；拒绝损坏录音并保留原文件和当前视图 P0 |

回放增益流程中的“原始 WAV 不变”和资源关闭，以及保存/迁移流程中的数据完整性检查继续随原场景验证，不为等级拆出脱离操作上下文的断言。代价是部分 UI 场景增加独立进程启动，收益是各等级可独立执行且失败原因更明确。实际验证范围与环境限制见 [VALIDATION](VALIDATION.md)。

## 默认安全入口

Windows PowerShell：

```powershell
.venv\Scripts\python.exe scripts/test_no_audio.py -q -rs
.venv\Scripts\python.exe -m ruff check linguaflow scripts tests
git diff --check
```

macOS：

```bash
.venv/bin/python scripts/test_no_audio.py -q -rs
.venv/bin/python -m ruff check linguaflow scripts tests
git diff --check
```

可在无音频入口后指定测试路径。它阻止当前及继承环境的 Python 子进程导入项目原生音频后端，使用 offscreen，并拒绝任何音频导入尝试；不替代对外部命令/原生 API 的检查。常规验证使用此入口；未获授权不枚举设备、采集、播放、改系统设置或中断用户录音。

既有 Mac 录音保护继续有效：用户未明确结束录音或允许前，不枚举/访问设备、采集、播放、改系统音频设置或中断用户进程。文件推理和取消内存中止阈值的既有授权，只能按可定位原用户指令的输入、对象、阈值和范围沿用，不扩大到设备操作；保留相应超时和资源记录。[Mac 文件推理记录](archive/testing/MACOS_FILE_TESTS_20261006.md) 保留当时的限制与后续授权变化，记录本身不授予新测试权限。

开发优先 Python 3.12，兼容范围以 `pyproject.toml` 为准。优先项目环境；新兼容版本使用隔离环境，记录 Python 和实际 PySide/NumPy 等版本，不能把依赖变化归结为“只换 Python”。保留 pytest 正常临时路径和真实中文/深目录场景；显式短路径仅用于对照，不能成为隐藏产品缺陷的通过条件。

## 按改动选择验证

| 改动 | 必要验证 |
| --- | --- |
| 纯逻辑/缺陷 | 先复现，再测修复及失败/取消边界；断言行为，不镜像实现 |
| 配置/保存/路径 | 旧/缺失/损坏字段、写失败、原子性、旧回执、中文/空格/深路径、真实映射与权限 |
| 异步/UI/资源 | 活动任务中关闭、重复取消、迟到结果、事件循环响应、真实关闭与线程/进程释放；相关窗口尺寸与缩放 |
| 共享流程/广泛修改 | 完整无音频回归和静态检查；两端分支模拟，再补目标系统实测 |
| 课程 SDK/渲染 | 实际 SDK/引擎集成，完整页内容/资源解码、取消释放和许可；替身结果单独标注 |
| ASR/分句/翻译/DSP | 同输入/环境基线对照，完整文件链路、原文与译文对应、质量/延迟/资源；不能只测函数速度 |
| 音频/权限/录音生命周期 | 经授权在目标机测选源、开始/取消/暂停/继续/切换/停止、保存回听和退出 |
| 打包/升级 | 最终封存包探针及旧包→候选包安装、签名、恢复、用户数据与环境兼容；见 [RELEASING](RELEASING.md) |

常用回归定位：`test_capture_control.py` / `test_wlk_session.py`、`test_recording_save.py` / `test_recording_document.py`、`test_translation_*.py` / `test_qwen_*.py`、`test_knowledge_*.py`、`test_ui_*.py`、`test_packaging.py` / `test_update_*.py`。实际选择以调用关系为准，不强制每次重跑无关模型。

UI 改动须按 [Demo 一致性契约](UI_DESIGN.md#demo-一致性与优先复用)，核对组件 Demo、正式流程 Demo 与受影响正式页面：同主题、尺寸及状态比较外观，同操作序列验证交互、动效和恢复。组件 Demo 作为按需人工检查入口；自动回归优先 `test_workflow_preview.py` 的准备/恢复流程及对应核心页面测试，不恢复外观细节专用门禁。新增共享能力按需要补 Demo 场景。仅改规范文档时检查链接与契约一致性，不以未执行的 UI 检查作验收声明。

## 通过条件与 CI

- 缺陷测试应能在修复前失败。修根因，不靠生产测试专用分支、假算法、吞异常、无条件重试、删测试或放宽断言换绿；测试替身留在测试侧。
- 精简重复测试须指出保留用例如何覆盖被删断言；名字或结构相似不等于重复。明确退役的低优先级检查应说明减少的覆盖，不冒充等价替代。只在参数确实改变执行路径或输入边界时保留参数化，不为减少数量合并不同的失败、取消、数据保护或平台契约。
- UI 使用独立进程隔离 Qt 应用类型；共用 `tests/ui_support.py` 的有期限等待、退出和日志检查。`close()` 被调用不等于关闭成功，零退出码也不能掩盖 Python 绘制回调异常或 QPainter/QThread/QProcess 销毁警告；不能只在任务空闲后测退出。
- Electron 基础、交互、全链路及对照探针复用 `desktop/scripts/close-workspace.cjs`：关闭 IPC 的正常上下文销毁不当作业务失败，仍要求页面关闭、真实进程退出码 0、无终止信号，并等待已记录 PID/创建时间的自有辅助进程退出，之后才卸载成品 DMG；不终止或等待其他应用。
- 图片/网页要检查真实解码/页面内容，不能仅检查 HTML 含标签。状态等待有截止时间，布局稳定与业务结果分别断言，不用固定短 sleep 调整通过率。
- 动画中途反向须在渲染帧内同时读取当前尺寸并激活反向动作，保留真实中间帧与最终尺寸断言；历史采样不能保证下一次跨进程读取仍处于动画中途。
- 跨进程中文断言同时指定子进程输出和父进程解码的 UTF-8，不能依赖机器区域设置。通知等待实际收起，字幕定位等待目标卡片进入视口；窗口尺寸稳定不能代替业务完成。
- `.github/workflows/checks.yml` 是 CI 矩阵的执行权威：两端 Python 3.11–3.13 无音频回归，Python 3.12 另做课程 SDK 和原生文档渲染，Ruff 独立执行。专用集成设置 `AGENTSCRIBE_REQUIRE_INTEGRATIONS=1`，选中用例有跳过即失败。
- 普通无音频、课程 SDK 和原生文档渲染任务均在测试前安装并构建 Electron；构建通过 `AGENTSCRIBE_DESKTOP_PYTHON` 使用 `setup-python` 输出的完整解释器路径，不假定这些任务存在 `.venv`。独立 Electron 任务仍使用其专门创建的 `.venv`。
- 修改上述准备步骤时，在不含 `.venv` 的隔离源码目录验证前端构建，并通过无音频入口运行 `tests/test_knowledge_ui.py::test_new_format_import_filter_and_local_preview_without_cloud`，检查真实本地图片预览；YAML 检查不能代替运行验证。
- 普通回归列出跳过原因：平台不适用、缺组件、缺权限或尚未部署分别说明。模拟链接不能证明真实映射保护；另一平台模拟不能替代实机。
- Cocoa 原生预览须有窗口服务，受限环境用 offscreen。预览入口 `scripts/preview_workspace.py --capture --output .work/browser/ui-design-<平台>` 使用示例库/设置，不能代替原生框架、权限、真实音频或 GPU 验收。

### 流程测试与故障边界的分工

正常路径优先复用已有完整流程，在同一个任务中检查输入、状态转移、结果持久化及资源释放；不要另建一套“完整流程”框架，也不要把不相关的故障拼成一个大测试。外部设备、模型输出与网络响应可以使用确定性夹具，文件库、保存器、会话线程及进程通信仍走真实实现。不同层次的测试不能互相冒充：Window 的模拟 Session 验证界面编排，真实 Session/worker 子进程验证通信与排空，两者都不证明真实模型质量。

| 主流程入口 | 覆盖职责 | 仍独立保留的边界 |
| --- | --- | --- |
| `test_ui.py::test_named_recording_start_finish_and_settings_routes` | 草稿命名/选文件夹、开始、暂停/继续、停止、保存、删除恢复与退出 | 异步保存旧回执、失败重译、损坏录音、无效启动 |
| `test_ui.py::test_preferences_roundtrip_and_recording_guards` | 重开持久化、录音中保护 | 损坏/旧配置解析、平台专属菜单与设备分支 |
| `test_library_defaults.py` / `test_recording_page.py` | 空库恢复默认目录、过期目录选择、空目录菜单、新工作区保留旧录音 | 默认目录写入失败单独运行；非法名称及旧文件保护继续断言 |
| `test_wlk_session.py::test_captured_pcm_drains_to_wav_and_correlates_with_capture_log` / `test_runtime_preparation.py::test_successful_sessions_reuse_process_with_fresh_language_and_audio` | 合成 PCM 经真实 Session、子进程与 WAV 写入，核对排空、诊断关联和跨会话进程复用 | 加载中停止、暂停/切源、后代占管道、超时、取消、清理失败重试 |
| `test_library.py::test_reopen_keeps_revisions_and_exports_only_final` | 保存、重开、字幕修订、草稿过滤、初译元数据和导出标记 | 原子写失败、路径越界、重名、删除恢复冲突、迁移校验 |
| `test_workflow_preview.py` / `test_workspace_appearance.py` | 正式窗口导航、准备失败重试/取消、本地 HTTP 下载跨页进度 | 迟到进度、下载归属、未完成任务退出、实际传输取消 |

UI 测试统一从 `ui_support` 导入：`run_ui` 创建无设备发现的正式窗口；`run_ui_process` 运行需要自行初始化的隔离脚本。两者共用超时、UTF-8 输出、真实窗口关闭和 Qt 错误检查，保留调用方原超时及平台环境。专用预览、原生平台诊断或并非 Window 的进程探针保留自身启动协议。测试模块不再从 `test_beta_features` 借用夹具。

### 当前取舍：2026-10-21 低优先级检查退役

按用户“重要程度不高的测试都去掉”的要求，本轮直接删除低优先级门禁，不把断言搬进大用例。以上一轮结束的 **1135 个收集项、713 个测试函数、19722 行测试 Python** 为基线，退役 **47 个函数、57 个收集项、6 个完整文件**；保留 **1078 个收集项、666 个函数、17809 行**，净减 **1913 行（9.7%）**。此前的流程归并记录仅说明当时状态，后续退役以本节为准。

| 退役范围 | 取消的自动覆盖 |
| --- | --- |
| 整个 `test_component_lab.py` | 演示页自身的控件交互、主题焦点、像素、IME 示例、弹窗边界和模拟任务；演示脚本保留，正式业务的取消/退出另有测试 |
| 整个 `test_ui_alignment.py`、`test_ui_island.py` | 标题/摘要/长设备名几何、小岛尺寸/动画/控件边界、录音时钟文案和空设备菜单的专用检查 |
| 整个 `test_playback_controls.py`、`test_caption_changes.py`、`test_quiet_refresh_and_menu.py` | 平滑跟随帧轨迹、修订提示措辞、自动/手动刷新提示细节 |
| `test_caption_view`、`test_caption_feedback`、`test_interaction_fixes` | 平滑跟随/触控板阶段、文字命中区域更新、滑杆和提示气泡、回放箭头和句子偏移；仍保留字幕点击/选择、录音禁播、真实流关闭和 tooltip 销毁 |
| `test_ui_presentation`、`test_responsive_transport`、`test_startup_workspace_polish`、`test_ui_model_overlay` | 刘海/工具栏布局、逐字动画、对比度/壁纸平台样式、阴影边距、时间显示和按钮显隐、窄窗滑杆、首启下载路由、顶部渐隐、浮窗拖拽/字号/透明度 |
| `test_ux_journeys`、`test_window_platform`、`test_ui_backdrop` | 主题/长路径布局、资料页滚动位置、简单 resize 边界、标题栏与旧 Qt 样式、壁纸缓存合并性能、浮窗恢复设置的专用检查；保留活动渲染退出、原生调用边界与显示器移除后位置恢复 |
| `test_user_workflows`、`test_preparation_feedback`、`test_ui_feedback`、`test_update_feedback` | 提示尺寸/位置/过期、首启向导展示、重复错误提示保留、识别错误展示细节、新页不重扫优化、更新完成提示重开；保留失败后重试、迟到结果、任务取消和保存状态保护 |
| `test_model_guidance_ui`、`test_export_search_feedback`、`test_download_progress`、`test_resource_monitor` | 版本菜单、启动更新提示、重复设置/准备展示、搜索分页、下载字节回调刷新频率、精细 CPU/RAM 数字和缺失 GPU 数字逐值检查；保留下载异常恢复/离线边界、监控超时/恢复/退出及隐私过滤 |
| 保留流程内的细节检查 | 从 `test_workflow_preview` 删除小岛变形、长菜单键盘/几何及圆角截图；从 preferences 流程删除上轮迁入的设置搜索/导航/动效检查，保留实际设置往返与录音中修改保护 |

保留标准：数据完整性、录音/翻译核心结果、算法边界、权限与路径、失败/取消/迟到结果、进程线程退出、安装更新信任与恢复。低优先级功能并未从产品删除，但其外观和便利性退化可能不再被日常自动回归发现；这是明确减少覆盖，不宣称等价替代。测试数量和通过率不代表产品全部验收。

本轮删除清单与前后快照在 `.work/reports/test-priority-retired.json`、`test-priority-before.json`、`test-priority-summary.json`；实际执行结果见 [VALIDATION](VALIDATION.md)。

### 2026-10-21 流程归并

以本轮开始时的工作区快照为基线（含上一轮尚未提交的进程修复），全套 **1140 个收集项、719 个测试函数、19849 行测试 Python**。本轮改变 41 个测试/支持文件，84 个文件原样保留；合并 6 个函数，新增共享入口超时参数项，收集项变为 **1135**，函数数 **713**，测试 Python **19722 行**（净减 127 行）。这些数字不混用上一轮 1190 项的历史基线；主要收益是收敛重复启动和流程归属，不是大幅压缩测试体积。

| 原独立检查 | 归并后的证据位置 |
| --- | --- |
| `test_recording_page` 的选定名称/文件夹后开始 | `test_named_recording_start_finish_and_settings_routes` 从实际空草稿开始，检查 Session 的设备设置、唯一目录归属，再继续暂停和保存 |
| `test_ui_experience` 的搜索/导航/动效/重开 | `test_preferences_roundtrip_and_recording_guards` 保留搜索命中、空结果清除、指南跳转、Disclosure、取消命名及持久化；退役“旧跟随菜单不存在”的历史控件枚举，其实际跟随行为仍由 playback/UI 流程验证 |
| `test_library_defaults` 的过期目录选择和空目录菜单 | 接入已有删除—重建—恢复目录流程，检查仅余目录的选择、无目录时的菜单重建及不创建空录音；写入失败仍独立 |
| `test_wlk_session` 的普通 PCM 排空 | 与诊断关联共用同一次真实 Session/worker 运行，保留帧数、采样率、位宽、录音时长和 worker 消费字节数 |
| `test_library` 的初译保存/导出 | 接入已有保存—重开—修订流程，并通过新的 Library 实例读取初译来源/阶段，保留 TXT/SRT 标记 |
| 29 处子进程启动与 Beta 模块内共享窗口夹具 | 移至现有 `ui_support.py`，保留隔离、退出检查和原超时，统一中文输出/超时诊断；真实非零退出及超时参数检查证明失败不会被吞掉 |

算法分句/翻译版本与队列边界、数据保护、取消/迟到结果、课程许可、安装签名与平台差异没有按“名称相似”删减。完整运行结果及限制见 [VALIDATION](VALIDATION.md)。

### 2026-10-20 全测试体系精简

第二轮以 `188c99b` 为基线，盘点全部 122 个测试文件及 1190 个收集项，检查测试职责、调用入口、关键断言和参数矩阵。修改 36 个测试文件：删除或合并 26 个函数，缩减重复参数组合，测试净减少 861 行；最终 121 个文件、1134 个收集项，净减少 **56 项**。收集项包括参数化展开，不能把函数数、改名产生的 node ID 差异或循环次数当作删除数量。此前第一轮仅退役 6 项外观检查，历史结果保留在 VALIDATION。

检查后的取舍：

| 测试领域 | 处理与保留边界 |
| --- | --- |
| 录音、暂停/切源、ASR 与分句 | 保留采样完整性、代次、暂停交接、取消/停止、背压、修订/撤回及缓存回归；删除两个被其他分句用例覆盖的简单文本场景，减少相同前缀/上下文路径的中间参数 |
| 翻译模型、上下文与队列 | 保留双引擎、初译/定稿、单条/批量、背景越界、版本 ABA、迟到结果和资源释放；合并基础排队重复检查，减少初译重复背景配置及相同缓存开关的 GPU 组合 |
| 运行环境、模型准备与缓存 | 保留安装失败、损坏缓存、取消、进程树、管道、超时、活跃租约、回滚与清理归属；把重复复用检查并入真实跨会话测试，模型下载委派合入真实 ModelManager 用例 |
| 文件库、保存、导出、迁移与回放 | 保留所有写失败、旧回执、锁、崩溃恢复、原件保护、路径/链接、迁移失败及回放数据测试；SRT 时间进位和双语序列化归入导出测试 |
| 课程资料、SDK、渲染与云端权限 | 保留原文件/页覆盖、来源变更、每轮许可、取消、旧结果隔离、格式差异与真实 SDK 集成；相似测试覆盖不同入口、格式或生命周期阶段，不视为重复 |
| 更新、封装与原生平台 | 保留签名、信任、平台/渠道、旧包恢复、受控进程和封装载荷保护；许可证白名单一次同时放入三种无关文件，免去重复夹具 |
| 诊断日志、资源与性能 | 保留隐私、轮转/容量、慢盘/溢出、故障恢复、CPU/GPU 缺值、跨平台计数器与进程归属回归 |
| UI、交互与设置 | 保留用户操作、最低窗口尺寸、长文字、无响应/取消/退出与持久化；删除重复整窗布局循环、历史控件不存在断言、装饰像素及固定文案小项；独有行为移入保留用例 |
| 评测与测试基础设施 | 保留参考可信度、哈希/完整性、计分边界、无音频拒绝和 CI 禁止跳过门禁；删除 AMI 旧 offline 标记专用检查，移除已无平台分支的 runner 参数矩阵 |

删除/合并的具体归属（未列出的该文件测试继续保留）：

| 删除或缩减内容 | 保留覆盖或明确退役的范围 |
| --- | --- |
| `test_ami_evaluation.py` 的历史 offline；`test_audio_config.py` 的旧增强开关；`test_runtime_preparation.py` 的 retired ONNX；`test_runtime_network.py` 的 standalone 旧 offline | 退役对已删除功能名称的专用门禁。`test_preferences.py` 的读取/写回同时拒绝旧 offline 与 audio_processing；prepared worker 保留网络环境及会话 trace 重置，MLX 保留未设置/显式设置环境两条路径；设备快照由 worker/backend 测试保护 |
| `test_preferences.py` 的两个旧字段独立用例及逐值枚举旧 context 默认值 | 旧字段过滤并入 `test_legacy_defaults_and_corrupt_values`；保留读写往返、损坏值、Metal 迁移和 context 范围校验，实际会话默认值由 SettingsBinding/UI 回归覆盖 |
| `test_model_options.py` 的目录/推荐标识符重复断言；`test_model_cache.py` 的翻译准备委派 | 双平台桌面选择往返、真实目录下载信号继续覆盖目录用途；翻译模型与 `--only translation` 迁入 `test_model_preparation.py`，后者仍验证命令失败 |
| `test_runtime_preparation.py` 的 compatible preparation 专用用例 | 空闲重复 prepare 并入 `test_successful_sessions_reuse_process_with_fresh_language_and_audio`；活跃 prepare/二次租约拒绝并入 `test_second_lease_is_rejected_without_disrupting_first` |
| `test_translation_queue.py` 的基础 coalescing 用例 | `test_translation_context.py::test_initial_inflight_is_superseded_and_queued_revisions_coalesce` 通过实际消费、发布和 `queue.join()` 覆盖；原版本 ABA 判断保留 |
| `test_wlk_captions.py` 的 unfinished clause / learned boundaries 简例 | 原文保真由 semantic model、长文本/碎片 token 和 pending-tail 用例覆盖；无标点模型边界及 ready 状态由 `test_model_offsets_determine_short_and_unpunctuated_segments` 覆盖并保留 reason 断言。上下文 20 行与 200 行用例重复，保留 3/10/200 行；前缀保留起点、1024 分块前后及末尾 |
| `test_core.py` | 删除文件；全部 SRT 进位与双语精确输出断言迁入 `test_recording_export.py`，没有取消格式回归 |
| `test_caption_feedback.py` 的 brand/pointer pixel；`test_recording_page.py` 的 control sizes 与 former-plus 坐标；`test_responsive_transport.py` 的 input-level 布局 | 文字点击/双击/选择/录音禁播由 `test_interaction_fixes.py` 保留；组件用例补公开 activated 信号；暂停零电平迁入录音时钟用例。退役品牌对齐、控件精确尺寸、阴影及已删加号位置门禁 |
| `test_ui_presentation.py` 的 no-shortcuts、混合 save/model/tree、floating hover；`test_workspace_appearance.py` 的 theme/model/progress | 查找由用户流程/长录音搜索覆盖；保存旧回执由 `test_ui.py`/`test_ux_recovery.py` 覆盖；旧译文 pending 显示迁入 caption reveal；模型选择/只读检查由 model overlay/options 覆盖；保留实际 HTTP 下载跨页进度。退役无快捷键属性、Qt 树箭头及重复 hover/主题循环 |
| `test_ui_experience.py` 的语言弹层；`test_startup_workspace_polish.py` 的 folder/reset；`test_ui_model_overlay.py` 的独立透明背景；`test_user_workflows.py` 的无详情入口布局 | 语言 Escape/不启动录音迁入 `test_language_selection.py`；新工作区/文件夹由 recording page/library defaults 覆盖；背景透明度持久化迁入 overlay drag/resize，隐藏控制栏由 live overlay 流程覆盖；重试点击迁入 feedback 用例。退役透明像素采样及按钮列表精确相等 |

参数精简保留真实执行分支：翻译长历史矩阵从 32 项变为 20 项，保留初译 0/1 邻句、定稿 0/3/10 邻句和双引擎/批量维度；缓存启动保留 CPU/GPU 两类，设备识别另有 Metal/CUDA/Vulkan 专用回归。共享设置/提示流程使用当前平台，平台选择测试仍显式覆盖 Windows/Mac；Mac 目录信号用例保留模拟 Mac 路径。设置页无关宽度、runner 无效系统维度以及 MLX 环境 `'0'` 的重复组合退役。

本次降低自动检查粒度，不宣称覆盖完全等价：细粒度样式、历史控件名称及任意中间参数不再全部作为门禁。UI 变更仍须按上文 Demo 契约做相关检查。关键失败/取消/数据保护/平台分支不能为缩短耗时而删减；实际运行结果与平台限制见 [VALIDATION](VALIDATION.md)。

## 算法与性能证据

诊断日志变更需覆盖进程独立文件、会话/解码序号关联、重叠不重复计为新增音频、异常/正常退出释放诊断回调、轮转与保留、中文路径、创建/写入失败不打断业务，以及原文/异常原文不落盘。新增范围需验证操作关联、重复进度合并、慢盘/队列溢出/恢复/退出、活跃日志保留、进程树 CPU/RAM 口径、GPU 缺值及超时退避、采样失败恢复。相关回归在 `test_diagnostic_log.py`、`test_resource_monitor.py` 与 `test_wlk_session.py`；使用 `AGENTSCRIBE_LOG_DIR` 将人工探针日志放入独立临时证据目录。日志中的解码耗时与积压估计不能代替真实音频质量和 GPU 吞吐验收。

先固定输入、环境、问题和对照，再改变一个因素，比较真实核心流程的质量、延迟和资源。使用原速连续会话，不按答案句界切音频、不向模型提供待测参考、不择低报告。固定课堂样本见 [media](../media/README.md)，整场协议见 [AMI](testing/AMI_BENCHMARK.md) 和 [评分](testing/SCORING_SYSTEM.md)。

同时记录输入/代码哈希、依赖与设备、模型/量化、设置、缓存/预热、完整输出和无效运行原因。区分模型加载、稳态、首次/持续/收尾延迟、积压和资源；RSS、系统交换和 GPU 分配不是同一口径。局部计时不能推出整场收益，术语/断句改进不能只看 WER 或段数。

测试变绿或字幕条数减少不能单独证明用户体验改善。GPU 目标须有所选设备的实际推理、完整输出、延迟和资源证据；Windows CUDA、Mac Metal/MPS/MLX 分别验收，CPU 对照、GPU 检测或权重加载不算完成。共享修改在另一平台未实测时明确待验收。

## 记录与文档更新

临时原始证据在 `.work/`，提交的简短结果写清代码范围、系统/架构、Python/关键依赖、设备/后端、命令、通过/失败/跳过和未验证内容。无效/失败运行保留并标明，私人录音/全文/密钥不进 Git。

[VALIDATION](VALIDATION.md) 只索引证据与边界；历史详细记录归档。未完成验收在 [ROADMAP](ROADMAP.md) 跟踪。测试方法变化改本文，行为变化改 spec，具体结果不得反复追加进 AGENTS 或架构。


## Electron 正式入口

启动响应回归须覆盖冷进程导入与慢来源发现，不能仅在已导入音频/科学计算库的 pytest 进程内验证。`test_desktop_service.py` 检查发现期间协议可响应、重复请求合并、失败保留旧列表及关闭后丢弃结果；`test_audio.py` 检查轻量导入及发现子进程成功/失败/超时的回收。无音频原生流程结果不替代正常启动模式的来源发现与真实窗口操作。

安装桌面 Python 开发依赖至 `.venv`，再在 `desktop/` 执行 `npm ci`、`npx install-electron --no`、`npm run build`。版本由 `desktop/package-lock.json` 固定；构建从原 Python 主题生成 CSS，Windows 使用 `.venv/Scripts/python.exe`，Mac 使用 `.venv/bin/python`，可由 `AGENTSCRIBE_DESKTOP_PYTHON` 指定已准备的解释器。

- 服务回归：仓库根执行 `.venv/bin/python scripts/test_no_audio.py tests/test_desktop_service.py tests/test_frontend_switch.py tests/test_electron_packaging.py -q`；Windows 换相应解释器路径。覆盖协议、后台读库、原格式、保存锁/恢复、模型检查回执和课程归属。
- 原生流程：`desktop/` 执行 `npm test`；使用 Playwright Electron，创建隔离库/偏好及 Electron profile，Python 子进程继承音频导入保护。验证共享组件、中文编辑、搜索、主题、独立课程窗口/草稿、悬浮窗口权限、回听控件几何及退出。回听控件只用模拟位置，不播放音频。Mac 需可用的原生桌面会话；失败不能改用浏览器截图冒充原生通过。
- 真正前后端回归：`npm run test:chain`。保留 renderer → preload → Electron IPC → JSONL → DesktopService 校验 → 共享后台；模型安装/下载在 `scripts/desktop_chain_fixture.py` 中仅替换执行命令，真实 Preparation、监督进程、BackgroundCheck、取消和完成回执照常运行；云端执行替换为本地回答，KnowledgeClient、worker、许可、版本和真实文件持久化不替换。测试夹具仅由临时 `sitecustomize.py` 加载，正式入口没有测试控制路由。不得用 `Service.request` 返回成功来验收推荐组合或其他命令。真实 WAV 文件只读取元数据，禁止访问设备。证据在 `output/playwright/parity-fixed/`。
- 用户反馈交互回归：`npm run test:interaction`。实际菜单互斥/嵌套选择、单击/双击字幕、返回播放位置、检查更新及深色窄窗口；真实 IPC、参数校验、DesktopService、PlaybackController 与 WAV 读取均保留。`scripts/desktop_playback_fixture.py` 只提供延迟 350ms 才能定位的无设备 QMediaPlayer/QAudioOutput 适配器和离线 HTTP 响应；仅测试实例的回听入口允许使用适配器，采集/设备发现仍被禁止。不能替代真实声音、系统媒体后端或 Windows 实机验收。输出在 `output/playwright/interaction-fixes/`，帧间隔仅为本机 rAF 与 transform 采样，不是全平台显示器呈现保证。
- 媒体适配器：`npm run test:audio-adapter`；在 Node 中运行正式音频 preload，仅替换 Audio/AudioContext 设备边界，覆盖就绪前多次定位、暂停、取消、错误及旧回调失效。旧 Qt 双向切换已退役。
- Windows 标题栏：`npm test` 复用 `titlebar-checks.cjs`，保留原生 setter，检查真实 settings、bootstrap 重载后透明背景/图标主题及覆盖层尺寸。该断言不代替视觉与系统命中验收：用原生窗口截图检查深浅主题、窄窗口和最大化，实际点击最小化、最大化/还原及关闭；页面截图不包含完整原生控制，不能据此判定通过。只操作隔离、未录音且无用户编辑的测试窗口。
- 回放全文回归：`test:interaction` 使用 650 条已保存双语字幕，核对一次载入、首屏从头、Home/End 的实际可见位置、跨原 200/400 边界的播放定位，以及搜索后全文仍保留；不能只断言 DOM 条数。Python 对照为 `test_desktop_service.py`、`test_caption_view.py`、`test_ux_recovery.py`，另保留实时显示窗口与修订/删除/预览保护。音频仍为隔离适配器，不证明真实声音输出。
- Qt 交互对照回归复用 `test:interaction` 与 `parity-checks.cjs`：检查局部忙碌、分类滚动、数值回执、树/模型键盘操作、分隔条持久化、目录解析、来源状态呈现、单层弹窗滚动、参数帮助、摘要与短目录。来源变化呈现使用事件夹具，首次选择/失效不替换等后台行为由服务回归验证，不冒充真实设备变化。Windows 缩放可能让请求 640×480 得到 640×481/482，测试允许 2px 的系统舍入，截图清单记录实际尺寸；控件移动比较实际设备像素，仍要求完全相同。
- 录音状态对照：`parity.cjs` 使用 Python 共享反馈函数生成连接来源、采集中加载、就绪、暂停和收尾状态，校验活动按钮 48px 中心距、等待文字居中及加载提示出现/清除。它仍是显示夹具；真实首包/WAV、模型并行和结束资格需 Session 回归及授权后的独立实机录音证明，不能以 `send('state')` 或截图通过代替。
- 冷启动采集回归：`test_audio.py` 的 48kHz 分支禁止导入 SciPy，16kHz 继续核对原重采样；`test_desktop_service.py` 验模型/采集独立、切源回执与音量状态，`test_wlk_session.py` 验实际线程/子进程下的合成 PCM、模型加载和保存。Mac 音频保护继续有效；Windows 实录也须明确采集范围、临时库与时间上限，不播放或上传，保留原始证据。
- 封存载荷的 Electron 界面：`npm test` 可指定 `AGENTSCRIBE_PROBE_RESOURCES` 为实际包内 Resources、`AGENTSCRIBE_PROBE_ELECTRON` 为包内 Electron 可执行文件、`AGENTSCRIBE_DESKTOP_PYTHON` 为包内 Python，并设置 `AGENTSCRIBE_PACKAGED=1`、`AGENTSCRIBE_RESOURCES` 与 `PYTHONDONTWRITEBYTECODE=1`；`AGENTSCRIBE_PROBE_EVIDENCE` 区分源码和安装包证据。探针仍使用临时库/偏好/profile 和音频阻断，不安装应用、不访问已有录音；实际旧版升级另验。
- 组件演示：`npm run components`；直接复用正式基础组件与 Playback。旧 Qt Demo 是完整对照基准，Electron Demo 当前覆盖尚不完整，不能据此关闭 I09–I14 全部验收。
- 与 Qt 对照：使用 `preview_workspace.py` 相同示例文字，分别检查900×650、640×480、1280×840及明暗主题；记录实际内容尺寸、DPR、Qt离屏/原生与 Electron 原生的区别。比较菜单动作、焦点、输入法、动态状态与数据结果，不能只比静态截图。

产物在 `output/playwright/electron/`（本轮已有隔离证据）与 `.work/reports/electron-*.log`，不提交。CI 新增独立 Windows/Mac Electron job，原 Python job 保留；本地通过不代表远程 CI 已执行。真实设备、模型/供应商、不同缩放多屏、Windows 原生和安装更新是独立证据。


### 新旧前端逐页对照

先构建当前 `desktop/`，依次执行 `.venv/bin/python scripts/preview_parity.py --capture` 与 `node desktop/scripts/parity.cjs`；需要原生桌面会话，两个截图任务不要同时争用焦点。Qt 探针在导入界面前安装音频保护；Electron 使用独立库、偏好、profile，并让全部 Python 子进程继承保护。显示夹具提供同样的字幕、模型清单和 `/录音示例` 路径，实际业务仍使用临时库、拒绝音频访问。不会采集、播放、下载或调用云端。

范围包括录音工作区、六个设置页、模型弹窗、课程三个页签和悬浮字幕，深浅主题 × 1280×797 / 900×650 / 640×480；大窗口高度根据本轮 macOS 原生内容区可用高度选取。清单记录实际尺寸与小岛矩形，不把系统约束后的截图冒充请求尺寸。Electron 另测正常/反向小岛和音量动画、开关中间帧、减少动态效果、弹窗/切页时长和字幕追加/修订。几何与动画使用正式组件，不请求真实采集。

两份清单完成后执行 `.venv/bin/python scripts/compare_desktop_ui.py`，生成 `.work/browser/ui-parity/index.html`，可按页面双栏/叠加比较，并查看动画轨迹与小岛几何差值。图片和显示数据留在 `.work/`，不写入个人录音或源码图例。原生业务交互仍另跑 `npm --prefix desktop test`；截图夹具不替代服务端回执、平台设备与模型验收。

### 双前端共享流程回归

`python scripts/test_no_audio.py -q tests/test_shared_desktop_workflows.py tests/test_desktop_startup.py tests/test_knowledge_client.py tests/test_update_recovery.py` 覆盖自动连接许可、阻塞导入的实际进程树退出、录音结束持久化分类、定位身份/代次、文档准备并行、更新各门禁及取消、启动健康和存活桌面下的恢复保护。`cd desktop && npm run test:migration` 使用真实 Electron/IPC、隔离库与模拟媒体，检查搜索只定位不播放、忙碌授权按钮和 Mac 更新菜单；不授权真实云端访问。

完整无音频套件仍通过默认安全入口执行。原生 GUI 探针需要登录的图形会话；全量/模拟回归与安装版原生更新器初始化不等于真实下载、签名校验、安装或 Windows 验收。

### 双前端后台契约回归

`tests/test_frontend_backend_contracts.py` 对 Qt 和 Electron 适配器执行同一故障契约：构造失败必须持久化为未完成，写盘失败必须保留锁与失败终态、重试成功才能释放，课程 status/idle/disconnected 必须即时影响切换门禁。单独子进程验证共用后台可在 QCoreApplication 下导入及创建，不依赖 QtWidgets 或前端模块。

使用 `.venv/bin/python scripts/test_no_audio.py -q tests/test_frontend_backend_contracts.py tests/test_shared_desktop_workflows.py`；涉及共享保存、迁移、准备或退出时还须运行全量无音频回归及 Electron `test:chain`、`test:interaction`、`test:audio-adapter`。异步退出测试等待资源实际终态，不以单次处理事件代替退出完成；不会放宽文件状态、锁或失败保存断言。


## 无 Qt 正式运行与旧界面对照

正式依赖安装 `.[dev]`，不安装 PySide6/shiboken6。`tests/test_qt_free_backend.py` 拒绝全部 Qt 导入，执行后台启动、库/设置和退出，并审计正式源文件与平台锁；另覆盖设置迁移、失败提交、线程顺序与竞争文件锁。`tests/test_playback_controller.py` 使用生成的静音 WAV 校验 HTTP 范围读取、失效代次和释放，不输出音频。

完整历史对照套件仍需 `.[dev,legacy-qt]`；Qt 仅用于旧界面及图像夹具。它不进入正式安装依赖。实际 HTML/Markdown/图片测试需要先 `cd desktop && npm ci && npm run build`，Mac 需原生图形会话。背景材质比较允许不同栅格器最多一个 8-bit 通道舍入级，尺寸、主题、缓存及交互断言保持。

正式 CI 的 Electron job 不安装 Qt，运行基础、交互、全链路、音频适配器与无 Qt 后台检查。安装包探针断言载荷不含 PySide6/shiboken6；后台/渲染与原生 Electron 窗口分别提供证据。源码回归不能代替 Windows 真实设备、已签名成品、原生更新验收。


`npm test` 还运行 `helper-lifetime-checks.cjs`：使用真实 Electron 辅助进程，检查大结果完整写入、输出流提前关闭与父进程先退出。辅助进程不得因 EPIPE 弹出错误框或遗留；错误须交回 owner。这个测试不访问设备，不替代安装态更新验证。
