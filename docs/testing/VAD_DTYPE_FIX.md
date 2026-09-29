# Windows VAD 半精度启动崩溃修复（2026-09-29）

## 原因与处理

HY-MT2 在后台线程通过 Transformers 4.57.6 加载半精度权重时，会暂时改变 PyTorch 的进程级默认 dtype。WLK 的 `FixedVADIterator` 使用 `torch.Tensor(numpy_frame)` 创建输入，因而可能得到 BFloat16；Silero ONNX 包装器调用 `.numpy()` 时抛出 `Got unsupported ScalarType BFloat16`。单独加载识别模型、关闭翻译的测试不能覆盖这一启动竞争。

`runtime_compat.configure_vad_float32` 在 WLK 开始处理音频前安装实例级适配，逐帧用 `torch.from_numpy` 保留 Float32。上游检测阈值、停顿、上下文、事件顺序和重置逻辑继续复用。Float32 输入与初始化时可能为半精度的零上下文拼接后仍为 Float32；循环状态由上游显式 `.float()` 保证。适配不修改全局 dtype，不修改已安装依赖，也不改变 Qwen、HY-MT2 的半精度配置。SaT 保持必需依赖。

## 验证

环境：Windows 11 / AMD64、Python 3.12.8、RTX 5070 Ti、PyTorch 2.11.0+cu128、Transformers 4.57.6。

- 原版 WLK 在默认 dtype 为 BFloat16 时，首个 512 点 Float32 NumPy 音频块稳定复现相同异常。
- `tests/test_vad_runtime.py` 使用真实本地 Silero ONNX 模型。另一线程分别保持 BFloat16、Float16、Float32，验证不等长输入分包、多帧事件、检测器重置、阈值保留，以及所有检测概率与原版 Float32 基准逐项完全一致。适配没有更改后台线程设置的 dtype。
- 完整测试：`.venv\Scripts\python.exe scripts/test_no_audio.py -q`，**183 passed, 2 skipped**。原生音频导入保护未发现访问尝试。
- 本次变更文件 Ruff 通过。全仓检查仍有先前已有的 44 项问题，未将无关文件格式修复混入此次改动。
- 实际文件推理：Qwen3-ASR 1.7B / CUDA + HY-MT2 1.8B / CUDA + SaT / CPU；48 kHz 原声直通前端，6.624 秒输入（含 1 秒尾部静音）。完整英文词序列通过，三段字幕均定稿并输出中文译文，无错误，worker 返回 `done` 并正常退出。PyTorch 显存分配峰值 7.23 GiB，不含驱动等额外占用。

对应文件测试命令如下；本次运行另外通过 `sitecustomize` 加载 `scripts/test_no_audio.py` 的原生音频导入保护，并设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`：

```powershell
.venv\Scripts\python.exe scripts/smoke_wlk.py --backend qwen3-streaming --qwen-model Qwen/Qwen3-ASR-1.7B --translate --translation-model tencent/Hy-MT2-1.8B --audio-preset "原声直通 · 系统音频" --output .work/cache/vad-dtype/qwen17-hy-sat.json
```

本机证据保留在 `.work/cache/vad-dtype/`：`qwen17-hy-sat.json`、`.log`、`.settings.json`、`.txt`、`tests.log`、`ruff-full.log`。

本次没有访问麦克风、系统音频设备或播放声音。此记录验证启动竞争修复和短文件完整链路，不代表长会话、所有语言、真实录音设备或 macOS 已重新验收。
