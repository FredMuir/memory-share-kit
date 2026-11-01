# Obsidian OneDrive Sync 与 Noema

## 1. 每个平台一个同名 Vault

桌面与移动端使用同一个逻辑 Vault，例如 `MyVault`。各电脑可以有不同绝对路径。Obsidian 选择“打开文件夹作为仓库”，不要在已有 Vault 内再建一个同名 Vault。

本机安装器补充以下目录，不删除原笔记：

```text
00-Inbox/
10-Personal/
20-Projects/
30-Knowledge/Technology/
30-Knowledge/References/
40-Agent-Memory/Generated/
41-Memory-Notes/
42-Noema-Packs/
50-Daily/
90-Archive/
99-Attachments/
```

40 是各电脑从缓存渲染的只读视图；41 是用户可编辑的补充；42 是指定一台电脑发布的离线资料包。Vault 根目录的 `README-共享记忆用法.md` 说明如何检索、审批和修改记忆。

## 2. OneDrive Sync（当前 VPS 与移动端配置）

VPS 的 Memory Share Vault 和移动端使用社区插件 **OneDrive Sync**（插件 ID `onedrive-sync`，作者 Jeff Steinbok）。按插件的个人 Microsoft 账户设备码流程登录，使用 App Folder 根目录；Vault 的本地目录应位于 rclone 挂载目录之外。

- 文件改动触发同步；VPS 配置关闭定时轮询、并发上限 2，冲突时创建副本。
- 保留 `40-Agent-Memory/Generated/`，让记忆阅读视图随 Vault 同步；不要在 Obsidian 里编辑这批生成文件。
- 不要再对同一 Vault 启用 Remotely Save、OneDrive 桌面客户端或把 Vault 移入 rclone 挂载目录。本机只由 Obsidian 插件写 Vault；rclone 仅把 OneDrive 挂载到另一个目录。
- 插件说明与高级设置：[JeffSteinbok/obsidian-onedrive](https://github.com/JeffSteinbok/obsidian-onedrive)。个人账户默认使用 App Folder；企业/学校账户需要额外 Entra app 配置。

## 3. 记忆如何显示和编辑

后台 worker 每 30 秒尝试同步并导出。手动命令：

```text
PYTHON -m memory_share --state STATE export
```

生成文件名使用 `<标题短名>--<完整_fact_id>.md`，Markdown 标题使用人类可读的记忆标题；YAML 属性同时保留 `title`、完整 `fact_id`、`revision`、`scope`、`certainty`、`status`、`pending`。文件名便于浏览，完整 ID 便于 Agent 精确定位。修改记忆标题后，导出器会在旧文件仍与导出清单一致时安全重命名；手动改动过的旧文件会保留并报告。重复导出相同内容不重写，减少版本噪声。

生成文件是只读视图。**直接改 Markdown 不会提交主库**。修改前先用 `memory_get` 获取当前 revision，再由 Agent 调用 `memory_update`；新增用 `memory_store`，撤销用 `memory_retract`。`certainty=candidate` 表示待核实，用户确认或有可复核证据后才设为 `confirmed`；`pending` 指客户端事件尚未获得服务端确认，不代表用户审批状态。同步后导出视图会更新。

应在 41-Memory-Notes 写补充，或让电脑 Agent 使用 memory_update；要修改已有共享事实，先 memory_get 获取 revision。尚不开发 Obsidian 插件。

如果误改了生成文件：先把修改移到普通笔记并通过 Agent 提交；确认修改已保存后，移走该生成文件，下一次 export 会从缓存重建。不要盲目删除整个目录或 manifest。

## 4. 本机 Agent 读取普通笔记

MCP 提供 `obsidian_read_note(relative_path)`，默认仅允许 `20-Projects`、`30-Knowledge`、`41-Memory-Notes`，限制 Markdown 256 KiB。路径穿越和指向 Vault 外的 symlink 被拒绝。

该工具只在本机读取，程序不会自动把整篇文档上传协调端；但宿主 Agent 可能把工具返回内容发送给它自己的模型服务。共享记忆与云模型上下文的边界需要分别理解。只在当前任务需要且用户已授权的目录中读取。

## 5. Noema 离线辅助

指定一台电脑作为资料包发布端（例如 Mac），先确认 sync 成功，再执行：

```text
PYTHON -m memory_share --state STATE pack --output VAULT/42-Noema-Packs/shared-memory-2026-10-31.md
```

替换实际绝对路径和日期；目标文件已存在会拒绝覆盖，使用新文件名。不要由多台电脑发布同一个目标。资料包只含共享范围有效事实，不含 local；包括 candidate/confirmed 标识。它不包含整个私人 Vault，也不包含撤销事实。过期资料包内的历史内容不会被自动撤回，因此不能长期保留旧包作为最新依据。

1. 等 Remotely Save 完成资料包同步，确认 iPad/iPhone 上实际有本地文件。
2. 在 Noema 导入资料包，另行选择需要的 Obsidian 文档；安装本地模型与 embedding 模型并完成索引。
3. 使用 `prompts/NOEMA-OFFLINE.txt`。
4. 飞行模式下询问包中真实存在的两条事实，检查出处。
5. 更新资料包后验证 Noema 的刷新/重建行为；若它保留旧导入副本，明确替换旧数据集，避免同时检索多份互相矛盾的快照。

**本包没有让 Noema 自动跟踪 Vault、自动刷新索引或自动回写的假接口。** “生成包成功”不是“已导入 Noema”。需要后续真机记录具体操作；它不阻塞电脑端共享记忆上线。

依据：https://noemaai.com/docs/dataset-integration 、https://noemaai.com/docs/constellation 。模型和资料须分别准备在 iPad/iPhone；聊天同步不等于数据集同步。

## 6. 什么时候才做插件

只有需要在 Obsidian 内进行版本化新增/更新/撤销、显示队列、处理冲突时再开发小插件。插件不作为 Noema 后台服务器，不替代电脑端 MCP，不用它重造 OneDrive 同步器。
