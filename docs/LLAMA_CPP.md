# llama.cpp 翻译引擎

## 使用

“设置 → 翻译模型”先选择推理引擎，再选择该引擎的模型和计算设备。

| 引擎 | 模型输入 | 设备 |
| --- | --- | --- |
| PyTorch | 原有 HY-MT2、NLLB、兼容 Hugging Face 模型目录 | CPU；Windows CUDA |
| llama.cpp | 内置 HY 1.8B Q4_K_M，或本地 GGUF 指令模型 | Mac CPU / Metal；Windows x64 CPU / CUDA / Vulkan |

两种模型选择分别保存。已有配置保持 PyTorch；此前直接选择 Metal 的配置迁移到 llama.cpp。Mac 的 HY 快捷按钮选择内置 GGUF 和 Metal，不改变原先的 PyTorch 模型选择。

“下载 / 检查翻译模型”准备所选平台的固定 b11254 运行组件。内置 HY 下载固定 revision 的官方 Q4_K_M；自定义模型需自行准备 GGUF 文件，此按钮只校验本地文件并准备运行组件。安装不加载模型或访问音频设备。

也可在项目根目录执行：

```bash
# Apple Silicon
.venv/bin/python scripts/install_llama.py --device metal

# Windows PowerShell：CPU、cuda、vulkan 三选一
.venv\Scripts\python.exe scripts\install_llama.py --device cuda
```

## 兼容范围

- GGUF 是文件格式。FP32、FP16、量化精度由具体权重决定；引擎选择不会转换或量化文件。
- 当前内置并实测的模型为 HY 1.8B Q4_K_M。自定义文件必须是当前 llama.cpp 支持的架构，并适合通过聊天模板完成翻译指令；文件头校验只检查准备状态，实际加载还可能报告架构或模板不兼容。
- 初译、上下文、队列、缓存和字幕状态复用共享流程。llama.cpp 的通用翻译提示词与 HY 相同，新模型的语言质量、指令遵循和是否输出额外说明需单独验收。
- 当前服务上下文为 4096 token，最多生成 1024 token；不自动滑动截断上下文，超限请求报告错误并保留已有文字。生成参数集中于 `translation_models.py`。
- GPU 选择当前使用该后端的首个设备，要求全部层加载到 GPU；不提供多卡选择或部分卸载配置，不静默切换 CPU。
- Windows 使用同一版本 CPU 主程序与所选 GPU 组件，CUDA 额外准备对应运行库；依然需要兼容的显卡驱动。Windows ARM64 和其他系统尚未提供此安装入口。

## 进程与离线行为

翻译服务只绑定 127.0.0.1，每次启动生成独立认证信息，客户端忽略系统代理。会话停止、取消或父进程退出时释放自己启动的服务。Windows 管道使用 PeekNamedPipe 检测断开，POSIX 使用 select；平台处理集中在 `process_platform.py`。

准备后只读取本地模型。桌面预检会提示缺少的文件；实际模型加载或翻译失败会报告错误，不将空白或达到输出上限的译文标记为成功。

## 验证

2026-09-29，M2 / 8GB、macOS 26.6.2：使用隔离偏好与录音库预览 PyTorch / llama.cpp 设置，覆盖 900 × 650 窗口，未访问音频设备。首次 Cocoa 预览在受限执行环境的 HIServices 应用注册阶段退出；在允许访问窗口服务的执行环境复跑完成，此错误发生在创建窗口前。

Windows 的设备选项、安装包组合、路径、进程启动/清理参数和管道检测使用模拟测试；尚未进行 Windows 实机安装或 GPU 推理验收。

本地界面证据：`.work/cache/llama-desktop/`。完整文件链路证据：`.work/mac-file-tests/llama-shared/`；资源与音频保护记录：`llama-shared-observe/`。历史 HY 性能和质量限制见 [HY Metal 验证](testing/HY_METAL.md)。

### 本轮结果

- 无音频设备回归测试：275 项通过；修改文件 Ruff 和 `git diff --check` 通过。
- 共用后端的 101.176 秒英文音频回放：Metal 确认 33/33 层，24 段全部定稿并完成最终翻译，无字幕错误。词错误率 1/256（0.39%），无增词或漏词。首条原文约 2.45 秒，收尾约 4.89 秒。
- 诊断记录 34 次翻译消费，耗时中位约 0.5 秒、P95 约 1.0 秒；统计精度为 0.1 秒，包含潜在缓存命中。整机交换空间增长约 3506 MiB，不代表全是应用占用，也不能据此宣称相对旧实现性能提升。
- 本地 GGUF 文件选择 + CPU：真实 HY 文本推理返回“早上好。”，辅助进程退出码 0、日志线程结束；证据在 `.work/mac-file-tests/llama-shared-cpu/`。此项验证 CPU 选择与文件入口，没有验证另一种模型架构或高精度权重。
- 所有上述推理使用文本或文件音频；无音频设备访问尝试。
