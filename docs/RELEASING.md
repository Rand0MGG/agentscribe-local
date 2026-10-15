# 集成、构建与发行

功能承诺见 [更新 spec](specs/updates.md)，测试门槛见 [TESTING](TESTING.md)，当前缺口见 [ROADMAP](ROADMAP.md)。本文只维护执行顺序、发布身份与兼容要求。

## 集成与版本

`windows` / `mac` 开发 → 检查整个待合并差异 → 用户审核授权 → `main` 固定提交 → 选择平台/渠道准备草稿 → 候选包验收 → 发布原文件 → 推进对应订阅。

分支和授权按 [AGENTS](../AGENTS.md#分支与交付)。共享改动小批次集成并同步另一端；提交/合并不自动发行，平台可独立发布，未验收平台不附包。

两端从已审核共同基线开发。接口、数据或核心算法不兼容时，先明确契约与集成顺序；远程无冲突不能证明另一台机器没有未提交工作。每批合并前审查整个差异，避免夹带未审核内容；获授权合入 `main` 后及时同步另一端。

文本冲突逐处处理，语义冲突回归组合行为；不以整文件 ours/theirs 或重复业务实现代替集成。保留 `windows` / `mac` 平台分支，后续开工先检查它与 `main` 的差异。

统一版本序列：兼容修复用补丁、新功能/平台支持用次版本，预览加 `-beta.N`。版本准备同步 `pyproject.toml`、`linguaflow/__init__.py` 和包内说明；检查现有标签避免冲突。每版用不可变 `vX.Y.Z` 标签固定同一来源；同版本两端若发布，必须对应同一源码。已发布标签/附件不移动、不覆盖；改内容发新版本。

产物按平台命名 `AgentScribe-X.Y.Z-macos-arm64.dmg` / `AgentScribe-X.Y.Z-windows-x64.exe`，记录来源提交、平台、架构、最低系统、依赖/构建摘要、字节数和 SHA256。源代码、脚本和锁进 Git，二进制与清单进 Release。

## 准备构建

1. 在目标系统构建；检查源码干净、版本/标签/main 完整 SHA 一致，审查所有待发行差异。不能把运行器名称当作架构证明。
2. `prepare-release.yml` 选择已审核 main SHA、已有不可变标签和目标平台，调用同一生产脚本，不在 CI 临时改版本。普通平台推送只运行开发检查。
3. Mac 用 `scripts/build_macos.py --fetch` 后再运行同脚本。Windows 在 x64 MSVC 开发命令行运行 `scripts/build_windows.py --fetch`、同脚本构建载荷，再用 `scripts/build_windows_installer.py --payload <载荷目录> --fetch` 封装 Inno 安装器。

两端锁定完整便携 Python、实际桌面依赖、Node、Qt/原生组件与许可，不复制开发 venv。应用清单只取 Git 跟踪且声明支持的文件类型；新资源类型须更新共享复制入口。源码归档固定提交，不依赖安装机系统 Git。

许可文件只接受 `licenses.json` 声明的相对路径与摘要，未声明文件不进包。仅裁剪确认不需要的开发/测试内容，保留运行模块、资源和许可，再由数值运算及完整包探针验证。依赖声明、两端锁及复制清单一致性要随修改检查。

## 最终包、签名与草稿

- 以外部工作目录和干扰 PYTHONPATH 验证启动，仅加载包内应用。完整无音频包探针检查真实窗口关闭、Qt 日志、WebEngine、Node/npm、venv、依赖、更新及恢复组件；不能仅检查导入成功。
- Windows 在装入更新组件后、封装前探针；Mac 最终 DMG 封存后只读挂载运行探针并保证失败也卸载。探针失败不封存，成功不等于已完成安装升级/录音验收。
- Mac 正式候选需 Developer ID/公证，Windows 需 Authenticode；当前脚本未自动完成它们。`--without-updater` 只供开发/过渡包，不进入订阅。
- 系统签名完成后重新核对构建清单摘要/字节数，再以 `scripts/sign_update_artifact.py --artifact <文件> --manifest <清单> --target <平台>` 签署最终字节，得到同名 `.ed25519`。封存后不可更改；变更须重新封存、签名和验收。
- `packaging/updates.json` 保存固定公钥/身份。私钥不进源码、日志或清单，分别部署至受保护 `release-build` 环境的 `MACOS_UPDATE_PRIVATE_KEY` / `WINDOWS_UPDATE_PRIVATE_KEY`；不得跨平台借用或重建公钥来绕过缺钥。签名器核对公钥并只接受规定 seed 格式。
- Release 草稿同时包含安装包、SHA256、`.build.json` 和 `.ed25519`。`prepare-release.yml` 拒绝覆盖已发布 Release 或同名附件；草稿上传另受 `release-draft` 环境保护。

## 验收与发布

在目标机器用真实旧包→同一候选包检查下载/取消/断网/篡改、录音安装门禁、保存失败、自有进程退出、程序替换失败、启动失败恢复、用户数据/模型/运行环境保留和重启。新包能单独启动、替身编译或隔离更新演练均不足以替代。

用户验收后发布原来检查的那批文件，不重新构建。版本与渠道验收必须覆盖 beta→beta、beta→稳定、稳定不收 beta。当前 beta 客户端固定读取 `beta.xml`，稳定版发布只推进 `stable.xml`，beta→稳定传播尚未闭环；须先完成实现与真实旧包验收，不能仅凭版本排序测试勾选通过。源码发布不能冒充安装包可用。

发布后显式执行 `publish-updates.yml`，填写固定 tag/target，只有该平台真实升级通过才勾选 accepted；首次空站点才用 initialize。不能依赖 `GITHUB_TOKEN` 创建 Release 自动触发另一工作流。直接网页发布也需执行同一订阅逻辑。

订阅使用 GitHub Pages Actions 部署及 `release-updates` 环境：导入完整既有站点、共用串行锁，只替换选中平台/渠道并再次比较版本，保留另一端入口。部署失败保留旧入口，允许只重试订阅；不能改已发布包。首次部署核对配置中的订阅 URL、生产站点与客户端可达性。

## 兼容与恢复

应用/安装身份、订阅地址、公钥信任、支持架构/最低系统、产物格式和用户数据兼容必须维持。改变构建工具本身不必改变升级协议；不兼容时先提供旧客户端能验证安装的过渡包，保留旧入口及信任材料。

独立基础 Python、兼容环境链、启动观察器和归属校验由共享恢复逻辑维护；原生更新器不保证业务级回滚。安装前备份旧程序，新版登记身份并显示主窗口后才报桌面健康；无法确认自有进程或安全替换时保留备份，不自动覆盖。Windows 安装器只清理由旧清单确认且未变化的失效程序文件。

## 当前状态

2026-10-15 只读核对 GitHub Release：最新已发布包仍为 Mac `v0.6.0-beta.2`，无应用内安装器；源码版本为 `0.8.0`，不能代表新版安装包已发布。当前原生后台检查仍会发送检查/结果通知，取消后的回调也缺少请求代次过滤；静默检查和取消验收尚未完成。它们与 beta→稳定传播、两端原生构建/升级、密钥部署、系统签名和 Pages 的工作统一在 [ROADMAP](ROADMAP.md) 跟踪；历史演练和各平台证据见 [VALIDATION](VALIDATION.md)。

依据：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[Actions 触发限制](https://docs.github.com/en/actions/how-tos/trigger-workflows)、[Sparkle](https://sparkle-project.org/documentation/)、[WinSparkle](https://winsparkle.org/guides/getting-started/)、[Inno Setup](https://jrsoftware.org/ishelp.php)。
