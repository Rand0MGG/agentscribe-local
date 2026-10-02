# AgentScribe · Agent 协作开发的本地语音工作台

Windows / macOS 桌面应用：麦克风或系统声音 → 本地原文字幕 → 本地翻译。
v0.5.0 源码预览版，原名 LinguaFlow。使用完整 WhisperLiveKit 音频处理链路，提供 Whisper / AlignAtt 和 Qwen3-ASR 两个本地后端。
Qt 界面与模型运行环境隔离；应用自行启动、停止推理进程，不需要 WSL、端口或手动服务。

本版加入 HY-MT2 前后文翻译、本地文件夹录音工作区，并修复重译失败丢失已有译文、错误标记完成及损坏元数据无法正常处理的问题。详见 [版本说明](docs/RELEASE_v0.5.0.md) 和 [上下文翻译](docs/CONTEXT_TRANSLATION.md)。当前提供源码及安装脚本，尚无独立 EXE/DMG 安装包。内部 `linguaflow` 模块名、旧启动命令和本地设置位置保留兼容。

当前版本已完成 WhisperLiveKit / Qwen3-ASR 本地流式链路和桌面回归验收；已通过项目及适用范围见 [验证记录](docs/VALIDATION.md)。

![界面示例](docs/preview.png)

## 安装

需要 Python 3.11–3.13（建议 3.12）、Git、至少 16GB 系统内存。GPU 环境及大模型会占用十余 GB 磁盘，请留足空间。
首次安装与下载需要网络；模型准备后支持严格离线。录音与字幕不上传到云端。

### Windows

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe scripts\install_runtime.py
.venv\Scripts\python.exe scripts\install_semantic.py
.venv\Scripts\python.exe -m linguaflow
```

之后双击 `run-windows.cmd` 启动。`install-gpu-windows.cmd` 安装同一套推理环境。
没有 NVIDIA 显卡时用 `scripts\install_runtime.py --cpu`，并在模型管理中将识别与翻译都设为 CPU。
安装器仅修改项目虚拟环境，Git 长路径选项只对安装子进程生效，不更改系统配置。

### macOS（Apple Silicon）

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_semantic.py
.venv/bin/python -m linguaflow
```

也可使用 `bash run-macos.command`。Whisper CPU 已通过文件识别测试；新增 Qwen3-ASR 1.7B / MLX 4-bit **试验入口**，已在 M2 / 8GB 上完成英文短音频和 101 秒连续音频的 GPU 字幕测试。中文、长会话和真实录音仍待验收。

试用 Apple GPU 路线，另行执行 `.venv/bin/python scripts/install_mlx.py`（或模型管理 → 运行环境 → 安装 Apple GPU）。然后选择“试用 Mac 4-bit 设置”，下载 / 检查 Qwen 模型，并指定原文语言。此配置使用 SaT 分句并关闭翻译；请先准备 SaT 模型，可按需要再开启翻译。MLX 单独使用 `.venv-mlx`，避免与现有 Windows / WLK 的 Transformers 版本冲突。

MLX 的近期完整原文现接入与 Qwen 流式路线相同的提交与修订策略：短停顿保留音频上下文，默认使用 30 秒识别窗口；原文定稿由真正的话语结束或收尾驱动。已有窗口内的词可随后文修正，首次提交等待独立控制；翻译采用小上下文初译和大上下文定稿。详见 [语义分段](docs/SEMANTIC_SEGMENTATION.md)。

