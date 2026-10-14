# 验证索引

本页记录已有什么证据及其限制；不是全平台支持声明。方法见 [TESTING](TESTING.md)，未完成验收统一在 [ROADMAP](ROADMAP.md)。历史记录中的“当前/本轮/未提交”只对应各自时点。

## 最近可核对的证据

| 证据 | 已证明 | 范围与限制 |
| --- | --- | --- |
| 2026-10-14 Windows 退出/深路径修复 | Python 3.11.15、3.12.8、3.13.9 的完整无音频各 984 passed / 25 skipped，零音频导入尝试；深 PNG/HTML/DOCX、绘制中关闭及资源日志检查 | Windows 11/x64；PySide6 分别 6.12.0、6.11.2、6.12.0。25 跳过涉及 Mac 专属、符号链接权限和未配置的原生编译器；非 Mac/设备/GPU/安装升级验收 |
| 2026-10-14 打包修复 | 完整无音频 943/23，Inno 以文本假载荷原生编译，模拟两端封存探针/清理边界 | 不执行假安装器，不证明真实 Windows 载荷可安装；后来被上一行源码回归补充 |
| Mac GPU 文件链路 | MLX 识别、SaT CPU、HY Q4_K_M/Metal 真实输出与保存审计；包含 101 秒合成英文及短课堂片段 | 历史 M2/8GB/macOS 26.6.2/Python 3.12.14，具体配置以记录为准；不是中文、完整长课堂、真实采集或当前源码重新验收 |
| Mac 系统声音与 UI | 历史短系统采集、暂停/继续、切源和 WAV 保存，以及原生界面检查 | 采集探针使用模拟推理，不能推出 GPU 联动或安装态权限通过 |
| Mac 隔离更新/恢复 | 隔离应用的实际 Sparkle 下载、安装、重启及故障旧版恢复 | 非正式系统签名包，不替代 Windows 原生或生产旧包升级 |

第一行命令为各解释器执行 `scripts/test_no_audio.py -v -rs --tb=short`；本地日志 `.work/reports/runtime-integrity-fixes-20261014/final311.log`、`final312.log`、`final313.log`，结构化摘要为同目录 `validated-results.json`。文档整理时重新核对了日志，不是重新运行模型或全量测试。该轮源码基线是 `08fe5d6` 加本地修复，代码随后提交为 `f84b388`；推送/合并不增加平台验收或发行证据。

## 详细证据

- [Windows/共享验证记录](archive/testing/VALIDATION_20261015.md)：各轮命令、失败与修复、平台边界及本地证据路径；末节保留三 Python 最终回归。
- [Mac 适配记录](archive/testing/MACOS_SUPPORT_20261011.md)：原生 UI、系统声音、短探针及资源限制。
- [Mac 文件推理](archive/testing/MACOS_FILE_TESTS_20261006.md)：CPU/MPS/MLX 的失败与成功、授权/资源边界、101 秒与课堂片段。
- [历史专题与发行](archive/README.md)：分句/翻译/DSP、基准方法的旧结果、版本说明。

原始 `.work/` 证据通常只在执行机器，不随 Git 同步；链接记录存在不保证另一台机器保有原始音频或日志。数据集或机器转写的参考可信度由 [评分协议](testing/SCORING_SYSTEM.md) 分别声明，不把 WER、词差异、句界或人工可读性混为一个指标。

## 已发布产物

2026-10-15 通过 GitHub CLI 只读核对 Release 列表及全部附件：beta.2/beta.1 提供 Mac arm64 DMG、构建清单和 SHA256，v0.5.0/v0.4.0 仅提供源码 ZIP 和摘要；无已发布 Windows 安装包或 0.8.0 Release。源码版本不代表安装包来源，具体产物/签名/哈希以 [发行页](https://github.com/Rand0MGG/agentscribe-local/releases) 为准。
