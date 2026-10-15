# 固定课堂对照样本

识别、音频处理、草稿刷新、分句和翻译的质量修改使用本地 `test.m4a` 做固定课堂对照；短合成测试不能替代此录音。仅改文档等无关内容无需运行。`test.txt` 是用户提供的 Qwen Scribe + 1.7B 输出，未经人工校对，不能作为准确率标准答案，也不能放进识别提示词。文件和权限边界按 [测试规范](../docs/TESTING.md) 执行。

下列命令面向 Windows CUDA 文件回归，不访问采集设备。先按 [安装指南](../docs/WORKSPACE.md#windows-源码安装) 准备组件与模型，确认本机保留这两个私人样本，再在项目根目录运行：

```powershell
$classroomPython = & .venv\Scripts\python.exe -c "from linguaflow.runtime_paths import runtime_python; print(runtime_python())"
& $classroomPython scripts/prepare_classroom.py
.venv\Scripts\python.exe scripts/smoke_wlk.py --backend qwen3-streaming --qwen-model Qwen/Qwen3-ASR-1.7B --audio .work/classroom.wav --reference media/test.txt --comparison --draft-seconds .5 --endpoint-seconds 1.5 --timeout 900 --output .work/classroom-draft.json
```

WLK 解释器由 `runtime_paths.py` 解析当前管理环境或兼容的旧环境，不固定依赖 `.venv-wlk` 目录。此回放脚本显式使用 CUDA；Mac 的 MLX/Metal 文件验收按 [测试规范](../docs/TESTING.md) 及对应验证记录执行，不直接照抄设备设置。原速回放的超时须覆盖音频时长、加载和收尾；示例为固定课堂样本显式留出预算，脚本默认超时不足以回放完整样本，不能把超时输出当完整结果。

脚本保存文件哈希、转换规则、带接收时间的字幕事件和最终原文。按实际音频速度送入相同 worker，复用应用的 [自动音频处理配置](../linguaflow/audio_processing/config.py)。默认关闭翻译；`--translate` 需先准备脚本指定的翻译模型，其默认 NLLB 配置不代表推荐 HY 组合，实际参数见 [`smoke_wlk.py`](../scripts/smoke_wlk.py)。

对照文本的编辑距离只表示两份结果的分歧，不能称为真实错误率。检查原文修订次数、更新间隔、错误分段合并、最终漏词和术语；判断准确性仍须回听。音频和参考文本仅保留本地，不自动提交到 Git。
