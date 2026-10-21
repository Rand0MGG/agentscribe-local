# 测试规范

测试验证用户可观察的结果和 [spec](specs/README.md) 的约束；代码与测试一致仍不等于行为合理。纯文档修改检查事实、引用和差异，不必启动应用、安装依赖或运行模型。

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
- 图片/网页要检查真实解码/页面内容，不能仅检查 HTML 含标签。状态等待有截止时间，布局稳定与业务结果分别断言，不用固定短 sleep 调整通过率。
- 跨进程中文断言同时指定子进程输出和父进程解码的 UTF-8，不能依赖机器区域设置。通知等待实际收起，字幕定位等待目标卡片进入视口；窗口尺寸稳定不能代替业务完成。
- `.github/workflows/checks.yml` 是 CI 矩阵的执行权威：两端 Python 3.11–3.13 无音频回归，Python 3.12 另做课程 SDK 和原生文档渲染，Ruff 独立执行。专用集成设置 `AGENTSCRIBE_REQUIRE_INTEGRATIONS=1`，选中用例有跳过即失败。
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
