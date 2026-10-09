## 2026-10-09 安装包之前的共享运行基础

环境：Windows 11 x64、桌面和既有 WLK Python 3.12.8；基于 `windows` / `813c134` 的共享运行基础改造。本节记录提交前的本地验证，提交与推送以 Git 记录为准；未制作 EXE/DMG、改动系统 Python、升级现有环境或下载识别权重，未合并或发布。

- 硬件：`python -m linguaflow.hardware` 本机通过；模拟覆盖无 NVIDIA、驱动不足、Volta/Pascal、混合显卡、Windows ARM64、Mac Intel/Rosetta 与原生 arm64。门槛固定为当前 PyTorch 2.11 / CUDA 12.8 的计算能力 ≥ 7.5、驱动 ≥ 570.65；依据 [PyTorch 构建范围](https://dev-discuss.pytorch.org/t/dropping-volta-support-from-cuda-12-8-binaries-for-release-2-11/3290) 和 [NVIDIA CUDA 12.8 驱动表](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)。这不是对所有满足预检查的电脑承诺实时性能，准备后还执行实际 GPU 运算。
- 事务与数据：模拟 pip、GPU 检查、写入失败，验证旧环境指针及录音逐字节保留；覆盖损坏/越界指针、应用依赖版本不匹配、固定源码摘要失败、新用户外部目录与旧保存位置兼容。真实自有子进程及后代模拟下载，取消后全部关闭输出管道、线程退出，已下载部分保留。环境切换不结束活动会话，下一次使用新解释器；核心导入约束覆盖共享安装/更新模块，GPU 库仅在独立检查进程导入。
- 最终完整回归：`.venv\Scripts\python.exe scripts/test_no_audio.py -q --basetemp=.work/cache/pkg-last`，**660 passed、5 skipped，128.57 秒**。覆盖有效保存位置不受不可读旧目录干扰、Whisper 缓存路径、更新检查期间的模拟录音和保存。Ruff 与 `git diff --check` 通过，测试保护报告零原生音频导入尝试。跳过仍不是平台验收。
- Whisper 收尾：原加载路径缺少缓存时会交给上游下载，上游下载校验会读取完整权重。现改为分块下载/摘要、先校验后替换，并让 worker 只传本地模型路径。模型缓存、共享 worker 和导入约束 **28 passed，1.34 秒**（`whisper-prepare-fixed`），覆盖 XDG 旧缓存及别名、空文件、缺失分片、摘要失败保留旧权重、成功替换和有效缓存不联网；缺失模型在加载/ready 前拒绝。没有真实下载 Whisper 权重，不能将文件检查当模型识别验收。
- 路径限制对照：补跑使用较长的 `--basetemp=.work/cache/pkg-readiness-with-whisper-final` 时，**3 failed、656 passed、5 skipped**；三项均为既有课件渲染测试，写入深层临时文件时报 Windows 路径错误。本机 `LongPathsEnabled=0`，未修改系统注册表或放宽断言；失败夹具保留。此次固定源码重打包已避开上游实验长文件名，但不据此声称任意长用户录音库路径或完整新环境安装已验收。
- Windows 依赖构建：直接让 pip 解压原始 Qwen 固定源码归档，复现上游实验输出的长路径故障。准备器只保留原始声明的包目录、构建文件、README 和许可证，不修改源码、不改变提交；原始归档及派生归档均校验 SHA256。使用已缓存派生归档执行 `pip download --no-deps --no-build-isolation` 与 `pip wheel --no-deps --no-build-isolation`，两份依赖的安装元数据和 wheel 均构建成功。产物在 `.work/cache/runtime-source-check/`、`runtime-source-wheels/`；未安装到现有环境。这不是全新电脑或完整依赖安装的验收。
- GPU 组件探针：`.venv-wlk\Scripts\python.exe .work/cache/runtime-probe-20261009/probe.py` 明确阻止原生音频导入，调用生产 `runtime_check.verify('wlk')`。NVIDIA GeForce RTX 5070 Ti、PyTorch **2.11.0+cu128 / CUDA 12.8** 的小型张量运算通过；没有加载 ASR/翻译权重、采集音频或评测字幕质量/延迟。
- 更新：实际只读请求 GitHub 发布接口成功，当前应用 0.5.0 返回没有新的已发布版本，未把 `windows` 分支新提交当发布。模拟覆盖平台各自最新、稳定/beta、缺失摘要、未上传/无产物、恶意 URL 和禁止降级。仅点击时检查，源码态只链接源码发行页，没有自动替换程序或数据。复核发现更新后台误占模型准备互斥，新增独立 Qt 回归修复前 **1 failed**，修复后实际延迟的替身更新检查期间仍可开始/停止模拟会话并保存字幕；安装、UI、准备/取消和更新组合 **69 passed，13.28 秒**（`pkg-isolation`）。
- Windows 界面：`AGENTSCRIBE_NATIVE_UI=1` 下运行独立 Qt 窗口，**2 passed，4.78 秒**；检查 1280×900 / 900×650 逻辑尺寸的更新入口、设置搜索和旧录音位置提示。截图在 `.work/browser/pkg-readiness-final-20261009/`，无音频访问。

待验证：macOS arm64 实际新环境准备、MPS/MLX 组件检查、共享进程树取消；全新 Windows 电脑的完整依赖安装与驱动错误；真实录音生命周期。随包完整 Python/Node、签名、安装/卸载和程序替换尚未构建，不能称为独立安装包支持。新默认录音在独立用户目录；项目内旧录音不自动搬移，界面提醒清理项目之前备份，未来卸载器不得把它们当缓存删除。

## 2026-10-09 取消模型加载时的断管清理

环境：Windows 11 x64、Python 3.12.8，既有 `windows` / `f8e830a` 之上的共享清理修复；没有新增依赖或修改模型、音频设备与录音格式。

- 远端基线：[Code checks 37904804596](https://github.com/Rand0MGG/agentscribe-local/actions/runs/37904804596) 的 9 个任务有 8 个通过，Windows 四个任务全部通过；仅 macOS arm64 / Python 3.13.15 全库失败。失败项为 `test_stop_cancels_model_loading_without_waiting`，取消加载后误报 `会话模型释放失败：[Errno 32] Broken pipe`；该任务 **1 failed、585 passed、20 skipped，97.49 秒**。日志保留在 `.work/cache/mac313-ci-20261009/failed.log`，没有把此结果当作整组通过。
- 根因与边界：`PreparedWorker.close()` 已终止并等待自有进程退出，关闭 stdin 时仍会冲刷缓冲中的会话设置；接收端已经退出，此时 BrokenPipeError 属于预期清理。旧代码让该异常越过关闭循环，误报释放失败并跳过 stdout/stderr 关闭。现在只在已退出进程的 stdin 关闭处处理 BrokenPipeError，其他异常继续传播，且输入管道出错仍关闭输出/诊断管道；重复调用可完成清理。共享实现供两端使用，没有新增 Mac 专属流程或放宽原测试断言。
- 确定性回归：标准库真实 TextIOWrapper / BufferedWriter 包裹故障注入原始流，保留尚未冲刷的设置，再关闭已退出的进程。分别覆盖 BrokenPipeError 和非断管 EIO 错误；修复前 **2 failed**，修复后验证预期断管不报错、EIO 原异常继续传播、三条管道全部关闭、重复清理成功。此为故障注入，不冒充 macOS 实机重现。
- 取消、停止、超时、进程复用与模拟 PCM 保存：`.venv\Scripts\python.exe scripts/test_no_audio.py -q tests/test_runtime_preparation.py tests/test_wlk_session.py --tb=short --basetemp=.work/cache/mac313-fixed-b49`，**36 passed、1 skipped，8.64 秒**；跳过的是 Mac MLX helper 检查。
- 完整无音频回归：`.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short --basetemp=.work/cache/mac313-full-c6a`，**609 passed、5 skipped，128.07 秒**，零原生音频导入尝试。Ruff 与 `git diff --check` 通过，跳过不视为通过。

以上修复后的结果为本地 Windows Python 3.12 验证；macOS Python 3.13 必须由修复后的新提交 CI 复核。未在本机访问真实音频设备、加载 GPU/MLX 模型或调用云端；无音频检查不能替代真实录音、取消/停止、保存/回听与退出清理的设备验收。

## 2026-10-09 Beta 默认关闭与 Windows CI 编码修复

环境：Windows 11 x64、Python 3.12.8，既有 `windows` / `00a17cf` 之上的未提交工作。新增体验开关默认关闭；本轮未新增依赖、读取密钥或访问音频设备，也未提交、推送、合并或发布。

- Beta 隔离：独立 Qt 进程验证缺失设置默认关闭、开启/关闭后重开窗口仍保留选择；关闭时隐藏入口、拒绝课程打开与旧录音的自动笔记许可，不读取 Qwen 课程上下文。模拟开始/停止仍保存原文和译文。开启后使用实际课程子进程保存审核术语，再关闭开关，确认面板隐藏并清空视图、自有进程和读写线程退出、旧代次消息无效，课程与录音关联文件逐字节保留。13 组偏好值覆盖损坏/非法设置不能误开启；Beta 开关不授予课件或笔记上传许可。
- 真实窗口：`.venv\Scripts\python.exe scripts/test_no_audio.py -q tests/test_beta_features.py --tb=short --basetemp=.work/cache/beta-ui-96a`，**2 passed，5.31 秒**。测试子进程使用 Windows Qt 平台、`QT_SCALE_FACTOR=1.25` 额外倍率；检查开启/关闭后的主窗口、1200×800 与 900×700 逻辑尺寸的常规设置，设置无横向滚动，截图文字/开关无遮挡。四张截图保留在 `.work/browser/beta-features-20261009/`；未枚举音频设备或启动真实推理。
- CI 根因：用户报告的 [Code checks 37901440295](https://github.com/Rand0MGG/agentscribe-local/actions/runs/37901440295) 对应 `00a17cf`；失败的是 Windows 3.11/3.12/3.13 全库与 Windows 可选 SDK 四个任务，重复失败的是同三条课程 UI/worker 测试。课程后台原先没有固定标准输入/输出编码，西文 Windows 编码下中文协议消息导致错误或退出。使用 `PYTHONIOENCODING=cp1252` 复现同一 UI 失败；在修复前新增实际子进程编码回归为 **1 failed、1 passed**，西文分支稳定失败。`serve()` 现在在启动读线程前明确设置两端 UTF-8，不依赖控制台语言，也不修改全局环境。测试的失败子进程清理不再用管道关闭异常掩盖主要断言。
- 修复后定向回归：在 `PYTHONIOENCODING=cp1252` 下运行 `test_beta_features.py`、`test_knowledge_ui.py`、`test_knowledge_worker.py`，`--basetemp=.work/cache/beta-ci-fixed-2e9`：**21 passed，18.43 秒**。覆盖本次 CI 的三条失败测试；连续字幕测试分别强制子进程初始 UTF-8 / cp1252，确认中文笔记完整返回。供应商使用替身，测试不发真实请求。历史 CI 日志保留在 `.work/cache/beta-ci-20261009/failed.log`。
- 最终完整回归：在 `PYTHONIOENCODING=cp1252` 下运行 `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short --basetemp=.work/cache/beta-full-71d`，**607 passed、5 skipped，129.22 秒**，零原生音频导入尝试。`ruff check linguaflow scripts tests`、`git diff --check` 通过；跳过不视为通过。

本轮验证只覆盖本地 Windows Python 3.12 和模拟录音/模型。未运行真实云端、音频采集/回听、GPU、macOS，未重新执行远程 CI；历史 macOS 检查通过不证明本轮新改动已经在 Mac 验收。已开始录音继续使用冻结的术语快照，开关关闭不改写该快照；核心录音/保存生命周期没有改动。

## 2026-10-09 审查五项修复与课程功能隔离

环境：Windows 11 x64、Python 3.12.8、既有 `windows` / 本地 `a6fe5e6` 之上的未提交工作；保留上一轮多格式实现。未升级依赖、读取密钥或访问音频设备。本轮修复不表示提交、推送、合并或发布。

- 完整无音频回归：`.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short --basetemp=.work/cache/full-fix-619`，**591 passed、5 skipped，122.13 秒**，零原生音频导入尝试；`ruff check linguaflow scripts tests` 和 `git diff --check` 通过。跳过不视为通过。
- 录音收尾：模拟 worker 在 ready 后持续报告日志但不发送 done，覆盖用户重复停止和采集自然结束；测试缩短内部期限，确认失败通知、强制终止自有进程、完整保留已写 WAV 与字幕。生产期限 180 秒，未在慢设备或长课堂实测此阈值，也未访问真实音频后端。
- 导入一致性：独立进程分别在复制新页面后、发布课程引用前、发布后直接 `os._exit(77)`。主 HTML 不变、CSS 改变；前两种仍读取旧版，发布后读取完整新版，旧图片保留，后续重导可修复未发布残缺目录。另覆盖发布异常、损坏缓存重导及无 snapshot 字段的旧材料目录。验证的是进程中断，不是断电持久性。
- 网页布局：真实 Qt CPU 渲染 fixed / sticky 栏，横纵共六个分片；正文中间标记、右下角标记和栏内内容均保留，旧网页布局版本明确拒绝。HTML 会将固定栏放回静态排版，不保证原互动页面的全部状态或任意复杂网页。
- 可选组件：独立测试进程将 PATH 限定为 Windows 系统目录，模拟没有 Node。`test_knowledge_formats.py -k real_offline_import --basetemp=.work/cache/no-node-c67`：**15 passed、8 skipped、10 deselected，12.06 秒**；图片、网页、文本继续运行，Office 渲染跳过。另有夹具回归模拟 `document_renderer()` 抛 RuntimeError。
- 缓存资源：使用审查时相同的生成 TXT、10×10 PNG、已完成阅读的课件流程；模型为替身，重复读取不调用 API。8 页 PNG 读入 **416 → 16 次、41,184 → 1,584 字节**；16 页 **1600 → 32 次、158,400 → 3,168 字节**。修复后单次重复读取分别 0.3769 / 0.6816 秒，未测旧实现耗时或进程 RSS/显存，不据此承诺整体速度或内存收益。证据 `.work/cache/knowledge-fixes-20261009/cache-io.json` 和同目录生成探针；正式回归另断言缓存命中不重写来源数据库、不逐页发送完整视图，文件替换与新增阅读文件使缓存失效。
- 解耦：静态导入约束覆盖录音、字幕、翻译、保存到知识模块的依赖，限定为纯术语数据规则；桌面不导入课程 SDK/worker/来源数据库，课程 worker 不反向依赖实时链路。独立 Qt 进程阻止云端 SDK 导入、放入损坏课程配置、模拟课程后台异常退出，Whisper 仍能开始/停止并保存原文和已有译文。Qwen 开录继续校验它使用的冻结术语；移动/删除文件前保留自有后台释放要求。该测试不运行 ASR/翻译真模型。

课程相关定向回归另有 **97 passed，74.25 秒**。真实 DeepSeek、真实采集/回听、GPU、macOS、复杂用户课件和长会话资源仍待验收；本轮没有触发远程 CI。历史默认迁移失败见下节，本轮全库未复现，不认定其根因已修复。

## 2026-10-09 多格式课件接入（工作区试验实现）

环境：Windows 11 x64、Python 3.12.8、Node.js 24.13.0，既有 `windows` / 本地 `a6fe5e6` 之上的未提交工作。Office/PDF 复用已安装 LibreOffice Kit 0.1.3；网页/文本/图片使用已有 PySide6 的独立 Qt helper，网页 CPU 光栅化，不新增运行依赖、模型权重、浏览器下载或 DSH 插件框架。未读取密钥、请求真实供应商或运行采集、播放、音频设备及模型 GPU 测试。

| 验证 | 结果 | 证据范围 |
| --- | --- | --- |
| 最终完整无音频回归 | **577 passed、5 skipped，99.44 秒** | `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short --basetemp .work/cache/final-728af2`；无原生音频导入尝试，跳过项不视为通过 |
| 前一轮完整回归 | **576 passed、5 skipped，114.49 秒** | `.work/cache/full-a92351`，尚未加入最终原页预览 UI 回归；与最终结果分别保留 |
| 格式/原生窗口/worker 组合 | **44 passed，52.69 秒** | `test_knowledge_formats.py`、`test_knowledge_ui.py`、`test_knowledge_worker.py`；真实 Windows 窗口，`QT_SCALE_FACTOR=1.25` 为额外 Qt 倍率，860×680 和 640×540 逻辑尺寸；截图 `.work/browser/course-formats-20261009/`，无横向滚动 |
| 新增格式真实本地导入 | 23 种新增后缀通过 | DOC/DOCX/ODT、XLS/XLSX/ODS、PPT/ODP；HTML/HTM、MD/Markdown、TXT、CSV/TSV；PNG/JPG/JPEG/WebP/GIF/BMP/ICO/SVG。DOC/XLS/PPT 使用固定来源的 Apache POI 小型公开样本；其他夹具自行生成。原有 PDF/PPTX 的真实 Kit 回归继续通过 |
| 网页完整静态画面 | 通过 | 本地 CSS 图片、JS Canvas、屏幕样式和横纵溢出；实测四个分片包含页面右下角彩色标记，打印样式隐藏的内容仍可见，滚动条不造成接缝漏像素。位图/网页 PNG 目视检查；不证明真实视觉模型理解 |
| Excel 来源位置 | 通过 | 两个可见工作表，故意限制打印区域为 A1，仍渲染至 B3；保留工作表/A1/矩形/分片信息。没有新增公式重算、编辑、批注或隐藏状态读取功能 |
| 来源、取消及失败恢复 | 通过 | 有界目录资源、原件快照、图片/资源校验；主文件相同而图片变化时版本改变，旧缓存损坏可重导修复。模拟课程描述写入失败后恢复原页面、原资源和原文本缓存；取消未发布部分课件 |
| 新格式到全页模型请求的闭环 | 模拟服务通过 | 新 HTML 导入后离线预览不发请求；允许上传后，实际生成的四张 PNG 按顺序进入替身服务，全部来源校验通过后覆盖才显示完成。真实 SDK 图片传输仍由既有内存 HTTP 回归覆盖 |
| Ruff、Node 语法与差异空白 | 通过 | `ruff check linguaflow scripts tests`、`node --check linguaflow/knowledge/render_document.mjs`、`git diff --check` |

旧迁移 `WinError 5` 在上述两轮默认顺序全库回归中均未复现；本轮没有修改 `library.py` 或其迁移测试，仍不能认定已经定位或修复原根因。历史失败记录和夹具保留在下节。可选 CI 主机缺少 Kit 时明确跳过真实 Office 渲染，不把底层格式清单当应用验证；尚未推送运行两平台 CI。

许可与来源见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)，包括 DSH MIT 适配规则、独立 Kit MPL-2.0、既有 Qt/Chromium 和公开旧格式样本。使用与容量见 [WORKSPACE](WORKSPACE.md#课程资料与笔记)。真实 DeepSeek、用户课件、复杂字体/公式、动态网页交互、峰值内存、Mac 渲染和识别质量仍待验收；已生成所有静态页面不等于模型正确读懂全部内容。本轮未提交、推送、合并或发布。

## 2026-10-08 完整课件视觉读取（工作区试验实现）

环境：Windows 11 x64、Python 3.12.8、Node.js 24.13.0；既有 `windows` 分支、本地 `a6fe5e6` 之上的未提交改动，包含前一轮五项修复。安装独立 `@deepseek-ai/libreoffice-kit@0.1.3`；PDF 使用 native PDFium，PPTX 使用 native LibreOffice。组件及依赖本轮约 197 MiB，不含下载缓存；这是磁盘大小，未测整个渲染进程峰值内存。未读取真实密钥、调用供应商、上传用户材料、访问音频设备或运行模型 GPU。

| 验证 | 结果 | 证据范围 |
| --- | --- | --- |
| 无音频课程回归：`test_knowledge_visual.py`、`test_knowledge.py`、`test_knowledge_api.py`、`test_knowledge_worker.py` | **60 passed，18.49 秒** | 全页覆盖、空文字/空白页、逐页缓存与取消续读、许可撤回、原件变化、损坏图片、长解读摘录与完整来源保留、后续引用修订 |
| 实际 Kit 渲染 | PDF / PPTX 各三页通过，包含无文字图形页、空白页，渲染缓存复用 | 自编有效夹具；实际页面图像目视检查；PPTX 文字和简单公式清晰、PDF 三角形可见。未验证用户课程字体、复杂公式或视觉模型理解 |
| 实际 ChatDeepSeek / Deep Agents SDK | 模拟 HTTP 请求通过 | PNG 的实际字节进入 user `image_url`，超过 12 页可按页数处理；图片单独计费预算、8,192 页面输出上限、多轮原页重读、图片许可撤回及 SDK 截断异常拒绝。没有请求真实 DeepSeek |
| Node 子进程取消 | 通过 | 生成的替身 converter 启动自己的子进程；取消后 dispose 等待其退出、清理临时渲染目录。实际 Kit 正常完成路径已验证；未强杀用户进程 |
| 真实 Windows Qt 窗口 | **2 passed，3.56 秒** | 125% 缩放、860×680 / 640×540；原页、页数状态、来源标注与无横向滚动。截图 `.work/browser/course-visual-20261008/`；模型解读为测试生成数据 |
| 课程与录音库组合回归 | **82 passed，23.30 秒** | 上述课程核心/API/worker 测试及 `test_knowledge_ui.py`、`test_library.py` 同进程顺序运行，包含 SDK/Qt/实际渲染；无原生音频导入尝试 |
| 默认顺序完整无音频回归 | **1 failed、548 passed、5 skipped，70.20 秒** | 旧 `test_legacy_migration_is_repeatable_and_keeps_originals` 在目录 rename 时出现 `WinError 5`。前一次亦为同一项失败；跳过不视为通过，不能标记全库检查通过 |
| 排除视觉与窗口测试的对照 | **532 passed、5 skipped，59.15 秒** | `--ignore=tests/test_knowledge_visual.py --ignore=tests/test_knowledge_ui.py`；同一无音频入口和新短路径临时目录。该对照不包含新视觉测试，不当完整通过证据 |
| Ruff、Node 语法、差异空白 | 通过 | `ruff check linguaflow scripts tests`、`node --check linguaflow/knowledge/render_document.mjs`、`git diff --check` |

测试均使用 `.venv\Scripts\python.exe scripts/test_no_audio.py -q`，临时目录通过 `--basetemp` 指向项目 `.work/cache/` 下新建的短目录，避免本机沙箱临时目录和 Windows 路径问题。真实窗口测试另设置 `AGENTSCRIBE_UI_PLATFORM=windows`、`QT_SCALE_FACTOR=1.25` 与截图输出目录。默认顺序失败夹具保留在 `.work/cache/vfull-afe282/`、`.work/cache/vfinal-12e1cc/`；其他工作产物均不提交。

完整回归遗留问题：`library.py` / `test_library.py` 没有改动；录音库单独 **20 passed**，课程与录音库组合 **82 passed**，但默认全库顺序两次触发上述访问错误。尚未定位持有句柄的主体或执行顺序原因，不断言是外部扫描器，也不据此盲目重试或改写迁移规则。需要后续单独排查；没有使用忽略测试的结果替代完整回归结果。

实际云端图表/公式理解、密集页内容完整性、真实费用、系统凭据写入、Mac 渲染及两端 ASR 质量仍待验收。“已读 N/N 页”只表示逐页请求和结构化结果校验全部完成。使用、容量和许可边界见 [工作区说明](WORKSPACE.md#课程资料与笔记)，组件许可见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

## 2026-10-08 五项复审修复

环境：Windows 11 x64，Python 3.12.8，桌面 `.venv`；分支 `windows`，修复基线为本地提交 `a6fe5e6`，本轮修复尚未提交。未读取真实密钥、调用真实云 API、访问原生音频或运行 GPU 推理。

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short` | **533 passed、5 skipped，62.40 秒**；无原生音频导入尝试 | 完整无音频回归，新增 17 项正式回归；跳过项不视为通过 |
| `.venv\Scripts\python.exe -m ruff check linguaflow scripts tests` / `git diff --check` | 通过 | 静态与差异检查 |
| 上传许可 | 排队后撤回许可阻止服务创建；真实框架第二轮被拦截；第一批保存后撤回许可保留该批并阻止后续调用 | 模拟模型、生成资料；未请求供应商 |
| 删除范围 | 本批未提供的有效旧笔记不能被删除，整个非法补丁回滚 | 仍保留用户编辑和章节范围保护 |
| 原件恢复 | 缺失/损坏原件均可重新导入修复，有效文本缓存不重新解析 | 测试生成的 PPTX，未操作用户课件 |
| 长笔记分批 | 六条约千字笔记分批更新，后续批次仍读取已在首批处理的新讲述；真实框架三批整理共用同一请求预算 | 检查输入与进度完整性，模拟输出不证明摘要质量或真实费用 |
| 术语快照 | 草稿读取当前关联课程的审核词表；移动草稿保留原课程归属；recording/complete/incomplete 状态保留已存快照 | 数据层和既有 Qt 闭环，不替代 Qwen GPU 参数/效果实测 |

实现与使用边界见 [设计文档 v1.4](AgentScribe_软件开发设计文档.md#132-当前实施状态2026-10-09) 和 [工作区说明](WORKSPACE.md#课程资料与笔记)。未新增依赖、设置或推理后端；真实供应商、Mac Apple GPU、Windows 实际识别与课程质量仍待验收。

## 2026-10-08 课程资料、静态上下文与来源笔记（工作区试验实现）

环境：Windows 11 x64，Python 3.12.8；分支 `windows`，基础提交 `6a41ed08db2fc8a1d11732e0a52fb736994b8d1b`，本轮修改尚未提交。未访问、枚举或播放音频设备，未下载新模型、调用真实云 API 或运行 GPU 推理。

| 验证 | 结果 | 边界 |
| --- | --- | --- |
| `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short` | 516 passed、5 skipped，58.32 秒；无原生音频导入尝试 | 包括模拟设备/模型，不能替代两端真实设备验收 |
| `.venv\Scripts\python.exe -m ruff check linguaflow scripts tests` | 通过 | 静态代码检查 |
| 固定 SDK 实际请求路径/JSON/用量与释放 | 内存 HTTP 与占位测试密钥通过 | 未读取真实密钥、未请求供应商；模拟 usage 不是真实账单 |
| Deep Agents 工具往返与越权工具拒绝 | 真实框架 + 脚本模型通过 | SDK/执行层兼容证据，不是 DeepSeek 服务质量 |
| 课件/术语/保存/后台进程/界面闭环 | 生成 PDF/PPTX、真实 Qt 与自有进程通过 | 未评价真实课程、扫描页、OCR 或视觉解析 |
| PyTorch context / MLX system_prompt | 同一审核快照传到实际适配函数，模拟模型检查通过 | 未测实际识别提升、GPU、Metal/MLX 运行 |
| 来源版本与发布 | ABA 修订、迟到保存、撤回/重开、新证据、原子引用、个人编辑、后台代次与取消通过 | 词项相关性仍可能漏掉远距离或跨语言纠正 |
| 文件管理与恢复 | 外部移动拒绝旧结果、原件/缓存校验、课程恢复与共享删除保护通过 | 不自动移动或清理用户材料/录音 |
| Windows 窗口 | 125% 缩放、640×540 窄布局与三页显示检查通过 | `.work/implementation-20261008/ui/`；未做 Mac 原生窗口验收 |

依赖安装限定桌面 `.venv`，根版本为 Deep Agents 0.7.23、langchain-deepseek 1.1.1、pypdf 6.19.0、keyring 25.7.0；未更改 WLK/MLX 环境和应用版本。许可证/Python 范围核对来自已安装分发元数据，根版本固定不等于完整传递依赖锁定。原 CI 之外新增两平台 Python 3.12 的可选 SDK 模拟检查，尚未推送运行。

M1 的 6,000 次差分与存储/耗时测量仍仅对应合成 CaptionMapper，详见 [实施状态](AgentScribe_软件开发设计文档.md#132-当前实施状态2026-10-09)。剩余验收为真实供应商/凭据、授权课程质量、Mac Apple GPU 与 Windows 设备分别实测，以及长会话总资源/预算表现。历史 GPU 数字不作为本轮新功能已通过的证据。

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

上述运行记录来自整合过程中的对应代码状态。随后调整过字幕映射、模型缓存解析和兼容代码，因此最终版本完整复测仍待完成，不能将表格等同于最终版本验收。

## 未通过的场景及保留的限制

- Whisper large-v3 反复播放同一句话 12 次的严格完整性检查失败。原版上游跨批次重复保护会重置解码段；一次缩小保护范围的实验导致后半段提交停滞，已撤回该实验。保留上游原始保护，没有声称此问题已修好。
- 101 秒不重复素材的零词错误结果出现在上述实验分支期间，该素材未触发重复保护；撤回实验后的最终版本仍应重跑，不用这一结果掩盖重复内容失败。
- Windows 上游对齐代码提示缺少 Triton，使用备用 median kernel；GPU 识别仍实际运行。没有隐藏该提示，也未把它当作所有问题的解释。
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

## 2026-10-05 Windows 预热兼容修复与启动实测

修复此前审查 `45bdd80` 发现的 P1：设备配置到达前预热 CPU ONNX Runtime，后续 CUDA 设置无法替换已经导入的包。本轮在现有 `windows` 分支复用该更新中的预热进程与租用实现，仅接入相关模块；没有合并整个 Mac 分支，也没有修改 +3 dB 后台处理或重新引入严格离线。

现在打开应用时读取当前设备快照，先选 ONNX 包再预热导入；会话开始时再次核对，CPU/CUDA 包不兼容时重建进程，兼容时保留复用。SaT 的 CUDA 选择同样参与判定；PyTorch CPU/CUDA 使用同一套包，不为此无条件重建。预热不构造模型、不访问音频设备、不修改联网环境；顺序会话之间重置 WLK 模型状态，取消和失败的进程不复用。停止后的旧 Session 不能终止新租约；空闲 30 分钟或退出释放整个进程树。

### 真实运行与性能

环境：Windows 10.0.26200 / AMD64 / Python 3.12.8 / RTX 5070 Ti；Torch 2.11.0+cu128、WhisperLiveKit 0.2.26、Qwen3-ASR 0.0.6、Transformers 4.57.6。测试使用本地 Qwen3-ASR-1.7B / CUDA、SaT / CPU、相同英文配置与 +3 dB / -1 dB 峰值保护；翻译关闭。

使用 `tests/fixtures/hello.wav`，共 5.624 秒，SHA256 `3a84f3f9f8eedb77cd09ddd2dbd5386931185d995e29df847cca6e7534674475`；经 PyAV 转成统一 48 kHz PCM。实际 `Session → AudioJournal → wlk_worker` 按 1 倍速度投递，交替测试普通启动和已完成预热，各 3 次，设置、音频及输入完整性相同。

| 方案 | 点击到识别就绪 | 点击到首条字幕 |
|---|---|---|
| 普通启动，3 次 | 13.125 / 13.907 / 13.422 秒 | 14.797 / 15.579 / 15.125 秒 |
| 预热完成，3 次 | 5.453 / 3.328 / 3.047 秒 | 7.125 / 4.843 / 4.594 秒 |
| 中位数 | **13.422 → 3.328 秒** | **15.125 → 4.843 秒** |

首次后台预热本身耗时 8.328 秒，被移到应用打开后的等待阶段；它不是消失的计算成本。表中预热在点击前已完成，不能保证用户打开应用立即点击也得到相同收益。第一次预热会话仍要加载模型，后两次还能复用部分框架缓存；不是全新进程的三次独立预热。六次输入全部投递，均得到相同完整文本、两条定稿字幕，模型与最终字幕审计匹配。素材是合成短英文，不能推广为课堂正确率或所有模型启动耗时。

测速后补充了 Windows 进程树清理。最终版本追加一次真实预热文件检查，点击到就绪 / 首条字幕为 5.328 / 6.953 秒；完整字幕与清理通过。没有将这一次替换进上表，也未重复六次主测速。

### P1、内存和资源验证

- 使用真实已安装运行库，分别在预热后运行 SaT 的 CPU/CUDA 推理，各连续两次，分句输出一致。CPU 走 ONNX Runtime 1.29.0 的 `CPUExecutionProvider`；CUDA 走隔离的 1.23.2 包，实际模型会话包含 `CUDAExecutionProvider`，不是仅检查显卡或模拟导入。历史 `offline=True/False` 输入均不改变环境，Hub 与 Transformers 未被预热锁成离线。1 项集成检查通过，23.60 秒。
- 会话结束后另行观察真实 GPU 分配：WLK 单例已重置，PyTorch 已分配约 36.5 MiB、保留约 68 MiB，识别权重没有常驻以换取启动速度。该检查 1 项通过，22.86 秒；第一次测试包装器遗漏 `--prepared` 而超时，修正后重跑，失败日志保留，不计作业务运行失败。
- Windows 虚拟环境有启动器与实际 Python 两层。补测统计整个已知进程树：仅预热后驻留内存约 0.70 GiB，识别结束并清理模型后约 2.31 GiB，进程树私有提交约 4.32 GiB。运行库、CUDA 上下文和分配器仍有显著代价，不能说停止后内存全部归还。主测速 JSON 的早期内存字段只统计启动器，不用于推理内存结论；以 `resources.json` 为准。
- 健康空闲退出与真实预热超时均确认启动器及实际 Python 子进程退出，1 项资源检查通过，25.59 秒。复用已有平台进程树清理函数；不通过枚举或终止其他 Python 进程清理资源。

### 回归与范围

- `.venv\Scripts\python.exe scripts/test_no_audio.py -q`：**428 项通过、5 项跳过，40.87 秒**。覆盖复用、CPU/CUDA/CPU 切换、忙碌时拒绝第二租约、停止后迟到调用、取消、启动失败、超时、空闲过期、两端启动参数及原录音/字幕/保存路径。静态 Ruff 与差异检查通过。
- `.venv\Scripts\python.exe scripts/test_no_audio.py -q -s .work/cache/runtime-startup-20261005/test_measure.py`：1 项通过，112.07 秒。另运行同目录 `test_runtime_integration.py`、`test_resources.py`、`test_gpu_release.py`；全部完成且未发现原生音频导入尝试。完整测试曾因 UI 模拟构造器未接收新参数、进程启动模拟器误拦截清理命令而失败，修正模拟接口后重跑，未放宽原有断言。
- 全部产物保存于 `.work/cache/runtime-startup-20261005/`：测速 JSON、逐次事件/参数/字幕、SaT 探针、实际进程树内存、显存释放、脚本及失败日志。主测速对应的预热/会话代码另保留于 `measured-code/`，原先未提交版本备份于 `before/`。不下载模型或升级依赖。
- 此次未进行真实采集、播放、音频设备枚举、翻译链路性能、Whisper 启动性能或 Mac 实机测试；Mac 模拟分支测试不替代 Mac 验收。改动仅本地完成，未提交、推送、合并或发布。

## 2026-10-05 简化音频处理、CPU 分句与清理复核

此节记录同日后续改动，替代上一节中的 SaT 设备选择、CPU/CUDA 包切换和独立普通启动入口。原测速及失败日志作为历史证据保留。本轮仍在本地 `windows` 分支，保留已有未提交工作；未提交、推送、合并或发布。

### 最终行为

- 音频处理只保留连续重采样、固定 +3 dB 增益和 -1 dB 峰值保护，原始录音不变。删除音频实验室剩余实现、降噪、去混响、均衡、自动增益、预设及对应安装/实验脚本；旧增强配置读取时忽略退役字段。
- SaT 与语音活动检测固定使用 CPU ONNX Runtime。删除 SaT 设备、前瞻和单独准备控件，前瞻仍采用原默认 3 秒；下载 / 检查识别模型或安装运行环境时一并准备分句资源，失败会明确提示。旧 SaT 设置不再影响会话。
- 桌面与文件识别使用同一准备与租用流程。应用打开后的后台预热仍保留；直接创建文件 Session 时也走此流程。取消或失败进程不复用，旧 Session 不能取消新租约，退出与空闲过期释放进程树。重复取消只触发一次进程清理。
- SaT 不再选择 GPU 包。识别和翻译仍按用户选择使用 CPU / CUDA / Apple GPU；没有删除它们需要的 Torch/CUDA 依赖，也没有改变联网行为。

### 真实推理、处理与启动验证

环境：Windows 11（10.0.26200）/ AMD64 / Ryzen 7 7800X3D / RTX 5070 Ti / Python 3.12.8；最终 CPU ONNX Runtime 1.29.0、Qwen3-ASR-1.7B / CUDA。没有访问、枚举或播放音频设备，没有下载模型。

删除 GPU 包前，以已保存的 GenAI 第五节课文本测试真实 SaT 推理，各长度预热后执行 12 次；CPU 与 CUDA 使用独立模型和进程，以下为中位数：

| 输入字符数 | CPU | CUDA |
|---|---:|---:|
| 200 | 78.13 ms | 1.25 ms |
| 800 | 192.42 ms | 1.76 ms |
| 2041 | 461.89 ms | 2.66 ms |

GPU 明显更快；CPU 对本机短字幕分句足够，但这些数据不能证明低性能 CPU 或长会话不会积压。首次 CPU 加载约 9.12 秒，包含运行库与模型初始化，不能与上表单次推理时间混同。

清理完成后，真实 SaT 与 VAD 会话均确认 `CPUExecutionProvider`；阻止实际导入 `onnx` 图编辑包时仍能运行。保留的是 `onnxruntime` 推理库；无需保留独立的 `onnx` 图编辑包。分句探针边界为 `[29]`，记录见 `cpu-models.json`。

最终文件检查使用 `tests/fixtures/hello.wav`，5.624 秒，经实际 `Session → AudioJournal → wlk_worker` 投递完整 PCM，Qwen GPU 识别、CPU 分句、最终字幕与审计通过。以下各一次，比较同一启动流程在点击前是否已完成准备：

| 准备时机 | 开始到识别就绪 | 开始到首条字幕 |
|---|---:|---:|
| 应用后台已准备 | 5.281 秒 | 6.953 秒 |
| 会话开始时准备 | 13.891 秒 | 15.594 秒 |

两次完整输出一致。此次是单对验证，不替代上一节三轮测速，也不证明课堂正确率；用户立即开始而预热未完成时仍须等待。处理检查覆盖 48 / 44.1 / 16 kHz、不规则块长度、静音、峰值、收尾与重置，输出数量和峰值与此前 +3 dB 结果相同。

### 存储、界面与回归

- 删除 SaT 隔离 GPU 包、DeepFilter 权重、三项增强专用依赖及 `onnx` 图编辑包；删除放弃的增强试验派生音频，保留文字报告与标注。文件产物审计确认减少 **754,316,653 字节（约 719 MiB）**，另有卸载的 Python 包。
- 用户选择保留 AMI、MacWhinney、SlideSpeech 下载音视频、压缩包与对应基准音频；这些资料未删除。个人录音、必要模型及固定测试素材共 85 个受保护文件，前后 SHA256 全部一致。
- Qt offscreen 页面截图确认分句设置已隐藏、现有字幕和模型页面可显示；截图位于本机 `.work/cache/cleanup-20261005/ui/`。没有进行实体窗口缩放验收。
- `.venv\Scripts\python.exe scripts/test_no_audio.py -q --tb=short`：**421 项通过、5 项跳过，44.13 秒**；没有原生音频导入尝试。删除退役功能后测试数量变化，保留会话取消、释放、保存与字幕等回归；补充自动准备分句资源及旧设置兼容检查。
- 同入口运行 `.work/cache/cleanup-20261005/test_final_runtime.py`：**3 项通过，57.91 秒**，包含真实 CPU 模型、处理检查及 GPU 文件识别启动比较。Ruff、`git diff --check`、推理环境 `pip check` 均通过。
- 证据与审计位于 `.work/cache/cleanup-20261005/`，包括 `sat-cpu.json`、`sat-cuda.json`、`cpu-models.json`、`front-end-check.json`、`final-startup.json`、`storage-before.json`、`storage-after.json`、完整测试日志及未通过的初次测试包装器日志。

尚未验证本轮代码在 Mac 的实机表现、长课堂负载、真实采集/回听、Whisper 启动或完整翻译性能。最低可用 CPU 未确定：本机分句测试不能替代完整识别与翻译负载，M1 使用体验也需注明具体后端。Mac 的 SaT 为 CPU；Whisper CPU 与 Qwen MLX Apple GPU 是不同识别路线，已有 M2 / 8GB 文件测试不能当作 M1 CPU 性能结论。

## 2026-10-06 Windows 保存修复、共享适配与 Qwen 实测

在现有 `windows` 分支检查 `59bc32b` 的更新。环境为 Windows 11 / AMD64、Python 3.12.8、PySide6 6.11.2、RTX 5070 Ti（驱动 595.79）；推理环境为 PyTorch 2.11.0+cu128、Transformers 4.57.6、Qwen-ASR 0.0.6、WLK 0.2.26、wtpsplit 2.2.1、CPU ONNX Runtime 1.29.0。没有更新项目依赖、下载模型或访问音频设备。

### 保存与适配边界

GitHub `37356634520` 的 Windows / Python 3.11.9 在后台保存 `QThread` 构造中发生原生访问冲突。仅延后 `finished` 收尾后，本机隔离 Python 3.11.9 的 80 次加强测试仍复现 1 次同位置崩溃，因此未以单次通过认定修复。磁盘写入现使用标准 Python 线程；Qt 排队信号回到界面，任务完成处理先 join，再发布保存结果和启动下一任务。线程启动失败、写入失败和超时保留原文与已有磁盘结果。收尾回调绑定会话身份并退出原信号调用栈，拒绝重复或旧会话消息。

最终保存实现的隔离 Python 3.11.9 测试：80 次独立 UI 收尾测试及 7 种垃圾回收阈值全部通过（8 个 pytest 项，150.07 秒）；最终 UI / 保存测试另有 14 项通过，13.55 秒。隔离解释器使用官方便携包与已有 ABI3 Qt，NumPy / SciPy 使用对应 3.11 二进制；这不替代 GitHub 各版本矩阵。源码回归还覆盖 100 次快速保存后无存活写线程、创建写线程失败后保留旧结果并可重试、版本合并、错误与录音锁释放。

适配审查结果：

- ASR 的低能量切窗原先位于 `mlx_asr.py`；更新已移到 `asr_stability.py`，PyTorch 与 MLX 共用确认、重叠窗口、原文修订和 SaT / 翻译流程，未保留两套平台字幕业务。
- 模型准备与运行库预热重复写的控制台 / 进程组参数改为复用 `process_platform.spawn_options()`。MLX 的独立解释器与 Metal 推理保留在专属适配中；它与受保护进程组的关系不同，不统一成另一套进程启动框架。
- Mac 预热入口不再读取已退休的 `semantic_device`，旧值为 CUDA 也不能改变固定 CPU 分句；准备失败提示指向现有的识别模型入口。
- 实测还暴露出已有 PyTorch HY 的自由 JSON 合并入口不可靠：101 秒双语测试的 20 条原文全部报 ID 映射错误。短句探针返回了带 `id/source` 的 JSON 数组，而消费者需要 ID → 译文对象。已删除这个入口，通过现有队列逐段翻译；llama.cpp 保留有 schema 约束的合并。引擎差异不按操作系统复制实现，不添加自动重试或用户开关。

### 同一文件、同一处理的识别比较

基线 `f28a2cb` 与更新 `59bc32b` 均用真实 `Session → AudioJournal → wlk_worker`，48 kHz 输入按 1 倍速度投递；Qwen 1.7B / CUDA、英文、+3 dB 与 -1 dB 峰值保护、CPU SaT、关闭翻译，模型不接触对照文本。每条路线先完成同一预热，再顺序运行 101.176 秒标准英文和 GenAI 第五课 48:01–50:56 的 175 秒片段。原音频哈希、输入采样数和模型 / 字幕修订审计均一致或完整。

| 素材 / 路径 | 开始到就绪 | 开始到首条字幕 | 就绪后首条字幕 | 停止后收尾 | 进程树峰值 RSS | PyTorch 显存峰值 |
|---|---:|---:|---:|---:|---:|---:|
| 标准英文 / 原 windowed | 9.015 s | 11.640 s | 2.625 s | 3.121 s | 5.515 GiB | 4.09 GiB |
| 标准英文 / 共享完整编码器 | 6.000 s | 7.343 s | 1.343 s | 5.996 s | 5.501 GiB | 4.38 GiB |
| 课堂片段 / 原 windowed | 3.359 s | 4.828 s | 1.469 s | 2.000 s | 6.840 GiB | 4.10 GiB |
| 课堂片段 / 共享完整编码器 | 3.391 s | 4.313 s | 0.922 s | 4.125 s | 6.955 GiB | 4.53 GiB |

标准素材为 256 个对照词：原路径多出 2 个词，WER 0.78%；共享路径 WER 0。课堂片段原 / 新路径分别为 11 / 14 条定稿、393 / 389 词，最长行 132 / 109 词；没有独立校对稿，不把词数变化或旧识别稿差异当作 WER。两条新路径最终 ASR 与分句确认字段均为真，字幕与模型原文审计匹配，没有丢失音频输入。长行仍存在，不能宣称课堂断句已完全解决。

每条路径只有一组文件测试，运行顺序为基线后更新，期间有独立 Qt 模拟回归；框架、系统文件缓存和 CPU 负载可能影响绝对耗时，不能推断统计显著加速或所有硬件表现。结果支持这台 GPU 上保留统一窗口与既有预热；代价是课堂显存增加约 0.43 GiB、收尾增加约 2.13 秒。真实采集、回听、长课堂与其他 CPU / GPU 未验收。

### 连续双语、等待门与保存导出

删除 PyTorch 自由 JSON 批量后，101 秒英文文件能完成 20 条译文，但首条译文仍在开始后 112.469 秒才出现，晚于文件输入结束。日志确认 HY 已提前加载；持续输出、原文修订与心跳在等待字幕锁时也增加“正在更新”计数，连续任务使翻译门长期关闭。现在只在持有字幕锁并实际更新时关闭门；正在运行的推理仍保留版本校验，不通过忽略原文变化修复等待。

最终同一文件、Qwen 1.7B / CUDA、HY 1.8B / CUDA、SaT / CPU 实测：就绪 5.453 秒，首条原文 7.625 秒，首条译文 24.703 秒，录音进行中持续发布译文；停止后收尾 8.246 秒，PyTorch 显存分配峰值 7.55 GiB（不含驱动）。HY 权重就绪诊断在开始后 7.312 秒，加载本身 1.797 秒；诊断包装器只记录阶段，不参与推理。首译还受原文和分句确认策略影响，不能称为立即翻译。20 条均完成最终翻译，原文 WER 0、修订审计匹配、译文来源与当前原文一致；真实 `Library.save/load` 往返与 20 条双语 SRT 导出通过。

新增模拟回归制造字幕锁的活动任务与等待任务，要求活动任务计数为 1 且停止前收到译文；替换回原 `_serve` 时回归拒绝旧计数。没有新增用户开关、自动重试或平台独立翻译队列。本测试只证明此文件和这台机器的双语链路，不证明课堂译文质量或其他硬件性能。

### 回归与证据

- `.venv\Scripts\python.exe scripts/test_no_audio.py -q`：474 项通过、5 项跳过，44.99 秒；没有原生音频导入尝试。
- `.venv\Scripts\python.exe -m ruff check linguaflow scripts tests`、`git diff --check` 通过。500 段历史回归继续验证背景上限；PyTorch 相邻请求现在各自只传本段原文和所选邻段，llama.cpp 的 schema / 批量解析校验保持。
- 本机证据在 `.work/cache/github-fixes-20261006/`：`comparison.json`、环境与音频 manifest、逐次事件及修订审计、真实 HY 格式探针、保存加强测试与模拟测试日志。个人课堂音频及完整识别结果不提交 Git。

## 2026-10-06 统一识别与 SaT 启动

本轮基于现有 `windows` 的 `2bdf096`，沿用上一节 Windows 11 / AMD64、Ryzen 7 7800X3D、RTX 5070 Ti、Python 3.12.8 及推理依赖。目标是减少 Mac 独立业务代码：原先只有 Mac / MLX / 已有 SaT 缓存的组合使用并行初始化，SaT 缓存也按系统名称排除了 Windows。现在两者分别使用一份共享实现，不新增用户设置、安装环境或依赖。

### 共享边界与失败处理

- 新的 `inference_startup.load_components()` 只依赖标准库，协调识别与 CPU SaT 的同步加载工厂，在后台并行执行；两者成功后才创建音频处理 / VAD 和流式任务。保留既有 float32 VAD 保护，避免在 Transformers 临时修改 Torch 默认 dtype 的加载阶段创建检测状态。
- `wlk_worker.py` 为 PyTorch Qwen、MLX Qwen 和 Whisper 装配同一个协调器。MLX 在阻塞加载握手前登记客户端；成功、模型错误、SaT 失败、取消及后续会话初始化失败均关闭自有客户端，再等待加载任务结束。取消后迟到的资源立即关闭；进程内加载无法通过取消 Python 线程中断，仍由既有父进程启动期限 / 进程树清理兜底。
- 删除 `begin_mlx_loading`、Mac 后台加载线程、就绪事件 / 错误状态、`wait_ready` 和预加载客户端参数。MLX 适配仍负责隔离解释器、协议、GPU 确认、请求超时与关闭进程；模型格式和实际推理后端保持独立。没有复制字幕、翻译或保存链路。
- SaT 缓存删除系统门控，支持兼容 CPU ORT 运行库；Windows 1.29.0 已实测，Mac 保留既有 1.30.0 路径。身份格式未变，仍按运行库、架构和本地原始权重隔离；没有完整兼容缓存时沿用原 ONNX。监听期间不转换图，不掩盖实际损坏错误。

### Windows 真实缓存与课堂文件对照

先用现有 VAD 小图验证安装的 CPU ONNX Runtime 1.29.0 会执行 mmap 加载，原生日志确认映射初始化权重；随后通过实际生产路径生成完整 SaT 缓存、加载并推理。缓存为 **428,589,904 字节，约 409 MiB**，原始权重 SHA256 前后保持 `8573277b4dbea9c5fb1b4cfd8c21e5aa628069ac8258d1342ba664e1b64ada6d`。实际 provider 为 `CPUExecutionProvider`。固定 GenAI 第五课文本的 42 个重叠窗口及中英文短句共 44 项，缓存 / 原 ONNX 的原文偏移边界全部一致。缓存生成需要额外磁盘空间和一次准备开销；准备发生在点击开始之前，不计入下表的启动耗时。

两条路线先完成相同的运行库预热，再按“基线、共享、共享、基线”回放 GenAI 第五课 **48:01–48:41** 的 40 秒片段。基线从 `2bdf096` 加载原 `wlk_worker.py`、`semantic_model.py`、`semantic_cache.py`，保持其他 Windows 识别代码相同；共享路线使用本轮生产实现。两边均为 Qwen 1.7B / CUDA、CPU SaT、英文、固定 +3 dB / -1 dB、关闭翻译，真实 `Session → AudioJournal → wlk_worker`，48 kHz 输入按 1 倍速。两组预热进程在测量前均就绪，第二次使用各自同一进程；记录模块哈希和仅负责阶段计时的包装器哈希。

| 顺序 / 路线 | 开始到就绪 | 就绪到首条字幕 | 停止后收尾 | 自有进程树峰值 RSS | PyTorch 分配峰值 |
|---|---:|---:|---:|---:|---:|
| 1 / 原串行、原 ONNX | 9.172 s | 1.344 s | 3.672 s | 5.657 GiB | 4.38 GiB |
| 2 / 共享并行、缓存 | 5.250 s | 1.422 s | 3.672 s | 5.184 GiB | 4.38 GiB |
| 3 / 共享进程复用 | 3.062 s | 0.922 s | 3.688 s | 6.516 GiB | 4.51 GiB |
| 4 / 原进程复用 | 3.359 s | 0.922 s | 3.640 s | 6.929 GiB | 4.49 GiB |

阶段日志确认共享路线的 SaT 与 ASR 加载区间重叠，基线不重叠。四轮均完整投递 1,920,000 个样本，最终 5 行 / 94 词，最终文字一致，零错误、修订审计匹配。没有独立校对稿，因此一致性不等于课堂 WER 或准确率证明。每条路线只测两次，首次还包含按需导入与不同的文件缓存状态；不能把首次差值全归于并行，也不能承诺固定加速比例。上述 RSS 是工作进程及其子进程，不是全系统内存；显存为 PyTorch 分配口径，两个复用进程的峰值也包含各自此前运行状态，不包含驱动。

### 完整双语与回归

最终生产代码另用 101.176 秒标准英文文件，Qwen 1.7B / CUDA、HY 1.8B / CUDA、SaT / CPU、同一后台处理，投递 4,856,466 个样本。就绪 5.187 秒、首条原文 9.453 秒、首条译文 24.593 秒、停止后收尾 10.121 秒，显存分配峰值 7.54 GiB。20 条原文与译文全部定稿、来源版本一致，原文 WER 0（256 个固定对照词）、修订审计匹配；实际 `Library.save/load` 往返和 20 条双语 SRT 导出通过。这是链路正确性检查，单次耗时不能与上一节单次结果构成稳定性能结论。

- `.venv\Scripts\python.exe scripts/test_no_audio.py -q`：**477 项通过、5 项跳过，47.49 秒**；Ruff 与差异格式检查通过。覆盖两端模拟调用、三个识别后端的装配、并发就绪、阻塞 MLX 握手、加载失败、取消、迟到资源、前端失败和既有翻译 / 保存。SaT 必需性回归改用有效配置并模拟推理依赖，继续断言失败时不接受音频、不 ready、不发布字幕；初次失败的旧测试传空配置，不能用于新的装配顺序，没有放宽保护断言。
- 真实缓存准备：1 项通过，27.76 秒；44 个边界一致性对照：1 项通过，26.59 秒；四轮课堂回放：1 项通过，214.57 秒；最终双语回放：1 项通过，126.82 秒。均从 `scripts/test_no_audio.py` 入口运行，零原生音频导入尝试。
- 证据位于 `.work/cache/shared-startup-20261006/`，包含源码基线、阶段日志、逐轮 manifest / 事件 / 修订审计、RSS、`comparison.json`、`sat-prepared.json` 和 `sat-boundary-parity.json`；最终双语产物在 `.work/cache/github-fixes-20261006/shared-startup-final/`。缓存及个人课堂材料不提交 Git，没有下载模型、升级依赖或改动原始录音。

本轮没有 Mac / Apple GPU 实机验证、Whisper 真模型验证、真实采集 / 回听、低性能 CPU 或长课堂压力测试。共享装配和受控 MLX 管道测试不能替代这些验收；旧 Mac 实测只证明当时的代码。应用打开时仍只预热运行库，权重在会话开始后加载；设备、联网、识别窗口及翻译参数未改变。
