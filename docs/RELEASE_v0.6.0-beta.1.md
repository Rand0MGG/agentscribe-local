# AgentScribe 0.6.0-beta.1 · Mac 安装包预览版

新增 Apple Silicon DMG，可拖入 Applications 安装。最低声明 macOS 15，验收环境为 Apple M2 / 8GB / macOS 26.6.2。Windows 尚未构建安装包，也未实机验收本轮改动。本版使用 `v0.6.0-beta.1` 标签，发行记录见 [GitHub Release](https://github.com/Rand0MGG/agentscribe-local/releases/tag/v0.6.0-beta.1)；属于预览版，不代表正式稳定版或真实录音验收。此次 Release 仅提供 Mac 安装包；以后同一源码版本可同时提供两端安装包，也可只发布一个平台。

## 包内内容

- 原生 arm64 启动器与稳定身份 `io.github.rand0mgg.agentscribe`、麦克风用途说明、图标、统一版本信息。
- 完整 Python 3.12.15 便携发行版；桌面/课件 SDK 的 79 个依赖锁定版本与原始 wheel SHA256，保持推理依赖隔离。
- PySide6 / Qt 6.11.2 的实际使用模块、Cocoa/offscreen 插件、图像与回听组件、WebEngine 框架/辅助程序/资源/语言文件。原生文件统一为 arm64，按内到外 ad-hoc 签名。
- Node.js 22.23.0 / npm，课件安装和渲染均选择包内 Node，禁止安装态意外借用开发电脑 PATH。
- Python 内置库、Node、Qt/PySide 及 Chromium 的版权/许可、Python 包原始元数据、安装说明、依赖锁、源码和依赖哈希构建清单。

不包含模型、用户配置、密钥、录音、源代码版 venv 或本机缓存。识别/翻译运行环境与权重、Office/PDF 引擎由设置中既有按钮按需准备。大模型组件需要联网及额外空间，建议预留至少 20 GB；SDK 随包不改变 agent 默认关闭状态。

## 数据与更新

默认录音、模型、组件位于 `~/Library/Application Support/AgentScribe/`，程序资源只读。偏好兼容原 `LinguaFlow/LocalCaptions`，已指定库/模型位置保留；不自动迁移或删除开发目录。替换/删除 `.app` 不涉及用户目录。

更新检查沿用独立 Mac arm64 资产和 stable/beta 规则，beta 能收到更新的 beta 和稳定版。实际升级需下载下一版 DMG，结束录音并退出旧程序后手动替换 `.app`；没有自动下载/自替换。源码分支的新提交不等同于新的安装包发行。

## 签名与许可

本包为 ad-hoc 签名，没有 Apple Developer ID 和公证。网络下载后的 Gatekeeper 拦截需用户在系统设置中单独确认；不移除隔离标记，不关闭系统安全保护。应用源码尚未指定开源许可证；第三方组件保持各自许可。正式签名/公证（若选择）、真实音频和其他机器验收仍为后续工作。

## 复现构建

在 Apple Silicon Mac 安装源代码的 `[dev,knowledge]` 桌面依赖；需 Apple Command Line Tools（仅构建机器需要）。

```bash
.venv/bin/python scripts/build_macos.py --fetch
.venv/bin/python scripts/build_macos.py
```

构建依赖的 URL/摘要位于 `packaging/macos/assets.json`、`licenses.json` 和 `desktop.lock`。产物在 `.work/packaging/dist/`，附 `.dmg.sha256` 和 `.build.json`。构建清单记录源提交、参与构建的源码是否修改和每个来源文件的哈希；无关的本机数据不计入构建源码改动，发布清单不包含本机构建目录。发行前先提交源码，再从该固定提交重建并核对源码哈希；标签、源码和安装包必须对应。

```bash
.venv/bin/python scripts/probe_macos_package.py /absolute/path/AgentScribe.app
.venv/bin/python scripts/test_no_audio.py -q
.venv/bin/python -m ruff check linguaflow scripts tests
```

探针使用隔离设置、录音库和继承的音频守卫；没有普通应用入口、真实设备枚举或采集/回听。Qt WebEngine 需要真实 macOS 窗口服务，即使渲染窗口采用 offscreen；先检测 Quartz，受限环境缺窗口服务时明确退出。不能为测试成功绕过音频守卫。

## 当前验证边界

本轮完整无音频设备回归 **681 项通过（97.68 秒）**，零原生音频导入尝试；全仓 Ruff 和差异空白检查通过。

- DMG 校验通过；只读挂载后复制到含中文和空格的目录，应用及嵌套组件的严格签名检查通过。测试过程不安装到用户 Applications，也不替换正在运行的程序。
- 在只有系统工具的 PATH 下，原生启动器、包内 Python/Qt/Node/npm、真实独立 venv 和 pip 检查通过；NumPy/SciPy 数值计算与合成 PCM 重采样通过。
- 用独立偏好/文件库启动真实样式的窗口，未创建音频会话或模型预热；生产网页子进程实际输出 PNG，下一版 Mac beta 的更新产物选择通过。
- 生产课件安装器在隔离数据目录首次联网安装 LibreOffice Kit 0.1.3，能力检查和公开许可的 PPT 样本渲染通过，不借用本机已有课件组件。
- 生产运行环境安装器使用包内 Python，在隔离用户目录全新建立 MLX 和 WLK 环境；依赖校验及真实 2×2 Metal / MPS GPU 运算通过，未加载权重。MLX 0.32.2、MLX-Audio 0.5.6、Transformers 5.19.0 与 WLK 的 PyTorch/torchaudio 2.11.0、Transformers 4.57.6 保持独立。本轮 WLK 第一次下载因 PyPI 临时未返回候选失败，正常重试通过；没有更换固定版本。推理组件保持已有根版本约束，没有把它们误称为完整传递依赖锁定。
- 本地 ad-hoc 签名完整性通过；Gatekeeper 安全评估仍拒绝此未公证包，不能将签名完整性等同于 Apple 已认可发行。

实际日志、截图及 JSON 证据在 `.work/packaging/`。开发诊断若直接运行包内 Python，需保留启动器的 `PYTHONDONTWRITEBYTECODE=1`；向签名包写入临时字节码缓存会破坏资源封印。应用启动器和正常准备子进程已经设置此项；不要在程序包中安装、升级依赖。

关键证据为 `full-tests.log`、`final-build.log`、`final-installed-copy.json`、`installed-probe.log`、`runtime-install-probe.log`（含首次失败）、`runtime-install-retry.log` 与 `probes/runtime-nq5q3kgb/result.json`。小型 GPU 运算只证明新环境的依赖和设备可执行，不是安装版识别准确率、字幕链路或内存压力验收。

本轮不访问用户正在录音的设备，不替换正在使用的程序。麦克风权限弹窗、真实采集/回听、网络下载后的新机器 Gatekeeper 流程、其他 Mac/较旧系统及安装版长会话仍待验收。此前 MLX / Apple GPU 与 HY / Metal 的文件实测属于已有源码链路证据，不能冒充这一安装包的新机器完整验收。
