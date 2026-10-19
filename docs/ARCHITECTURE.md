# 架构与实现边界

本文维护实现职责与当前方案，行为要求见 [spec](specs/README.md)，测试方法见 [TESTING](TESTING.md)。职责描述不代表全部异常路径已符合规范；已确认的实现差距在 [ROADMAP](ROADMAP.md#实现缺口)，不能当作已发行或全平台验收证明。

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
| 原文即时预览 | `source_preview.py` 从完整 ASR 快照投影未分句的可修订尾部；WLK worker 在 SaT 之前发布，Qwen 修订通道可在 SaT 工作期间独立更新。预览版本与已映射前文分开校验，桌面/悬浮窗立即显示；不进入翻译规划或改变 mapper 定稿状态；`preview_captions` 将最新预览投影为保存草稿，后台队列按版本合并，正常异常收尾共用该投影 |
| 录音与传输 | `recording_state.py`、`wlk_session.py`、`capture_control.py`、`journal.py`；会话、采集代次、PCM 次序、停止边界 |
| 回放增益 | `playback_stream.py` 将原始 WAV 作为可随机定位的只读流提供给媒体播放器，按读取块处理 PCM 增益并限制峰值，不生成文件副本；未完成录音经锁检查后仅在读取视图修复固定 PCM WAV 的长度，原件不变；窗口拥有输入流并在切换/关闭时释放 |
| 系统音频 | `audio.py`、按需 `audio_macos.py`；Windows WASAPI，Mac CoreAudio 输入 / ScreenCaptureKit 电脑声音，只回传 PCM，复用公共保存/字幕流程 |
| 推理启动与识别 | `wlk_worker.py`、`inference_startup.py`、`backends.py`；统一装配/资源登记。`qwen_accurate.py`、`asr_stability.py`、`qwen_revisions.py` 负责共享原文确认与修订；`mlx_asr.py` / worker 仅负责独立模型协议 |
| 分句与翻译 | `semantic_model.py`、`semantic_cache.py`、`wlk_captions.py`；`translation_context.py` 规划，`translation_queue.py` 排队，`translation_service.py` 消费/发布，`translation_models.py` / `llama_translation.py` 适配模型 |
| 保存与文件库 | `recording_save.py`、`recording_document.py`、`recording_export.py`、`library.py`；锁适配在 `library_access.py`，启动/复制迁移在 `library_startup.py` / `library_migration.py` |
| 准备与运行环境 | `runtime_paths.py` 路径权威；`runtime_install.py` / `runtime_base.py` / `runtime_cleanup.py` 管事务与归属；`runtime_preparation.py` 管预热租用；`preparation_task.py` 管监督进程，模型管理/准备复用它 |
| 课程材料与来源 | `knowledge/materials.py`、`glossary.py`、`session.py`、`schemas.py`；`rendering.py` / `render_document.mjs` / `render_web.py` 管独立渲染，`readings.py` 管逐页解读 |
| 课程任务与存储 | `knowledge/client.py` / `worker.py` 消息与后台；`files.py` 路径/原子 IO，`storage.py` 来源/笔记短事务，`retrieval.py` 检索，`api.py` / `harness.py` 许可、预算及 SDK |
| 更新与恢复 | `updates.py` 源码检查；`native_updates.py` 原生桥接；`update_config.py` 身份；`update_recovery.py` 独立恢复。`packaging/recovery.c` 只保留进程身份、退出和原子移动差异 |

原生更新事件先排入 Qt 线程，按请求代次过滤；后台检查终态回收状态但不显示无更新/失败提示，用户主动查看时沿用同一请求并显示结果。Mac 通过 Sparkle 的周期结束委托补齐后台失败回调，取消后的迟到选择自动拒绝。

## 诊断日志

`diagnostic_log.py` 提供进程独立 JSONL 轮转日志与无用户正文的异常堆栈。桌面/worker 入口初始化；Session 生成会话 ID 并传给 worker。Qwen 记录解码序号、窗口及推进原因，通过已有协议回传耗时元数据，由桌面补采集侧积压估计。保存与翻译捕获异常分别在所属线程记录，日志不接管第三方原始 stdout/stderr，也不改变解码调度。

Qwen 的 `asr_decode_start/end` 可按 `session + decode_id` 关联：窗口范围、输入长度、新增音频、耗时和触发原因；`asr_window_roll` 记录切点、移走/保留长度；`asr_commit` 记录收尾原因；`asr_revision` / `caption_revision` 记录字符数、稳定长度及定稿条件，不含正文。`asr_capture_lag` 是收到结果时采集进度减解码覆盖末端的估计，不是词级延迟；`pipeline_progress` 另记流水线积压和磁盘待送量。窗口重叠不算新增音频，空文本也保留本次解码耗时。Whisper 有公共会话/积压/字幕日志，但没有套用 Qwen 的内部窗口事件。

开发回放可用 `AGENTSCRIBE_LOG_DIR` 指定独立证据目录。日志参数不改变模型、窗口、刷新或定稿策略。

日志目录、轮转保留、隐私及故障反馈方法统一见[使用指南](WORKSPACE.md#诊断日志与问题反馈)。字段用于解释运行过程，不构成真实设备性能或异常退出恢复的验收证明。

## 状态与资源归属

- 模型和推理配置使用启动时 Settings 快照；采集来源单独按递增代次更新，不改变录音文件和采样时钟。Caption 的原文/切分版本与译文来源分开，队列发布不得反向覆盖当前原文；保存回执绑定录音、视图、版本和终态。准备、渲染和更新的有效性应按各自任务归属判断，不套用字幕字段；未落实的检查见 ROADMAP。
- 分句线程的取消等待与实际退出分开处理：协程取消不释放仍在运行的 mapper 的锁；正常停止先发布在途结果再做 EOF，整场取消等待退出并抑制迟到结果。
- 正常停止关闭新采集入口，允许已接受音频及同一会话有效字幕/翻译在收尾期限内完成；取消、超时或换代失效后的结果不得发布。收尾与取消不是同一状态，重复停止不重置期限。
- Session 在等待运行环境/模型之前启动采集线程；首个已保存块确认录音状态，模型 ready 只启动缓冲发送，不再次启动采集。加载中的 PCM 留在磁盘 journal，模型就绪后无墙钟节流地发送，推理队列有界并将背压传回 journal；进度用采集时钟减已处理时钟，不把“已发送”冒充“已识别”。加载期间停止也受总收尾期限保护。
- Session 拥有采集和推理进程；准备监督进程、课程进程和翻译服务分别由创建者回收。加载工厂登记可取消资源，迟到对象也关闭。进程确认退出、读写线程结束后才关闭管道。
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
