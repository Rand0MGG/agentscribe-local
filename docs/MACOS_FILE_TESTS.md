# Mac 现成音频推理测试 · 2026-09-28

## 结论

当前应用的 Whisper tiny / CPU 路线在这台 M2 / 8GB Mac 上完成了短音频和 101 秒连续语音的实时文件回放测试。两次均产出定稿字幕并正常结束，没有使用麦克风或音频播放设备。

这证明现有识别链路可以处理这些样本，不代表所有模型、中文、噪声、长会议或识别加翻译同时运行都已达到可用标准。首次测试未完成翻译与 Metal 性能测试；后续 MLX GPU 的成功结果见文末“取消内存中止阈值后的实际结果”。

## 环境与输入

- macOS 26.6.2、Apple M2、8GB 内存、8 个逻辑核心、Python 3.12.14。
- 项目 `.venv-wlk`：PyTorch / torchaudio 2.11.0、WhisperLiveKit 0.2.26（项目固定提交）、qwen3-asr-causal 0.1.0（项目固定提交）、Transformers 4.57.6。安装成功且 `pip check` 通过。
- Whisper `tiny.pt` 来自上游列出的 OpenAI 下载地址，SHA-256 为 `65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9`，下载后已校验。
- 输入为仓库已有 `tests/fixtures/hello.wav`（5.62 秒）和 `continuous-en.wav`（101.18 秒），都是历史英文合成语音夹具。参考文本只用于事后评分，不传给识别模型。
- 固定 `source=en`、`translate=false`、`offline=true`，音频处理使用默认直通配置；因此不包含翻译、SaT 模型或可选降噪的开销。

路径与桌面共用：

```text
现成 WAV → 48 kHz 单声道文件（按原速发送）
→ Session(capture_fn=文件读取) → AudioJournal → wlk_worker
→ WhisperLiveKit / AlignAtt → 字幕修订与定稿
```

执行的是 `scripts/replay_streaming.py`，外围资源保护工具和配置保存在 `.work/cache/`、`.work/mac-file-tests/`。没有使用声卡回放来模拟输入。

## CPU 实测结果

| 指标 | 短音频 | 连续语音 |
| --- | ---: | ---: |
| 音频长度 | 5.62 秒 | 101.18 秒 |
| 启动至开始送入文件音频 | 10.54 秒 | 3.72 秒 |
| 开始送入音频至首条字幕事件 | 2.29 秒 | 1.51 秒 |
| 文件输入结束至会话完成 | 0.57 秒 | 0.63 秒 |
| 最终字幕段数 | 2 | 14 |
| 词错误率 WER | 0% | 1.17%（3 / 256） |
| 测试进程树 RSS 采样峰值 | 586 MiB | 551 MiB |
| 所有剩余字幕定稿 | 是 | 是 |
| 会话正常结束 | 是 | 是 |
| 原生音频后端导入尝试 | 0 | 0 |

启动时间包含进程启动、运行库导入及模型准备；短音频为首次执行，第二次可能受系统缓存影响。首条字幕时间相对于文件开始送入，不是每个词的精确延迟。WER 比较忽略大小写和标点，因此不反映标点及字幕断句质量。

测试按音频原速输入，所以总运行时间不能用作纯模型计算 RTF。连续语音输入完毕后约 0.63 秒收尾，说明此次测试未积累持续增长的处理欠账；不能将其外推为所有场景实时。

短音频最终文本：

> Hello, welcome to our meeting. Today we are discussing a new project

## Metal / MPS 尝试

PyTorch 在可访问 GPU 的本地执行环境中报告 `mps_available=true`；受限沙箱内为 false。这两个结果不能混同为硬件不支持。

本次使用临时试验适配器将 Whisper 权重放到 MPS，稀疏对齐元数据仍留在 CPU。日志确认模型设备为 `mps:0`，但尚未完成启动或产出字幕，约 6.2 秒后就触发资源保护：

- 系统交换空间占用由 1,289.69 MiB 增至 1,988.69 MiB，增加 699 MiB，超过预设的 256 MiB 增量阈值。
- 系统可用内存比例从 42% 降到 23%。停止后复查为 59%。
- 监测器只终止了本轮测试的独立进程组；原生音频后端导入尝试为零。
- 已立即向用户报告并停止后续 GPU 推理。全系统内存变化不构成测试导致该变化的因果证明，也无法据此确认用户录音是否受到间接影响。

