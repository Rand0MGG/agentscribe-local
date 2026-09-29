# 分句实验前的代码基线

2026-09-29，分支 `codex/ui-experience`。这是界面、VAD Float32 兼容和两阶段翻译的工作基线，不是新 Release。

## 验证

- Windows AMD64 / Python 3.12，`.venv\Scripts\python.exe scripts/test_no_audio.py`：207 passed、2 skipped；没有原生音频后端导入尝试。
- 本次改动及新增 Python 文件 Ruff 通过；全仓 Ruff 有 43 项既有告警。`git diff --check` 通过。
- 此次提交前未重测真实音频设备和 macOS。此前文件推理与界面证据的环境和范围见 `TWO_PHASE_TRANSLATION.md`、`VAD_DTYPE_FIX.md` 和 `../UI_EXPERIENCE.md`。

## 已知不足

完整课堂录音的分析表明，当前分句仍会保留 ASR 错误句号造成的碎句。对同一保存文本重新执行 SaT，给出更多后文也不能消除所有错误边界。去标点有局部改善，但去标点并转小写会明显过度合并，不能按字幕条数评价效果。

当前实现还限制已提交片段内部重新拆分，且对带句末标点的已定稿尾部不重新合并。这些限制需要和分句模型能力分别评估。

后续实验固定输入、保留原文，只改变边界策略；比较错误切分、遗漏边界和等待代价。私人录音、全文、模型及实验日志保留在本地 `.work/cache/`，不提交 Git。实验结果不能替代真实流式识别和翻译验收。
