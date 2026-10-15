# 测试规范

测试验证用户可观察的结果和 [spec](specs/README.md) 的约束；代码与测试一致仍不等于行为合理。纯文档修改检查事实、引用和差异，不必启动应用、安装依赖或运行模型。

## 默认安全入口

Windows PowerShell：

```powershell
.venv\Scripts\python.exe scripts/test_no_audio.py -q -rs
.venv\Scripts\python.exe -m ruff check linguaflow scripts tests
git diff --check
```

macOS：

```bash
.venv/bin/python scripts/test_no_audio.py -q -rs
.venv/bin/python -m ruff check linguaflow scripts tests
git diff --check
```

可在无音频入口后指定测试路径。它阻止当前及继承环境的 Python 子进程导入项目原生音频后端，使用 offscreen，并拒绝任何音频导入尝试；不替代对外部命令/原生 API 的检查。常规验证使用此入口；未获授权不枚举设备、采集、播放、改系统设置或中断用户录音。

既有 Mac 录音保护继续有效：用户未明确结束录音或允许前，不枚举/访问设备、采集、播放、改系统音频设置或中断用户进程。文件推理和取消内存中止阈值的既有授权，只能按可定位原用户指令的输入、对象、阈值和范围沿用，不扩大到设备操作；保留相应超时和资源记录。[Mac 文件推理记录](archive/testing/MACOS_FILE_TESTS_20261006.md) 保留当时的限制与后续授权变化，记录本身不授予新测试权限。

开发优先 Python 3.12，兼容范围以 `pyproject.toml` 为准。优先项目环境；新兼容版本使用隔离环境，记录 Python 和实际 PySide/NumPy 等版本，不能把依赖变化归结为“只换 Python”。保留 pytest 正常临时路径和真实中文/深目录场景；显式短路径仅用于对照，不能成为隐藏产品缺陷的通过条件。

## 按改动选择验证

| 改动 | 必要验证 |
| --- | --- |
| 纯逻辑/缺陷 | 先复现，再测修复及失败/取消边界；断言行为，不镜像实现 |
| 配置/保存/路径 | 旧/缺失/损坏字段、写失败、原子性、旧回执、中文/空格/深路径、真实映射与权限 |
| 异步/UI/资源 | 活动任务中关闭、重复取消、迟到结果、事件循环响应、真实关闭与线程/进程释放；相关窗口尺寸与缩放 |
| 共享流程/广泛修改 | 完整无音频回归和静态检查；两端分支模拟，再补目标系统实测 |
| 课程 SDK/渲染 | 实际 SDK/引擎集成，完整页内容/资源解码、取消释放和许可；替身结果单独标注 |
| ASR/分句/翻译/DSP | 同输入/环境基线对照，完整文件链路、原文与译文对应、质量/延迟/资源；不能只测函数速度 |
| 音频/权限/录音生命周期 | 经授权在目标机测选源、开始/取消/暂停/继续/切换/停止、保存回听和退出 |
| 打包/升级 | 最终封存包探针及旧包→候选包安装、签名、恢复、用户数据与环境兼容；见 [RELEASING](RELEASING.md) |

常用回归定位：`test_capture_control.py` / `test_wlk_session.py`、`test_recording_save.py` / `test_recording_document.py`、`test_translation_*.py` / `test_qwen_*.py`、`test_knowledge_*.py`、`test_ui_*.py`、`test_packaging.py` / `test_update_*.py`。实际选择以调用关系为准，不强制每次重跑无关模型。

## 通过条件与 CI

- 缺陷测试应能在修复前失败。修根因，不靠生产测试专用分支、假算法、吞异常、无条件重试、删测试或放宽断言换绿；测试替身留在测试侧。
- UI 使用独立进程隔离 Qt 应用类型；共用 `tests/ui_support.py` 的有期限等待、退出和日志检查。`close()` 被调用不等于关闭成功，零退出码也不能掩盖 QPainter/QThread/QProcess 销毁警告；不能只在任务空闲后测退出。
- 图片/网页要检查真实解码/页面内容，不能仅检查 HTML 含标签。状态等待有截止时间，布局稳定与业务结果分别断言，不用固定短 sleep 调整通过率。
- `.github/workflows/checks.yml` 是 CI 矩阵的执行权威：两端 Python 3.11–3.13 无音频回归，Python 3.12 另做课程 SDK 和原生文档渲染，Ruff 独立执行。专用集成设置 `AGENTSCRIBE_REQUIRE_INTEGRATIONS=1`，选中用例有跳过即失败。
- 普通回归列出跳过原因：平台不适用、缺组件、缺权限或尚未部署分别说明。模拟链接不能证明真实映射保护；另一平台模拟不能替代实机。
- Cocoa 原生预览须有窗口服务，受限环境用 offscreen。预览入口 `scripts/preview_workspace.py --capture --output .work/browser/ui-design-<平台>` 使用示例库/设置，不能代替原生框架、权限、真实音频或 GPU 验收。

## 算法与性能证据

先固定输入、环境、问题和对照，再改变一个因素，比较真实核心流程的质量、延迟和资源。使用原速连续会话，不按答案句界切音频、不向模型提供待测参考、不择低报告。固定课堂样本见 [media](../media/README.md)，整场协议见 [AMI](testing/AMI_BENCHMARK.md) 和 [评分](testing/SCORING_SYSTEM.md)。

同时记录输入/代码哈希、依赖与设备、模型/量化、设置、缓存/预热、完整输出和无效运行原因。区分模型加载、稳态、首次/持续/收尾延迟、积压和资源；RSS、系统交换和 GPU 分配不是同一口径。局部计时不能推出整场收益，术语/断句改进不能只看 WER 或段数。

测试变绿或字幕条数减少不能单独证明用户体验改善。GPU 目标须有所选设备的实际推理、完整输出、延迟和资源证据；Windows CUDA、Mac Metal/MPS/MLX 分别验收，CPU 对照、GPU 检测或权重加载不算完成。共享修改在另一平台未实测时明确待验收。

## 记录与文档更新

临时原始证据在 `.work/`，提交的简短结果写清代码范围、系统/架构、Python/关键依赖、设备/后端、命令、通过/失败/跳过和未验证内容。无效/失败运行保留并标明，私人录音/全文/密钥不进 Git。

[VALIDATION](VALIDATION.md) 只索引证据与边界；历史详细记录归档。未完成验收在 [ROADMAP](ROADMAP.md) 跟踪。测试方法变化改本文，行为变化改 spec，具体结果不得反复追加进 AGENTS 或架构。
