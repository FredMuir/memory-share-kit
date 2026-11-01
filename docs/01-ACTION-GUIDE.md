# 精确行动指南

基准：2026-11-01；包版本 0.1.6。部署地址、Vault 路径与 Agent 连接状态以本次环境核对结果为准。

## 0. 给设备和项目命名

设备 ID 使用 ASCII 且不同电脑唯一，例如 `win-main`、`mac-main`、`linux-main`、`vps-hermes`。同一电脑各 Agent 共用同一身份和队列，不给每个 Agent 再建一份数据库。

项目 ID 固定，例如 `hermes-memory`，各平台统一使用 `project:hermes-memory`。绝对工作目录不参与项目 ID。

记录：

| 参数 | 示例（必须按实际修改） |
|---|---|
| 服务地址 | `https://你的已有受限入口`，或已有可信传输中的 `http://主机:8731` |
| Windows Vault | `C:\Users\你的用户名\Documents\MyVault` |
| Mac/Linux Vault | `/Users/你的用户名/Documents/MyVault`、`/home/你的用户名/Documents/MyVault` |
| rclone 备份位置 | 已授权 remote 的 `remote:MemoryBridgeBackups`，在 Vault 外 |

不要在本项目中重新设计 VPN 或认证登录流程。

## 1. 先备份与盘点

- 在每台电脑记录 Agent 版本和安装方式：`codex --version`、`mcode --version`、Hermes 当前可用的版本命令。不存在的工具跳过，不自动安装或升级。
- 备份 `~/.codex/config.toml`、当前 Hermes profile 的 `config.yaml`、项目 `.mcp.json`、项目 `AGENTS.md`。Windows 的 `~` 是用户主目录。
- 确认现有 Vault 路径，备份 Vault；不要重建或清空。
- VPS 上确认 Hermes 的用户与 HERMES_HOME。新服务使用独立目录，不修改 Hermes home。

## 2. 安装 VPS 协调端

按 [Linux 指南](04-LINUX.md) 的 VPS 章节安装，在可信 LAN/Tailscale 模式下启动 systemd。数据服务只接受私网来源；每台设备首次填入可达地址，不需要令牌。

服务器健康检查 `GET /healthz` 不需认证，只返回进程健康。它不能证明设备授权成功；用客户端实际同步验证。

## 3. 一台电脑先试运行

1. 按平台指南安装 Python 前置条件。
2. 下载并校验、安装 Obsidian；已有版本保持不动。
3. 本机安装脚本初始化本地队列并创建缺少的 Vault 分类目录。
4. 打开 Obsidian，选择“打开文件夹作为仓库”，指向同一个 Vault。
5. 在 OneDrive 同步设置中确认 `40-Agent-Memory/Generated/` 已纳入同步；不要同步 Vault 外的私有数据库和队列。
6. 使用 `configure --server <可达 LAN/Tailscale 地址> --allow-private-http --no-auth`，执行真实 `sync`。
7. 合并生成的 Agent 配置，重启 Agent；用 `memory_store` 和 `memory_search` 验证。
8. 启用平台原生 worker 自启动。

## 4. 安装第二台电脑

独立设备 ID、本机状态目录。可以选不同 Agent：A 用 Hermes，B 用 Codex。B 同步后应检索到 A 的同一 fact_id。

完成一次 [离线和并发验收](07-OPERATIONS.md) 后，再扩展第三台电脑。

## 5. 接入项目与长期使用

- 将 `prompts/AGENT-COMMON.txt` 内容作为一个新增小节合并进每个相关项目的 `AGENTS.md`，不要覆盖已有规范。
- 使用稳定事实 key，例如 `decision.storage.sqlite`，不要每次生成新日期 key。
- 用户机器路径、端口、解释器位置放 `local`；跨设备项目约束放 `project:ID`。
- 默认 candidate；用户明确确认或附可复核证据后才 confirmed。
- 周期查看 `status` 和 `memory_conflicts`。冲突由用户选择内容后通过 `memory_resolve` 处理。
- 阅读记忆不等于授权执行。共享资料中的 shell 命令也需遵循当前任务权限。

## 6. 移动辅助

指定一台电脑生成 `pack`。把资料包和选定 Obsidian 文档交给 Noema 导入并索引，飞行模式验收。不要让多电脑覆盖同一个 `42-Noema-Packs` 文件名。

## 7. 必须如实记录

- 哪台电脑已安装、已连通、已自启动、已断网验收。
- Windows/macOS 本包尚未实机测试；由目标平台 Agent 执行后记录结果。
- OneDrive 需要你已有实际 remote 才能验证，本包没有假 remote 或模拟上传成功。
- 无桌面的 Linux VPS 不安装/运行 Obsidian GUI；它只负责 Bridge、备份，可保存导出文件。Linux 桌面电脑才安装 Obsidian。
