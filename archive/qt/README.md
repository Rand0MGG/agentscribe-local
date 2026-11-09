# 已退役的 Qt 界面

2026-11-10 按用户决定停止维护。此目录仅保留历史源码与界面对照证据，不安装、不运行、不纳入 CI。正式入口为 Electron，Python 后台继续维护。

`retired-tests.json` 列出退役界面对照用例；混合文件在此保留完整旧版，现行 `tests/` 继续执行其中的纯后台用例。旧 Qt 专属控件/绘制/布局测试退役，录音保存、数据保护、取消、退出和平台规则由现行后台回归与 Electron 探针负责；后续只在正式入口补测试。

旧 INI/plist/注册表设置、录音格式、锁和窗口几何读取兼容仍留在正式代码。归档不删除用户数据或已安装的环境。历史升级探针对旧已发行包的兼容分支另行保留。

现行保护对应：

| 原有职责 | 当前验证入口 |
| --- | --- |
| 开录失败、保存锁、退出门禁、课程编辑 | `tests/test_desktop_service.py`、`test_frontend_backend_contracts.py`、`test_shared_desktop_workflows.py` |
| 最新预览、旧分句回执、未完成文字与强制退出后 WAV | `tests/test_source_preview.py`、`test_desktop_service.py`、Electron caption preview 探针 |
| 音频切换、MLX、平台兼容和打包 | 原混合测试文件保留后台用例，另有 `test_platform_consolidation.py` |
| 图像真实格式、像素与桌面材质 | `test_knowledge_formats.py`、`test_desktop_platform.py`，使用合成图片及 Electron |
| Qt 控件、绘制、布局、窗口交互 | 原 Qt 专属用例退役；正式 UI 用 `npm run test:chain`、`test:interaction` 和 `test:audio-adapter` |

归档文件不会继续跟随后台接口更新；不是可运行的第二套应用。
