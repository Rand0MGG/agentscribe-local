# 0.3 集成验证记录（2026-09-07）

环境：Windows、Python 3.12、RTX 5070 Ti 16303 MiB、驱动 595.79。
推理环境：PyTorch 2.11.0+cu128，WhisperLiveKit 及 Qwen 适配的提交见 requirements-runtime.txt。

## 已取得的真实运行证据

| 测试 | 结果 | 证据文件（本机 .work，未上传） |
| --- | --- | --- |
| Qwen 0.6B + NLLB 1.3B / CUDA，79.484 秒重复语音 | 12 次完整原文、12 段译文；上游 RTF 0.28 | qwen-long-smoke.json/.log |
| Qwen 0.6B，无额外静音的 67.484 秒语音，短句映射阶段 | 12 次完整原文，36 条字幕及译文 | qwen-continuous-segmented.json/.log |
| Qwen 真实 Qt Session，严格离线 | 完整原文、GPU 译文、SRT；PyTorch 分配峰值约 4.08 GiB | qwen-final-session.log、qwen3-streaming-session.json/.srt |
| Whisper large-v3 真实 Qt Session，严格离线 | 完整词序列、GPU 译文、SRT；PyTorch 分配峰值约 9.85 GiB | whisper-session.log、wlk-whisper-session.json/.srt |
| Whisper large-v3，101.176 秒不重复英文语音，加 1 秒结尾静音 | 256 个参考词与输出词一致，归一化 WER 0%；全部短段有译文，峰值约 10.54 GiB | whisper-narrative.json/.stdout.log |

固定语音由 Windows Microsoft David Desktop 合成。短音频为 tests/fixtures/hello.wav；长音频与参考文本为 continuous-en.wav/.txt。词比较忽略大小写和标点；这些是合成英文回归素材，不是一般准确率基准，也不证明口音、噪声、中文或真实会议效果。

上述运行记录来自整合过程中的对应代码状态。随后调整过字幕映射、模型缓存解析和兼容代码，因此最终版本完整复测仍待完成，不能将表格等同于最终版本验收。

## 未通过的场景及保留的限制

- Whisper large-v3 反复播放同一句话 12 次的严格完整性检查失败。原版上游跨批次重复保护会重置解码段；一次缩小保护范围的实验导致后半段提交停滞，已撤回该实验。保留上游原始保护，没有声称此问题已修好。
- 101 秒不重复素材的零词错误结果出现在上述实验分支期间，该素材未触发重复保护；撤回实验后的最终版本仍应重跑，不用这一结果掩盖重复内容失败。
- Windows 上游对齐代码提示缺少 Triton，使用备用 median kernel；GPU 识别仍实际运行。没有隐藏该提示，也未把它当作所有问题的解释。
- 未在实体 Mac、实体 8GB 显卡、Qwen 1.7B 或所有支持语言上验收。Mac 当前桌面入口仅提供 CPU，不宣称已启用 MLX/Metal。
- 当前 Whisper CPU 模式不支持同进程 CUDA 翻译，会明确报错；Whisper CUDA + CUDA 翻译以及 CUDA + CPU 翻译均由配置表达，前者已实际运行。