**此项记为资源保护中止，不能记为 GPU 推理通过，不能给出 Metal 加速比。** 临时适配器留在 `.work/cache/mps_worker.py`，未合入应用后端或向用户界面开放 MPS。

NLLB 600M 的官方权重约 2.46GB；下载启动后，因上述资源事件取消，保留部分下载以便后续继续。未加载翻译模型、未得到译文或翻译速度结果。本次 MPS 轮次未加载 PyTorch Qwen 1.7B 或 HY-MT2。

## 资源与录音保护

- 推理子进程使用 `nice 15`，CPU 数学库线程限制为 2。
- Python 测试及继承环境的子进程阻止导入 SoundCard、sounddevice、PyAudio、QtMultimedia；没有枚举音频设备，没有修改权限、音量、采样率或用户录音程序。
- 约每 2 秒检查测试进程树 RSS、系统可用内存和交换空间；RSS 超过 1,800 MiB、可用比例低于 18%、交换空间较启动增长超过 256 MiB，或运行超过 300 秒时结束测试。
- RSS 是采样值，且不覆盖独立 GPU 驱动/编译服务占用；上述保护不能保证系统其他工作完全不受计算负载影响。因此触发保护后没有继续加载更大的模型。

## 本机证据

所有文件均位于 Git 忽略的 `.work/mac-file-tests/`：

- `tiny-cpu-short/`、`tiny-cpu-long/`：`summary.json`、`resources.json`、`captions.srt` 与 `replay/events.jsonl`、`replay/manifest.json`。
- `tiny-mps-short/`：中止原因、资源采样、部分启动日志；该 replay 不完整。
- `runtime-freeze.txt`：本次推理依赖版本。
- `test-tools.json`：执行脚本与临时试验适配器的哈希。
- `hello.json`、`continuous-en.json`：原音频与准备后 PCM 的路径、长度和哈希。

后续在用户录音结束后继续 MPS 内存与启动排查，再做翻译单独测试及识别加翻译的完整测试；GPU 完整识别验收通过后，才考虑将试验入口提升为稳定支持及发布测试版。

## Qwen 1.7B / MLX 4-bit 验证（同日后续）

用户在得知前次资源事件后明确授权验证 4-bit 版本。下载并固定了 [MLX 社区模型](https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-4bit/tree/78a389c776a5483b2d0d4ea5494e11012e0d6159)，使用 MLX-Audio 0.5.6 / MLX 0.32.2 的独立环境。

测试仍只读取 `hello.wav`，不访问麦克风、播放或设备枚举。为这次授权的量化模型，将测试进程树 RSS 阈值设为 3,200 MiB、启动前系统可用比例至少 30%；保留可用比例 18%、交换增长 256 MiB 和 300 秒超时保护。MLX 内部还限制分配 3 GiB、缓存 128 MiB。没有放宽系统交换保护。

| 指标 | 结果 |
| --- | --- |
| 实际设备 | MLX GPU（启动握手确认） |
| 权重加载时间 | 约 2.1 秒 |
| 本轮总时长 | 4.09 秒后自动终止 |
| 系统交换占用 | 2,007.62 → 2,407.19 MiB（+399.57 MiB） |
| 系统可用比例 | 56% → 29% |
| 识别文本、耗时、准确率 | 未得到结果，不能评分 |
| 原生音频后端导入尝试 | 0 |

这是 **GPU 加载通过、完整推理因资源保护中止**。不能推断 4-bit 永远跑不动，也不能宣称已实时；系统交换增长亦不能单独证明用户录音受到影响。已立即告知用户，未继续真实模型推理。RSS 采样不覆盖完整 Metal 分配，不能把采样到的 212.5 MiB 当作模型总内存。此前 2–3.5 GB 是估计范围，本次未完成稳态内存测量。

证据：`mlx-4bit-probe/resources.json`、`console.log`；工具为 `.work/cache/run_mlx_check.py`、`mlx_probe.py`。真实测试调用了现在的 `MLXClient` 与 `mlx_asr_worker`；之后又增加了配置校验，未重跑 GPU 推理。

另外使用明确标记的模拟识别器跑通实际 WLK 文件管线：全部 269,935 个 48 kHz 样本送达，字幕经历草稿、修订、定稿，模型正常关闭，会话成功结束。输出固定为 “Synthetic pipeline test.”，仅用于验证传输，不计算 WER 或 GPU 性能。证据为 `mlx-mock-pipeline/replay/events.jsonl`、`manifest.json` 和外围 `resources.json`。

