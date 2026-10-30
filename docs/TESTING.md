# 测试规范

测试保护用户可观察的结果和 [spec](specs/README.md) 的约束。纯文档修改核对事实、引用和差异；不必启动应用或模型。历史结果见 [VALIDATION](VALIDATION.md)，不在本页维护容易过期的通过数。

## 测试重要程度

按失败后果分级，不按文件名、耗时、是否使用替身或界面类型判断。

| 等级 | 保护范围 | 典型场景 |
| --- | --- | --- |
| P0：安全与重大损失 | 用户数据、隐私、系统与授权边界 | 原件误删/覆盖、路径越界、误杀进程、未授权上传/付费、不可信更新执行 |
| P1：核心流程 | 录音→识别→分句→翻译→保存，以及启动/退出 | 音频遗漏、字幕或译文错配、停止卡死、保存失败后的恢复 |
| P2：独立功能 | 不阻断核心流程的独立能力 | 搜索、回放定位、导出格式、课件解析、诊断日志容量与查询 |
| P3：使用体验 | 功能和结果正确，主要影响展示与便利性 | 排版、动画、非关键文案、轻微卡顿 |

每个 pytest 用例在函数上显式标注一个 `@pytest.mark.p0` 至 `p3`，不对混合文件统一打标。`tests/conftest.py` 在筛选前拒绝漏标、重复或继承式统一标记；`--strict-markers` 拒绝拼错的标记。默认按 **P0→P1→P2→P3** 稳定排序并执行全部用例，等级内保留收集顺序；`-m p0`、`-m "p0 or p1"` 仅用于明确的局部验证，不能代替完整回归或绕过漏标检查。

按具体失败路径定级：已有文件被破坏是 P0，导出内容错误通常是 P2；模型准备阻断首次识别是 P1，可选模型不可用通常是 P2。不能因极端假设随意升为 P0。诊断内容泄露是 P0，日志体积/边界关联是 P2，日志写入导致录音线程阻塞则是 P1。

不同独立职责应拆分，例如导出格式与防覆盖、草稿保护与控件状态。正常流程中必要的原件保护、释放及退出断言应保留上下文，按主要风险定级。P2/P3 不等于可删；精简必须指出替代覆盖或明确退役的范围，不按相似名称删除取消、迟到结果、版本 ABA、平台和权限边界。

独立 Node/模型/设备脚本不由 pytest 收集，不能用 `-m` 筛选：Electron 流程及真实 ASR/翻译探针主要覆盖 P1，交互/评测辅助覆盖 P2/P3，路径、设备阻断、原件及升级信任保护属于 P0。执行范围见对应脚本与下文；分级不授予设备、联网或付费权限。

## 默认安全入口

macOS 使用 `.venv/bin/python`，Windows 使用 `.venv\Scripts\python.exe`，参数相同：

```bash
.venv/bin/python scripts/test_no_audio.py --collect-only -q
.venv/bin/python scripts/test_no_audio.py -q -rs
.venv/bin/python scripts/test_no_audio.py -q -m "p0 or p1"
.venv/bin/python -m ruff check linguaflow scripts tests
git diff --check
```

可追加测试路径缩小范围。入口对当前及继承环境的 Python 后代阻断原生音频导入，使用合成 PCM/设备替身；不枚举设备、采集、播放、改变音频设置或中断用户进程。原生 GUI、进程列表和本地回环服务可能需要相应系统权限，受阻应说明，不能改成假流程或跳过换绿。真实设备、文件模型推理、联网与云端调用另按用户授权执行。

开发默认 Python 3.12，兼容版本以 `pyproject.toml` 为准。正式运行/Qt-free 检查安装 `.[dev]`；完整旧界面对照还需 `.[dev,legacy-qt]`。保留 pytest 正常临时路径、中文/空格/深目录边界；不得通过全局缩短路径掩盖问题。优先复用现有依赖，不因文档审查安装模型或改变机器设置。

## 按改动选择验证

