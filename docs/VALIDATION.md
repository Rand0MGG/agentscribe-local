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

上述运行记录来自整合过程中的对应代码状态。随后调整过短字幕长度、模型缓存解析和兼容代码，因此最终版本完整复测仍待完成，不能将表格等同于最终版本验收。

## 未通过的场景及保留的限制

- Whisper large-v3 反复播放同一句话 12 次的严格完整性检查失败。原版上游跨批次重复保护会重置解码段；一次缩小保护范围的实验导致后半段提交停滞，已撤回该实验。保留上游原始保护，没有声称此问题已修好。
- 101 秒不重复素材的零词错误结果出现在上述实验分支期间，该素材未触发重复保护；撤回实验后的最终版本仍应重跑，不用这一结果掩盖重复内容失败。
- Windows 上游对齐代码提示缺少 Triton，使用备用 median kernel；GPU 识别仍实际运行。没有隐藏该提示，也未把它当作所有问题的解释。
- 早期字幕适配曾把带句号的整行过早锁定，导致漏掉后续词；现已改为对上游已确认词生成短段，草稿继续修订。迟到的独立标点不会单独送去翻译。短问候会与后续文本合并，以提供更多翻译上下文。
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
