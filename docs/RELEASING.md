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

### 开发候选安装包

仅需试用当前源码时，可使用 `build-installers.yml`：在获准提交和推送现有 `windows` / `mac` 分支后，提交消息包含 `[build installers]` 会触发两端候选构建；工作流进入默认分支后也可手动运行。两端固定同一提交，在 Windows x64 / Apple Silicon runner 复用下述生产脚本，完成无音频回归及包探针后，将安装包、校验和与构建清单保存为 Actions artifacts。

候选包保留当前版本，Windows 无 Authenticode，Mac 仅 ad-hoc 签名、未经公证；不能据此认定正式安装/升级验收完成。此流程不创建标签、Release 或更新订阅，不使用发行私钥；正式发行仍遵循本页原有门槛。当前本地未提交源码须先按授权固定提交，不能伪造干净状态或绕过封装器的来源校验。

手动构建可勾选 `with_electron`，两端将包含锁定的 Qt/Electron 双界面；除原成品 Qt 探针外，还从最终 Mac DMG 挂载目录、Windows 安装后的独立目录启动包内 Electron，复用基础无音频探针。默认 Qt 构建不变。候选 Mac 双界面文件名含 `-dual-ui`；发布到既有自动更新渠道时使用规定的标准文件名，改名不改变安装包字节，校验和文件须记录发布名称，并重新核对摘要与清单。签名只针对最终封存字节，安装探针不代替旧版升级验收。

成品探针先检查应用及已记录自有辅助进程正常退出；一次性 CI 上卸载本轮只读探针映像若返回资源忙，可仅对该映像使用强制清理回退，不强停应用进程。其他卸载错误仍失败，用户机器不走此回退。此清理不授予生产安装或数据操作权限。

封装完成但后续探针失败时仍保存候选文件用于诊断；产物可下载不代表通过。只有对应构建运行成功、来源和签名均核对后，才能进入发行验收。

本机上传受限时，`macos-preview.yml` 可从已有不可变标签构建 Mac 包，完成完整无音频回归、真实 Sparkle 回调及最终 DMG 探针后上传到已有草稿。手动指定标签，或修改该工作流并在 mac 提交消息加入 `[upload mac preview]`；后者使用源码版本对应标签。仅替换该草稿中同名 Mac 附件，不触碰已发布版本、Windows 附件或更新订阅；发布前另核对最终附件摘要。

### 正式发行构建

1. 在目标系统构建；检查源码干净、版本/标签/main 完整 SHA 一致，审查所有待发行差异。不能把运行器名称当作架构证明。
2. `prepare-release.yml` 选择已审核 main SHA、已有不可变标签和目标平台，调用同一生产脚本，不在 CI 临时改版本。普通平台推送只运行开发检查。
3. Mac 用 `scripts/build_macos.py --fetch` 后再运行同脚本。Windows 在 x64 MSVC 开发命令行运行 `scripts/build_windows.py --fetch`、同脚本构建载荷，再用 `scripts/build_windows_installer.py --payload <载荷目录> --iscc <Inno 7 编译器> --fetch` 封装安装器。CI 通过 `prepare_compiler()` 按 `packaging/windows/inno.json` 的 URL/SHA256 准备固定的便携 Inno 7，仅写入 `.work/packaging/`，不注册文件关联；随后运行真实长许可证路径编译回归。Inno 6 无法完整编译长路径许可文件，不能靠省略许可或缩短测试路径通过。

两端锁定完整便携 Python、实际桌面依赖、Node、Qt/原生组件与许可，不复制开发 venv。应用清单只取 Git 跟踪且声明支持的文件类型；新资源类型须更新共享复制入口。源码归档固定提交，不依赖安装机系统 Git。

许可文件只接受 `licenses.json` 声明的相对路径与摘要，未声明文件不进包。仅裁剪确认不需要的开发/测试内容，保留运行模块、资源和许可，再由数值运算及完整包探针验证。依赖声明、两端锁及复制清单一致性要随修改检查。

## 最终包、签名与草稿

