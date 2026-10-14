# 安装与使用指南

本文描述当前源码操作；旧安装包以其发行说明为准。平台证据见 [VALIDATION](VALIDATION.md)，核心功能准备后可断网使用。

## 安装与首次准备

### Mac 安装包

从 [beta.2 发行页](https://github.com/Rand0MGG/agentscribe-local/releases/tag/v0.6.0-beta.2) 下载 DMG，拖入 Applications。支持原生 Apple Silicon/macOS 15+，不支持 Intel/Rosetta；包内有桌面依赖，无需自行安装桌面 Python。当前预览包未 Developer ID 签名/公证，系统拦截时按发行说明操作，不全局关闭安全保护。

打开后在设置准备运行组件与模型，首次需要网络和磁盘空间。当前源码比该包新，勿把本指南所有入口当作 beta.2 已有功能。

### Windows 源码安装

下载 [Windows 分支](https://github.com/Rand0MGG/agentscribe-local/archive/refs/heads/windows.zip)，安装 Python 3.12，在项目目录执行：

```powershell
py -3.12 -m linguaflow.hardware
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe scripts\install_runtime.py
.venv\Scripts\python.exe -m linguaflow
```

源码桌面支持 Python 3.11–3.13。当前完整推理环境要求 Windows x64、NVIDIA Turing/计算能力≥7.5、驱动≥570.65；检查失败先解决提示，不继续安装或回退 CPU。之后可用 `run-windows.cmd`；无需 WSL 或手动启动服务。尚无已发布 Windows 安装包。

### macOS 源码安装

下载 [Mac 分支](https://github.com/Rand0MGG/agentscribe-local/archive/refs/heads/mac.zip)，在原生 Apple Silicon 项目目录执行：

```bash
python3.12 -m linguaflow.hardware
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_mlx.py
.venv/bin/python -m linguaflow
```

之后用 `run-macos.command`。桌面、WLK 和 MLX 环境分开管理；不需重复安装已兼容组件。

## 模型与首次录音

1. 新建并命名录音，确认文件夹；取消不创建文件。
2. 缺模型时按引导准备，也可到“设置 → 模型管理 → 下载模型…”。推荐组合为 Qwen 1.7B + HY 1.8B Q4_K_M，Mac 使用 MLX 4-bit/Metal，Windows 使用 PyTorch/CUDA。SaT 随识别模型准备；Qwen 要指定原文语言。
3. 选择声音来源、语言，按需启用翻译，点击“开始聆听”。下载完成不自动录音；仅查看或单独下载不改变当前选择。

双击已下载模型可修改下一会话的模型/设备和高级参数；两种翻译引擎分别保存选择。Whisper 需要兼容权重，旧 faster-whisper/CTranslate2 目录不可直接使用。导入 GGUF 或填写 `hf://作者/仓库/文件.gguf` 不保证架构和聊天模板兼容，失败按提示换兼容文件，不静默改设备。

准备进度及取消入口保留在模型管理任务卡，切换设置页不取消。取消后有效缓存保留；缺文件重新准备，组件异常用“运行环境”修复。环境修复与模型下载分开，已有有效模型不必重下。

## 录音、回顾与保存

- 聆听时可切换来源；暂停后选择在继续时生效。过渡和收尾期间暂不可切换。设备失效需重新选择，不自动换麦克风；空闲隐藏音量条，聆听显示音量，暂停归零。
- Mac 源码支持“系统音频 · 电脑声音”，开始时申请系统录制权限；不保存屏幕图像，无需 BlackHole，已有虚拟输入仍可用。权限拒绝后到系统“隐私与安全性 → 屏幕与系统音频录制”允许并重开；源码权限归属当前 Python 应用。安装包最低系统仍为 macOS 15，实际可用性以对应包验收为准。
- 暂停/继续沿用同一文件，不保存暂停时间；停止处理尾部再保存。标题“×”关闭视图，不删除录音；关闭窗口同样等待保存与资源释放，失败保留内容，不反复强退。
- 左侧真实文件夹管理录音，行内“＋”创建子项，右键/“···”操作；活动会话期间限制库变更。删除进入垃圾桶，恢复保护同名文件，永久删除需确认；旧 `.最近删除` 继续可读。
- 回听按段落时间高亮；拖动可定位，手动翻阅暂停跟随，“返回播放位置”恢复。查找原文/译文只定位，不自动播放；时间不保证逐字准确。
- 导出定稿为 SRT/TXT/Markdown，保留已有译文及初译标记。未完整结束会明确标注；重要录音请备份，强杀可能丢失尚未落盘的最近文字。
- 改保存位置须选择空目标，由后台复制、校验再切换；取消/失败保留原件。默认位置及旧库兼容见 [目录地图](PROJECT_STRUCTURE.md#源码与数据)，不要自行删除旧库或运行目录。

## 课程资料与笔记

在“设置 → 常规”开启“体验 Beta 功能”，选中录音后打开“课程资料与笔记”。默认关闭；关闭保留已有材料和笔记，不中断正在运行的本地录音。

1. 关联课程并导入完整静态材料。支持 PDF、常见 Office/OpenDocument、离线 HTML、Markdown、TXT/CSV/TSV 和常见图片；只读取可呈现静态页/分片，不承诺动画、隐藏内容或网页交互。
2. 本地预览可离线使用。源码需 `.venv` 安装 `.[knowledge]`；PDF/Office 另需 Node≥22.19，通过“运行环境 → 安装/修复课件渲染组件”或 `scripts/install_documents.py` 准备。网页/文本/图片复用 Qt，无需额外浏览器。
3. 要云端阅读，配置系统凭据中的 DeepSeek 密钥并允许本课程图文上传，点击“完整阅读并提取术语”。每页保存，取消后可复用有效结果；完整读完才启用课程云端笔记/问答。
4. 审核候选术语并保存，供下次 Qwen 录音使用。当前预算为最多 50 项/512 UTF-8 字节；超出项明确显示。不是越多越准，也不改变已开始录音的快照。
5. 笔记用途另行授权，仅处理已保存定稿及相关课件；个人编辑不会被 AI 覆盖，来源变化会提示核对。引用可回原页/估计时间；失效 AI 内容不作为当前结论导出。

网页依赖须在材料同目录或子目录且可离线读取；资源不全、容量超限或缓存损坏时按提示补齐、分章或重新导入，不把部分完成当作完整阅读。撤回许可停止后续请求并拒绝迟到保存，已发送内容无法撤回；不上传音频。真实云端理解和笔记质量尚待验收。

## 显示、更新与常见问题

- “减少动态效果”关闭动画，保留自动跟随；上翻停止跟随，可返回最新内容。悬浮字幕可移动/缩放，背景透明度不降低文字不透明度。
- 检查更新与模型下载独立。安装版由对应原生更新器处理，录音和未保存期间不安装/重启；源码版只提示源码更新。已发布 beta.2 无应用内安装能力，需一次手动过渡。
- 无声音先核对所选来源、静音及系统权限；模型失败核对格式、设备和组件，勿把错误当成自动 CPU 回退。保存失败保留窗口与录音目录，尝试导出已有文字并解决磁盘/权限问题。

具体行为要求见 [spec](specs/README.md)，验证边界见 [VALIDATION](VALIDATION.md)。旧 LinguaFlow 启动入口、偏好及录音保持兼容。
