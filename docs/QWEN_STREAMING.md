# 可选：本机 Qwen3-ASR 流式服务

桌面已实现适配器，服务需另行启动。此路径未在本机部署真实权重，不把协议测试视为推理成功。官方流式仅有 vLLM 后端，Windows 原生或 macOS 的普通 Transformers 文件转录不能替代它。

在支持 NVIDIA GPU 的 Linux 或同机 WSL2 环境中操作。先确保该环境能正常使用 GPU；不要把以下依赖装入桌面 `.venv`。从项目目录执行：

```bash
python3.12 -m venv .venv-qwen
source .venv-qwen/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-qwen.txt
python scripts/qwen_stream_server.py --model Qwen/Qwen3-ASR-0.6B --gpu-memory-utilization 0.65
```

首次启动由服务下载所选模型。看到 `Qwen ready` 后，在桌面“模型管理 → 识别模型”选择 Qwen 流式接口，模型选同一名称，地址保留 `http://127.0.0.1:8765`，点击检查服务。WSL localhost 转发须可用；不支持改填远程主机地址。

`0.65` 是 vLLM 的显存利用设置，不是全机显存上限，也不保证所有 GPU 和依赖版本兼容。0.6B 优先，翻译保留在 CPU；切勿同时运行另一份 Whisper GPU 会话。8GB 运行情况尚待实机验证。

服务只监听环回，拒绝浏览器 Origin，仅接受本项目 JSON 协议；没有配置云端。一个服务一次处理一个会话。音频请求不自动重试，避免中断后重复提交同一片段。

默认 2 秒流式块；停顿触发尾部刷新后定稿。官方实现会回退尾部 token 纠错，部分已固定前缀可能不再被模型修订；UI 支持同一行原文更新，不保证任意历史字词均可回改。连续 60 秒无端点会中止并清理状态。SRT 时间戳是本机采集时间范围，不是模型返回的词级时间戳。

参考：[官方仓库与流式示例](https://github.com/QwenLM/Qwen3-ASR)、[官方推理实现](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_asr.py)。依赖组合跟随官方包，安装前应检查其 CUDA 与 vLLM 要求。
