# HY-MT2 1.8B / Metal 文件验证

## 范围

2026-09-29，在 Apple M2 / 8GB、macOS 26.6.2 上验证腾讯官方 HY-MT2 1.8B Q4_K_M。测试使用项目英文音频和短文本，不访问麦克风、系统声音、播放设备或正在运行的录音会话。

先用本机历史实验脚本 `.work/cache/check_hy_metal_prototype.py` 验证模型，再接入桌面正式会话：设置选择 HY 1.8B 与 Apple GPU / Metal 后，`backends.create_translator` 加载 `LlamaTranslator`，自动管理本机服务。下文保留前期实验数据，并单列桌面链路复测；桌面版本不使用实验适配器注入。

## 固定输入与运行参数

- 模型：[腾讯官方 GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/tree/a0c709d9fac510f2c807aa3af52872340dc37a4a)，revision `a0c709d9fac510f2c807aa3af52872340dc37a4a`，文件 `Hy-MT2-1.8B-Q4_K_M.gguf`，约 1.13 GB。
- 运行时：[llama.cpp b11254 官方 macOS arm64 发行包](https://github.com/ggml-org/llama.cpp/releases/tag/b11254)，实验解压到 `.work/tools/`；桌面通过 `scripts/install_llama.py --device metal` 校验并安装到 `.runtime/llama-b11254/`，不修改现有 Python 推理环境。
- 明确指定 `--device MTL0 -ngl 99 --fit off`；日志确认设备 Apple M2、33/33 层 offload 到 GPU。
- 上下文 4096、一个推理槽、CPU 线程 2。模型映射到 Metal 的缓冲约 1075.74 MiB，Metal KV 缓冲 256 MiB，Metal 计算缓冲约 48 MiB；这些数值不等于完整进程或整机峰值内存。
- 翻译复用应用提示词、初译/最终上下文策略，温度 0.7、top-p 0.6、top-k 20、重复惩罚 1.05、实验固定 seed 42，桌面沿用随机采样，最多生成 1024 token。服务仅绑定 127.0.0.1，不上传样本文字。
- ASR：Qwen3-ASR 1.7B MLX 4-bit，draft/endpoint 各 1 秒；SaT CPU；源语言英语，目标简体中文；前文 3 段、后文 1 段。
- 音频 `tests/fixtures/continuous-en.wav`，101.176375 秒，参考词数 256。按真实速度提交 48kHz PCM，参考文本不提供给识别或翻译模型。
- 原始文件 SHA-256：`6566ffbc089c693a54cc0f6438fbc0ab9bad49868989cfe50956645c9f7514c2`。各次测试保存模型、运行时和代码校验值。

## 初步观察

6 条短文本独立测试的整段翻译耗时约 0.16–0.57 秒；上下文中的 crane 正确译成“鹤”，bank 译成“岸边”，中译英时间表达完整。这是少量人工检查样例，不能当作总体翻译质量评分。

首次连续并行测试，翻译请求中位数 0.48 秒、P95 1.51 秒，短时队列峰值 6 条，可随后清空。但识别后半程单次推理升至 16.83 秒，整机 swap 增长约 3635 MiB，收尾约 29.59 秒。最终字幕遗漏末尾 24 个词，不能通过完整性验收。

检查后补上 EOF 最终快照读取：上游 formatter 在消费者处理快照期间可能完成最后一次 ASR，然后直接退出，未发布刚写入的词。对应模拟回归和同条件文件复测保留在本次分支中。

修复后同一段音频的连续回放：

| 指标 | 结果 |
| --- | --- |
| 最终字幕 / 已完成最终翻译 | 25 / 25 |
| 英文词错误率 | 1 / 256（0.39%）；无增词、漏词 |
| 首条原文 / 输入结束后的收尾 | 2.06 / 4.57 秒 |
| 实际模型请求 | 40 次，均正常结束 |
| 请求耗时中位数 / P95 / 最大值 | 0.37 / 0.90 / 1.13 秒 |
| 排队等待最大值 / 队列峰值 | 1.6 秒 / 3 条 |
| 最后字幕时间 | 101.176375 秒 |
| 系统 swap 增长 | 约 1354 MiB |

这次最终字幕包含完整结尾，兼容层的确定性模拟测试同时覆盖了 EOF 竞争条件。复测运行时的内存压力与首次测试不同，耗时改善不能全部归因于收尾修复。

修复后的两次暂停回放：

| 指标 | 结果 |
| --- | --- |
| 暂停位置 | 音频第 29、69 秒 |
| 两次暂停墙钟时间合计 | 约 4.02 秒 |
| 最终字幕 / 已完成最终翻译 | 22 / 22 |
| 英文词错误率 | 0 / 256；无增词、漏词 |
| 最后字幕时间 | 101.176375 秒；未加入暂停时长 |
| 实际模型请求 | 35 次，均正常结束 |
| 请求耗时中位数 / P95 / 最大值 | 0.39 / 0.77 / 1.06 秒 |
| 排队等待最大值 / 队列峰值 | 1.5 秒 / 2 条 |
| 输入结束后的收尾 | 约 5.04 秒 |
| 系统 swap 增长 | 约 1942 MiB |

请求耗时包含本机 HTTP 往返和生成，排队等待另外统计。模型服务和 worker 启动不计入单次翻译耗时。系统 swap 是整机读数，不能全部归因于本模型；也不能直接用不同运行的差值宣称某项改动提升了性能。

## 桌面链路复测

在隔离的原生 Qt 窗口中选择“使用 HY 1.8B · Apple GPU”，导出实际 Settings，再通过普通 `scripts/replay_streaming.py run` 回放同一音频。没有替换翻译工厂，没有手动启动模型服务。

| 指标 | 结果 |
| --- | --- |
| GPU 确认 | Apple M2 / Metal，33/33 层 |
| 最终字幕 / 完成最终翻译 | 25 / 25，无翻译错误 |
| 英文词错误率 | 1 / 256（0.39%）；无增词、漏词 |
| 翻译消费耗时中位数 / P95 / 最大值 | 约 0.4 / 1.0 / 1.1 秒 |
| 排队等待最大值 / 队列峰值 | 1.5 秒 / 3 条 |
| 首条原文 / 收尾 | 4.73 / 5.08 秒 |
| 系统 swap 增长 | 约 3319 MiB |

翻译消费统计来自正常会话的诊断信息，精度 0.1 秒，共 37 次，可能包含缓存命中；不能与实验脚本逐次 HTTP 请求数据完全等同。首次服务加载与识别并行，HY 从开始加载到确认 GPU 约 11.45 秒。退出后未发现残留 llama-server。音频未访问设备，所有 4,856,466 个 PCM 样本均被接收。

速度已能跟上本段输入，但译文仍受源文分句影响，例如 “They also watched.” 与后续片段分开翻译，意思不够连贯；“different speakers” 的中文也不够自然。该测试不等于翻译质量全面通过。

随后退出回归触发 Python 崩溃报告：辅助进程的守护线程阻塞读取缓冲 stdin，在收到终止信号后仍持有缓冲锁，解释器清理时触发 `SIGABRT`。原测试只检查子进程消失，漏查辅助进程退出码。已改为主线程轮询原始管道，并验证 EOF、终止信号、子进程先退出三种情况均正常退出；测试也检查退出码和 fatal 错误。实际 Metal 文本推理的正常退出另存 `hy-metal-shutdown/`。

## 桌面使用

1. Apple Silicon Mac：设置 → 翻译模型 → “使用 HY 1.8B · Apple GPU”。计算设备应显示“Apple GPU · Metal”。
2. 首次点击“下载 / 检查翻译模型”，或执行 `.venv/bin/python scripts/install_llama.py --device metal`。已准备完整权重时不会重复下载。
3. 开启翻译，下次聆听自动加载并显示实际 GPU 层数。正在运行的旧应用应在录音结束后重新启动以载入代码。
4. 模型或运行组件缺失会在创建录音前提示；GPU 加载失败保留原文并报告翻译错误，不静默回退 CPU。

## 复现

桌面链路使用包含 `translation_model: "tencent/Hy-MT2-1.8B"`、`translation_device: "metal"`、`translate: true` 的 Settings JSON：

```bash
.venv/bin/python scripts/replay_streaming.py run \
  --prepared .work/mac-file-tests/continuous-en.json \
  --settings .work/cache/hy-metal-desktop/settings.json \
  --output .work/mac-file-tests/hy-metal-desktop-new/replay
```


当前文本检查直接调用正式适配器：

```bash
.venv/bin/python scripts/check_llama.py --device metal --output .work/mac-file-tests/llama-text-new
```

完整链路使用上面的 `replay_streaming.py run`，暂停验证增加 `--pause-at 29 --pause-at 69`。每次使用新输出目录，避免覆盖已有证据。前期实验脚本及结果保存在本机 `.work/`，不再维护第二份翻译实现。

程序阻止原生音频 Python 模块导入，包括子进程；退出时只停止自身启动的推理服务。本次实测通过 `.work/cache/run_mlx_observe.py` 加入 300 秒总超时和资源采样，没有内存阈值中止。

## 证据与限制

- 首次短文本：`.work/mac-file-tests/hy-metal-single/`。
- 初次连续并行：`.work/mac-file-tests/hy-metal-concurrent/`。
- 初次暂停验证：`.work/mac-file-tests/hy-metal-pauses/`。
- 修复后暂停验证：`.work/mac-file-tests/hy-metal-pauses-final/`。
- 修复后连续验证：`.work/mac-file-tests/hy-metal-continuous-final/`。
- 桌面链路：`.work/mac-file-tests/hy-metal-desktop/`，包含原始事件、双语字幕、汇总和补充适配器校验值；界面截图及隔离设置在 `.work/cache/hy-metal-desktop/`。
- 每个 `*-observe/` 保存资源采样；前期实验的 `server.log` 记录 GPU 分配，`requests.jsonl` 记录真实翻译，`replay/` 保存会话事件和 manifest。模型及个人本机路径不进入 Git。

该方案已证明 HY 量化翻译可以实际运行在 Apple GPU，并在本段音频中及时处理翻译请求。但两套模型共享 8GB 统一内存，仍出现明显交换空间增长；尚未验收长会话、多语言识别、真实设备，以及 Windows。前置分句仍会出现短碎句和跨句连接，翻译模型不能自动修正所有错误的原文边界。

## 代码和界面检查

- HY 桌面接入阶段 `.venv/bin/python scripts/test_no_audio.py -q`：253 项通过，无原生音频导入尝试。
- 本次修改及新增的 Python 文件 Ruff 检查通过，`git diff --check` 通过。全库 Ruff 仍有 41 项既有问题，均在未修改文件中。
- 原生 Cocoa Qt 预览使用独立设置和示例库，900 × 650 窗口下检查“暂停”“继续录音”“停止”，未截断或重叠。截图在 `.work/ui-experience/recording-listening.png` 和 `recording-paused.png`。

- 翻译页原生 Cocoa 预览覆盖 1280 × 840 和 900 × 650；Metal 选项可见。模拟 Windows 保留 CPU/CUDA，未在 Windows 实机验收。

共享引擎选择的后续检查见 [llama.cpp 翻译](../LLAMA_CPP.md)。
