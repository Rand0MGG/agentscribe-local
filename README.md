# LinguaFlow · 本地同声字幕

Windows / macOS 桌面应用：麦克风或系统音频 → 本地语音识别 → 连续双语字幕。
0.2 版采用连续音频缓冲和可修订原文。Whisper 是近实时适配；Qwen3-ASR 提供可选本地流式服务连接。尚未提供云端 API、安装包或语音合成。

![界面预览（示例字幕）](docs/preview.png)

## 已实现

- 音频设备选择：Windows WASAPI 回环和麦克风；macOS CoreAudio 输入。
- faster-whisper 模型选择：tiny / base / small / medium / large-v3 / turbo，或兼容 CTranslate2 模型目录。
- NLLB 翻译模型选择：600M / 1.3B，或完整 NLLB 本地模型目录。
- 自动识别源语言，界面提供中、英、日、韩、法、德、西、俄、阿、葡、意及繁体中文。
- 原文以草稿显示并随后文修订；停顿后定稿再翻译。可调整刷新间隔和定稿停顿。
- 独立模型管理：识别 / 翻译 / 聆听行为；下载、检查文件、导入目录和流式服务检查。
- 独立置顶字幕窗口、双语 SRT 导出、模型/语言偏好保存、严格离线模式。
- 录音、识别、翻译分线程运行；积压音频写入临时缓冲，显示延迟，不因队列满而丢弃。
- 融合 MIT 许可的 Whisper-Streaming `HypothesisBuffer`，保留来源与许可证。

![模型管理](docs/models-preview.png)

流式能力与来源说明见 [原文修订设计](docs/STREAMING_DESIGN.md)。Qwen 接入步骤见 [本地 Qwen 服务](docs/QWEN_STREAMING.md)。

## 安装与启动

推荐 Python **3.11 或 3.12（64 位）**，至少 16GB 系统内存，预留约 8GB 磁盘空间。
第一次加载模型需要访问 Hugging Face；后续可勾选严格离线。

### Windows PowerShell

在项目目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m linguaflow
```

安装后也可双击 `run-windows.cmd`。无 NVIDIA 环境时选择 CPU。
使用 NVIDIA 模式时先双击 `install-gpu-windows.cmd`，或执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gpu]"
```

