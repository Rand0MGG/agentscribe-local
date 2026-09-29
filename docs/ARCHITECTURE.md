# 模块职责与依赖约束

项目按变化原因划分职责：界面布局、偏好格式、录音状态、文件管理、推理调度、翻译和音频处理分别维护。不以单个文件的行数作为拆分标准。`app.Window` 是桌面装配入口，负责连接控件和服务；业务模块不反向读取窗口属性。

## 当前边界

| 职责 | 模块 | 边界 |
| --- | --- | --- |
| 数据与导出 | `core.py` | Settings、Caption、SRT；不依赖 Qt 或模型 |
| 偏好格式 | `preferences.py` | 集中键、默认值、类型转换和历史后端别名；接受存储接口，不导入 QSettings |
| 控件适配 | `settings_binding.py`、`qt_controls.py` | 控件与偏好互转、生成独立会话配置快照；不持有 Window |
| 设置与对话框 | `workspace_widgets.py`、`management.py`、`deleted_dialog.py` | 显式传入所需控件/配置，通过信号报告操作；Qt parent 仅用于窗口归属与生命周期 |
| 界面表面与动效 | `ui_components.py`、`ui_theme.py` | 统一菜单、弹窗、渐显、可展开选项与颜色；不导入模型、会话或文件库；减少动态效果通过偏好控制 |
| 字幕浏览 | `caption_view.py` | 根据滚动位置自动跟随、平滑追踪底部、保留阅读位置与返回按钮；不改变 Caption 或推理流程 |
| 录音交互状态 | `recording_state.py` | 空闲、启动、聆听、收尾及对应按钮策略；不依赖 Qt |
| 文件库 | `library.py` | 普通本地文件夹、元数据、路径安全、迁移、最近删除；不弹窗 |
| 库启动策略 | `library_startup.py` | 默认/指定目录、重试、迁移策略；选择目录与错误展示通过回调注入 |
| 文件锁适配 | `library_access.py` | QLockFile 的获取和检查；只使用 Library 提供的已校验路径 |
| 本地推理环境路径 | `runtime_paths.py` | 会话、模型管理和音频工具共用；不导入 Qt 或模型 |
| 会话传输 | `wlk_session.py` | 采集、连续音频暂存、子进程协议及停止清理 |
| 推理装配 | `wlk_worker.py` | ASR 初始化、音频和字幕事件协调；不依赖桌面模块 |
| 字幕边界与修订 | `wlk_captions.py`、`qwen_revisions.py` | 文本边界、稳定性、版本保留；与 UI 独立 |
| 翻译调度 | `translation_queue.py`、`translation_service.py` | 合并排队版本、缓存、错误、过期结果拒绝；后端通过工厂注入 |
| 模型适配 | `backends.py`、`semantic_model.py`、`runtime_compat.py` | 实际模型及上游兼容接口；按需加载依赖 |
| Mac ASR 适配 | `mlx_asr.py`、`mlx_asr_worker.py` | WLK → 独立 MLX 环境，仅传递本地 PCM；复用 Qwen 窗口、字幕和翻译流程，不访问音频设备 |
| 音频实验室 | `audio_processing/lab.py`、`recorder.py` | 实验室负责交互，Recorder 负责定长采样/WAV/信号健康；可注入采集函数测试 |
| DSP 与评测 | `audio_processing/config.py`、`pipeline.py`、`health.py`、`evaluation.py`、`ami_evaluation.py` | 保持既有独立边界；评测不借用 UI 或修改原始识别结果 |

## 必须保持的行为约束

- 偏好新增或修改从 `PREFERENCES` 开始；窗口只装配控件映射。`audio_device` 在设备枚举时恢复，`library_directory` 在窗口构建前读取，两者有不同生命周期，不强行塞进控件恢复循环。
- 设备元组使用 Python 内容相等比较；Qt `findData` 对相同内容的元组可能无法匹配。设备不存在时保留原选择记录并提示，不偷偷切换来源。
- 启动时深拷贝音频配置，之后 UI 配置变化不能影响已经启动的会话。
- 录音控件的启用/禁用统一从 `Window.set_recording_state` 设置。停止后到达的 ready/status 不得恢复成聆听状态；错误不能被进度刷新覆盖。简洁状态显示在主界面，具体日志保留在诊断与提示中。
- 修改文件库前统一经过 `can_edit_library`：活动会话检查、保存未写入的字幕、必要时检查目标目录中的录音锁。磁盘安全校验留在 Library 内部，窗口不调用其私有方法。
- 原文提交和定稿由 ASR / 字幕层独立决定。SaT 保持必需，只负责分句；稳定尾部时钟只触发首次提交，ASR 段结束或会话 EOF 才触发定稿。
- `translation_context.ContextPlanner` 为首次提交和原文定稿分别建立请求快照，中间修订不触发翻译。最终上下文只捕获一次，不等待未来邻句。翻译开始前及发布时验证请求；初译可以对应较早原文，并明确记录来源。发布在字幕锁内执行，保留当前 Caption 的原文、时间和定稿字段，只更新译文、错误和翻译阶段/来源。出错或取消也必须归还已取出的队列任务计数。
- VAD 音频张量通过 `runtime_compat.configure_vad_float32` 显式保持 Float32，避免后台半精度模型加载改变 PyTorch 全局默认类型时崩溃；见 [修复与实测记录](testing/VAD_DTYPE_FIX.md)。
- 默认保存目录仍为安装目录下的 `录音`；开发态使用项目下的 `录音`。自定义目录不自动混入其他库的数据。取消选目录不进入无限重试；成功打开后才记住新的路径。

## 验证与后续修改

`tests/test_architecture.py` 扫描包内显式导入，检查循环依赖、核心模块的间接 Qt/模型依赖、推理层对桌面的反向依赖。这些是静态约束，不替代运行时测试，也不能识别所有动态导入。

测试覆盖偏好关闭重开、旧配置/损坏配置、设备恢复、启动校验和失败恢复、收尾状态、活动录音文件锁、最近删除恢复、翻译期间原文修订、翻译加载失败、队列清理和定长音频采样。Qt UI 与 QCoreApplication 测试使用独立进程，避免两种应用实例相互污染；核心逻辑直接测试，不加载模型。

2026-09-15 重构验证：完整测试 131 项通过，改动文件 Ruff 通过；使用真实 Windows Qt 窗口生成并检查主界面、设置页和窄窗口预览。示例音频是静音夹具，此验证不代表重新测量了 ASR/翻译质量或 GPU 性能。

当前保留 Windows 窗口材质/拉伸、QSS、ASR 参数、分句与修订算法。它们各有明确职责，本次没有为了搬代码而重写。后续增加业务逻辑时优先放入对应模块；只有跨控件的呈现协调留在 Window，避免再把 Window 作为通用服务传给其他组件。
