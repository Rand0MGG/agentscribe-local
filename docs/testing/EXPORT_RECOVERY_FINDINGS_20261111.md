# 2026-11-11 导出回执与恢复关闭缺陷

固定代码：[`main@203ede5`](https://github.com/Rand0MGG/agentscribe-local/tree/203ede5a493e1dc7366cd1e37c932d623a7d69db)。两项均待修复，与 [R36 的并发路径替换](../VALIDATION.md#2026-11-10-独立导出与恢复备份的并发路径审计) 不同；本次只记录问题，不修改实现或规范。状态和验收条件统一在 [ROADMAP](../ROADMAP.md#实现缺口) 维护。

## R37：恢复关闭在解锁失败前清除未保存状态

- **触发与复现：** 合成录音保留未保存草稿和保存错误，完成全部文字备份；以非 root 用户将该合成录音目录临时设为只读，再调用 `close_recovered`。实际锁文件删除返回 `PermissionError`。
- **实际结果：** 录音仍选中、锁仍持有，但 `dirty=False`、`save_error=''` 已提前生效。再次关闭被“录音内容已变化，请先停止并重新备份全部文字”拒绝，失败后的状态和重试路径不一致。
- **根因：** [`close_recovered`](https://github.com/Rand0MGG/agentscribe-local/blob/203ede5a493e1dc7366cd1e37c932d623a7d69db/linguaflow/desktop_library.py#L228-L245) 先清状态，再调用 [`RecordingWorkflow.release_lock`](https://github.com/Rand0MGG/agentscribe-local/blob/203ede5a493e1dc7366cd1e37c932d623a7d69db/linguaflow/recording_workflow.py#L265-L271)；[`FileLock.unlock`](https://github.com/Rand0MGG/agentscribe-local/blob/203ede5a493e1dc7366cd1e37c932d623a7d69db/linguaflow/file_lock.py#L69-L76) 的权限异常直接返回调用方。
- **对照与边界：** 正常权限下关闭、解锁均完成；失败组备份仍含完整草稿，源 `session.json` 摘要不变，没有证明文字或音频丢失。应保证关闭成功后才进入一致终态，或失败后保留明确、可重试的恢复状态，不能只吞掉解锁异常。

## R38：恢复回执读取异常中断导出队列收尾

- **触发与复现：** 连续排队全部文字备份及普通导出，使第一项的回执 `Path.read_bytes` 抛出 `MemoryError`。此前同一固定版本在受控进程内存压力下，对 16,777,559 字节备份得到真实 `MemoryError`；发布前另以定点注入复核该分支，未重复内存压力实验。
- **实际结果：** 第一项文件已生成，但无恢复回执、无导出失败记录或最终通知；队列为 `job=None`、`pending=1`、`busy=True`，500 ms `flush` 超时，后一项文件未生成。随后新提交一次导出可重新启动遗留队列，因此不是永久死锁。
- **根因：** [`DesktopLibrary._exported`](https://github.com/Rand0MGG/agentscribe-local/blob/203ede5a493e1dc7366cd1e37c932d623a7d69db/linguaflow/desktop_library.py#L213-L226) 一次读取整个备份且只捕获 `OSError`；异常跳出 [`RecordingSaver._finished`](https://github.com/Rand0MGG/agentscribe-local/blob/203ede5a493e1dc7366cd1e37c932d623a7d69db/linguaflow/recording_save.py#L97-L106) 的 `completed.emit`，后续 `_start` 和 `idle` 不执行。Dispatcher 报出异常，不会补做队列收尾。
- **对照与边界：** 同位置抛普通 `OSError` 时能记录失败、继续下一项并结束队列。`MemoryError` 组备份字节、dirty 状态和录音锁仍保留；受控实验不代表日常 16 MiB 备份必然失败。摘要宜分块读取，队列需在监听器失败时给出准确错误并安全处理后续任务，不能把异常改报成功。

## 证据范围

- Linux / Python 3.12.14，临时合成库、草稿、备份与真实文件锁。执行真实 `DesktopLibrary`、`RecordingSaver`、Dispatcher 和 `RecordingWorkflow.release_lock`，最小宿主仅替代界面接线；没有访问用户录音、音频设备或模型。
- 原审查覆盖 16 个场景：11 组正常/保护对照、2 组清理诊断观察及上述两项缺陷的 3 组反例。发布前重新核对最新 main/dot 和 35 个 Git blob，补跑正常关闭、真实权限失败、`OSError` 对照和 `MemoryError` 注入四组，结果与上述描述一致。全部执行源码字节保持不变。
- 没有运行完整仓库测试、Electron UI/IPC、Windows/macOS、物理介质或断电验收。原内存压力只作用于隔离测试进程，权限实验只作用于临时合成目录，测试后恢复；这些结果不能替代实机完整流程验收。

## R39：退出末尾解锁失败没有完成或失败终态

2026-11-12 补充，固定 [`main@e8b9e5f`](https://github.com/Rand0MGG/agentscribe-local/tree/e8b9e5f1a6bfb5a3b4fe8f9dcc14e71cff41c271)。这是 `app.close` / stdin EOF 的退出收尾缺口；与 R37 的 `close_recovered` 提前清状态分别记录。

- **触发与复现：** 以非 root 用户启动真实 `desktop_service.main` / JSONL 后台，使用隔离偏好、合成录音和实际录音锁，令一条新草稿进入最终保存。在保存成功的 state 回调后、解锁前将本次合成录音目录设为 `0500`；真实 `unlink` 返回 `EACCES`。分别通过 `app.close` 和关闭 stdin 触发退出，恢复目录权限后继续观察 600 ms。
- **实际结果：** 最终保存成功，新旧字幕均在 `session.json`；进程仍存活、锁仍持有、`closing=True`，没有 `closed` 事件或对应的协议失败通知。直接服务对照确认退出重试计时器已停止。观察期间恢复权限未自行推进；有连接时 `bootstrap` 被“正在退出”拒绝，但再次 `app.close` 可正常结束。EOF 组已无命令输入通道，观察后仅由测试清理终止自有子进程，不算产品自行恢复，也不声称永久死锁。
- **根因：** [`ShutdownWorkflow.advance`](https://github.com/Rand0MGG/agentscribe-local/blob/e8b9e5f1a6bfb5a3b4fe8f9dcc14e71cff41c271/linguaflow/application_lifecycle.py#L111-L115) 停止计时器并返回成功后，[`DesktopService._continue_close`](https://github.com/Rand0MGG/agentscribe-local/blob/e8b9e5f1a6bfb5a3b4fe8f9dcc14e71cff41c271/linguaflow/desktop_service.py#L916-L933) 才释放录音锁，已在统一异常/abort 范围之外。异常由 Dispatcher 记录，但不会恢复关闭状态或发出终态；[`_disconnect`](https://github.com/Rand0MGG/agentscribe-local/blob/e8b9e5f1a6bfb5a3b4fe8f9dcc14e71cff41c271/linguaflow/desktop_service.py#L935-L950) 也忽略重复断连。修复需覆盖最后释放步骤的失败与重试，不以吞异常或强制退出换成成功。
- **对照与边界：** 正常 JSONL 关闭和 EOF 均保存全文、释放锁并退出。注入主保存失败后，EOF 的真实文字备份包含原文与新草稿，原 `session.json` 不变；主备份位置失败时可写临时备份，两处均失败则保留 dirty/error 与锁并中止关闭。普通资源释放失败能退出 closing 并允许重试。既有 R37 也在完整 DesktopService 调度中复现，恢复目录权限后仍不能重复 `close_recovered`，但 `app.close` 可成功。
- **证据限制：** 共 12 组隔离场景，含 5 组真实 JSONL 后台子进程与 7 组完整 DesktopService 调度；76 个源码/参考 blob 逐字节核对为固定 main，执行源码未修改。子进程仅以构造器包装建立合成状态并安排权限故障，仍执行真实 main、协议读线程、Dispatcher、保存及关闭代码；普通保存/备份失败为定点注入。未启动 Electron 原生窗口，未验证真实设备、Mac/Windows 或完整仓库回归。所有权限在观察后恢复，只清理本次自有进程与数据；没有修改程序、测试或 spec，没有实际用户数据丢失证据。
