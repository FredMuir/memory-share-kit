# 验收、故障排查、恢复与回滚

下文 `PYTHON`、`STATE` 替换为平台指南中实际绝对路径。不要原样执行占位符。

## 1. 自动化测试

在源码包根目录，使用已安装依赖的 Python：

```text
PYTHON -m unittest discover -s tests -v
```

测试使用临时目录和真实 loopback HTTP/MCP stdio，不访问生产主库。覆盖本地进程退出后读写、失败重连、重复事件100次、丢失响应、同键去重、并发冲突与解决、撤销保护、本地范围隔离、备份恢复epoch、身份伪造、导出人工编辑保护、路径越界以及配置片段。

Linux 本次真实通过；Windows/macOS 请在目标系统执行后记录。OneDrive 和 Noema 无可用账号/真机，尚未集成验收。

## 2. 跨电脑验收

1. A 的 Agent 保存 `project:memory-share-acceptance`、key `acceptance.shared-memory`，记录 fact_id；调用 memory_sync。
2. B 同步并查询，必须读取同一 fact_id。
3. **停止协调端服务**；A、B 分别新增不同 key。工具需返回 queued，本机搜索立即可见。
4. 退出两个 Agent，重启后仍能查询本机新增。
5. 恢复协调服务；两端同步，最终能互相读取。
6. A、B 先同步同一事实并记录同一个 revision，然后在同步前分别 memory_update 成不同内容；再同步。
7. 必须保留一个当前值和一个冲突事件，而不是最后写入直接覆盖。调用 memory_conflicts 检查双方内容。
8. 用户选择后用 memory_get 获取最新版本，再 memory_resolve，另一台同步后冲突消失。

“VPS 故障可工作”指记忆工具依赖本机缓存。依赖远端模型的 Agent 还需要其模型服务可用。

## 3. 状态定位

`PYTHON -m memory_share --state STATE status`

- `pending`：未取得服务端确认；不要删除队列。
- `accepted/noop`：有持久回执；保留用于旧备份恢复重放。
- `conflict`：事件已持久保存，但未应用为当前事实。
- `rejected`：服务端验证拒绝，事件仍保存在 outbox；检查设备 ID、协议版本和本地事件，不要循环改 ID 假装重试。
- `local`：只保存在本机的记忆，不会上传。
- `last_sync`：最后一次完成上传/拉取流程的 Unix 时间；新设备此前不可知的记忆不会自动出现。
- `last_error`：只显示类型或 HTTP 状态，避免回显凭据和正文。

一次 sync 最多上传 100 条，避免长时间阻塞工具。大量队列会由 worker 后续轮次继续上传；`ok:true` 表示本次同步流程完成，不等于 pending 必然为 0。上线验收应同时检查 pending=0。

`HTTP 401` 优先核对服务器设备 token 是否被轮换/撤销，使用 configure 重新隐藏输入。`HTTP 3xx` 不跟随重定向，避免令牌跨来源泄漏；改为准确入口 URL。

VPS 服务日志：`journalctl --user -u memory-share-server.service --since today`。
客户端 Linux：`journalctl --user -u memory-share-client.service --since today`。
Windows：任务计划程序状态及本地 status；macOS：launchctl print 与状态目录日志。

## 4. 备份与恢复

生成一致性备份：

```text
PYTHON -m memory_share --state SERVER_STATE backup --output NEW_BACKUP_FILE
```

目标必须为新文件，不能覆盖运行主库。上传与远端 SHA256 验证用 backup-upload，详见 Linux 指南。备份含私人记忆和设备 token 哈希，不能放公开目录。客户端 client.json 含实际令牌，不要随手放入普通笔记。

恢复演练先在临时目录进行，成功后才操作生产。生产恢复步骤：

1. 停止协调服务；如果是灾难恢复，确认没有另一个旧协调进程仍对外服务。
2. 备份当前 authority.sqlite3、WAL/SHM，保留故障现场；停服后再移走旧文件，不要直接往运行主库上覆盖。
3. 把选定的一致性备份复制为 SERVER_STATE/authority.sqlite3；确保此目录不残留旧主库对应的 WAL/SHM。
4. 执行 `PYTHON -m memory_share --state SERVER_STATE rotate-epoch`。
5. 启动服务。
6. 各客户端 sync；epoch 变化触发快照重建和已保留回执/事件重放。
7. 核对数量、关键事实、撤销和冲突。

回放可以补回仍保存在客户端的已确认事件，**不承诺所有客户端同时损坏后的零丢失**。设备从未同步的新增只在该设备，不在服务器备份。

数据库备份包含当时设备 token 哈希；备份后新发放或轮换的 token 可能需要重新配对，401 时先解决身份授权，再补传。

## 5. OneDrive 故障

- 普通笔记同步、数据库备份上传、记忆 HTTP 同步是独立路径。
- rclone 上传失败退出非零，保留本地备份；不要清理本地唯一副本。
- 下一次任务上传新的完整备份。历史未上传备份保留，必要时用 rclone copyto 重传，再通过 rclone cat 校验。
- 未配置真实远端时不能写“上传已验证”。

## 6. 升级

不要重跑安装脚本覆盖正在使用的虚拟环境。先关闭相关 Agent、停止 worker/协调服务，备份数据库与配置；在新的 venv 安装新版本、运行测试，再重新生成 MCP/自启动路径并切换。v0.1 没有跨版本自动迁移承诺，升级指南必须随新版本给出；保留旧环境直到验证成功。

## 7. 回滚 / 停用

1. 停止 worker 自启动任务（平台指南有命令）。
2. 退出 Agent，移除自己新增的 shared-memory MCP 项，保留其他配置。
3. 项目 AGENTS.md 仅移除新增规则小节。
4. 如果停用整个系统，再停止协调服务和备份 timer。
5. 保留私有状态目录、outbox、SQLite 和备份；不要卸载时删除。
6. Obsidian 普通笔记和 Hermes 原生记忆继续使用。生成视图可保留阅读，不应改为另一个写入主库。

## 8. 暂不实现的功能

没有双主故障转移、点对点同步、自动语义合并、通用后台抓取所有 Agent 会话、自动 LLM 摘要、Noema 自动索引/回写、自研 Obsidian 插件、远程 HTTP MCP。实际 REST 服务路径不能配置成远程 MCP。
