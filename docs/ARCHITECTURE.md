# 架构与实现边界

本文维护实现职责，行为要求见 [spec](specs/README.md)，测试方法见 [TESTING](TESTING.md)。以下对应当前源码，不能当作已发行或全平台验收证明。

## 数据与执行流

```text
Window / 设置快照
  → Session：采集 → AudioJournal（有序 PCM / 暂停标记）
  → WLK worker：音频处理 → ASR → 修订记录 → SaT / CaptionMapper
  → ContextPlanner → 最新版本队列 → 模型适配 → 有效性校验 → 字幕
  → RecordingSaver：冻结快照 → 串行原子保存 → 带归属/版本回执

已保存定稿 / 本地材料 → 可选 knowledge 子进程 → 许可/预算检查
  → 页面解读 / 受限 harness → 来源版本事务 → 笔记与引用
```

Qt 线程只装配和显示。采集、推理、下载、渲染和磁盘操作不阻塞它；业务不反向读取 Window。音频回调及字幕锁内不运行云请求、文档解析或长事务。

## 职责定位

模块名相对 `linguaflow/`；按需要定位，不要求每次开发读取全部文件。

| 职责 | 主要模块与边界 |
| --- | --- |
| 轻量数据、设置 | `core.py`、`preferences.py`、`model_options.py`、`translation_config.py`；集中格式、默认值、迁移和选择，无 Qt/模型依赖 |
| 桌面装配 | `app.py`、`management.py`、`workspace_widgets.py`、`settings_binding.py`；显式快照/信号连接，不把窗口传入业务 |
| 呈现与系统窗口 | `ui_theme.py`、`ui_components.py`、`ui_backdrop.py`、`caption_view.py`、`subtitles_overlay.py`；系统调用收敛 `window_platform.py` / 按需 `ui_macos.py` |
| 录音与传输 | `recording_state.py`、`wlk_session.py`、`capture_control.py`、`journal.py`；会话、采集代次、PCM 次序、停止边界 |
| 系统音频 | `audio.py`、按需 `audio_macos.py`；只回传 PCM，复用公共保存/字幕流程 |
| 推理启动与识别 | `wlk_worker.py`、`inference_startup.py`、`backends.py`；统一装配/资源登记。`qwen_accurate.py`、`asr_stability.py`、`qwen_revisions.py` 负责共享原文确认与修订；`mlx_asr.py` / worker 仅负责独立模型协议 |
| 分句与翻译 | `semantic_model.py`、`semantic_cache.py`、`wlk_captions.py`；`translation_context.py` 规划，`translation_queue.py` 排队，`translation_service.py` 消费/发布，`translation_models.py` / `llama_translation.py` 适配模型 |
| 保存与文件库 | `recording_save.py`、`recording_document.py`、`recording_export.py`、`library.py`；锁适配在 `library_access.py`，启动/复制迁移在 `library_startup.py` / `library_migration.py` |
| 准备与运行环境 | `runtime_paths.py` 路径权威；`runtime_install.py` / `runtime_base.py` / `runtime_cleanup.py` 管事务与归属；`runtime_preparation.py` 管预热租用；`preparation_task.py` 管监督进程，模型管理/准备复用它 |
| 课程材料与来源 | `knowledge/materials.py`、`glossary.py`、`session.py`、`schemas.py`；`rendering.py` / `render_document.mjs` / `render_web.py` 管独立渲染，`readings.py` 管逐页解读 |
| 课程任务与存储 | `knowledge/client.py` / `worker.py` 消息与后台；`files.py` 路径/原子 IO，`storage.py` 来源/笔记短事务，`retrieval.py` 检索，`api.py` / `harness.py` 许可、预算及 SDK |
| 更新与恢复 | `updates.py` 源码检查；`native_updates.py` 原生桥接；`update_config.py` 身份；`update_recovery.py` 独立恢复。`packaging/recovery.c` 只保留进程身份、退出和原子移动差异 |

## 状态与资源归属

- Settings 是会话快照；采集来源另有递增代次。Caption 的原文/切分版本与译文来源分开，队列发布不得反向覆盖当前原文。保存回执同时绑定录音、视图、版本和终态。
- Session 拥有采集和推理进程；准备监督进程、课程进程和翻译服务分别由创建者回收。加载工厂登记可取消资源，迟到对象也关闭。进程确认退出、读写线程结束后才关闭管道。
- `Window.closeEvent` 等待保存及自有任务；壁纸任务用非阻塞轮询等待线程 join，拒绝迟到图像并重新请求关闭，Qt 不提前退出。
- 课程桌面层只传消息。实时模块仅使用轻量 schemas/glossary，不依赖 SDK、worker 或 harness；云端失败不能阻断录音/字幕保存。库移动/删除前回收课程后台是文件一致性要求。
- 运行环境在最终目录建立并原子切指针；依赖/ABI/平台与回退链统一决定复用和清理，不按应用版本无条件重装。

## 数据与适配边界

| 权威内容 | 位置/责任 |
| --- | --- |
| 成功保存的原文、设置与音频 | 每个录音的 `session.json` / WAV；保存服务负责写入资格 |
| 课程原件、页面快照与解读 | 课程 `.agentscribe/`；独立版本发布，兼容旧布局 |
| 关联/许可、来源与笔记 | 录音 `knowledge/manifest.json`、`knowledge/state.sqlite`；数据库不取代录音主文件，个人编辑不可被 AI 覆盖 |
| 用户/资源/模型/解释器路径 | `runtime_paths.py`；安装包只读，用户目录独立，保留旧库和模型缓存 |

Windows 课件 IO 以扩展长度路径访问，普通路径用于身份比较；Qt/Office 使用临时副本渲染后校验发布，Mac 沿用原渲染路径。VAD Float32 与 Windows nagisa/DyNet 中文路径兼容集中在 `runtime_compat.py`，保留真实算法；不以假分词或异常吞没绕过。

固定依赖/组件版本由 `pyproject.toml`、`requirements-*.txt`、平台锁与 `packaging/updates.json` 维护。`tests/test_architecture.py` 检查显式导入循环、核心隔离和依赖方向，不能覆盖所有动态导入或真实模型行为。
