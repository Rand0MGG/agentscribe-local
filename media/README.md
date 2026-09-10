# 固定课堂对照样本

后续识别、音频处理、草稿刷新、分句和翻译修改均使用 `test.m4a` 做真实音频回归；短合成测试不能替代此录音。`test.txt` 是用户提供的 Qwen Scribe + 1.7B 输出，未经人工校对，不能作为准确率标准答案，也不能放进识别提示词。

在项目根目录运行：

```powershell
.venv-wlk/Scripts/python.exe scripts/prepare_classroom.py
.venv/Scripts/python.exe scripts/smoke_wlk.py --backend qwen3-streaming --qwen-model Qwen/Qwen3-ASR-1.7B --audio .work/classroom.wav --reference media/test.txt --comparison --draft-seconds .5 --endpoint-seconds 1.5 --output .work/classroom-draft.json
```

脚本保存文件哈希、转换规则、带接收时间的字幕事件和最终原文。按实际音频速度送入相同 worker。默认不加音频增强和翻译，以便隔离识别变量；应用中的增强配置不能由此测试推断。`--translate` 可另测完整翻译链路。

对照文本的编辑距离只表示两份结果的分歧，不能称为真实错误率。检查原文修订次数、更新间隔、错误分段合并、最终漏词和术语；判断准确性仍须回听。音频和参考文本仅保留本地，不自动提交到 Git。