## 取消内存中止阈值后的实际结果

用户明确要求“别管内存保护了，运行试试”。按这一新授权，外围工具改为只记录 RSS、系统余量与交换空间，不再根据内存数据中止；保留 300 秒超时、低优先级、数学库 2 线程和原生音频导入拦截。没有改变用户的录音进程或系统音频配置。

### 单文件模型推理

5.62 秒 `hello.wav`，固定 English，模型与音频均来自本地。测试专用包装器移除应用额外设置的 3 GiB MLX 分配上限，保留 MLX 原生限制与 128 MiB 缓存限制。

- GPU 权重加载约 2.1 秒。
- 第一次完整识别 2.20 秒，同一进程第二次识别 0.58 秒（有首次初始化/缓存差异）。
- 两次文本均正确；忽略标点和大小写后的 WER 为 0%。
- MLX 分配峰值约 2.24 GiB；这是 MLX 分配计数，不是整个软件或系统的总内存。
- 系统交换空间采样增长约 428.93 MiB，但测试成功完成；先前的保守阈值中止不能用于证明模型无法运行。

证据：`mlx-4bit-unrestricted-short/`；工具 `.work/cache/run_mlx_observe.py`、`mlx_probe_observe.py`、`mlx_worker_observe.py`。

### 实际软件字幕流程

随后直接运行现有 `scripts/replay_streaming.py`，通过 Session → AudioJournal → WLK → MLX → 字幕，而不是模拟模型。音频按 1 倍速度输入。外围内存中止仍关闭；应用保持其正常 3 GiB MLX 分配上限，两次都没有触及上限。`translate=false`，未加载 SaT，1 秒草稿目标与停顿检测。这些历史结果不代表当前完整链路的性能。

| 指标 | 5.62 秒短音频 | 101.18 秒连续语音 |
| --- | ---: | ---: |
| 启动至文件输入 | 4.68 秒 | 4.37 秒 |
| 文件开始至首条字幕 | 2.00 秒 | 2.02 秒 |
| 输入结束至会话退出 | 1.46 秒 | 1.62 秒 |
| 最终字幕段数 | 2 | 24 |
| WER（忽略大小写、标点） | 0%（0 / 12） | 0.39%（1 / 256） |
| MLX 分配峰值 | 2.23 GiB | 2.42 GiB |
| 计算延后采样 P95 / 最大 | 1.5 / 1.7 秒 | 2.1 / 2.6 秒 |
| 系统交换采样最大增量 | 23.76 MiB | 113.06 MiB |
| 系统可用比例最低值 | 21% | 22% |
| 全部音频送达、字幕全部定稿 | 是 | 是 |
| 会话正常结束、字幕状态问题 | 是 / 0 | 是 / 0 |
| 音频硬件导入尝试 | 0 | 0 |

连续音频唯一词错误为 `forecast` → `forecasts`，没有词删除或插入。字幕标点和分段仍有改进空间，WER 不评估这些问题。计算延后来自 WLK 状态的 0.1 秒精度采样，不能视为逐词延迟；短时间测试也不能证明长会议稳定性。

同一连续英文样本此前 Whisper tiny / CPU 为 1.17% WER、首条字幕 1.51 秒、收尾 0.63 秒；Qwen 4-bit 这次词错误更少，但字幕出现和收尾更慢。它们是不同模型，不能把这个比较当成纯 GPU 加速比，也不能用于证明 Mac 超过 Windows。

本轮修复了正常关闭 MLX 时直接终止子进程的问题：现在先发送停止消息，超时再终止/强杀。实际软件两次退出没有出现短文件探针先前的资源清理警告；相关关闭、超时和父进程退出测试通过；最新完整回归 173 项通过，原生音频导入尝试为零，改动文件 Ruff 与 diff 空白检查通过。

证据：`mlx-4bit-stream-short/`、`mlx-4bit-stream-long/` 的 `resources.json`、`summary.json`、`replay/events.jsonl` 与 `replay/manifest.json`。评分工具 `.work/cache/score_mlx_files.py` 只在识别完成后读取参考文本，不向 ASR 提供参考。

