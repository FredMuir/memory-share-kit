# 局域网部署模板

本文提供 VPS 协调端、Hermes MCP 客户端和 Windows Codex 客户端的通用部署步骤。请在本机维护实际 IP、端口、用户名、Vault 绝对路径和设备令牌；提交到公共仓库前一律保留占位符。

## 拓扑与边界

- VPS 上运行 Memory Share 协调服务和 Hermes。服务绑定 VPS 的局域网地址；Hermes Dashboard 按需监听网卡，并启用 Basic Auth。
- 每台设备使用自己的本地队列和设备令牌。网络中断时本地 Agent 继续工作；恢复连接后由 worker 同步队列，并在配置了 Vault 时导出 Obsidian 阅读视图。
- Obsidian 的 `40-Agent-Memory/Generated/` 是只读视图；记忆更新必须通过 shared-memory MCP。
- 协调端 HTTP 仅用于可信局域网或现有 VPN。不要把服务端口转发到公网，也不要把令牌写进 Git、提示词或日志。

## 1. VPS 安装协调服务

设置部署时的实际局域网地址和端口：

```bash
VPS_LAN_IP='<VPS_LAN_IP>'
MEMORY_SHARE_PORT='<MEMORY_SHARE_PORT>'
cd "$HOME/Tools/memory-share-kit"
MEMORY_SHARE_BIND_HOST="$VPS_LAN_IP" bash installers/install-server-linux.sh
SERVER_ROOT="$HOME/.local/share/memory-share-server"
SERVER_PYTHON="$SERVER_ROOT/venv/bin/python"
```

为 VPS Hermes 与每台工作站分别签发令牌。令牌只输入对应设备的隐藏 `configure` 提示：

```bash
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device vps-agent
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device workstation-agent
```

启用安装器生成的用户级 systemd unit。若服务需要在用户退出后继续运行，由管理员按 VPS 实际运行用户启用 linger。只在可信 LAN/VPN 放行协调端端口；检查 `http://${VPS_LAN_IP}:${MEMORY_SHARE_PORT}/healthz` 返回健康状态。健康检查不代表设备令牌已验证，之后还要执行一次客户端真实同步。

## 2. Hermes 接入 shared-memory MCP

使用运行 Hermes 的普通 Linux 用户。共享 Vault 放在 Hermes 原生配置目录之外：

```bash
cd "$HOME/Tools/memory-share-kit"
HERMES_VAULT="$HOME/.local/share/memory-share-vault"
bash installers/install-unix.sh vps-agent "$HERMES_VAULT"
CLIENT_ROOT="$HOME/.local/share/memory-share"
CLIENT_PYTHON="$CLIENT_ROOT/venv/bin/python"
"$CLIENT_PYTHON" -m memory_share --state "$CLIENT_ROOT" configure \
  --server "http://${VPS_LAN_IP}:${MEMORY_SHARE_PORT}" --allow-private-http
"$CLIENT_PYTHON" -m memory_share --state "$CLIENT_ROOT" sync
```

将 `vps-agent` 专属令牌输入隐藏提示。备份 Hermes 当前 profile 配置，只合并生成配置中的 `shared-memory` MCP 子项，不覆盖整份配置或原生记忆设置。对每个实际使用的 profile 重启/重新连接 Hermes，并调用 `memory_status`、`memory_search` 验证。

## 3. Windows Codex 接入

在 PowerShell 中将模板变量替换为实际地址与端口：

```powershell
$VpsLanIp = '<VPS_LAN_IP>'
$MemorySharePort = '<MEMORY_SHARE_PORT>'
$MemoryRoot = Join-Path $env:USERPROFILE '.local\share\MemoryShare'
$Vault = Join-Path $env:USERPROFILE '.local\share\MemoryShareVault'
.\installers\install-windows.ps1 -Device workstation-agent -Vault $Vault -InstallRoot $MemoryRoot
$Python = Join-Path $MemoryRoot 'venv\Scripts\python.exe'
& $Python -m memory_share --state $MemoryRoot configure `
  --server "http://${VpsLanIp}:$MemorySharePort" --allow-private-http
& $Python -m memory_share --state $MemoryRoot sync
```

输入 `workstation-agent` 专属令牌后，合并生成的 MCP 配置子项并重启 Codex。检查 `memory_status` 的同步结果，再用 `memory_search` 检索同一条共享事实。

## 4. Obsidian 与 OneDrive

VPS 和移动端可以使用社区插件 [OneDrive Sync](https://github.com/JeffSteinbok/obsidian-onedrive) 连接同一个 OneDrive App Folder。插件通过设备码授权。保持 Obsidian Vault 位于 rclone 挂载目录之外，避免两个写入器操作同一份本地文件；不要把 Vault 放进 `~/OneDrive` 或其他 rclone 挂载目录。`README-共享记忆用法.md` 说明如何审批和修改记忆。

## 5. 验收与回滚

1. 每台设备分别确认 `memory_status` 的最后成功同步时间和待处理队列。
2. 一端保存候选测试事实，另一端同步后用相同 scope 检索，核对 `fact_id`。
3. 可在隔离测试事实上验证断网排队、恢复后同步；不要使用私人事实做演示。
4. 令牌遗失或暴露时，使用协调服务的撤销命令撤销对应设备，再重新签发并在该设备本地配对。
5. 备份客户端本地状态和服务端 SQLite 数据库；不要把数据库、令牌或个人 Vault 内容提交到公共仓库。
