# macOS 适配记录

## 范围

当前在 `codex/macos-support` 分支开发，基于 `1ccf4a6`（v0.5.0）。本次尚未发布新版本，也不代表完整 Mac 录音和推理链路已验收。

用户随后明确了交付要求：至少语音识别模型必须使用 Apple GPU。已有 CPU 文件识别结果仅作对照；后续已完成 MLX 的英文文件 GPU 识别与字幕测试，中文及真实录音仍待验证。针对 M2 / 8GB，优先评估 Qwen3-ASR 1.7B 的 MLX 量化后端，量化后的准确率和流式行为也必须验证，不能直接替换当前 PyTorch 权重后宣称支持。

用户正在使用这台 Mac 录音，本轮跳过真实音频设备枚举、录制、播放、权限弹窗和系统音频设置变更。用户随后授权使用现成音频做真实推理；[文件推理测试记录](MACOS_FILE_TESTS.md) 包含已完成的 CPU 识别与因资源保护停止的 MPS 尝试。音频硬件检查仍需等待用户明确允许。

## 本轮修改

- **采集缓冲**：Windows 保留 48,000 帧缓冲；Mac 不再强制指定该值，使用 CoreAudio 设备默认缓冲。应用仍每次处理 4,800 帧、48 kHz 音频。SoundCard 会检查硬件缓冲范围，固定的大缓冲可能导致启动失败；依据为 [SoundCard CoreAudio 实现](https://github.com/bastibe/SoundCard/blob/master/soundcard/coreaudio.py)，并核对了本地安装的 0.4.6 源码。
- **取消采集**：已取消的采集在导入音频后端前退出，设备解析后再次检查取消状态。
- **系统声音**：Mac 对 Windows 回环配置提前给出 BlackHole 输入提示；不会把不支持的回环请求传入 CoreAudio。BlackHole 仍作为普通输入使用，本次未安装驱动或调整设备。
- **增强设备**：Mac 音频实验室仅提供 CPU。载入 Windows 的 CUDA 增强配置时转为 CPU，保留增强开关、混合比例等参数；Windows 保留 CUDA 选项与配置。
- **播放初始化**：音频实验室在用户点击回听时才创建 Qt 播放器和输出设备，查看设置或修改参数无需初始化播放后端。
- **安装检查**：Mac 请求 CUDA 增强时，在安装依赖前退出；推理安装器在创建环境前拒绝 Intel / Rosetta Python，提示使用原生 Apple Silicon Python。Mac 的 PyTorch 使用普通 wheel，Windows 仍按 CPU / CUDA 选择指定构建。
- **安装进程**：增强安装器若已经是会话首进程，不再重复调用 `setsid()`。

## 不访问真实音频的测试

```bash
.venv/bin/python scripts/test_no_audio.py -q
```

此入口为当前进程树中的 Python 测试注入 `sitecustomize`，拦截 SoundCard、sounddevice、PyAudio 与 QtMultimedia 的真实导入；模拟模块可正常使用。若发生被拦截的尝试，即使测试捕获异常，入口仍以失败退出。子进程需要继承环境，不使用 `-I` / `-S` 等绕过启动配置的选项。

这是一项针对项目现有音频调用路径的测试保护，不是系统音频沙箱。外部录音程序或直接调用原生 API 仍需人工排除；不要在用户录音期间运行 `smoke_loopback.py`、真实 `smoke_session.py` 或普通应用入口。

## 验证记录（2026-09-28）

- 环境：macOS 26.6.2、arm64、Python 3.12.14、PySide6 6.11.2、SoundCard 0.4.6；桌面依赖安装于项目 `.venv`。
- 自动测试：173 项通过（含后续 MLX 正常关闭和超时退出回归）；原生音频后端导入尝试为零。包括模拟 Windows / Mac 的缓冲参数、回环策略、旧配置恢复、安装命令，以及 Qt 会话子进程的停止与清理。
- 界面测试使用 Qt offscreen，验证配置控件和生命周期；回听逻辑使用模拟播放器，另有 9 项平台回归复测通过，不代表 CoreAudio 播放已实测。已检查模型设置和音频增强页面截图，位于本机 `.work/browser/mac-model-settings.png`、`.work/browser/mac-audio-settings.png`。
- 本次修改的 Python 文件 Ruff 检查通过；桌面环境 `pip check` 通过。
- 全仓库 Ruff 有 46 项历史问题（导入顺序、未使用导入、单行语句等）；已逐文件与 `HEAD` 对照，错误类型、说明和行号一致。本次未扩大范围清理这些问题，不声称全仓静态检查通过。
- 第一轮自动测试时未安装推理环境；后续已安装 `.venv-wlk` 并通过 `pip check`，完成 Whisper tiny 的真实文件识别，详见后续记录。仍无 Windows 实机验证。

## 后续实机验收

待用户允许使用音频设备后：

1. 安装并验证推理环境，检查固定上游依赖在 Apple Silicon 上的可安装性。
2. 验证麦克风权限、内置/外接麦克风、48 kHz 与非 48 kHz 设备、断开及重新连接。
3. 验证开始、取消、停止、退出与录音保存，检查 CPU Whisper / Qwen 及翻译的端到端行为。
4. 验证录音回听、音频增强和已由用户配置的 BlackHole 输入。
5. 在 Windows 上回归 WASAPI、CUDA、旧配置和录音工作区，再决定合并和测试版发布。

Apple GPU（MPS/MLX）、Intel Mac、原生系统音频捕获和独立安装包尚不在本次已验证范围内。

## MLX 4-bit 接入（2026-09-28 后续）

- 增加 Apple GPU / MLX 试验引擎、独立安装入口和一键 4-bit 配置。旧 CPU / Windows CUDA 路线保留；加载其他平台的配置不会向 Mac 提供 CUDA。
- `.venv-mlx` 安装 MLX-Audio 0.5.6、MLX 0.32.2；实际解析到 Transformers 5.17.0。`pip check` 通过，依赖完整快照在 `.work/mac-file-tests/mlx-runtime-freeze.txt`。
- 模型下载固定 `mlx-community/Qwen3-ASR-1.7B-4bit` 的 `78a389c776a5483b2d0d4ea5494e11012e0d6159`，复用项目本地缓存，启动不下载。
- 模型和 Metal 分配在独立子进程；父进程取消或退出时释放。音频通过本地 PCM 传入，共用 WLK 音频处理、字幕修订、翻译和录音库。
- 12 秒目标窗口、最多 17 秒单次输入、128 MiB MLX 缓存上限、3 GiB MLX 分配上限。内存上限只约束 MLX 分配，不是全系统内存保障；目前仍需要外围测试监测。
- 真实 4-bit 文件测试在 GPU 加载后触发资源保护，未获得识别结果。模拟模型的完整文件传输、字幕定稿和模型关闭成功；这只证明装配，不证明识别准确率和速度。
- 界面 offscreen 截图：`.work/browser/mac-mlx-settings.png`。当前明确标为试验功能，不默认覆盖用户已有设置。

## “Mac 体验优于 Windows”的验收目标

这是后续目标，当前尚未达到。需要分别记录：

1. **识别**：Apple GPU 实际返回中英文文本；同一份参考音频比较量化与原模型的 WER/CER、重复和遗漏。
2. **延迟**：记录首条草稿、持续字幕延迟、停止收尾时间；长音频不持续积压。没有相同输入和配置的 Windows 基线前，不声称更快。
3. **资源**：在 M2 / 8GB 上至少完成长会话，记录 MLX 分配、进程内存、系统压力和交换增长；单独识别与同时翻译分别测。
4. **桌面**：设备恢复、权限、取消、保存、回听、快捷键和外接设备切换完成真实 Mac 验证，Windows 原有流程回归。

后续用户明确授权取消内存中止阈值，已完成 GPU 英文文件识别与资源分析；随后已完成 HY Metal 与 MLX 的 101 秒英文并行文件验证并接入桌面设置（见 [HY Metal 测试](testing/HY_METAL.md)）；下一步需验证中文和更长会话，真实音频设备测试仍需用户允许。

### 后续 GPU 实测已完成

此前“仅加载通过”的状态已被后续测试更新：取消外围内存中止后，短文件和 101 秒英文文件均通过实际软件 GPU 字幕流程；长文件 WER 0.39%，首字幕 2.02 秒，收尾 1.62 秒，MLX 分配峰值 2.42 GiB。详见 [完整结果](MACOS_FILE_TESTS.md#取消内存中止阈值后的实际结果)。这满足英文文件 GPU 识别的阶段目标，不等于全部 Mac 功能或超越 Windows 的目标完成。