M2 / 8GB 的 101 秒文件测试已跑通 GPU 识别与 SaT 分句：首条字幕约 2.26 秒、收尾约 3.04 秒，25 段字幕全部定稿，WER 0.39%。测试关闭翻译，没有访问音频设备；系统交换空间增长约 1.46 GiB，仍需验证长会话。详见 [测试记录](docs/MACOS_FILE_TESTS.md)。
Apple Silicon 的翻译可选择“设置 → 翻译模型 → 使用 HY 1.8B · Apple GPU”，推理引擎显示“llama.cpp · GGUF”，计算设备显示“Apple GPU · Metal”。首次点击“下载 / 检查翻译模型”，或运行 `.venv/bin/python scripts/install_llama.py --device metal`，准备官方量化权重和本地运行组件。开启翻译后，下次聆听自动加载；诊断会显示实际 GPU 加载层数。已打开的应用需在录音结束后重新启动，才能载入更新的代码。长会话和内存压力下的稳定性仍待验收，详见 [HY Metal 测试](docs/testing/HY_METAL.md)。
系统设置中需允许 Terminal/Python 使用麦克风。系统声音使用 [BlackHole](https://github.com/ExistentialAudio/BlackHole) 输入与多输出设备；尚无原生 ScreenCaptureKit 捕获。

Mac 适配进展、已验证范围和待实机测试项目见 [macOS 适配记录](docs/MACOS_SUPPORT.md)。如果电脑正在进行其他录音，开发验证请使用 `.venv/bin/python scripts/test_no_audio.py`；该入口使用模拟音频，并阻止原生音频后端导入，不启动实际应用或录音测试。

## 使用

当前工作区新增真实文件夹、录音命名、删除恢复、自动保存与回听；默认存放在安装目录下的“录音”，可在设置中更改。详见 [工作区说明](docs/WORKSPACE.md)。

首页底部的语言与识别引擎按钮可直接打开对应设置。侧栏“使用指南”介绍首次准备、字幕修订和录音整理；设置支持搜索 SaT、GPU、HY-MT2 等关键词。`Ctrl+,` 打开设置，`Ctrl+F` 聚焦设置搜索，`Ctrl+N` 新建录音，`Esc` 从设置返回录音。在“常规 → 减少动态效果”中可关闭切页、弹窗和开关动画。界面变更与验证范围见 [界面体验说明](docs/UI_EXPERIENCE.md)。

1. 打开左下角“设置 → 识别模型”，选择 Whisper 或 Qwen、计算设备，下载模型。识别、翻译、聆听行为分别管理。
2. 在首页底部直接选择音频来源，在语言快捷入口选择原文与目标语言；在左侧文件夹行点击“＋”，填写录音名称并确认保存位置。Windows 的“系统声音”选择当前播放设备；Qwen 必须指定原文语言。字幕位于底部时自动平滑跟随；向上滚动暂停，点击圆形向下箭头或自行回到底部即可恢复。
3. 在“模型管理 → 字幕与延迟”准备 SaT 分句模型、选择 CPU/CUDA 并调整稳定尾部首次提交等待。然后点击“开始聆听”。首次提交与已提交原文的变化立即进入小上下文初译队列；识别段结束后原文独立定稿，再生成大上下文最终译文。SaT 加载失败会阻止启动，推理异常会停止会话并提示原因，详见 [语义分段](docs/SEMANTIC_SEGMENTATION.md)。
4. 聆听时点击“暂停”会释放当前采集句柄，继续处理已有音频和翻译；点击“继续录音”接着写入同一份录音，暂停期间的声音和等待时间不计入录音及字幕时间轴。暂停时也可直接停止。“停止”会处理剩余音频和翻译，然后释放推理进程；关闭窗口也会先停止采集并处理剩余任务，随后保存会话。加载期间仍可取消启动。暂停功能已用模拟采集及文件回放验证，真实设备验收范围见 [暂停测试记录](docs/testing/RECORDING_PAUSE.md)。
5. 录音和定稿自动保存在本机，点击侧栏会话可回听。可打开置顶字幕窗口，结束后导出双语 SRT。导出包含已确认字幕。

![模型管理](docs/models-preview.png)

麦克风环境可先打开左下角“设置 → 音频实验室 · 增强与回听”，确认录音来源与输入电平，再用同一段样本比较预设和自定义处理。提供 WebRTC APM、WPE、DF3、响度/EQ/峰值保护；DF3 可选 CPU/CUDA。详见 [音频处理与故障恢复](docs/AUDIO_PROCESSING.md)。

## 翻译引擎

设置 → 翻译模型可独立选择 **PyTorch** 或 **llama.cpp · GGUF**，再选择 CPU / GPU。

- PyTorch 保留现有 HY-MT2、NLLB 及兼容目录；原有设置默认继续使用它。
- llama.cpp 提供已验证的 HY 1.8B Q4_K_M，也可选择本地 `.gguf` 指令模型。FP16、FP32 或量化精度由文件决定，选择 llama.cpp 不会自动量化。
- 两种引擎分别记住模型选择；原有 Metal 翻译偏好会迁移到 llama.cpp。
- Mac 提供 CPU / Metal；Windows x64 提供 CPU / CUDA / Vulkan 的准备与启动路径，**Windows 尚待实机验收**。
- 新模型必须受固定版本的 llama.cpp 支持，并能使用聊天模板执行翻译指令。GGUF 文件校验通过不代表翻译质量已经验收。

详细准备方法、限制与验证范围见 [llama.cpp 翻译](docs/LLAMA_CPP.md)。

## 模型与显存

- Whisper 使用 WhisperLiveKit 的 AlignAtt 解码器：支持 tiny/base/small/medium/large-v3/turbo、原始 `.pt` 文件或兼容 Hugging Face 目录。**旧 faster-whisper/CTranslate2 目录不能直接用于此解码器。** 在模型管理中重新准备对应格式。
- Qwen 使用 `Qwen/Qwen3-ASR-0.6B` 或 `1.7B` 的窗口式流式适配，限制重编码窗口，运行于本地 PyTorch。没有启用社区英语专用 causal 权重。Qwen 词时间戳是估计值，不适合精密对齐。
- NLLB 支持 600M/1.3B 及兼容目录，可独立选择 CPU 或 CUDA FP16；翻译失败保留原文。
- HY-MT2-1.8B 初次提交和提交后的原文修订默认参考前 1 段已定稿原文；原文定稿时默认参考前 10 段、后 1 段已定稿原文，不等待新后文。已排队的相邻同阶段内容可合并翻译、共享上下文，排队中的旧版本由最新版本替换。支持 CPU/CUDA 和完整本地模型目录；Apple Silicon 可选择官方 1.8B Q4_K_M / Metal。最终翻译失败保留初译并提示未完成。
- Whisper 识别与 NLLB 翻译可以独立选择 CPU 或 CUDA；共用 GPU 时请留出两套模型的显存。Qwen 的设备设置由其独立后端处理。
- 8GB 显存优先尝试 Whisper small 或 Qwen 0.6B，加 NLLB 600M。16GB 可使用 large-v3，但总占用受窗口、运行库及其他程序影响，软件没有强制显存配额。
- 模型管理中的更新间隔是调度参数，不表示模型只计算该时长；上游流式后端负责窗口推进。停顿阈值控制话语边界，不是唯一提交依据。

原始 Whisper 下载到 `~/.cache/whisper`；Qwen/NLLB 使用 Hugging Face 缓存，可通过 `HF_HOME` 设置后者位置。翻译下载只选择一种权重格式。
NLLB 权重遵循 [CC-BY-NC-4.0](https://huggingface.co/facebook/nllb-200-distilled-600M)，不默认适用于商业发行。

## 架构和验证

- `.venv`：桌面界面、音频采集、模型下载管理。
- `.venv-wlk`：固定版本 WhisperLiveKit、Qwen 适配、CUDA PyTorch 和翻译。
- `wlk_session.py`：Qt 会话、连续音频临时缓冲、子进程通信。
- `wlk_worker.py`：上游 AudioProcessor/VAC/ASR、字幕映射、异步翻译。
- `wlk_captions.py`：已提交原文与可修订尾部映射，避免提前锁定增长中的上游行。

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/smoke_wlk.py --backend qwen3-streaming --translate --repeat 12
.venv\Scripts\python.exe scripts/smoke_session.py --backend qwen3-streaming
.venv\Scripts\python.exe scripts/smoke_session.py --backend wlk-whisper --model large-v3
```

实际运行证据及适用范围见 [VALIDATION](docs/VALIDATION.md)。设计见 [STREAMING_DESIGN](docs/STREAMING_DESIGN.md)，依赖来源见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。

音频临时缓冲约 690MB/小时（48 kHz float32），会话结束删除。没有云端 API、语音合成或独立安装包；不声称达到商业软件所有场景的准确率。

项目目录说明见 [PROJECT_STRUCTURE](docs/PROJECT_STRUCTURE.md)。

参与开发前阅读 [开发规范](AGENTS.md) 和 [模块职责与依赖约束](docs/ARCHITECTURE.md)。开发规范集中维护于 `AGENTS.md`，功能行为及验证证据保留在各自文档中。

固定开发分支的提交和 Pull Request 配置了 [自动代码检查](.github/workflows/checks.yml)：Ruff 与 Windows/macOS、Python 3.11–3.13 的无音频单元测试。自动检查不下载模型、不访问音频设备，也不替代 GPU 推理及真实录音验收。
