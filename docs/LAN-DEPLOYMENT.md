# 局域网部署模板

本文提供 VPS 协调端、Hermes MCP 客户端和 Windows Codex 客户端的通用部署步骤。请在本机维护实际 IP、端口、用户名、Vault 绝对路径和设备令牌；提交到公共仓库前一律保留占位符。

## 拓扑与边界

- VPS 上运行 Memory Share 协调服务和 Hermes。服务绑定 VPS 的局域网地址；Hermes Dashboard 按需监听网卡，并启用 Basic Auth。
- 每台设备使用自己的本地队列和设备令牌。网络中断时本地 Agent 继续工作；恢复连接后由 worker 同步队列，并在配置了 Vault 时导出 Obsidian 阅读视图。
- Obsidian 的 `40-Agent-Memory/Generated/` 可直接编辑标题和正文；客户端 worker 按 revision 自动提交。
- 协调端允许 LAN/overlay 无 token 访问，但只接受私有地址、ULA 和 Tailscale 地址。不要把服务端口转发到公网。

## 1. VPS 安装协调服务

设置部署时的实际局域网接口和端口。私网无 token 模式会绑定 IPv4 接口，并在服务层拒绝公网来源：

```bash
VPS_LAN_IP='<VPS_LAN_IP>'
MEMORY_SHARE_PORT='<MEMORY_SHARE_PORT>'
cd "$HOME/Tools/memory-share-kit"
MEMORY_SHARE_ALLOW_UNAUTHENTICATED_PRIVATE_NETWORK=1 \
MEMORY_SHARE_BIND_HOST='0.0.0.0' bash installers/install-server-linux.sh
SERVER_ROOT="$HOME/.local/share/memory-share-server"
SERVER_PYTHON="$SERVER_ROOT/venv/bin/python"
```

启用安装器生成的用户级 systemd unit。若服务需要在用户退出后继续运行，由管理员按 VPS 实际运行用户启用 linger。应用层拒绝非私网来源；不要配置路由器端口转发。检查健康状态后还要执行一次真实同步。无 token 模式下 Agent 和设备标签由客户端自报，服务端同时记录来源 IP。

## 2. Hermes 接入 shared-memory MCP

使用运行 Hermes 的普通 Linux 用户。共享 Vault 放在 Hermes 原生配置目录之外：

```bash
cd "$HOME/Tools/memory-share-kit"
HERMES_VAULT="$HOME/.local/share/memory-share-vault"
bash installers/install-unix.sh vps-agent "$HERMES_VAULT"
CLIENT_ROOT="$HOME/.local/share/memory-share"
CLIENT_PYTHON="$CLIENT_ROOT/venv/bin/python"
"$CLIENT_PYTHON" -m memory_share --state "$CLIENT_ROOT" configure \
  --server "http://${VPS_LAN_IP}:${MEMORY_SHARE_PORT}" --allow-private-http --no-auth
"$CLIENT_PYTHON" -m memory_share --state "$CLIENT_ROOT" sync
```

Hermes 与每台电脑只需首次设置可达的 LAN 或 Tailscale URL，不需要令牌。备份 Hermes 当前 profile 配置，只合并生成配置中的 `shared-memory` MCP 子项，不覆盖整份配置或原生记忆设置。对每个实际使用的 profile 重启/重新连接 Hermes，并调用 `memory_search` 验证。

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
  --server "http://${VpsLanIp}:$MemorySharePort" --allow-private-http --no-auth
& $Python -m memory_share --state $MemoryRoot sync
```

合并生成的 MCP 配置子项并重启 Codex。用 `memory_search` 检索共享事实；仅在排查同步时查看 `memory_status`。

## 4. Obsidian 与 OneDrive

VPS 和移动端可以使用社区插件 [OneDrive Sync](https://github.com/JeffSteinbok/obsidian-onedrive) 连接同一个 OneDrive App Folder。插件通过设备码授权。保持 Obsidian Vault 位于 rclone 挂载目录之外，避免两个写入器操作同一份本地文件；不要把 Vault 放进 rclone 挂载目录。`README-共享记忆用法.md` 说明直接编辑和冲突处理。

## 5. 验收与回滚

1. 确认客户端可在 LAN/overlay 内读取共享事实并同步；排查时查看 `memory_status`。
2. 一端保存候选测试事实，另一端同步后用相同 scope 检索，核对 `fact_id`。
3. 可在隔离测试事实上验证断网排队、恢复后同步；不要使用私人事实做演示。
4. 令牌遗失或暴露时，使用协调服务的撤销命令撤销对应设备，再重新签发并在该设备本地配对。
5. 备份客户端本地状态和服务端 SQLite 数据库；不要把数据库、令牌或个人 Vault 内容提交到公共仓库。
