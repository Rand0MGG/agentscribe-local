# 开源项目对照与本次修复

检查日期：2026-09-06。对照公开源码和说明；没有复制第三方实现代码。

| 对照来源 | 观察 | 本项目修复 |
| --- | --- | --- |
| [WhisperLive 依赖声明](https://github.com/collabora/WhisperLive/blob/main/setup.py) | 明确指出 CTranslate2 首次转写需要 CUDA 12 cuBLAS / cuDNN 9，模型包未必携带匹配运行库；该项目在 Linux 上显式声明 NVIDIA 包 | 增加 Windows GPU 可选依赖及安装脚本，进程内注册 DLL 路径，验证 DLL 与计算类型 |
| [WhisperLive 后端](https://github.com/collabora/WhisperLive/blob/main/whisper_live/backend/faster_whisper_backend.py) | 区分后端准备成功和错误，并把状态发送给客户端 | 预热完成后才通知开始录音；失败消息保留，不能被队列消息覆盖 |
| [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper#gpu) | GPU 有额外运行库要求；transcribe 返回的 segments 是惰性生成器 | 预热时关闭 VAD，实际消费生成器，检查第一次运算时才加载的依赖 |
| [Speech Translate](https://github.com/Dadangdut33/Speech-Translate) | 提供实时录音、独立字幕窗及 CPU/GPU 安装路径；其翻译主要接 API | 保留本地 NLLB，提供独立 GPU 安装入口和阶段诊断，避免照搬云端翻译方案 |

## 实际根因

1. 本环境只有 CPU 版 PyTorch，缺少 CTranslate2 需要的 `cublas64_12.dll`。
   模型权重下载、WhisperModel 创建成功都不代表 CUDA 第一次运算可用。
2. 旧实现直到收到音频才执行首次 GPU 运算；失败后录音队列提示和结束提示会覆盖真正错误。
3. Transformers 4.57 的默认远程加载路径含后台 safetensors 自动转换逻辑，
   能造成 `.bin` 之后又下载等体积 safetensors。修复为先解析单份模型缓存，再以本地目录加载。
4. 解耦翻译模型加载后，实机测试暴露出 PyTorch 首次导入与 SciPy 重采样并发的初始化竞争。
   现在先初始化基础运行库，再开启录音；权重加载仍与原文识别解耦。
5. 100ms 原生录音缓冲在模型加载时出现断续，扩大为 1 秒容量，仍每 100ms 读取。
   最终固定音频的回环测试无断续警告，原文完整。

`hf_xet` 缺失只影响下载方式，符号链接警告只影响缓存空间利用；这两项不是无字幕的直接原因。
已安装 hf_xet，没有开启系统开发者模式、修改系统 PATH 或删除用户模型缓存。

## 验收

已在本机使用用户缓存的 large-v3 与 NLLB 1.3B 完成 GPU → CPU 离线推理，
并通过实际 Windows 回环、分段、Qt 信号及 SRT 导出链路。
详情见 [验证记录](VALIDATION.md) 和 [实际回环输出](loopback-result.json)。