| 改动 | 必要验证 |
| --- | --- |
| 纯逻辑/缺陷 | 修复前反例，修复结果，相关失败/取消/迟到边界 |
| 保存/路径/迁移 | 原件字节、旧回执、写失败、原子性、锁、损坏输入与真实映射权限 |
| 异步/资源/启动退出 | 活动任务中关闭、重复取消、实际退出与线程/进程释放、事件循环响应 |
| ASR/分句/翻译/DSP | 同输入基线、完整链路与原文/译文对应；真实质量和性能另验 |
| 广泛共享改动 | 完整无音频回归、静态检查；平台模拟后补目标系统实测 |
| 课程 SDK/渲染 | 实际引擎内容与资源解码、许可、取消与释放；替身证据单列 |
| 打包/更新 | 封存包、签名、原生升级/恢复与数据兼容，见 [RELEASING](RELEASING.md) |

常用定位：`test_capture_control.py` / `test_wlk_session.py`、`test_recording_*.py`、`test_translation_*.py` / `test_qwen_*.py`、`test_knowledge_*.py`、`test_desktop_service.py` / `test_shared_desktop_workflows.py`、`test_packaging.py` / `test_update_*.py`。选择以实际调用关系为准，不要求每次运行无关模型。

## 通过条件与 CI

