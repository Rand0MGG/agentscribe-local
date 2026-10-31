# 架构与实现边界

本文维护实现职责与当前方案，行为要求见 [spec](specs/README.md)，测试方法见 [TESTING](TESTING.md)。职责描述不代表全部异常路径已符合规范；已确认的实现差距在 [ROADMAP](ROADMAP.md#实现缺口)，不能当作已发行或全平台验收证明。

## Electron 正式入口

`desktop/` 是唯一正式桌面入口。旧 Qt 界面源码仅保留为开发对照，通过 `legacy-qt` 可选依赖运行旧回归，不进入正式安装包。Electron 主进程拥有窗口、原生文件选择、剪贴板和本地 Python 子进程；沙箱 renderer 通过受限 preload 请求业务，不获得 Node、任意路径打开或进程执行能力。主窗口、非模态课程窗口及悬浮字幕各有 IPC 白名单；请求同时校验本应用窗口、顶层 frame 与本地页面 URL。

`desktop_startup.py` 与 `desktop/electron/launcher-lifetime.cjs` 用仅监听 `127.0.0.1` 随机端口、校验本次随机令牌的连接绑定启动器存活状态，不依赖 Windows GUI 进程不可用的标准输入管道。建立连接不等于启动成功，仍须收到令牌及 Electron PID 均匹配的真实前端就绪回执。启动器退出或崩溃导致连接断开时，Electron 请求原有窗口关闭流程，保留编辑确认、录音保存与后台释放门禁。

`linguaflow/desktop_service.py` 使用标准库 `events.Dispatcher`，复用 Session、RecordingSaver、LibraryReader、Preparation、BackgroundCheck、KnowledgeClient 和 PlaybackController；正式后台及课件子进程不导入 Qt。后台线程结果按顺序回到 owner 线程，计时器取消与对象释放使旧回调失效，退出等待真实线程/进程结束。UTF-8 JSONL v1 使用请求编号与有界消息；超时只报告等待失败，不假定后台操作已取消。stdout 专用于协议，诊断日志保持原隐私边界。

后台入口在启动 stdin 协议读线程之前完成 NumPy 初始化，两端共用此顺序。Windows 的管道读取与首次 NumPy 原生模块加载可能互相阻塞，因此不能推迟到首次打开录音读取 WAV 时长时才初始化；初始化失败通过启动进程的 stderr 报告，不发送就绪回执。

Qt `Window` 和 Electron `DesktopService` 组合相同的后台流程；后者另负责 JSONL 请求和事件适配。共享模块不导入 QWidget、Qt 控件或 React：

- `recording_workflow.RecordingWorkflow` 持有唯一的录音领域状态、Session、保存器和自动保存计时器，负责启动事务、启动失败持久化、暂停/继续、字幕修订、预览、结束分类、保存回执和锁释放。保存失败保留终态、脏数据和锁；旧 Session 的迟到信号不能写入新录音。Qt 的旧属性名只转发到此状态，字幕卡片保留独立显示副本。
- `library_workflow.LibraryWorkflow` 统一活动录音的文件操作门禁、迁移锁、复制完成后的偏好提交及旧目录清理。新目录偏好未成功写入前，不清理旧副本。
- `session_settings.session_settings` 统一不可变会话快照、语言/设备映射及模型引用规范化；`SettingsBinding` 仅采集 Qt 控件值。
- `preparation_workflow.PreparationWorkflow` 统一准备任务所有权、冲突校验、取消与真实线程结束回执；`preparation_command` 统一准备命令和选择校验。Qt 模型面板保留控件、下载反馈和重试展示。
- `application_lifecycle.Activity/ShutdownWorkflow` 统一切换门禁和退出顺序。取消自有任务、等待录音/保存、关闭课程与回听、异步释放推理环境后才允许退出；失败保留资源所有者。原生窗口关闭确认、动画和界面交接呈现由适配层负责。
- `knowledge/lifecycle.KnowledgeState` 保存当前课程任务状态，除部分 view 外也消费 status/idle/disconnected；命令提交即标忙碌，切换门禁不依赖课程窗口是否打开或旧显示快照。自动连接和导入取消仍共用同一实现。

录音采集保持原实现：SoundCard 麦克风与 Windows WASAPI 回环、macOS ScreenCaptureKit 均未更换。设置由 `SettingsStore` 原子写入 JSON，首次读取旧 INI/plist/注册表而不修改原文件；跨进程文件锁用操作系统锁串行化竞争，并识别仍存活的旧 Qt 锁。

`update_workflow.py` 共用安装等待、未保存编辑/录音/文件/准备/检查门禁、后台释放、取消和恢复；Qt 直连、Electron 通过受限 IPC 调用。释放前及完成后复查状态，取消释放期间不提前解除操作限制。Electron 的未保存名称、术语和笔记由宿主汇总后交后台门禁。Mac 安装后台通过既有 PyObjC 桥泵送 Cocoa RunLoop，保留 Sparkle 原生身份，不再创建 Qt 应用。

`captions.locate` 携带录音 ID 和代次；后台验证后同时返回字幕位置和不自动播放的定位结果。播放器尚未创建时只保存待定位时间，首次主动播放才打开音频。课程引用携带其原录音身份，迟到的旧录音结果不能定位当前录音。文档组件准备与录音可并行，模型/推理环境准备仍禁止开始录音。

React 组合共享 Radix 基础控件，`Playback.tsx` 同时用于实际回听与演示。Vite 从 `ui_theme.THEMES` 生成颜色；布局仍须按 v0.10.2 校准。课程窗口隐藏时保留本次运行的各课程草稿；原生关闭请求先交给编辑保护，主程序退出仍等实际录音保存、子进程和任务终态。采集只通过已有 Python 平台适配；回听由独立 Electron 音频宿主输出，浏览器采集权限拒绝，`--no-audio` 阻断设备与回听入口。

Windows 窗口控制使用 Electron 原生 `titleBarOverlay`，与 36px 拖动栏同高、背景透明；构造、bootstrap 及 settings 共用颜色选项，避免已保存深色启动仍用浅色按钮。按钮动作保持系统行为，原生关闭仍交给既有编辑/保存保护，不新增 renderer 窗口控制权限。

`LibraryTree.tsx` 集中树键盘导航与分隔条交互；`layout.sidebar` 校验并持久化独立显示偏好，不改录音设置。行菜单只提交已有库 ID，宿主向 `path.recording` 解析目录后打开，renderer 不能传任意路径。主工作区 busy 仅覆盖冲突的录音/库/前端切换请求，其余任务消费各自事件。`NumberField` 保存回执前保留上次确认值，校验或保存失败恢复并提示；设置分类重新挂载滚动容器，模型弹窗只由外层内容区滚动。

`captions.page` 在 IDLE 返回从 0 开始的完整字幕，bootstrap、打开与停止后的字幕事件沿用同一契约；仅活动录音使用 200 条窗口。Electron 回放的滚动、搜索定位与播放位置更新复用已载入全文，不再跨播放页请求/替换字幕；单条更新只在活动录音裁剪卡片。全文会增加长录音的前端内存与首次排版成本，不能用恢复回放分页来掩盖性能问题。

显式导出使用每次请求独立的队列身份，自动保存仍按录音版本合并；恢复备份另存录音身份、版本与文件摘要，全部排队写入结束才结束导出进度，后续成功不覆盖同批失败。模型准备范围使用 `all/asr/translation`，`all` 不下传为 CLI `--only`；完成、取消及选择变化合并触发后台资源检查，过期检查不覆盖新选择。

Electron 服务拥有可复用的 `RuntimePreparation`，会话只借用；环境维护及退出在独立任务中等待释放，失败保留 owner 以便重试。回听元数据通过原 `PlaybackStream` 只读 WAV 获取，不为显示时长创建音频设备；`PlaybackController` 持有文件、随机令牌本机媒体流、录音代次、播放状态和命令，Electron 音频适配器等待媒体就绪后先定位再播放；释放/错误清除待执行请求，成功定位回执恢复前端跟随。保存结束并释放录音锁后刷新，建立播放器时重新应用音量。两前端共享悬浮窗逻辑坐标，旧 Qt 二进制几何继续作为兼容回退。启动库失败时，宿主只在原后台已退出、尚未完成启动的情况下允许重新选目录；新后台验证库后才持久化选择。

回听媒体服务只绑定 `127.0.0.1` 的随机端口，直接使用数字地址，不进行反向主机名查询；避免系统解析器阻塞后台 owner 线程。令牌校验、范围读取及旧录音代次拒绝仍由 `PlaybackController` 负责。

源码入口、验证方法见 [TESTING](TESTING.md#electron-正式入口)，实现缺口见 [ROADMAP](ROADMAP.md#electron-迁移对照)。Qt-free 构建仍复用现有原生启动器和平台锁；安装版 Electron 后台由外层原生启动器以 `--python -m linguaflow.desktop_service` 承载，保留 Sparkle 的应用身份；检查更新不再切换界面，仍使用 Sparkle/WinSparkle，未引入 electron-updater。不要把本地构建或逻辑回归理解为跨平台发行验收。

`desktop_launcher.py` 统一原 `python -m linguaflow` 与 console-script 入口，始终启动 Electron；显式 Qt 启动返回退役提示。`frontend_switch.py` 保留旧交接上下文及 Electron 重启支持，等待旧 owner 结束才启动目标；界面已移除 Qt 切换按钮。

课件继续由 Python 负责文件准入、资源快照、预算、哈希、缓存及发布事务。`render-tool.cjs` 使用包内 Electron/Chromium 截图及图片标准化，隔离 profile、沙箱、有限文件白名单和禁止联网/媒体/窗口/下载；不把导入和课程业务搬到 React。Markdown 使用固定版本 Marked（无额外运行依赖），HTML/Markdown 渲染版本更新使旧布局缓存重新导入后刷新。壁纸和应用图标也复用 Electron，NumPy/SciPy 保留原材质算法。

`desktop_startup.py` 在私有临时目录接收当前 Electron 子进程的实际界面就绪回执，由原生启动进程确认更新健康；启动 Electron 进程本身不算成功，更新后也不强制改用 Qt。子进程不继承原启动恢复票据。Windows 原生父进程继续持有安装互斥量到 Electron 退出；父进程存活管道断开时 Electron 请求正常关闭。恢复另核对已登记的 Electron PID/创建时间；仍存活则保留新旧包，交人工恢复，不在其下方替换程序。

切换归属通常只接受当前进程或直接父进程；Windows venv 的 Python redirector 会多出一层启动器，仅当直接父进程的可执行路径与 `sys.executable` 解析后相同、其父进程正是请求的 owner 时接受该宿主，不接受任意祖先进程。交接 JSON 的生产与测试读写均明确使用 UTF-8。

Electron 的 `audio.refresh` 立即返回已有来源列表，并用现有 `_Task` 管理异步发现；同一发现未结束时合并重复刷新，成功以 `devices` 事件更新，失败保留旧列表，关闭期间丢弃迟到结果。原生 SoundCard 枚举通过 `audio.discover_devices` 在受现有进程归属保护的短时子进程执行，15 秒超时后回收自有进程树；关闭等待该任务完成，不把原生 COM 对象带入业务线程。NumPy 在实际采集时导入；桌面 48kHz 直通采集不加载 SciPy/BLAS，仅需要 16kHz 重采样时才导入原转换实现。来源发现不加载采集计算库。无音频入口在启动任务前拒绝访问。

`recording_state.capture_feedback` 提取 Qt 原有的状态、输入音量说明、等待文字和模型加载资格，Qt 直接使用，Electron 消费 snapshot 的 `capture`。连接来源、首包已到但模型尚未就绪、静音、切源、暂停和收尾分别呈现；bootstrap 也提供在途模型状态，不依赖可能错过的单个事件。来源切换回执更新显示状态，失败/非 LISTENING 的电平归零。小岛按钮按 40px 宽、8px 间距居中，状态行电平占剩余空间；空字幕等待文字以主工作区为中心，不能把模型加载描述当作采集状态。

来源控件消费 `audio-discovery` 的忙碌与失败状态，以及 `devices/device` 的列表和选择；bootstrap 补充在途状态供重载恢复。首次尚无选择且未建立会话时选首个来源；保存的来源消失时保留原选择并提示重选，不自动换设备。

`desktop_platform.py` 是短时、无网络/音频/录音资源的系统显示查询：读取 Qt 与系统同源的双击/拖动阈值，并通过未显示的空 QWidget 转换旧悬浮窗二进制几何；它不运行业务窗口。Electron 服务的资源采样包含宿主及其子进程。通知按任务独立存储、优先级选择和收起，课程笔记编辑收到持久化回执才关闭。

## 数据与执行流

```text
Window / 设置快照
  → Session：立即采集/写 WAV → AudioJournal（有序 PCM / 暂停标记）；并行加载模型
  → WLK worker：音频处理 → ASR → 修订记录 → SaT / CaptionMapper
  → ContextPlanner → 最新版本队列 → 模型适配 → 有效性校验 → 字幕
  → RecordingSaver：冻结快照 → 串行写入/逐文件原子替换 → 带归属/版本回执

已保存定稿 / 本地材料 → 可选 knowledge 子进程 → 许可/预算检查
  → 页面解读 / 受限 harness → 来源版本事务 → 笔记与引用
```

Qt 线程负责装配、呈现和发起操作，只有它更新 UI。耗时任务通过快照、回调或信号连接。菜单刷新及点击打开录音由 `library_loading.py` 读取独立索引，失败保留视图，退出等待回收并拒绝结果；待录音页复用当前索引和目录行，不重复全库扫描或重建列表。启动建库、实际创建录音和部分元数据操作仍有同步入口，不概括为全部 IO 已异步。大库和长会话成本按 ROADMAP 实测。

音频回调及字幕锁内不运行云请求、文档解析或长事务。加载工厂和任务创建者负责登记、取消及释放资源，清理可重复调用且保持安全；等待有截止条件，超时不代表资源已退出，不能提前销毁运行中的线程、进程或管道。

## 职责定位

模块名相对 `linguaflow/`；按需要定位，不要求每次开发读取全部文件。

| 职责 | 主要模块与边界 |
| --- | --- |
| 轻量数据、设置 | `core.py`、`preferences.py`、`model_options.py`、`translation_config.py`；集中格式、默认值、迁移和选择，无 Qt/模型依赖 |
| 桌面装配 | `app.py`、`management.py`、`workspace_widgets.py`、`settings_binding.py`；显式快照/信号连接，不把窗口传入业务 |
| 呈现与系统窗口 | `ui_theme.py`、`ui_components.py`、`ui_backdrop.py`、`caption_view.py`、`playback_controls.py`、`ui_tooltips.py`、`subtitles_overlay.py`；回放音量控件只发出数值，由窗口绑定应用音频输出；系统调用收敛 `window_platform.py` / 按需 `ui_macos.py` |
| 原文即时预览 | `source_preview.py` 从完整 ASR 快照将文字修订投影到已有卡片，未变化卡片及译文沿用原身份，跨边界改写仅调整受影响区域；WLK worker 在 SaT 之前发布，Qwen 修订通道可在 SaT 工作期间独立更新。预览版本与已映射前文分开校验，桌面/悬浮窗立即显示；不进入翻译规划或改变 mapper 定稿状态；`preview_captions` 将最新预览投影为保存草稿，后台队列按版本合并，正常异常收尾共用该投影 |
| 录音与传输 | `recording_state.py`、`wlk_session.py`、`capture_control.py`、`journal.py`；会话、采集代次、PCM 次序、停止边界 |
| 回放增益 | `playback_stream.py` 将原始 WAV 作为可随机定位的只读流提供给媒体播放器，按读取块处理 PCM 增益并限制峰值，不生成文件副本；未完成录音经锁检查后仅在读取视图修复固定 PCM WAV 的长度，原件不变；`playback_controller.py` 拥有输入流并在切换/关闭时释放 |
| 系统音频 | `audio.py`、按需 `audio_macos.py`；Windows WASAPI，Mac CoreAudio 输入 / ScreenCaptureKit 电脑声音，只回传 PCM，复用公共保存/字幕流程 |
| 推理启动与识别 | `wlk_worker.py`、`inference_startup.py`、`backends.py`；统一装配/资源登记。`qwen_audio.py` 保留原声队列及 VAD 标签；`qwen_accurate.py`、`asr_stability.py`、`qwen_revisions.py` 负责共享窗口、原文确认与修订；`mlx_asr.py` / worker 仅负责独立模型协议 |
| 分句与翻译 | `semantic_model.py`、`semantic_cache.py`、`wlk_captions.py`；`translation_context.py` 规划，`translation_queue.py` 排队，`translation_service.py` 消费/发布，`translation_models.py` / `llama_translation.py` 适配模型 |
| 保存与文件库 | `recording_save.py`、`recording_document.py`、`recording_export.py`、`library.py`；锁适配在 `library_access.py`，启动/复制迁移在 `library_startup.py` / `library_migration.py` |
| 准备与运行环境 | `runtime_paths.py` 路径权威；`runtime_install.py` / `runtime_base.py` / `runtime_cleanup.py` 管事务与归属；`runtime_preparation.py` 管预热租用；`preparation_task.py` 管监督进程，模型管理/准备复用它 |
| 课程材料与来源 | `knowledge/materials.py`、`glossary.py`、`session.py`、`schemas.py`；`rendering.py` / `render_document.mjs` / `render_web.py` 管独立渲染，`readings.py` 管逐页解读 |
| 课程任务与存储 | `knowledge/client.py` / `worker.py` 消息与后台；`files.py` 路径/原子 IO，`storage.py` 来源/笔记短事务，`retrieval.py` 检索，`api.py` / `harness.py` 许可、预算及 SDK |
| 更新与恢复 | `updates.py` 源码检查；`native_updates.py` 原生桥接；`update_config.py` 身份；`update_recovery.py` 独立恢复。`packaging/recovery.c` 只保留进程身份、退出和原子移动差异 |

原生更新事件先排入 Qt 线程，按请求代次过滤；后台检查终态回收状态但不显示无更新/失败提示，用户主动查看时沿用同一请求并显示结果。Mac 通过 Sparkle 的周期结束委托补齐后台失败回调，取消后的迟到选择自动拒绝。

## 诊断日志

Qwen 确认按当前窗口直接输出累计，可靠换窗裁剪并继承已有观察，失配重建基准；`RevisionStore` 传递可不连续的 `stable_ranges`，兼容字段 `stable_end` 仍只代表连续前缀。字幕逐段检查覆盖范围与相邻已确认后文，前方存疑不会屏蔽后方字幕。显式收尾只关闭当前直接假设，挂起/复制的存疑历史不补成已确认；音频释放与 SaT 候选规则不由此改变。

`qwen_audio.NonzeroPCM` 在窗口前逐 10 ms 帧拦截全零输入；零段标记让解码队列先处理短尾音，失败保留标记以便重试。`KeptAudioClock` 映射保留采样与原录音时间：容量、新增量和确认推进不计零段，修订、字幕、调度 token 与日志仍用原时间；VAD 释放参考仍按原录音标签选择。原始 WAV 和采集/VAD 流不经此过滤，零段不清窗或强制定稿。

`diagnostic_log.py` 提供进程独立 JSONL 轮转日志与无用户正文的异常堆栈；`diagnostic_archive.py` 管封存块压缩、完整性校验、跨进程历史预算和崩溃遗留恢复。桌面/worker 入口初始化；Session 生成会话 ID 并传给 worker。Qwen 记录解码序号、窗口及推进原因，通过已有协议回传耗时元数据，由桌面补采集侧积压估计。保存与翻译捕获异常分别在所属线程记录，日志不接管第三方原始 stdout/stderr，也不改变解码调度。

`capture_diagnostics.CaptureTrace` 对照 Mac 原生回调与录音写入前的 PCM，以 `session + capture_id + source_revision` 关联，`recording_start_seconds` 标明本段在录音中的起点。仅记录首包、连续全零达到 3 秒及恢复、原生有效音频包中断达到 3 秒及恢复、首个超过 1 ms 的时间戳跳变和关闭汇总；持续静音/中断不重复刷日志，剩余跳变只累计。保留样本数、峰值、原生首尾时间戳、缺包间隔及流开关/错误码，不保存波形或正文，不替换音频、改变定稿或自动重连；诊断时间戳读取失败单独记录并继续原有 PCM 流。

Qwen 的 `asr_decode_start/end` 可按 `session + decode_id` 关联：窗口范围、输入长度、新增音频、耗时和触发原因；`admitted_audio_seconds` 单列不含恢复保护音的新增预算，`asr_audio_policy` 记录有效上下限；`asr_window_roll` 记录参考点/低能量/积压保护原因、切点及移走/保留长度；`asr_idle_start/end` 记录长静音等待和携带的原声长度；`asr_commit` 记录收尾原因；`asr_revision` / `caption_revision` 记录字符数、稳定长度及定稿条件，不含正文。`asr_capture_lag` 是收到结果时采集进度减解码覆盖末端的估计，不是词级延迟；`pipeline_progress` 另记流水线积压和磁盘待送量。窗口重叠不算新增音频，空文本也保留本次解码耗时。Whisper 有公共会话/积压/字幕日志，但没有套用 Qwen 的内部窗口事件。

处理链的关联与决策日志：

- Qwen `asr_revision` 区分连续前缀、当前直接输出及全部区段的确认字符数、范围数量与窗口文字起点；`unconfirmed_history` 仅表示前缀存在缺口，不限制后方区段。`asr_confirmation_reset` 只在对应失效时记录原因并关联 `decode_id`；多轮一致性不足、推进不足及尾部保留仍留证据。`asr_commit` 关联最后一次解码，收尾不一定产生新解码，也不代表所有历史文字已确认。
- `asr_zero_start/end` 仅记录进入/恢复及跳过的原时间范围；`zero_input` 标明短尾音解码原因，`skipped_zero_seconds` 区分窗口原时间跨度与实际送入模型的长度。持续零输入不逐包落盘。
- `source_revision` 将 `decode_id` 连接到 `source_stream + source_version`；版本只在修订存储接受变化时增加，记录区间与区间版本。`_diagnostic_source` 随同一锁内生成的内部快照传递，不进入 Caption 或录音文件格式。处理快照可能跳过中间版本；需按 `source_revision` 顺序还原各区间元数据，不能假定一次识别恰好对应一次分句。
- 每次字幕映射分配 `mapping_id`，但只在实际调用预测器、字幕发生变化、显式收尾或失败时写 `caption_mapping_end`；无变化的纯缓存轮询不写开始/结束或缓存命中事件。关键结果的 `splits` 附带本次最多两个分割用途、原 `split_id`、缓存状态和源文偏移，保留缓存来源关联。计时从本次映射开始计算，不需要每次入口另写一条记录。`sat_call_start/end` 记录每个真正执行的重叠文本窗口预测器调用；结束记录的 `model` 内嵌实际推理起点、耗时、阈值及成功/失败信息，嵌套调用不再单独写模型开始/结束。独立模型调用仍保留模型事件。即使结果没改变字幕，真实调用和失败也保留。每个候选位置仅记录一次：结束记录的 `boundaries` 包含首批最多 32 个源文字符偏移，其余以同一 call ID 的 `sat_boundaries` 接续；`offset/total` 标明完整性，候选顺序和重复值保留。`outside_core/separator` 是各块 `positions` 中被过滤项的局部索引，其余即采用项；空原因数组省略。不记录正文或概率数组。缓存重用时边界相对原分割的偏移按本次 `source_offset` 换算。
- `caption_revision` 记录源文范围、旧范围、切分版本、改变类型（文字/边界/时间/确认/可翻译状态）、边界观察次数、等待时长和已确认后文量；`caption_removed` 表示被重新映射淘汰的字幕 ID。它们是应用处理后的结果，不能把任何一次修订都算成 SaT 改了句界。
- `translation_planned` 记录初译/定稿触发与背景字幕版本；`translation_queued` 为每次入队分配 `translation_task_id`，携带源版本、`mapping_id`、字幕/切分版本与阶段。覆盖、删除、过期、取消和消费者退出分别留下终态。`translation_batch_start/compute_end/end` 每个批次各写一条（单条翻译也作为单成员批次），共同上下文数量、分句门等待、缓存与计算耗时只写一次。三个阶段的 `members` 均携带每个任务的完整关联字段，开始阶段另有各自等待时间，计算结束另有各自输出字符数和失败状态；批次通过 `translation_batch_id` 关联成员。重新排队是新任务，`retry_of` 指向旧任务。
- `translation_publication` 在现有发布校验内记录 applied/rejected 及拒绝原因；单条任务可直接关联 task ID，批量按 batch ID 与字幕 ID 对应。`translation_batch_end=publication_returned` 仅表示发布回调正常返回，是否采用看 publication；错误状态也可能被成功发布。取消只表示消费者停止等待，已进入线程的推理可能仍在运行；强杀进程没有可靠终态，不能据缺少结束事件断言模型挂起。

日志 schema 3 使用紧凑 JSON 分隔符，保留可读字段名以及每行自己的时间、进程、线程、会话和关联信息；不依赖可能先被轮转删除的首行字典。schema 2 旧文件不改写。关联上下文使用 ContextVar，传入 `asyncio.to_thread`，退出作用域恢复；只包含 ID 与元数据。默认记录关键节点和真实变化，不把高频轮询次数当作诊断信息；缓存计数不另设周期日志。原有低频进度日志仍约 5 秒限频，资源约 10 秒采样；实际推理、字幕变化、任务生命周期和异常不按该频率丢弃。日志仍有队列与轮转上限，检查 `dropped_events` 及轮转文件后才能判断链路是否完整；不通过扩大轮转预算掩盖噪声。这些事件不证明前端已显示，也不能在没有录音和对应版本正文时判定词错误、分句质量或翻译准确率；本轮不增加正文追踪或前端回执。

`ui_action` 与 `ui_dispatch` 按操作 ID 关联同步派发；`handled` 仅表示回调返回，异步任务的成功以独立结果事件为准。准备任务使用 task ID，保存/打开录音使用 recording ID，会话结束清除默认 session。明确绑定关键命令，不安装全局鼠标/键盘追踪器。`resource_monitor.py` 在桌面后台线程用 psutil 采样系统与本进程树；Windows NVIDIA 与 Mac `ioreg` 查询均有超时和失败退避，Mac 仅解析根加速器的 `PerformanceStatistics` 利用率白名单字段；不解析子树、不保留注册表原文。采样异常只在首次失败及恢复时记录。资源采样不枚举音频设备。

写盘使用有界队列与独立线程，空闲线程由队列唤醒，退出发送哨兵排空；字段深度、数组长度和单条大小均有上限。异常、坏字段、协议回传和日志故障不传播到业务；队列溢出报告丢弃数量，不能将日志视作无损审计。耗时回传仍走原协议，不依赖写盘完成。

开发回放可用 `AGENTSCRIBE_LOG_DIR` 指定独立证据目录。日志参数不改变模型、窗口、刷新或定稿策略。

轮转将当前文件关闭并改为唯一 `.pending` 封存块，再打开新的活跃文件。归档先流式 gzip 写临时文件并同步磁盘，读回校验 SHA-256/CRC 后原子发布，最后删除原件；归档时间沿用原始最后写入时间。目录 OS 锁在 Mac/Linux 使用 `flock`，Windows 使用字节区间锁，序列化恢复、发布和预算清理；锁文件持久存在，进程退出自动释放锁。只有已发布 `.gz` 计入共享预算，活跃文件、失败原件及临时文件不计入；正常尾部在写线程退出时归档，失败重试不阻断录音。原始文件恢复需要确认 PID 不存活，封存块是不可变数据，可由任一持锁进程恢复。保留参数和失败边界见下列使用指南。

日志目录、轮转保留、隐私及故障反馈方法统一见[使用指南](WORKSPACE.md#诊断日志与问题反馈)。字段用于解释运行过程，不构成真实设备性能或异常退出恢复的验收证明。Mac 驱动字段口径参照 [Stats 的原始采样实现](https://github.com/exelban/stats/blob/master/Modules/GPU/reader.swift)，命令选项核对 [Apple ioreg 源码](https://github.com/apple-oss-distributions/IOKitTools/blob/main/ioreg.tproj/ioreg.c)；这些参考不替代本项目 Mac 实机验证。

## 状态与资源归属

### 桌面模块边界

主窗口保留对外操作入口、控件绑定和显示反馈；录音、保存、模型准备、迁移与退出事务由上文的共享后台流程负责。以下显示与数据模块不导入 `app`，也不通过持有整个 Window 或动态代理访问业务状态：

| 模块 | 独立职责与接口 |
| --- | --- |
| `transcript.py` | 字幕映射与惰性 ID 顺序；内容修订复用顺序，增删才失效 |
| `caption_feed.py` | 实时字幕的 200 条显示窗口、分页、预览与跟随；已保存加载及回放模式展示全部卡片，通过信号请求定位播放 |
| `library_browser.py` | 录音树的构建、展开与选择显示；接收库索引，不自行执行迁移或删除 |
| `playback_controller.py` | 播放器、音频输出及文件流的唯一所有者；接收文件和恢复许可，通过信号反馈状态、错误和位置 |
| `recording_controls.py` | 录音/播放控制区的布局与控件；不发现设备，不启动会话，操作由窗口连接 |
| `window_chrome.py` | 窗口按钮、外框和图标；正式窗口与组件 Demo 共用 |

Window 的薄转发入口和控件引用用于现有调用方组合；旧录音属性直接指向 RecordingData，不保留第二套业务状态。跨模块的保存资格、录音锁、迟到结果与退出门禁由共享后台流程判断，不分散到纯显示组件。

### 高频路径

- 预览原文直接显示，通过 ID 映射复用字幕卡片；以未变化整卡锚定局部差异，限制大幅改写的字符比较规模，避免每次重算整段历史。已有字幕内容修订不重建分页，分页查询复用 Transcript 的 ID 顺序。
- 分句的时间和语言定位在有序字符片段上二分查找，保留时间定位的左边界与语言选择的右边界语义；分句、ID 修订及确认规则不变。
- Qwen 通过 `ContinuousQwenPCM` 复用 WLK 串行队列和积压合并，替换其丢弃自然静音的入口；VAD 标签保留检测时刻及原始采样时间，不能借用尚未到达的检测结果。原声窗口规则见 [字幕 spec](specs/captions-translation.md)。长静音只暂停模型输入；被挂起的旧假设不伪装为已确认，新段使用原录音时间，SaT 与翻译策略不变。
- Qwen PCM 使用 `audio_processing.buffer.PCMBuffer` 的连续存储，追加只写新采样，容量不足时增长或压紧，消费窗口只移动起点。临时积压结束后缩回合理容量；推理输入仍单独复制，避免共享可变缓冲。预留容量减少复制，但不承诺空闲时比零长度数组占用更少内存。
- 保存仍完整写入 JSON，复杂度不变成常数；过期排队请求在冻结字幕前拒绝，导出直接复用排序后的 Caption，按文件逐个生成，并核对实际字节后跳过相同文件的替换。失败或外部修改后的导出仍需恢复，不用成功缓存掩盖旧错误。

### 生命周期与结果有效性

- 模型和推理配置使用启动时 Settings 快照；采集来源单独按递增代次更新，不改变录音文件和采样时钟。Caption 的原文/切分版本与译文来源分开，队列发布不得反向覆盖当前原文；保存回执绑定录音、视图、版本和终态。准备、渲染和更新的有效性应按各自任务归属判断，不套用字幕字段；未落实的检查见 ROADMAP。
- 分句线程的取消等待与实际退出分开处理：协程取消不释放仍在运行的 mapper 的锁；正常停止先发布在途结果再做 EOF，整场取消等待退出并抑制迟到结果。
- 正常停止关闭新采集入口，允许已接受音频及同一会话有效字幕/翻译在收尾期限内完成；取消、超时或换代失效后的结果不得发布。收尾与取消不是同一状态，重复停止不重置期限。
- Session 在等待运行环境/模型之前启动采集线程；首个已保存块确认录音状态，模型 ready 只启动缓冲发送，不再次启动采集。加载中的 PCM 留在磁盘 journal，模型就绪后无墙钟节流地发送，推理队列有界并将背压传回 journal；进度用采集时钟减已处理时钟，不把“已发送”冒充“已识别”。加载期间停止也受总收尾期限保护。
- `process_platform` 的后台入口先建立进程归属，再导入 `wlk_worker` 或 `knowledge.worker`。Windows 由桌面持有禁止脱离、关闭即回收的 Job Object，入口加入后关闭自己的 Job 句柄；Mac 使用独立进程组。清理覆盖主进程已退出但后代仍持有输出管道的情况，读写线程未退出时拒绝直接关闭其缓冲流；课程清理失败保留归属供后续重试。
- Session 拥有采集和推理进程；准备监督进程、课程进程和翻译服务分别由创建者回收。加载工厂登记可取消资源，迟到对象也关闭。进程确认退出、读写线程结束后才关闭管道。
- 预热池关闭拒绝新租用，但保留工作进程直到清理成功；同步重试与异步关闭串行执行。翻译服务复用公共管道清理函数，读线程超时保留引用并报错，成功后才清空并注销退出清理。录音库线程启动失败也走排队的完成信号，在 UI 线程释放任务并报告错误。
- 推理预热与课程后台共用 `process_platform.start_worker`、`stop_worker`、`close_process_transport`，统一启动失败时的归属释放、进程树回收和管道关闭顺序。调用方保留自己的协议、串行化和超时；课程后台清理期间仍使用同一份资源引用，失败不搬移或丢弃，成功后才清空。启动线程可能迟到创建日志线程，公共清理按需取得并等待它，不提前关闭输出流。
- `Window.closeEvent` 等待保存及自有任务；壁纸任务用非阻塞轮询等待线程 join，拒绝迟到图像并重新请求关闭，Qt 不提前退出。
- `CaptionText` 缓存当前内容/字体/尺寸对应的文字命中区域，交互状态变化才重绘字幕卡片；悬浮窗跳过未变化内容的样式与文本更新。全局提示管理器在应用退出或气泡销毁时停止计时并注销事件过滤，禁止向已销毁的窗口发送显示/隐藏操作。
- 课程桌面层只传消息。实时模块仅使用轻量 schemas/glossary，不依赖 SDK、worker 或 harness；云端失败不能阻断录音/字幕保存。库移动/删除前回收课程后台是文件一致性要求。

## 运行环境与当前策略

- 桌面、WLK 与 MLX 的依赖和运行环境隔离，重型模型依赖不进入桌面启动或轻量核心数据模块。解释器和组件路径经 `runtime_paths.py` 解析：源码运行组件在 `.runtime/`，安装态在用户数据 `runtime/`；WLK/MLX 使用管理槽位，兼容已有 `.venv-wlk` / `.venv-mlx`。桌面 `.venv` 仍是源码开发入口，操作见 [WORKSPACE](WORKSPACE.md)。
- 平台库按需导入，另一平台能导入共享模块；Mac 不安装 Windows CUDA 组件。路径兼容中文、空格与深目录，平台差异收敛在音频、权限、窗口、进程和模型协议适配层，不复制公共业务。
- 运行环境在最终目录建立并原子切指针；依赖/ABI/平台与回退链统一决定复用和清理，不按应用版本无条件重装。模型权重与运行组件分别准备；兼容入口保留，不自动搬迁旧库或模型。
- 当前 ASR 与 SaT 共用并行加载和取消管理，SaT 在 CPU 运行，ORT 优化缓存按运行库、架构和权重隔离。模型准备与开录只读缓存的具体路径见 `inference_startup.py`、`semantic_model.py`、`semantic_cache.py`；这些是当前方案，调整需比较真实链路质量、延迟和资源。
- 当前 llama.cpp 适配对 GPU 选择校验全部层已卸载到所选设备，CPU 选择显式关闭 GPU 层，并关闭历史请求主机缓存以控制保留量。具体实现见 `llama_translation.py`；不把这些设置本身当作性能改善证据。
- 原文确认及初译阈值由 `asr_stability.py` / `wlk_captions.py` 维护，上下文默认值与预算由 `translation_config.py` / 模型适配维护，合并批量上限由 `translation_queue.py` 维护。规范要求有效、完整和可追溯，不把当前数值或实现方案当作永久产品约束。
- 课程原页渲染当前使用独立 LibreOffice Kit 和本地 Qt 渲染器，受限工具循环使用 Deep Agents；它们是现行依赖方案，许可、静态覆盖和来源约束仍由课程 spec 定义。代码包继续使用 `linguaflow` 内部名，并保留旧启动入口、偏好和录音兼容。

## 数据与适配边界

| 权威内容 | 位置/责任 |
| --- | --- |
| 成功保存的原文、设置与音频 | 每个录音的 `session.json` / WAV；保存服务负责写入资格 |
| 课程原件、页面快照与解读 | 课程 `.agentscribe/`；独立版本发布，兼容旧布局 |
| 关联/许可、来源与笔记 | 录音 `knowledge/manifest.json`、`knowledge/state.sqlite`；数据库不取代录音主文件，个人编辑不可被 AI 覆盖 |
| 用户/资源/模型/解释器路径 | `runtime_paths.py`；安装包只读，用户目录独立，保留旧库和模型缓存 |

录制中改名等待已有保存完成，将 `pending_name` 原子写入 `session.json`；后续保存保留该显示名称，采集目录和锁路径不变。成功收尾并释放锁后同步目录名，冲突保留原目录与名称。库操作按目标范围检查，不因整理其他录音而中断当前会话或课程后台。

`session.json` 与衍生字幕文件分别原子替换，不是整个录音目录的一次事务；WAV 在采集中流式写入。写入线程结束不等于全部所需文件保存成功，保存资格仍以带错误与版本信息的回执判断。

Windows 课件 IO 以扩展长度路径访问，普通路径用于身份比较；Qt/Office 使用临时副本渲染，临时目录先展开系统可能返回的 8.3 短名称，再按原有归属校验发布，Mac 沿用原渲染路径。VAD Float32 与 Windows nagisa/DyNet 中文路径兼容集中在 `runtime_compat.py`，保留真实算法；不以假分词或异常吞没绕过。

固定依赖/组件版本由 `pyproject.toml`、`requirements-*.txt`、平台锁与 `packaging/updates.json` 维护。`tests/test_architecture.py` 检查显式导入循环、核心隔离和依赖方向，不能覆盖所有动态导入或真实模型行为。
