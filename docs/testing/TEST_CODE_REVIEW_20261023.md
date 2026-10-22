# 测试代码全面审查（2026-10-23）

## 范围与结论

基于 `windows` 分支 `775fb20` 加本会话已有的拆分和分级改动。工作区原有修改全部保留，本轮只审查并记录，不修改测试或业务实现，不提交、推送。

覆盖 `tests/` 全部 121 个 Python 文件，其中 118 个测试文件、683 个测试函数，以及共享入口、夹具和测试配置；同时扫描 15 个无音频/模型/设备/包验收与评测脚本、pytest 配置和 CI。对内嵌 Python 字符串单独解析，避免只看到外层 `run_ui(...)` 而漏掉实际测试。函数主体合计 14369 行，不含文件级辅助代码，不能当作整个测试目录行数。

全量语法扫描、跨用例比较与相关调用方复核得到以下 **18 项确认的问题/维护缺口，以及 7 组精简候选**。其中 A01–A04 有受控探针证据；其余为可直接定位的静态事实，不等同于已在所有平台复现运行故障。未对真实设备、GPU、在线 API 或安装升级进行验收，也不宣称审查能保证穷尽所有运行时缺陷。

重复片段扫描得到 202 个候选块，归并为 111 组用例组合；大量属于导入、必要清理和同步，不是 202 个可删除用例。75 个函数调用 `run_ui`；44 个包含创建录音，30 个包含字幕回调，25 个同时包含二者。这些是准备模式的出现次数，不是重复测试数量，也不能据此计算提速比例。

