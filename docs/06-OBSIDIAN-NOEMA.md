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

40 是各电脑从缓存渲染的共享记忆；41 是用户可编辑的补充和冲突草稿；42 是指定一台电脑发布的离线资料包。Vault 根目录的 `README-共享记忆用法.md` 说明如何检索、审批和修改记忆。

## 2. OneDrive Sync（当前 VPS 与移动端配置）

VPS 的 Memory Share Vault 和移动端使用社区插件 **OneDrive Sync**（插件 ID `onedrive-sync`，作者 Jeff Steinbok）。按插件的个人 Microsoft 账户设备码流程登录，使用 App Folder 根目录；Vault 的本地目录应位于 rclone 挂载目录之外。

- 文件改动触发同步；VPS 配置关闭定时轮询、并发上限 2，冲突时创建副本。
- 保留 `40-Agent-Memory/Generated/`，让共享记忆和用户编辑随 Vault 同步。
- 不要再对同一 Vault 启用 Remotely Save、OneDrive 桌面客户端或把 Vault 移入 rclone 挂载目录。本机只由 Obsidian 插件写 Vault；rclone 仅把 OneDrive 挂载到另一个目录。
- 插件说明与高级设置：[JeffSteinbok/obsidian-onedrive](https://github.com/JeffSteinbok/obsidian-onedrive)。个人账户默认使用 App Folder；企业/学校账户需要额外 Entra app 配置。

## 3. 记忆如何显示和编辑

后台 worker 每 30 秒尝试同步、导入 Obsidian 修改并刷新共享记忆。手动命令：

```text
PYTHON -m memory_share --state STATE export
```

生成文件名使用 `<标题短名>--<完整_fact_id>.md`，Markdown 标题和正文可直接在 Obsidian 编辑。YAML 属性保留 `fact_id`、`revision`、`scope`、`certainty`、创建者、最近修改者及时间。正文里的内容标记之间是可编辑正文，“修改记录”表只读展示已接受版本。升级时会从服务端成功事件日志回填旧记忆的历史。

编辑标题行或内容标记之间的正文并保存，后台会把变更按笔记的 `revision` 排队提交；显示 `pending: true` 表示等待服务器确认。用户把 `certainty` 改成 `confirmed` 即表示批准该事实。不要编辑 `fact_id`、`revision`、`scope`、时间和归属属性；不要删除文件来撤销记忆，撤销仍用 `memory_retract`。

若另一台设备已经改过该事实，旧 revision 的 Obsidian 修改不会覆盖新版本；系统会在 `41-Memory-Notes/Shared-Memory-Conflicts/` 保存两版草稿，并在 `40-Agent-Memory/Conflicts/` 提供冲突说明。选择或合并后由 Agent 调用 `memory_resolve`，或将草稿按最新 revision 重新提交。

OneDrive 或 rclone 同步延迟时，修改先保留在本地 Vault；看到服务器确认后才算跨设备提交。删除生成页不会删除主库记忆；客户端会从共享缓存重建它。

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
