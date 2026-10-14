# 连续课堂回放与评分

目的：验证完整录音经过真实应用链路后的最终保留字幕，防止把机器参考、片段拼接或局部指标当成准确率。AMI 的数据集差异单独见 [协议](AMI_BENCHMARK.md)。

## 输入与参考

- 文件替代设备，经 `Session → AudioJournal → worker → ASR → SaT → 修订/撤回`，不按答案句界切割，不重置上下文，不把参考传给识别提示词。
- 先完整解码/准备，核验输入时间轴、采样数和哈希；1 倍速每 100ms 交付对应采样，不提前送未来音频。EOF 正常收尾并保存完成证据；中断、错误、时间轴不合协议或被修改的运行不得评分，不能拼接半段修复。
- 原始数据和人工校对分开。下载的 MacWhinney CHAT 带机器 ASR 来源且缺独立逐句核对，默认待核对；未核对时正式 `wer=null`，只报告“未核对词差异率”。历史六份参考与结果见 [冻结记录](../archive/testing/SCORING_SYSTEM_20261015.md)。
- 校对者独立回听全部音频，逐句记录词/时间，检查漏标与插话，确认整段覆盖；修改文字/时间撤销旧认证。听不清保留标记，不自动删成静音，不由程序批量声称听过。

## 评分规则

- 按字幕 ID/事件重建最后状态，撤回行移除，旧草稿不重复累加；不同位置真实重复必须保留。
- 有效参考使用 `WER=(替换+删除+插入)/参考词数`，报告三类编辑；WER 可超过 100%，`1-WER` 不叫准确率。空参考不定义，有参考无输出按全漏词。
- 固定 Unicode/大小写与标点标准化，保留缩写撇号、数字原样、填充词、重复和口头纠正；不按专业知识替换原话。CHAT 主层与语法/编辑注释分开，未支持标记进入核对。
- 精确 Levenshtein 全局对齐输出逐词差异；等价最短对齐的位置可能不同。辅助填充词排除指标同时报告，不择低。多说话人排序依协议声明，不冒充说话人归属、cpWER 或其他会议指标。
- 字幕估计时间不用于精确词级延迟；记录首次文字、修订、交付迟到及实际耗时。旧 feb14 时间轴有累计约 30ms 间隙，只支持其注明的文本比较，当前严格准备会拒绝；不重写旧结果。
- 默认脚本冻结的 fast 值是历史配置兼容标签；当前 Qwen 共用窗口/确认实现，不能据此宣称正在比较两套识别算法。每次保存完整 settings，不改变桌面偏好。

## 命令与证据

在项目根目录、已有可用环境和文件推理授权下使用新输出目录：

```powershell
.venv-wlk/Scripts/python.exe scripts/evaluate_streaming.py audit --corpus media/MacWhinney --output .work/macwhinney/references-new
.venv-wlk/Scripts/python.exe scripts/replay_streaming.py prepare --input media/MacWhinney/feb14.mp4 --output .work/macwhinney/feb14-new.f32
.venv/Scripts/python.exe scripts/replay_streaming.py run --prepared .work/macwhinney/feb14-new.f32.json --output .work/macwhinney/feb14-live-new
.venv-wlk/Scripts/python.exe scripts/evaluate_streaming.py score --reference .work/macwhinney/references-new/feb14.reference.json --run .work/macwhinney/feb14-live-new --output .work/macwhinney/feb14-score-new
```

脚本参数以各入口 `--help` 为准，macOS 使用对应 `.venv*/bin/python`。示例媒体需先按协议解决时间轴间隙，不能跳过检查；缺本地数据不下载或伪造验收。审计生成的 `*.review.html` 可在本地回听校对，刷新前导出 JSON 保存进度，再用有效人工参考复算，无需重跑模型。

保存输入/代码/依赖/设置、全部事件、采样与交付统计、`score.json`、可读报告、差异 CSV 和最终字幕。准确性调参后用独立课程验收；任何单一录音不能代表所有语言或课堂。私人媒体和完整文字不随软件发布。

参考：[CHAT 手册](https://talkbank.org/0info/manuals/CHAT.html)。通用质量/性能规则见 [TESTING](../TESTING.md)。