本报告的“先处理/随后处理”表示整改顺序，不代替 [TESTING](../TESTING.md#测试重要程度) 的 P0–P3 用例风险等级。当前分级仍是初版，A11/A12 的误标尚未修正；用例数量与等级分布没有因本轮审查改变。

## 确认的问题与维护缺口

### A01：无音频防护缺少真实拒绝路径自测（先处理）

- 位置：[test_no_audio_runner.py](../../tests/test_no_audio_runner.py) 的两个测试；[test_no_audio.py](../../scripts/test_no_audio.py) 的 `GUARD`。
- 现状：一个测试比较生成的字符串是否等于 `runner.GUARD`，另一个手工写入 `blocked.log`；二者均替换了子进程运行，未实际执行防护代码。
- 反例：在内存中把 `GUARD` 改为空串，现有 4 个参数展开项仍全部通过。没有导入任何音频模块，也没有访问设备。
- 处理：保留入口参数/返回码单元测试，另用受控子进程验证 finder 拒绝目标模块并记录日志，以及防护可继承到 Python 后代。不能通过真的打开设备来验证。

### A02：P0 清理保护只检查目录存在，不能证明文件未损坏（先处理）

- 位置：[test_runtime_cleanup.py](../../tests/test_runtime_cleanup.py) 的 `test_environment_cleanup_preserves_user_changes_and_unconfirmed_ownership`。
- 现状：6 类保护情形最后都只断言 `protected.exists()`。
- 反例：替身清理函数把本次新建的合成 `lecture.wav` 内容截断，但留下目录，`extra-recording` 分支仍通过。所有操作严格限制在新建审查夹具内。
- 处理：按分支验证受保护文件的字节、清单和相关归属标记；“目录还在”不能替代“用户数据没被改变”。保留 6 个不同分支，不因断言相似合并掉边界。

### A03：闲置释放测试在断言前主动关闭 worker，掩盖自动释放缺陷（先处理）

- 位置：[test_runtime_preparation.py](../../tests/test_runtime_preparation.py) 的 `test_idle_expiry_releases_imports_and_active_lease_is_protected`。
- 现状：等到指针清空后先调用 `worker.close()`，才检查进程已退出。
- 反例：用“到期只清指针、不关闭 worker”的替身运行原测试，仍然通过；关闭由测试自身补做。探针没有启动真实进程。
- 处理：先确认闲置回收自身完成退出，再在 `finally` 做兜底清理。活跃租用保护仍独立断言，不能因合并而取消。

### A04：真实 llama 验收脚本关闭后访问已清空的对象（先处理）

- 位置：[check_llama.py](../../scripts/check_llama.py) 的 `main`；[llama_translation.py](../../linguaflow/llama_translation.py) 的 `LlamaTranslator.close`。
- 现状：`translator.close()` 成功后将 `process`、`reader` 设为 `None`，脚本随后访问 `translator.process.returncode`、`translator.reader.is_alive()`。
- 证据：使用真实 `close()` 和内存流替身，两个后置访问均产生 `AttributeError`。没有加载模型、启动进程或完整运行验收脚本。
- 处理：关闭前保留待核对的进程/线程引用，关闭后检查这些引用及适配器释放状态；确保翻译错误也能留下摘要，不被收尾报告异常覆盖。

### A05：本地回归入口没有进程外总期限或停滞诊断（先处理）

- 位置：[test_no_audio.py](../../scripts/test_no_audio.py) 的 `subprocess.run`；[test_diagnostic_log.py](../../tests/test_diagnostic_log.py) 的 `test_worker_exit_releases_diagnostic_output`。
- 现状：CI 有 15 分钟 job 上限，本地入口没有相应进程外期限；`PYTHONFAULTHANDLER=1` 不会自动定时转储卡死堆栈。
- 既有证据：上一轮全量运行停在 worker 日志用例；单独标准库事件循环初始化也阻塞在 Windows `socketpair/accept`。协程内部的 `wait_for` 无法限制事件循环创建阶段。
- 处理：给本地执行提供明确的外部总期限和停滞堆栈，终止时只处理本次测试拥有的进程。不得改套接字实现、换假事件循环或跳过相关测试换绿。

### A06：部分异步主任务没有期限，后面的 `queue.join` 超时不起作用（随后处理）

- 位置：`test_shared_finalization::test_frozen_asr_prefix_does_not_block_initial_translation_of_a_stable_sat_sentence`；`test_translation_batch::test_adjacent_requests_share_one_context_without_losing_subtitle_alignment`；`test_translation_context::test_empty_final_translation_keeps_initial_and_marks_failure`；`test_translation_limits` 的长历史、背景拒绝两例；`test_translation_service` 的加载失败、发布失败两例。
- 现状：直接 `await run_translations(...)`，部分之后才对 `queue.join()` 设置期限。若消费任务本身不返回，后面的超时检查不会执行。
- 处理：限制主任务本身，失败时取消、释放并保留原始错误；已有 `wait_for(queue.join())` 继续保护排空语义。不能把所有裸 `.wait()` 都判为问题：很多已被外层期限覆盖。

### A07：三处正式窗口测试绕过共享 Qt 错误门禁（随后处理）

- 位置：[test_model_options.py](../../tests/test_model_options.py) 的双平台设置往返；[test_macos_support.py](../../tests/test_macos_support.py) 的设置恢复；[test_mlx_asr.py](../../tests/test_mlx_asr.py) 的 Mac profile 往返。
- 现状：直接 `subprocess.run` 后仅检查返回码，不调用 `assert_ui_process`；其他 UI 用例会拒绝绘制回调、QThread/QProcess 销毁警告。
- 处理：复用共同退出/日志检查，同时保留各自的平台环境、UTF-8 解码和原期限。不把原生探针等有专属协议的子进程强行改成普通 Window 测试。

### A08：Session 辅助入口的失败路径回收不完整（随后处理）

- 位置：[test_wlk_session.py](../../tests/test_wlk_session.py) 的 `execute`；[test_runtime_preparation.py](../../tests/test_runtime_preparation.py) 的 `execute`。
- 现状：前者在 Session 启动后的事件循环/`tick` 异常时没有统一 `finally`；超时分支二次 `session.wait(5000)` 的返回值也未确认。后者的二次等待同样未检查。
- 影响：产品缺陷导致测试失败时，测试对象可能尚在运行；后续 Qt 对象销毁和其他用例会被污染，原始失败也可能被退出错误盖住。
- 处理：保存本次资源引用，失败后有界停止并确认退出；回收失败独立报告，不能吞掉原始异常。平台生产代码已有的 Job/进程组保护不能代替测试确认资源已释放。

### A09：部分正向状态检查依赖固定短等待（随后处理）

- 位置：[test_model_ui_boundaries.py](../../tests/test_model_ui_boundaries.py) 的 `QTest.qWait(250)`；[test_workflow_preview.py](../../tests/test_workflow_preview.py) 的 50/80/100ms 等待。
- 现状：等待固定时间后立刻检查后台合并、页面切换或任务进度。在较慢环境中可能尚未到达目标状态。
- 处理：等待实际回调/卡片/任务状态并设期限，布局稳定另行判断。验证双击抑制所需的 `doubleClickInterval` 和用于模拟慢任务的 sleep 不属于此项，不能机械删除。

### A10：部分外部命令没有自身的执行期限（随后处理）

- 位置：[test_packaging.py](../../tests/test_packaging.py) 的临时 Git 仓库命令；[test_sparkle_cycle.py](../../tests/test_sparkle_cycle.py) 的 clang/codesign；[test_ux_recovery.py](../../tests/test_ux_recovery.py) 的跨进程录音锁探针；[benchmark_ami.py](../../scripts/benchmark_ami.py) 的编排/版本探针和 [probe_macos_update.py](../../scripts/probe_macos_update.py) 的部分外部工具。
- 现状：这些明确写出的调用没有 `timeout`。录音锁探针在 UI 子进程内还有外层 35 秒限制，不能说整条测试完全无期限，但子探针仍缺少独立诊断边界。
- 处理：按任务成本限制外部命令，并回收自有后代。对通过 `**kwargs` 包装的调用先追踪调用方，不能仅凭缺少字面量 `timeout` 就判为无期限。

### A11：模型边界用例混合四种职责，P2 标注漏掉 P0 保护（先拆分）

- 位置：[test_model_ui_boundaries.py](../../tests/test_model_ui_boundaries.py) 的 `test_inventory_interfaces_and_background_export`。
- 现状：一个用例包含浏览器契约、模型变更的检查合并、三格式导出快照，以及补扩展名后拒绝覆盖已有文件；整个函数标 P2。
- 处理：独立出 P0 防覆盖场景；其他职责按组件或 UI 接线边界整理。格式断言的下移见 B03，不能简单把该用例整项降级或删除。

### A12：用户术语草稿保护仍有 P2 误标（先复核等级）

- 位置：[test_ui_feedback.py](../../tests/test_ui_feedback.py) 的 `test_course_disconnect_disables_actions_and_keeps_unsaved_terms_for_reconnect`、`test_real_course_worker_exit_and_reconnect_preserve_draft`。
- 现状：既检查断开后的控件，又检查用户手动输入的术语在断开/重连后不丢失；当前均为 P2。
- 处理：控件可用性为 P2，用户不可恢复的手动草稿保护应按已接受标准列 P0。拆开可独立运行的场景，或在同一因果链中按数据保护的主要风险标注，不把数据保护断言挪成无实际操作的空检查。

### A13：清理 pending 的归属测试没有覆盖“不属于自己”的分支（随后补齐）

- 位置：[test_update_recovery.py](../../tests/test_update_recovery.py) 的 `test_failed_prepare_clears_only_its_own_pending`；实现的 `clear_pending` 有 token 比较。
- 现状：只创建 token 正好相等的 pending，再断言被删除。即使实现无条件删除 pending，这个用例仍会通过。
- 处理：补不同 token 时原文件字节不变，并核对缺失/损坏 pending 的既有契约。它与崩溃回滚或普通成功更新不是同一个边界，不能拿后者冒充覆盖。

### A14：本地课件 UI 预览只验证 `<img>` 标签，未验证 Qt 实际解码（随后补齐）

- 位置：[test_knowledge_ui.py](../../tests/test_knowledge_ui.py) 的 `test_new_format_import_filter_and_local_preview_without_cloud` 及视觉页面展示用例。
- 现状：检查 HTML 含 `<img>`、页数和文字，但没有检查 QTextDocument 中图片资源是否有效。后台的图片解码测试不能独立证明 UI 的 URL/资源传输成功。
- 处理：保留一个真实图片进入正式面板后的资源/尺寸检查；控件过滤器、宽窄布局可使用轻量面板数据。不能用更多字符串或截图文件存在检查替代实际资源验证。

### A15：搜索用例没有完整验证名称承诺的已保存原文/译文场景（随后修正）

- 位置：[test_user_workflows.py](../../tests/test_user_workflows.py) 的 `test_search_locates_saved_source_and_translation_without_starting_playback`。
- 现状：创建录音、注入字幕后直接打开当前内存搜索，只检索译文“上下文”；没有明确保存并重开，`persist_session` 位于断言之后，也没有原文检索断言。自动保存可能发生，不等于明确验证重开后的内容。
- 处理：用保存后重开的录音准备数据，分别检索原文和译文，保留不自动播放检查。大历史测试覆盖了其他分页场景，不能直接当成这一组合已被证明。

### A16：全量分级审计没有接入日常校验（随后处理）

- 位置：[conftest.py](../../tests/conftest.py)、[pyproject.toml](../../pyproject.toml)、[checks.yml](../../.github/workflows/checks.yml)。
- 现状：声明了四种 marker，但“恰好一个等级”的检查仅由本地 `.work` 审计插件执行；默认 CI 不拒绝新增漏标或同时标两个等级。`--strict-markers` 单独使用也不能保证恰好一个等级。
- 处理：用轻量收集检查维护该不变量，并给检查自身提供缺失/重复标记的反例；默认执行范围不缩减。当前 1100 项的一次性检查通过，不代表未来自动受保护。

### A17：日常功能回归夹带无断言的截图及外观切换（可独立移出）

- 位置：[test_installation_ui.py](../../tests/test_installation_ui.py) 的 `test_update_settings_and_inline_storage_path`；[test_workflow_preview.py](../../tests/test_workflow_preview.py) 的取消/迟到进度用例。
- 现状：默认生成 PNG；取消用例还循环明暗主题、窗口尺寸并等待截图。这些图像没有自动内容判断，保存的布尔结果也未检查。正常准备流程还夹带控件高度、相对位置等断言。
- 处理：功能回归保留取消、迟到结果和重试；外观取证放到已有预览/按需截图入口，不能把生成 PNG 宣称为外观验收。其他受 `AGENTSCRIBE_SCREENSHOTS` 控制的按需截图与此不同。

### A18：核心正常流程中串入多种独立故障，失败定位与等级职责混杂（需整理）

- 位置：[test_ui.py](../../tests/test_ui.py) 的 150 行 `test_named_recording_start_finish_and_settings_routes`。
- 现状：正常命名/暂停/保存后，继续执行空录音停止、begin 写失败、删除恢复、迟到状态、暂停时关闭、Session 构造失败，还检查设置页搜索。前面的无关失败会阻止后续边界执行。
- 处理：保留一条完整正常流程及随流程必要的保存/释放断言；独立故障放到对应已有边界测试，缺失时再增加最小场景。不能为了减少函数数继续扩大它，也不能把所有失败分支删掉后称覆盖等价。

## 精简候选：先确认替代覆盖，再实施

| 编号 | 位置与发现 | 建议及保留边界 |
| --- | --- | --- |
| B01 | `test_ux_recovery::test_long_recording_search_pages_and_playback_load_history` 用 405 次 `on_caption` 准备历史数据；与跨页不同高度用例都走新录音与保存/加载 | 历史数据直接通过真实 Library 准备，再走正式加载/搜索；保留 405 条分页和不同高度边界。实时字幕→保存另有核心流程验证，不必每次逐条更新 UI；尚未计时，不承诺具体提速 |
| B02 | `test_ux_recovery::test_old_terms_acknowledgement_does_not_clear_new_edits` 只使用独立 KnowledgePanel，却通过 `run_ui` 额外建立 Window；通知进度/优先级也只需组件 | 保持隔离 Qt 子进程，仅建立目标组件。还须注意 `finish_ui_code` 会无条件导入 `linguaflow.app.Window`，不能只更换调用名就宣称已去掉完整 App 依赖。正式主窗口接线保留集成测试 |
| B03 | UI 导出用例对 SRT/TXT/Markdown 重复写文件并检查内容，底层 `test_recording_export` 已有格式/写入用例 | 三格式完整内容与草稿过滤集中到底层参数化；先补齐当前底层 Unicode 用例没有逐格式断言的过滤边界。UI 层保留代表格式的快照冻结/接线、取消和独立 P0 防覆盖，不直接删三次循环后宣称等价 |
| B04 | `test_knowledge_adapters::test_pytorch_and_mlx_adapters_share_revision_finalization_and_translation_policy` 与 `test_mlx_submission::test_shared_submission_retranslates_corrected_source_then_finalizes` 有长段相同提交准备 | 跨适配器流程保留装配一致性；另一个可缩为 MLX 独有或兼容入口断言。但前者走 `update_changes`，后者走完整 `planner.update`，不是已证明可删除的完全重复用例 |
| B05 | `test_model_options`、`test_llama_ui` 和 `test_ui::test_preferences_roundtrip_and_recording_guards` 多次启动/关闭/重开窗口验证设置 | 一条持久化主流程统一验证通用字段；后端、平台和自定义 GGUF 保留独有分支。不能用默认模型的往返替代自定义路径，也不能合并掉录音中的文件保护 |
| B06 | `test_library_migration.populated` 默认准备录音、课件和回收站；多种负向测试只关注一个变更/归属条件 | 保留代表性的全资料迁移用例；对不依赖课件/回收站的负向场景使用最小数据。不得以减少目录深度掩盖上一轮 WinError 206/3；专门长路径证据及待修问题保留 |
| B07 | 17 处从其他 `test_*.py` 导入辅助对象；四条流程复制 FakeSession 的大段信号定义，部分课程 UI 又各写有期限等待循环 | 稳定、共同使用的纯准备辅助代码移入现有支持层，保留各测试的不同信号行为和原期限；不要增加通用场景框架或可变全局夹具。这主要减少维护重复，不能直接算作减少执行量 |

## 不应误删的相似测试

- 双平台/双后端模拟验证不同装配分支，不能只保留当前 Windows 或当前模型。
- 同一层里，成功、失败、取消、迟到结果、版本 ABA、删除、权限、路径映射和真实跨进程锁是不同契约；同为 P0/P1 不是合并理由。
- MLXClient、LlamaTranslator 和预热 worker 的关闭都涉及管道，但资源归属与调用方状态不同；共享底层 close 函数不证明只留一个调用方测试即可。
- Session+替身 worker、真实 worker+替身模型、真实模型与真实设备分别证明不同范围，不能互相替代。
- 双击延迟、200 行分页阈值附近的样本、32/64 字节签名、不同归档 Range 响应和真实链接权限条件不是仅为凑数量。
- 正常流程中记录原件字节、取消后保留内容、真实关闭与资源释放是必要结果，不因分级而移成失去上下文的孤立断言。

## 证据、限制与后续顺序

1. 先补 A01–A04 的检测能力/脚本故障，修正 A11/A12 的分级边界。
2. 再处理 A05–A10 的期限、失败回收和统一错误门禁；这些会直接影响后续评估运行耗时的可信度。
3. 补 A13–A16 的缺失验证，移出 A17 的默认截图；整理 A18 和 B01–B07 时逐条记录保留覆盖，再运行相关回归。

本轮受控探针的 6 个原测试项在刻意退化的替身下仍通过，证明 A01–A03 的检测缺口，不是新的产品通过证据；A04 只复用真实关闭函数验证后置访问，没有运行模型。原始脚本、机器可读清单和结果位于：

- `.work/reports/test-code-review-inventory-20261023.json`：逐函数源代码、调用、断言和重复候选。
- `.work/reports/scan_test_review_20261023.py`：静态扫描脚本。
- `.work/reports/probe_test_review_20261023.py`、`test-code-review-probes-20261023.json`：A01–A03 受控反例；只操作独立合成夹具。
- `.work/reports/test-code-review-llama-probe-20261023.json`：A04 真实关闭函数后的两个 AttributeError。

上一轮完整回归的事件循环阻塞、HEAD 原版 Beta 超时、长路径迁移失败仍按 [VALIDATION](../VALIDATION.md) 记录；本轮没有重跑受阻全套、缩短路径或修改系统环境，也未把静态审查当成真实流程验收。已有脚本路径/产物维护项继续归 [ROADMAP R7](../ROADMAP.md)，迁移长路径缺口继续归 R1，避免在此重复新建同义待办。