- 断言结果和安全边界，不镜像实现。不能靠生产测试专用分支、吞异常、放宽断言或删除失败测试换绿；替身留在测试侧。
- 完成/取消需要实际终态和有期限的等待；`close()` 被调用不等于退出，目录存在不等于原件未损坏。失败后回收本次自有资源，不处理其他应用。
- 旧 Qt 用例使用 `tests/ui_support.py` 隔离进程及统一退出/日志检查，拒绝绘制回调和 QPainter/QThread/QProcess 销毁错误。布局稳定与业务完成分开判断；固定短等待不能代替状态条件。跨进程中文使用明确 UTF-8。
- 图片检查真实解码与资源尺寸，页面检查实际内容；截图文件存在不是视觉验收。自动回归保留流程与必要布局边界，纯外观细节按 [UI_DESIGN](UI_DESIGN.md#demo-一致性与优先复用) 人工核对，不恢复已退役的像素/文案枚举。
- `.github/workflows/checks.yml` 是执行矩阵权威：Windows/Mac、Python 3.11–3.13 完整无音频回归；课程 SDK、原生文档渲染与 Electron 分别验证。P0–P3 均运行；专用集成设置 `AGENTSCRIBE_REQUIRE_INTEGRATIONS=1`，选中用例有跳过即失败。
- 普通 Python、SDK 和文档渲染任务先准备并构建 Electron，`AGENTSCRIBE_DESKTOP_PYTHON` 指向 `setup-python` 输出，不假定存在 `.venv`。改此前置流程时，在无 `.venv` 的隔离源码验证构建及真实本地图片预览；不能只检查 YAML。
- 普通回归列出跳过原因；本地通过、平台模拟、远程 CI、真实设备及安装升级分别报告。记录输入、代码和依赖版本，不能用一次通过数证明全部验收。

## 诊断与性能

日志事件与保留规则分别见 [架构](ARCHITECTURE.md#诊断日志) 和 [使用指南](WORKSPACE.md#诊断日志与问题反馈)。相关测试集中在 `test_diagnostic_log.py`、`test_diagnostic_archive.py`、`test_resource_monitor.py`，并联同 Session、Qwen、字幕与翻译回归验证：

- decode→source version→mapping/SaT→task→publication 的关联、确认原因、完整边界分块和取消/拒绝终态；不保存原文、译文或异常正文。
- 无变化的缓存轮询不落盘；时间达到翻译门槛、确认/收尾、真实计算与异常仍留证据。
- gzip 解压逐字节一致、8 MiB UTF-8 分块、共享压缩容量、活跃文件排除、多个旧块淘汰、退出尾部、失败恢复、双进程竞争及无关文件/链接保护。
- 慢盘/队列溢出、采样超时/恢复与资源释放；局部压缩计时不代表实际录音吞吐。

容量估算应注明样本时间范围、新录音实测或旧日志格式投影，按实际压缩字节计量。ASR/翻译评测固定输入、模型、环境和对照，保留完整输出与无效运行；采用原速连续会话，不按答案句界切音频，不择低报告。协议见 [AMI](testing/AMI_BENCHMARK.md) 和 [评分](testing/SCORING_SYSTEM.md)。真实 GPU/设备结果不能用替身或缓存探针替代。

## Electron 正式入口

在 `desktop/` 执行；探针使用隔离库、偏好、profile 和音频保护，不访问用户现有录音或设备。

首次打开录音的 IPC 回归必须使用全新后台子进程，在 stdin 保持打开且无后续输入时等待合成 WAV 的时长回执，再验证关闭和原件不变。提前在测试进程导入 NumPy、一次性发送全部请求或立即关闭 stdin，不能覆盖 Windows 首次原生模块加载与协议读线程的阻塞冲突。对应 `test_qt_free_backend.py::test_first_wav_open_with_idle_stdin_and_clean_shutdown`。

| 命令 | 证据范围 |
| --- | --- |
| `npm ci`、`npx install-electron --no`、`npm run build` | 锁定依赖与 Electron、TypeScript/Vite 构建；Python 路径见上文 |
| `npm test` | 原生窗口基础流程、平台与辅助进程退出、IPC；需要登录图形会话 |
| `npm run test:chain` | renderer→preload→IPC→DesktopService→共享后台的真实回执；下载/云端使用执行边界替身 |
| `npm run test:interaction` | 菜单、编辑、搜索、字幕修订/交接、650 条历史回放定位；不输出音频 |
| `npm run test:audio-adapter` | 正式音频 preload 的无设备适配器：迟到就绪、暂停/定位、失败和释放 |
| `npm run test:migration` | 历史迁移交互对照；正式入口始终是 Electron |
| `npm run components` | 按需组件演示，不能替代正式流程验收 |

Python 的 `test_qt_free_backend.py` 在拒绝 Qt 导入的条件下验证后台、设置迁移、竞争锁与退出；`test_playback_controller.py` 验证合成 WAV 的 HTTP 范围读取、旧代次拒绝及原件保护。Node 音频适配器由独立入口验证，不再通过 Python 包装重复运行。Qt 仅作为保留行为的对照及部分图像夹具，不进入正式依赖或安装载荷；不能仅因测试使用 Qt 就删除其独有保护。

共享保存、迁移、准备或退出修改需完整无音频回归及 Electron `test:chain`、`test:interaction`、`test:audio-adapter`。原生探针等待窗口和记录的自有辅助进程实际退出；不能终止其他实例或强制卸载映像掩盖退出问题。

按需外观对照使用 `scripts/preview_parity.py --capture`、`node desktop/scripts/parity.cjs` 和 `scripts/compare_desktop_ui.py`，同主题、尺寸、内容及动作核对。截图任务不并行争用焦点；记录实际窗口尺寸和 DPR，不把系统尺寸舍入或截图生成当作业务通过。

封存包探针可通过 `AGENTSCRIBE_PROBE_RESOURCES`、`AGENTSCRIBE_PROBE_ELECTRON`、`AGENTSCRIBE_DESKTOP_PYTHON` 指定包内资源、Electron 和 Python，同时设置 `AGENTSCRIBE_PACKAGED=1`、`AGENTSCRIBE_RESOURCES`、`PYTHONDONTWRITEBYTECODE=1`；`AGENTSCRIBE_PROBE_EVIDENCE` 区分包与源码证据。原生启动存活回归仅终止自建启动器，核对所属 Electron/后台退出；Windows 与 Mac 都需实际平台结果，不替代真实录音和安装升级。

## 证据与维护

临时证据放 `.work/` 或 `output/playwright/`，私人全文、音频、模型与密钥不进 Git。当前规则留在本文，精确运行结果留在 [VALIDATION](VALIDATION.md)，历史审查见 [2026-10-23 报告](testing/TEST_CODE_REVIEW_20261023.md)。历史报告的待办按当前源码复核，不直接当作仍存在的问题。