**当前结论：M2 / 8GB 的 Apple GPU 已完成这些英文样本的实际识别和完整字幕流程，能够按实时输入持续处理；中文、真实会议、翻译并行和长期内存稳定性仍待验证。**


## SaT 完整字幕链路验证（2026-09-28）

环境仍为 M2 / 8 GiB、macOS 26.6.2、Python 3.12.14。Qwen3-ASR-1.7B 4-bit 使用 MLX / Apple GPU，SaT-3l-sm 使用 ONNX Runtime CPU；`wtpsplit==2.2.1`，模型和分词器版本固定于 `semantic_model.py`。关闭翻译和可选音频增强，严格离线，按实时速度送入 101.176 秒的现成英文音频。没有访问、枚举或播放音频设备。

命令通过带原生音频导入保护、资源记录和 300 秒超时的文件回放包装器执行：

```bash
.venv/bin/python scripts/replay_streaming.py run \
  --prepared .work/mac-file-tests/continuous-en.json \
  --settings .work/mac-file-tests/sat.settings.json \
  --output .work/mac-file-tests/mlx-sat-stream-long/replay
```

| 指标 | 结果 |
| --- | ---: |
| 模型和进程准备 | 9.71 秒 |
| 开始送入音频至首条字幕 | 2.26 秒 |
| 输入结束至会话收尾 | 3.04 秒 |
| 最终字幕 | 25 段，全部定稿 |
| 字幕修订检查异常 | 0 |
| WER | 0.39%（1 / 256；无删除或插入） |
| MLX 分配峰值 | 2.42 GiB |
| WLK 计算延后 P95 / 最大值 | 2.4 / 3.0 秒 |
| 测试期间系统交换空间增长 | 1490.44 MiB |
| 音频设备访问尝试 | 0 |

模型状态确认 SaT 已加载，字幕事件的边界类型为“上下文分句”或“等待后文”。这些结果验证实际模型链路和正常收尾，WER 不衡量断句质量。交换空间数据覆盖整个系统，不能全部归因于 SaT；MLX 峰值也不包含 SaT、PyTorch、Qt 和系统占用。未验证翻译并行、中文、长会话或 Windows 实机。

证据：`.work/mac-file-tests/mlx-sat-stream-long/summary.json`、`resources.json`、`replay/manifest.json`、`replay/events.jsonl`。模型准备记录在 `.work/mac-file-tests/sat-prepare/`。SaT 权重已复制到本机默认 Hugging Face 缓存并通过离线加载检查。

同次代码验证：183 项回归通过，包含 SaT 加载失败不启动采集、推理失败停止会话并保留已显示字幕；整个测试过程阻止原生音频模块导入。改动 Python 文件 Ruff 检查通过，完整仓库仍有 44 项其他文件的既有静态检查问题。设置页使用禁止音频访问的 Qt 离屏窗口生成并检查，预览为 `docs/semantic-preview.png`。

### 断句人工核对

对照 `tests/fixtures/continuous-en.txt` 的句界，参考为 20 句，最终字幕为 25 段。按词位置核对内部句界（不计文件末尾）：参考 19 处，输出 24 处，重合 18 处，多切 6 处，漏切 1 处。本次输出与参考均为 256 词，只有一处词替换，因此词位置可以直接对应。这是单份合成英文素材的原稿对照，不是通用断句准确率或翻译分段质量分数。

- 明显不自然的切分：`At first. | They planned ...`、`They also watched. | For repeated words ...`、`They discussed the weather, the number of visitors. | And the equipment ...`。
- 上下文归属错误：在 `more than a minute` 后切开，又把 `With different sentences and natural pauses` 接到下一句 `on Monday morning ...` 前。对应一处多切与一处漏切。
- 另外两处多切位于 `The chairs were arranged` 和 `The sound was clear` 后。原稿将三个并列分句放在一句内；拆为字幕短段不一定影响理解，但仍不同于原稿句界。

输出中的这些位置已有句号，SaT 只返回边界而不改写标点；这次链路未把上述不自然边界合并回来。现有事件日志没有独立 ASR hypothesis/snapshot，不能据此量化音频窗口、识别标点、SaT 预测及字幕定稿各自的影响，需要后续记录各阶段文本与边界再定位。

结论：模型链路与正常收尾已验证，断句质量仍需改进。0.39% WER 只衡量归一化后的词错误，不能用于证明句界正确。