运行库仅安装到虚拟环境，应用会自动设置进程内 DLL 搜索目录，无需修改系统 PATH 或管理员运行。
安装普通 PyTorch 并不等于已经为 faster-whisper 配置好 CUDA。
版本要求请参考 [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper#gpu)。
启动会先检查 DLL 并执行真实推理预热，成功后才录音。失败原因会保留在界面和诊断记录中。
用户可切换 CPU 重试，不静默更改计算设备，也无需重新下载 Whisper 权重。

### macOS Terminal

当前安装方案面向 **Apple Silicon（M 系列）macOS**。Intel Mac 的新版 PyTorch 预编译包支持受限，
本版尚未提供经过验证的 Intel Mac 依赖组合。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m linguaflow
```

需要在“系统设置 → 隐私与安全性 → 麦克风”允许启动应用的 Terminal / Python 访问录音。
首版 macOS 使用 CPU INT8 识别，**未实现 Metal / MLX 加速**。建议从 base / small 开始。
也可运行 `bash run-macos.command`。

macOS 系统声音需要自行安装 [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)：

1. 安装后打开“音频 MIDI 设置”，新建多输出设备，勾选扬声器/耳机与 BlackHole 2ch。
2. 按 BlackHole 指南设置主设备和漂移校正，将该多输出设备设为系统声音输出。
3. 本软件刷新设备，选择 BlackHole 输入；播放声音后查看底部音量条。

驱动未随本项目捆绑。首版未实现原生 ScreenCaptureKit 系统音频捕获。

## 8GB 显存配置

| 环境 | 识别 | 翻译 | 说明 |
| --- | --- | --- | --- |
| 通用默认 | small / CPU INT8 | NLLB 600M / CPU FP32 | 不占用推理显存，速度取决于 CPU |
| NVIDIA 8GB | small 或 medium / INT8-FP16 | NLLB 600M / CPU FP32 | 将显存留给识别，建议先用 small 验证 |
| 低延迟优先 | base / CPU 或 NVIDIA | NLLB 600M / CPU | 识别准确度可能降低 |
| 更高精度试用 | large-v3 或 turbo / NVIDIA | NLLB 600M / CPU | 必须自行实测显存和延迟，不保证 8GB 任意环境可用 |

翻译固定在 CPU，Whisper 实时路径使用 beam=5、词级时间戳和重叠回听，不使用批量推理。8GB 是配置目标，
**软件没有硬性显存配额**；桌面和其他程序也会占用显存。发生显存不足时停止会话并选择更小模型。
600M 翻译权重约 2.5GB，加载和推理还需要额外系统内存。

## 使用方式

1. 打开“模型管理”，选择识别引擎，下载或导入模型。Qwen 须先配置独立本机服务。
2. 选择麦克风，或 Windows 中标有“系统声音”的当前播放设备。
3. 选择源语言和目标语言；已知源语言时固定选择通常比每段自动检测稳定。
4. 点击“开始聆听”。识别模型加载、基础运行库初始化和预热后开始录音。
   翻译模型权重加载期间原文继续显示，翻译就绪后补全等待队列中的译文。
5. 默认每新增 1 秒音频刷新一次原文，推理耗时另计。默认停顿 1 秒后定稿；连续长句按稳定前缀设定稿点，并保留尾部待修订。
6. 停止时处理剩余队列，结束后可导出 SRT；新会话开始前会提醒保存已有字幕。

Whisper 在滚动音频窗口上重复解码，当前字幕整行可修改；不是原生固定开销流式模型。VAD 只判断停顿，不裁掉送入识别的轻声音频。翻译与 SRT 只消费定稿原文。已定稿历史目前不会再次修订。

识别较慢时待处理音频和延迟会增长；不会通过丢片段制造“跟得上”的假象。连续 60 秒仍无法建立定稿边界会报错停止；异常停止或关闭窗口会取消剩余音频并删除临时缓冲。此版仍需要后续实际使用检验，不承诺已达到商业产品效果。

## 离线模型与隐私

- 取消严格离线：模型名称通过 Hugging Face 下载；不上传录音或字幕，不调用翻译 API。
- 勾选严格离线：两个模型都使用 `local_files_only=True`，缺失文件时报错。
- 识别目录须包含 faster-whisper/CTranslate2 格式文件，不能直接填写原始 Whisper `.pt` 或 GGUF。
- 翻译目录须包含 NLLB 权重、config 和 tokenizer 等文件，不能填写任意聊天模型或 GGUF。
- 默认缓存使用 Hugging Face 的系统默认缓存位置；可在启动前设置 `HF_HOME` 更改位置。
- 优先复用完整翻译缓存；缺失时只下载一种权重格式，随后从本地目录加载，避免后台转换重复下载。
- 诊断记录显示各阶段及耗时。`hf_xet` 已列入依赖；Windows 符号链接警告不影响推理，无需为此管理员运行。
- 录音写入本机临时 PCM 文件（约 230MB/小时），会话结束关闭并删除；长时间积压需要可用磁盘空间。字幕在会话内存中保留，只有手动导出才写入文件。
- Qwen 模式音频仅发到环回地址，客户端绕过代理；服务在同一机器 Linux/WSL 内运行。严格离线选项只控制桌面模型加载，Qwen 服务的首次下载由服务自身管理。
- 偏好使用 Qt QSettings，Windows 注册表 / macOS 系统偏好中只保存模型和语言设置。
- 关闭时等待当前推理/下载阶段返回再释放模型；下载阻塞时关闭可能较慢。

NLLB 模型遵循 [CC-BY-NC-4.0 模型许可](https://huggingface.co/facebook/nllb-200-distilled-600M)，
不是默认可商用模型。商业发行前需要换用许可适合的翻译模型及适配器。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check linguaflow tests scripts
.\.venv\Scripts\python.exe scripts/preview.py
```

macOS 将 Python 路径换成 `.venv/bin/python`。
预览脚本使用示例字幕，不录音、不加载模型，生成 `docs/preview.png`。
自动化覆盖原文修订与撤回、长句定稿保留尾部、积压音频完整性、草稿不进入翻译、SRT 时间、失败与停止行为，以及 Qwen 协议替身。历史 Segmenter 测试仅涉及不再用于实时路径的旧工具。
真实设备、模型推理和 macOS 驱动需在目标机器验证；自动化替身通过不代表硬件链路已通过。

安装完成后可按需运行真实模型检查（会下载模型，默认翻译权重约 2.5GB）：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_models.py
.\.venv\Scripts\python.exe scripts/smoke_models.py --audio "英语测试录音.wav" --asr-model tiny
.\.venv\Scripts\python.exe scripts/smoke_models.py --offline --audio tests/fixtures/hello.wav --asr-model large-v3 --asr-device cuda --translation-model facebook/nllb-200-distilled-1.3B
```

模型已缓存时加 `--offline`。脚本输出识别、翻译和耗时；它是手动验证工具，不属于无下载测试。

Windows 可运行 `scripts/smoke_loopback.py tests/fixtures/hello.wav`，播放本地合成测试语音，
经默认播放设备的真实回环生成字幕，输出到 `docs/loopback-result.json` 与 `.srt`。
运行前暂停其他应用播放。该脚本使用已缓存的 large-v3 / GPU 与 NLLB 1.3B / CPU。
本次对照和修复过程见 [开源项目对照](docs/OPEN_SOURCE_REVIEW.md)。

### 结构

```text
linguaflow/
  app.py          Qt 桌面界面、置顶窗口、导出
  audio.py        设备发现、48kHz 采集、16kHz 重采样
  core.py         分段、数据结构、队列和 SRT
  backends.py     Whisper / NLLB 模型适配
  engine.py       会话、后台阶段、停止与错误处理
tests/            无模型下载的自动化测试
scripts/preview.py  可重复的界面预览
```

后续接 API 可新增识别/翻译适配器，通过 Session 的工厂参数接入；尚未提供 API 配置界面。
后续正式发布需增加模型下载进度与取消、原生 macOS 系统音频、Apple Silicon 加速、
模型许可合适的商用翻译后端，以及分别在 Windows / macOS 构建并签名安装包。
