# 课堂音频处理预设实测

2026-09-11：对同一段 289.92 秒课堂录音测试 15 组处理方案，并对 7 组候选以另一种切分长度复测。**建议这段录音优先使用纯算法预设；AI 降噪版作为可选项，未证明比原声识别更准确。** 两项已加入应用“音频实验室”的预设列表，已有用户配置不会自动替换。

## 推荐参数

| 参数 | 课堂实测 · 纯算法 | 课堂实测 · AI 降噪 |
|---|---|---|
| 神经网络降噪 | 关闭 | DeepFilterNet3，混合 50% |
| WPE 去混响 | 开启，混合 25% | 关闭 |
| WPE 其他参数 | taps 10，delay 3，alpha 0.9999 | 不启用 |
| 自动增益 | 关闭 | 开启，最大 12 dB |
| 自动增益其他参数 | 不启用 | 变化速度 3 dB/s，余量 6 dB，噪声上限 -45 dBFS |
| 输出增益 | +6 dB | 0 dB |
| 限幅 | 开启，-1 dB | 开启，-1 dB |
| 传统降噪 / 高通 / 均衡 | 全部关闭 | 全部关闭 |

AI 实测使用 CUDA。应用选择预设时保留当前增强设备；CPU 的速度和数值一致性没有在本轮验证。纯算法预设的音频处理不使用神经网络，后续语音识别仍使用 Qwen。

## 两轮结果

**指标是与另一识别器转写的词差异率，越低越接近该文本，不是真实错误率。参考文本未经人工校对，不能据此宣称准确率提升多少。** 两种切分使用同一录音，属于敏感性复测，不是独立测试集。

| 方案 | 固定 30 秒切分 | 固定 20 秒切分 | 整段处理耗时 |
|---|---:|---:|---:|
| 原声 | 8.59%（53 词） | 8.75%（54 词） | 2.9 秒 |
| 推荐纯算法 | **8.27%（51 词）** | **8.10%（50 词）** | 70.3 秒 |
| 推荐 AI 降噪 | 8.27%（51 词） | 9.40%（58 词） | 101.5 秒 |
| 用户测试前保存配置 | 11.67%（72 词） | 10.70%（66 词） | 100.9 秒 |

纯算法两轮分别比原声少 2、4 个词的差异，收益较小。AI 候选第一轮略好，第二轮略差，不能认定有稳定识别收益。两套候选都比用户之前保存的较强增强配置更接近参考文本。

在本机，纯算法和 AI 预设的处理耗时约为音频长度的 0.24 倍、0.35 倍；耗时包含子进程启动和组件初始化，不包含识别。两者均快于实时，但这里没有测试音频增强与流式识别、翻译同时运行时的延迟和显存占用。

## 第一轮全部方案

| 脚本方案名 | 处理内容 | 词差异率 |
|---|---|---:|
| raw | 原声，经统一重采样 | 8.59% |
| gain6 | +6 dB，限幅 | 8.59% |
| highpass_gain6 | 高通，+6 dB，限幅 | 8.59% |
| agc | 自动增益，限幅 | 8.43% |
| apm_mild | WebRTC 降噪 level 0，自动增益，限幅 | 8.43% |
| apm_medium | WebRTC 降噪 level 2，自动增益，限幅 | 10.53% |
| wpe_mild | WPE 25%，+6 dB，限幅 | 8.27% |
| eq_mild | 2.5 kHz 均衡 +2 dB，输出 +6 dB，限幅 | 8.27% |
| df25 | DeepFilterNet3 25% | 8.43% |
| df50 | DeepFilterNet3 50% | 9.08% |
| df75 | DeepFilterNet3 75% | 12.16% |
| df50_gain6 | DeepFilterNet3 50%，+6 dB，限幅 | 8.43% |
| df50_agc | DeepFilterNet3 50%，自动增益，限幅 | 8.27% |
| df50_wpe | WPE 25%，DeepFilterNet3 50% | 8.91% |
| user_saved | 保存配置：高通、AI 50%、自动增益最大 20 dB、均衡 +6 dB、输出 +10 dB、限幅 | 11.67% |

第二轮中，均衡方案退至 9.08%，自动增益为 8.75%，AI 25% 为 9.40%，因此没有选它们作为最终预设。较强传统降噪、较强 AI 降噪和堆叠增强没有表现出优势。

## 测试方法与复现

- 输入 `media/test.m4a`，SHA256：`dcbee33fe0c1af149d24fead248bf01d51f9cb2065b91150ad2f5781d22d153f`。
- 使用与应用相同的 `AudioPipeline`：统一 48 kHz 单声道输入，状态连续处理并补齐尾部，再以 soxr 输出 16 kHz PCM。15 组均保留 4,638,720 个采样，未检测到满幅削波。
- Qwen3-ASR-1.7B 官方 Transformers 完整编码器，CUDA / bfloat16 / SDPA，固定英文，贪心解码，无上下文提示。每轮只加载一次模型；每组识别约 27–28 秒，不含模型加载。
- 不启用 VAD，不改变各组切分点，不输入参考文本作为提示；参考文本仅在识别后评分。标点作为分词边界，转小写后计算 Levenshtein 词编辑距离，参考共 617 词。
- 这是离线音频处理对比，不等同于已验证实时字幕系统端到端准确率；未人工逐句听写，也未证明其他录音上的泛化收益。

在项目目录使用现有推理环境运行：

```powershell
.venv-wlk/Scripts/python.exe scripts/benchmark_audio_presets.py
.venv/Scripts/python.exe scripts/summarize_audio_presets.py .work/audio-presets/results.json

.venv-wlk/Scripts/python.exe scripts/benchmark_audio_presets.py --reuse-audio-from .work/audio-presets --output .work/audio-presets-20 --chunk-seconds 20 --only raw agc eq_mild wpe_mild df25 df50_agc user_saved
.venv/Scripts/python.exe scripts/summarize_audio_presets.py .work/audio-presets-20/results.json
```

脚本支持 `--input`、`--reference`、`--saved-config`、`--df-device cpu|cuda` 和 `--only`。复用音频前检查源文件哈希和完整参数；每组识别完成后保存结果。原始报告位于 `.work/audio-presets/results.json` 和 `.work/audio-presets-20/results.json`。首轮目录保留各组 WAV、参数 JSON、文本和处理日志；复测 JSON 指向复用音频。参考录音、参考文本及 `.work` 测试产物均不提交到仓库。