- 以外部工作目录和干扰 PYTHONPATH 验证启动，仅加载包内应用。完整无音频包探针检查真实窗口关闭、Qt 日志、WebEngine、Node/npm、venv、依赖、更新及恢复组件；不能仅检查导入成功。
- Windows 在装入更新组件后、封装前探针；Mac 最终 DMG 封存后只读挂载运行探针并保证失败也卸载。探针失败不封存，成功不等于已完成安装升级/录音验收。
- Mac 正式候选需 Developer ID/公证，Windows 需 Authenticode；当前脚本未自动完成它们。`--without-updater` 只供开发/过渡包，不进入订阅。
- 既有 0.9.x 试用包固定使用 `stable.xml`；兼容订阅的名称不代表系统签名/公证已完成。试用更新仍须原公钥签名、真实旧包升级与恢复验收，并在发行说明保留临时签名状态；不降低正式系统签名门槛。
- 系统签名完成后重新核对构建清单摘要/字节数，再以 `scripts/sign_update_artifact.py --artifact <文件> --manifest <清单> --target <平台>` 签署最终字节，得到同名 `.ed25519`。封存后不可更改；变更须重新封存、签名和验收。
- `packaging/updates.json` 保存固定公钥/身份。私钥不进源码、日志或清单，分别部署至受保护 `release-build` 环境的 `MACOS_UPDATE_PRIVATE_KEY` / `WINDOWS_UPDATE_PRIVATE_KEY`；不得跨平台借用或重建公钥来绕过缺钥。签名器核对公钥并只接受规定 seed 格式。
- 也可在 Mac 本机以 `sign_update_artifact.py --target <平台> --keychain-account <该平台既有账户>` 签署任一平台的封存文件；使用锁定摘要的 Sparkle 官方 Ed25519 工具，核对该平台的公钥并复验公开签名，不导出私钥或混用两端账户。Windows 仍核对自己的 WinSparkle 公钥；这不是 Authenticode。只上传同名 `.ed25519`，安装包字节保持不变。
- Release 草稿同时包含安装包、SHA256、`.build.json` 和 `.ed25519`。`prepare-release.yml` 拒绝覆盖已发布 Release 或同名附件；草稿上传另受 `release-draft` 环境保护。

## 验收与发布

在目标机器用真实旧包→同一候选包检查下载/取消/断网/篡改、录音安装门禁、保存失败、自有进程退出、程序替换失败、启动失败恢复、用户数据/模型/运行环境保留和重启。`macos-update-check.yml` 在一次性 Mac runner 用 `probe_macos_update.py` 做该链路：先本地故障订阅，再用 `--live` 验证原始旧包的真实 HTTPS 订阅；保留来源、签名、状态和数据摘要。候选模式以只读权限下载已发布的 `old_tag`（默认 v0.9.2）与 `tag` 安装包，核对 GitHub 附件摘要、构建清单、标签提交和原公钥签名，再运行本地故障订阅；线上模式使用相同封存包。录音/保存门禁使用模拟状态，真实采集单独验收。不得在用户正在使用的 Mac 上运行该探针。

`verify-release-updates.yml` 同时调度一次性 Windows/Mac runner，默认从已发布 `v0.10.2` 升级到指定的已签名候选；本地故障模式允许读未发布草稿，正式 HTTPS 模式要求候选已发布。Windows 使用实际旧 Inno 安装包、WinSparkle 下载/验签、现有录音/保存/退出门禁与新安装包，覆盖取消、断流、篡改拒绝、正常升级和启动失败恢复；Mac 复用原 Sparkle 探针。两端均核对录音、最近删除、外部文件、模型/运行组件与偏好保留；Windows 探针强制仅能在一次性 GitHub Windows runner 执行。探针或工作流存在不代表已验收，以该候选原生运行结果为准。

发行前可填写 `commit`、已成功的 `build_run` 和两端公开签名，直接从该固定来源的 Actions 产物进行上述验收，先不建立不可变发行标签；签名输入不是私钥。工作流核对来源、构建结论、安装包摘要及原公钥后才执行。验收通过后，给同一提交建立版本标签并发布原字节；正式 HTTPS 验收只填写已发布标签，不传构建运行。

