# Obsidian、OneDrive 与 Noema

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

40 是各电脑从缓存渲染的本地视图；41 是用户可编辑的补充；42 是指定一台电脑发布的离线资料包。

## 2. Remotely Save

1. 在 Obsidian 设置 → 社区插件中搜索并安装 **Remotely Save**，核对项目为 `remotely-save/remotely-save`，不要安装名字相近的 fork。
2. 启用插件，按现有 OneDrive 授权方式连接；不复用 rclone 的配置文件作为插件配置。
3. 确认个人/企业 OneDrive 类型。免费 App Folder 文档指向个人 OneDrive；若账户类型不匹配，停止并核对当前插件支持，不能假装已授权。
4. 核对真实 App Folder 与 Remote Base Directory；一般使用同名 Vault。不是随意填写 OneDrive 根目录的 `Obsidian`。
5. 在忽略/排除路径的设置中排除 `40-Agent-Memory/` 整个子树。若当前设置接受正则，可使用 `^40-Agent-Memory(?:/|$)`；若接受路径，填写实际目录。以插件当前版本格式和同步预览验证，不能只填入后默认生效。
6. 排除记忆包自己的配置/凭据。私有状态目录本就应在 Vault 外。不要同步 Agent 凭据或用户整个 `.obsidian` 工作区状态。
7. 第一次只放一条无敏感的测试笔记，设备 A 上传、设备 B 下载，验证方向、目录和删除行为后再同步正式笔记。
8. 开启当前插件版本提供的启动/定时自动同步。iOS 只在 App 得到执行机会时运行，不保证后台固定频率。

源：https://github.com/remotely-save/remotely-save/blob/master/docs/remote_services/onedrive/README.md 。

**不要叠加 OneDrive 桌面客户端或 rclone 双向同步同一 Vault 路径。** 若已有 Vault 直接位于系统 OneDrive 同步目录，先备份并确定唯一同步器，再选择迁至普通本机目录配合 Remotely Save；不能一边运行两套同步一边迁移。

## 3. 记忆如何显示和编辑

后台 worker 每 30 秒尝试同步并导出。手动命令：

```text
PYTHON -m memory_share --state STATE export
```

生成文件包含 fact_id、revision、scope、certainty、status、pending。重复导出相同内容不重写，减少版本噪声。直接改过的文件会被保留并在 `preserved_user_edits` 报告；**这些修改不会自动提交主库**。

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