## 后续验收命令

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m ruff check linguaflow scripts tests
.venv-wlk\Scripts\python.exe -m pip check
.venv\Scripts\python.exe scripts/smoke_session.py --backend qwen3-streaming
.venv\Scripts\python.exe scripts/smoke_session.py --backend wlk-whisper --model large-v3
.venv\Scripts\python.exe scripts/smoke_wlk.py --backend qwen3-streaming --translate --audio tests/fixtures/continuous-en.wav --reference tests/fixtures/continuous-en.txt --output .work/qwen-narrative.json
.venv\Scripts\python.exe scripts/smoke_wlk.py --backend wlk-whisper --model large-v3 --translate --audio tests/fixtures/continuous-en.wav --reference tests/fixtures/continuous-en.txt --output .work/whisper-narrative-final.json
```

长素材预设验收门槛 WER ≤ 5%，全部定稿段有译文且无错误；重复短素材的检查仍要求完整重复次数，不降低门槛将失败改成通过。
新 Qwen 长素材测试被自动审批因账户额度拒绝，未启动该进程。需要额度恢复后继续，并完成真实系统回环及最终代码/文档核对。此记录不表示目标已经完成。

最近静态检查：Ruff 通过；不依赖临时目录 fixture 的 12 项回归通过。此前整合阶段完整 18 项回归曾通过；最终全套重跑受沙箱临时目录访问权限影响，不能将其记为最终通过。CPU/GPU 安装修复已改为精确指定 PyTorch 构建后缀，避免已有 CPU 包被错误判断为满足 GPU 安装要求；该安装切换仍待实际复核。

## 2026-10-05 Windows 预热兼容修复与启动实测

修复此前审查 `45bdd80` 发现的 P1：设备配置到达前预热 CPU ONNX Runtime，后续 CUDA 设置无法替换已经导入的包。本轮在现有 `windows` 分支复用该更新中的预热进程与租用实现，仅接入相关模块；没有合并整个 Mac 分支，也没有修改 +3 dB 后台处理或重新引入严格离线。

现在打开应用时读取当前设备快照，先选 ONNX 包再预热导入；会话开始时再次核对，CPU/CUDA 包不兼容时重建进程，兼容时保留复用。SaT 的 CUDA 选择同样参与判定；PyTorch CPU/CUDA 使用同一套包，不为此无条件重建。预热不构造模型、不访问音频设备、不修改联网环境；顺序会话之间重置 WLK 模型状态，取消和失败的进程不复用。停止后的旧 Session 不能终止新租约；空闲 30 分钟或退出释放整个进程树。

### 真实运行与性能

环境：Windows 10.0.26200 / AMD64 / Python 3.12.8 / RTX 5070 Ti；Torch 2.11.0+cu128、WhisperLiveKit 0.2.26、Qwen3-ASR 0.0.6、Transformers 4.57.6。测试使用本地 Qwen3-ASR-1.7B / CUDA、SaT / CPU、相同英文配置与 +3 dB / -1 dB 峰值保护；翻译关闭。

使用 `tests/fixtures/hello.wav`，共 5.624 秒，SHA256 `3a84f3f9f8eedb77cd09ddd2dbd5386931185d995e29df847cca6e7534674475`；经 PyAV 转成统一 48 kHz PCM。实际 `Session → AudioJournal → wlk_worker` 按 1 倍速度投递，交替测试普通启动和已完成预热，各 3 次，设置、音频及输入完整性相同。

| 方案 | 点击到识别就绪 | 点击到首条字幕 |
|---|---|---|
| 普通启动，3 次 | 13.125 / 13.907 / 13.422 秒 | 14.797 / 15.579 / 15.125 秒 |
| 预热完成，3 次 | 5.453 / 3.328 / 3.047 秒 | 7.125 / 4.843 / 4.594 秒 |
| 中位数 | **13.422 → 3.328 秒** | **15.125 → 4.843 秒** |

首次后台预热本身耗时 8.328 秒，被移到应用打开后的等待阶段；它不是消失的计算成本。表中预热在点击前已完成，不能保证用户打开应用立即点击也得到相同收益。第一次预热会话仍要加载模型，后两次还能复用部分框架缓存；不是全新进程的三次独立预热。六次输入全部投递，均得到相同完整文本、两条定稿字幕，模型与最终字幕审计匹配。素材是合成短英文，不能推广为课堂正确率或所有模型启动耗时。

测速后补充了 Windows 进程树清理。最终版本追加一次真实预热文件检查，点击到就绪 / 首条字幕为 5.328 / 6.953 秒；完整字幕与清理通过。没有将这一次替换进上表，也未重复六次主测速。

### P1、内存和资源验证

- 使用真实已安装运行库，分别在预热后运行 SaT 的 CPU/CUDA 推理，各连续两次，分句输出一致。CPU 走 ONNX Runtime 1.29.0 的 `CPUExecutionProvider`；CUDA 走隔离的 1.23.2 包，实际模型会话包含 `CUDAExecutionProvider`，不是仅检查显卡或模拟导入。历史 `offline=True/False` 输入均不改变环境，Hub 与 Transformers 未被预热锁成离线。1 项集成检查通过，23.60 秒。
- 会话结束后另行观察真实 GPU 分配：WLK 单例已重置，PyTorch 已分配约 36.5 MiB、保留约 68 MiB，识别权重没有常驻以换取启动速度。该检查 1 项通过，22.86 秒；第一次测试包装器遗漏 `--prepared` 而超时，修正后重跑，失败日志保留，不计作业务运行失败。
- Windows 虚拟环境有启动器与实际 Python 两层。补测统计整个已知进程树：仅预热后驻留内存约 0.70 GiB，识别结束并清理模型后约 2.31 GiB，进程树私有提交约 4.32 GiB。运行库、CUDA 上下文和分配器仍有显著代价，不能说停止后内存全部归还。主测速 JSON 的早期内存字段只统计启动器，不用于推理内存结论；以 `resources.json` 为准。
- 健康空闲退出与真实预热超时均确认启动器及实际 Python 子进程退出，1 项资源检查通过，25.59 秒。复用已有平台进程树清理函数；不通过枚举或终止其他 Python 进程清理资源。

### 回归与范围

- `.venv\Scripts\python.exe scripts/test_no_audio.py -q`：**428 项通过、5 项跳过，40.87 秒**。覆盖复用、CPU/CUDA/CPU 切换、忙碌时拒绝第二租约、停止后迟到调用、取消、启动失败、超时、空闲过期、两端启动参数及原录音/字幕/保存路径。静态 Ruff 与差异检查通过。
- `.venv\Scripts\python.exe scripts/test_no_audio.py -q -s .work/cache/runtime-startup-20261005/test_measure.py`：1 项通过，112.07 秒。另运行同目录 `test_runtime_integration.py`、`test_resources.py`、`test_gpu_release.py`；全部完成且未发现原生音频导入尝试。完整测试曾因 UI 模拟构造器未接收新参数、进程启动模拟器误拦截清理命令而失败，修正模拟接口后重跑，未放宽原有断言。
- 全部产物保存于 `.work/cache/runtime-startup-20261005/`：测速 JSON、逐次事件/参数/字幕、SaT 探针、实际进程树内存、显存释放、脚本及失败日志。主测速对应的预热/会话代码另保留于 `measured-code/`，原先未提交版本备份于 `before/`。不下载模型或升级依赖。
- 此次未进行真实采集、播放、音频设备枚举、翻译链路性能、Whisper 启动性能或 Mac 实机测试；Mac 模拟分支测试不替代 Mac 验收。改动仅本地完成，未提交、推送、合并或发布。

## 2026-10-05 简化音频处理、CPU 分句与清理复核

此节记录同日后续改动，替代上一节中的 SaT 设备选择、CPU/CUDA 包切换和独立普通启动入口。原测速及失败日志作为历史证据保留。本轮仍在本地 `windows` 分支，保留已有未提交工作；未提交、推送、合并或发布。

### 最终行为

- 音频处理只保留连续重采样、固定 +3 dB 增益和 -1 dB 峰值保护，原始录音不变。删除音频实验室剩余实现、降噪、去混响、均衡、自动增益、预设及对应安装/实验脚本；旧增强配置读取时忽略退役字段。
- SaT 与语音活动检测固定使用 CPU ONNX Runtime。删除 SaT 设备、前瞻和单独准备控件，前瞻仍采用原默认 3 秒；下载 / 检查识别模型或安装运行环境时一并准备分句资源，失败会明确提示。旧 SaT 设置不再影响会话。
- 桌面与文件识别使用同一准备与租用流程。应用打开后的后台预热仍保留；直接创建文件 Session 时也走此流程。取消或失败进程不复用，旧 Session 不能取消新租约，退出与空闲过期释放进程树。重复取消只触发一次进程清理。
- SaT 不再选择 GPU 包。识别和翻译仍按用户选择使用 CPU / CUDA / Apple GPU；没有删除它们需要的 Torch/CUDA 依赖，也没有改变联网行为。

### 真实推理、处理与启动验证

环境：Windows 11（10.0.26200）/ AMD64 / Ryzen 7 7800X3D / RTX 5070 Ti / Python 3.12.8；最终 CPU ONNX Runtime 1.29.0、Qwen3-ASR-1.7B / CUDA。没有访问、枚举或播放音频设备，没有下载模型。

删除 GPU 包前，以已保存的 GenAI 第五节课文本测试真实 SaT 推理，各长度预热后执行 12 次；CPU 与 CUDA 使用独立模型和进程，以下为中位数：

| 输入字符数 | CPU | CUDA |
|---|---:|---:|
| 200 | 78.13 ms | 1.25 ms |
| 800 | 192.42 ms | 1.76 ms |
| 2041 | 461.89 ms | 2.66 ms |

GPU 明显更快；CPU 对本机短字幕分句足够，但这些数据不能证明低性能 CPU 或长会话不会积压。首次 CPU 加载约 9.12 秒，包含运行库与模型初始化，不能与上表单次推理时间混同。

清理完成后，真实 SaT 与 VAD 会话均确认 `CPUExecutionProvider`；阻止实际导入 `onnx` 图编辑包时仍能运行。保留的是 `onnxruntime` 推理库；无需保留独立的 `onnx` 图编辑包。分句探针边界为 `[29]`，记录见 `cpu-models.json`。

最终文件检查使用 `tests/fixtures/hello.wav`，5.624 秒，经实际 `Session → AudioJournal → wlk_worker` 投递完整 PCM，Qwen GPU 识别、CPU 分句、最终字幕与审计通过。以下各一次，比较同一启动流程在点击前是否已完成准备：

| 准备时机 | 开始到识别就绪 | 开始到首条字幕 |
|---|---:|---:|
| 应用后台已准备 | 5.281 秒 | 6.953 秒 |
| 会话开始时准备 | 13.891 秒 | 15.594 秒 |

两次完整输出一致。此次是单对验证，不替代上一节三轮测速，也不证明课堂正确率；用户立即开始而预热未完成时仍须等待。处理检查覆盖 48 / 44.1 / 16 kHz、不规则块长度、静音、峰值、收尾与重置，输出数量和峰值与此前 +3 dB 结果相同。

### 存储、界面与回归

- 删除 SaT 隔离 GPU 包、DeepFilter 权重、三项增强专用依赖及 `onnx` 图编辑包；删除放弃的增强试验派生音频，保留文字报告与标注。文件产物审计确认减少 **754,316,653 字节（约 719 MiB）**，另有卸载的 Python 包。
- 用户选择保留 AMI、MacWhinney、SlideSpeech 下载音视频、压缩包与对应基准音频；这些资料未删除。个人录音、必要模型及固定测试素材共 85 个受保护文件，前后 SHA256 全部一致。
- Qt offscreen 页面截图确认分句设置已隐藏、现有字幕和模型页面可显示；截图位于本机 `.work/cache/cleanup-20261005/ui/`。没有进行实体窗口缩放验收。
- `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short`：**421 项通过、5 项跳过，44.13 秒**；没有原生音频导入尝试。删除退役功能后测试数量变化，保留会话取消、释放、保存与字幕等回归；补充自动准备分句资源及旧设置兼容检查。
- 同入口运行 `.work/cache/cleanup-20261005/test_final_runtime.py`：**3 项通过，57.91 秒**，包含真实 CPU 模型、处理检查及 GPU 文件识别启动比较。Ruff、`git diff --check`、推理环境 `pip check` 均通过。
- 证据与审计位于 `.work/cache/cleanup-20261005/`，包括 `sat-cpu.json`、`sat-cuda.json`、`cpu-models.json`、`front-end-check.json`、`final-startup.json`、`storage-before.json`、`storage-after.json`、完整测试日志及未通过的初次测试包装器日志。

尚未验证本轮代码在 Mac 的实机表现、长课堂负载、真实采集/回听、Whisper 启动或完整翻译性能。最低可用 CPU 未确定：本机分句测试不能替代完整识别与翻译负载，M1 使用体验也需注明具体后端。Mac 的 SaT 为 CPU；Whisper CPU 与 Qwen MLX Apple GPU 是不同识别路线，已有 M2 / 8GB 文件测试不能当作 M1 CPU 性能结论。

## 2026-10-06 Windows 保存修复、共享适配与 Qwen 实测

在现有 `windows` 分支检查 `59bc32b` 的更新。环境为 Windows 11 / AMD64、Python 3.12.8、PySide6 6.11.2、RTX 5070 Ti（驱动 595.79）；推理环境为 PyTorch 2.11.0+cu128、Transformers 4.57.6、Qwen-ASR 0.0.6、WLK 0.2.26、wtpsplit 2.2.1、CPU ONNX Runtime 1.29.0。没有更新项目依赖、下载模型或访问音频设备。

### 保存与适配边界

GitHub `37356634520` 的 Windows / Python 3.11.9 在后台保存 `QThread` 构造中发生原生访问冲突。仅延后 `finished` 收尾后，本机隔离 Python 3.11.9 的 80 次加强测试仍复现 1 次同位置崩溃，因此未以单次通过认定修复。磁盘写入现使用标准 Python 线程；Qt 排队信号回到界面，任务完成处理先 join，再发布保存结果和启动下一任务。线程启动失败、写入失败和超时保留原文与已有磁盘结果。收尾回调绑定会话身份并退出原信号调用栈，拒绝重复或旧会话消息。

最终保存实现的隔离 Python 3.11.9 测试：80 次独立 UI 收尾测试及 7 种垃圾回收阈值全部通过（8 个 pytest 项，150.07 秒）；最终 UI / 保存测试另有 14 项通过，13.55 秒。隔离解释器使用官方便携包与已有 ABI3 Qt，NumPy / SciPy 使用对应 3.11 二进制；这不替代 GitHub 各版本矩阵。源码回归还覆盖 100 次快速保存后无存活写线程、创建写线程失败后保留旧结果并可重试、版本合并、错误与录音锁释放。

适配审查结果：

- ASR 的低能量切窗原先位于 `mlx_asr.py`；更新已移到 `asr_stability.py`，PyTorch 与 MLX 共用确认、重叠窗口、原文修订和 SaT / 翻译流程，未保留两套平台字幕业务。
- 模型准备与运行库预热重复写的控制台 / 进程组参数改为复用 `process_platform.spawn_options()`。MLX 的独立解释器与 Metal 推理保留在专属适配中；它与受保护进程组的关系不同，不统一成另一套进程启动框架。
- Mac 预热入口不再读取已退休的 `semantic_device`，旧值为 CUDA 也不能改变固定 CPU 分句；准备失败提示指向现有的识别模型入口。
- 实测还暴露出已有 PyTorch HY 的自由 JSON 合并入口不可靠：101 秒双语测试的 20 条原文全部报 ID 映射错误。短句探针返回了带 `id/source` 的 JSON 数组，而消费者需要 ID → 译文对象。已删除这个入口，通过现有队列逐段翻译；llama.cpp 保留有 schema 约束的合并。引擎差异不按操作系统复制实现，不添加自动重试或用户开关。

### 同一文件、同一处理的识别比较

基线 `f28a2cb` 与更新 `59bc32b` 均用真实 `Session → AudioJournal → wlk_worker`，48 kHz 输入按 1 倍速度投递；Qwen 1.7B / CUDA、英文、+3 dB 与 -1 dB 峰值保护、CPU SaT、关闭翻译，模型不接触对照文本。每条路线先完成同一预热，再顺序运行 101.176 秒标准英文和 GenAI 第五课 48:01–50:56 的 175 秒片段。原音频哈希、输入采样数和模型 / 字幕修订审计均一致或完整。

| 素材 / 路径 | 开始到就绪 | 开始到首条字幕 | 就绪后首条字幕 | 停止后收尾 | 进程树峰值 RSS | PyTorch 显存峰值 |
|---|---:|---:|---:|---:|---:|---:|
| 标准英文 / 原 windowed | 9.015 s | 11.640 s | 2.625 s | 3.121 s | 5.515 GiB | 4.09 GiB |
| 标准英文 / 共享完整编码器 | 6.000 s | 7.343 s | 1.343 s | 5.996 s | 5.501 GiB | 4.38 GiB |
| 课堂片段 / 原 windowed | 3.359 s | 4.828 s | 1.469 s | 2.000 s | 6.840 GiB | 4.10 GiB |
| 课堂片段 / 共享完整编码器 | 3.391 s | 4.313 s | 0.922 s | 4.125 s | 6.955 GiB | 4.53 GiB |

标准素材为 256 个对照词：原路径多出 2 个词，WER 0.78%；共享路径 WER 0。课堂片段原 / 新路径分别为 11 / 14 条定稿、393 / 389 词，最长行 132 / 109 词；没有独立校对稿，不把词数变化或旧识别稿差异当作 WER。两条新路径最终 ASR 与分句确认字段均为真，字幕与模型原文审计匹配，没有丢失音频输入。长行仍存在，不能宣称课堂断句已完全解决。

每条路径只有一组文件测试，运行顺序为基线后更新，期间有独立 Qt 模拟回归；框架、系统文件缓存和 CPU 负载可能影响绝对耗时，不能推断统计显著加速或所有硬件表现。结果支持这台 GPU 上保留统一窗口与既有预热；代价是课堂显存增加约 0.43 GiB、收尾增加约 2.13 秒。真实采集、回听、长课堂与其他 CPU / GPU 未验收。

### 连续双语、等待门与保存导出

删除 PyTorch 自由 JSON 批量后，101 秒英文文件能完成 20 条译文，但首条译文仍在开始后 112.469 秒才出现，晚于文件输入结束。日志确认 HY 已提前加载；持续输出、原文修订与心跳在等待字幕锁时也增加“正在更新”计数，连续任务使翻译门长期关闭。现在只在持有字幕锁并实际更新时关闭门；正在运行的推理仍保留版本校验，不通过忽略原文变化修复等待。

最终同一文件、Qwen 1.7B / CUDA、HY 1.8B / CUDA、SaT / CPU 实测：就绪 5.453 秒，首条原文 7.625 秒，首条译文 24.703 秒，录音进行中持续发布译文；停止后收尾 8.246 秒，PyTorch 显存分配峰值 7.55 GiB（不含驱动）。HY 权重就绪诊断在开始后 7.312 秒，加载本身 1.797 秒；诊断包装器只记录阶段，不参与推理。首译还受原文和分句确认策略影响，不能称为立即翻译。20 条均完成最终翻译，原文 WER 0、修订审计匹配、译文来源与当前原文一致；真实 `Library.save/load` 往返与 20 条双语 SRT 导出通过。

新增模拟回归制造字幕锁的活动任务与等待任务，要求活动任务计数为 1 且停止前收到译文；替换回原 `_serve` 时回归拒绝旧计数。没有新增用户开关、自动重试或平台独立翻译队列。本测试只证明此文件和这台机器的双语链路，不证明课堂译文质量或其他硬件性能。

### 回归与证据

- `.venv\Scripts\python.exe scripts/test_no_audio.py -q`：474 项通过、5 项跳过，44.99 秒；没有原生音频导入尝试。
- `.venv\Scripts\python.exe -m ruff check linguaflow scripts tests`、`git diff --check` 通过。500 段历史回归继续验证背景上限；PyTorch 相邻请求现在各自只传本段原文和所选邻段，llama.cpp 的 schema / 批量解析校验保持。
- 本机证据在 `.work/cache/github-fixes-20261006/`：`comparison.json`、环境与音频 manifest、逐次事件及修订审计、真实 HY 格式探针、保存加强测试与模拟测试日志。个人课堂音频及完整识别结果不提交 Git。