用户验收后发布原来检查的那批文件，不重新构建。版本与渠道验收必须覆盖 beta→beta、beta→稳定、稳定不收 beta。稳定版发布同步进入该平台 `beta.xml`，保留更新的 beta；`stable.xml` 仅含稳定版。订阅生成回归不代替真实旧客户端升级。

发布后显式执行 `publish-updates.yml`，填写固定 tag/target，只有该平台真实升级通过才勾选 accepted；首次空站点才用 initialize。不能依赖 `GITHUB_TOKEN` 创建 Release 自动触发另一工作流。直接网页发布也需执行同一订阅逻辑。

订阅使用 GitHub Pages Actions 部署及 `release-updates` 环境：导入完整既有站点、共用串行锁，只替换选中平台/渠道并再次比较版本，保留另一端入口。部署失败保留旧入口，允许只重试订阅；不能改已发布包。首次部署核对配置中的订阅 URL、生产站点与客户端可达性。

## 兼容与恢复

应用/安装身份、订阅地址、公钥信任、支持架构/最低系统、产物格式和用户数据兼容必须维持。改变构建工具本身不必改变升级协议；不兼容时先提供旧客户端能验证安装的过渡包，保留旧入口及信任材料。

独立基础 Python、兼容环境链、启动观察器和归属校验由共享恢复逻辑维护；原生更新器不保证业务级回滚。安装前备份旧程序，新版登记身份并显示主窗口后才报桌面健康；无法确认自有进程或安全替换时保留备份，不自动覆盖。Windows 安装器只清理由旧清单确认且未变化的失效程序文件。

## 当前状态

2026-10-17 已发布 `v0.10.0`，标签固定 `95fa8c3`，Windows/Mac 安装包、清单和摘要均核对。Mac 使用既有更新私钥签署原 DMG，真实 0.9.2→0.10.0 的升级、故障恢复与数据保留通过，经既有 `release-updates` 审批部署 stable/beta 订阅；原始 0.9.2 包通过真实线上地址再验成功。Mac 仍为 ad-hoc、未公证；录音门禁用模拟状态，Windows 原生升级与真实采集尚未同等验收。证据见 [VALIDATION](VALIDATION.md)，剩余范围见 [ROADMAP](ROADMAP.md)。

依据：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[Actions 触发限制](https://docs.github.com/en/actions/how-tos/trigger-workflows)、[Sparkle](https://sparkle-project.org/documentation/)、[WinSparkle](https://winsparkle.org/guides/getting-started/)、[Inno Setup](https://jrsoftware.org/ishelp.php)。

## 双前端候选包

现有 Qt 构建命令不变。需要包含对照界面时，先准备 `desktop/` 中锁定的依赖与 Electron 二进制（见 TESTING），再为对应平台构建脚本增加 `--with-electron`；`--fetch --with-electron` 只获取固定版本输入。Electron 45.0.0 的 Mac arm64 / Windows x64 归档 SHA-256 维护于 `packaging/electron/assets.json`，构建拒绝版本不符、缺许可或未纳入版本控制的前端源码。

Mac：`python scripts/build_macos.py --with-electron`，候选 DMG 名包含 `-dual-ui-`，不会覆盖普通 Qt 产物。Windows：`python scripts/build_windows.py --with-electron` 后仍由原 `build_windows_installer.py` 封存。两者保留原 launcher、更新配置、公钥、用户数据边界及默认 Qt 入口；不把新增 runtime 当作新的发行身份。Electron 检查更新通过明确按钮切回原生 Qt 窗口。

前端包只带编译产物、受限主进程/桥、经校验的 Electron runtime 和生产依赖许可，不带 node_modules、开发服务器、浏览器 profile 或个人数据。`frontend-manifest.json` 记录源码、原始归档及最终文件摘要；Mac 原生签名后重算文件摘要，再重新封存外层应用。构建成功后还须验证包内双向切换、退出、真实设备和旧版升级，平台分别记录；本地候选不自动发布或推进更新订阅。
