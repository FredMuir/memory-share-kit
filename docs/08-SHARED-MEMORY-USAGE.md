# 共享记忆用法

此 Vault 用于查看和审阅多 Agent 的共享记忆。记忆的权威版本保存在 Memory Share 服务；Obsidian 中 `40-Agent-Memory/Generated/` 下的文件是自动生成的阅读视图。

## 文件名和属性

生成文件使用以下格式：

```text
<安全化标题短名>--<完整_fact_id>.md
```

例如：

```text
局域网共享记忆服务部署--<完整_fact_id>.md
```

标题供人浏览；完整 `fact_id` 和 `revision` 供 Agent 精确定位和版本检查。Markdown 标题和 frontmatter 中的 `title` 保留自然语言标题。标题改变时，导出器会重命名未被手动改过的旧生成文件；保留完整 ID 不变。

| 属性 | 含义 |
|---|---|
| `fact_id` | 记忆的稳定唯一 ID；改标题或内容时不变 |
| `revision` | 当前版本号；更新前必须先读取 |
| `scope` | `global` 全局；`project:<id>` 项目范围；`local` 本机范围 |
| `certainty` | `candidate` 待核实；`confirmed` 已确认 |
| `status` | `active` 有效；`retracted` 已撤销 |
| `pending` | 尚未获得服务端同步确认；不是审批状态 |
| `created_by_agent` / `created_by_device_id` | 首次被服务端接收时提交它的 Agent 和设备 |
| `created_at` | 首次提交的服务端 Unix 时间戳（UTC） |
| `updated_by_agent` / `updated_by_device_id` | 当前版本最近一次被服务端接收时的 Agent 和设备 |
| `updated_at` | 当前版本最近一次提交的服务端 Unix 时间戳（UTC） |
| `history` | 每个已接受版本的 revision、操作、Agent、设备和服务端接收时间；冲突或未同步的操作不计入 |

新记忆由服务端首次接收时记录创建者和时间。每次成功更新、撤销或冲突解决都会追加一条历史；离线排队期间只显示待同步修改，服务端确认后才进入正式历史。Agent 名称来自对应 MCP profile 的配置，设备 ID 来自配对身份。升级前已存在的记忆无法追溯首次提交时间和创建 Agent，会标记为未知；升级后发生的修改仍会完整记录。

## 审批或修改

不要直接编辑、重命名或删除 `40-Agent-Memory/Generated/` 中的生成文件；本地修改不会写回权威记忆，后续导出可能覆盖它。请让任一已连接的 Agent 通过 shared-memory MCP 操作：

1. 用 `memory_search` 找到条目，再用 `memory_get` 按完整 `fact_id` 读取内容和当前 `revision`。
2. 确认待核实条目后，用 `memory_update` 保留同一 `fact_id`，提交当前 revision；用户确认或证据足够时设为 `confirmed`，否则保持 `candidate`。
3. 修改已有内容或标题也用 `memory_update`，并基于刚读取的 revision；不要另建一条重复记忆。
4. 新事实用 `memory_store`；撤销旧事实用 `memory_retract`，它会保留历史。
5. 运行 `memory_sync`，并在确认服务端同步后等待生成视图刷新。遇到冲突先用 `memory_conflicts` 查看，再按用户决定使用 `memory_resolve`。

若要添加解释、讨论或个人备注，请写在 `41-Memory-Notes/`，不要改生成视图。共享范围由 `scope` 决定；凭据和令牌不得写入共享记忆。
