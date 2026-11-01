# Linux 桌面与 VPS

## A. Linux 桌面电脑

建议 Python 3.12 或发行版现有 3.11+。Debian/Ubuntu 例：

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv
python3 --version
```

发行版默认 Python 小于 3.11 时不要覆盖系统 Python；安装独立 3.12 并设置 `MEMORY_SHARE_PYTHON`。Fedora 可使用 `sudo dnf install python3 python3-pip` 后核实版本及 venv 可用性。

```bash
cd "$HOME/Tools/memory-share-kit"
bash installers/install-obsidian-unix.sh
bash installers/install-unix.sh linux-main "$HOME/Documents/MyVault"
MEMORY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/memory-share"
MEMORY_PYTHON="$MEMORY_ROOT/venv/bin/python"
"$MEMORY_PYTHON" -m memory_share --state "$MEMORY_ROOT" configure --server 'https://你的已有受限入口'
"$MEMORY_PYTHON" -m memory_share --state "$MEMORY_ROOT" sync
```

Obsidian AppImage 按 `uname -m` 选择 x86_64/ARM64，校验后安装于 `~/.local/opt/obsidian-memory-share`，启动：

```bash
"$HOME/.local/bin/obsidian-memory-share"
```

需要图形桌面。FUSE 不可用时，Ubuntu 24.04 可安装 `libfuse2t64`，旧版 Ubuntu 对应 `libfuse2`；先核对发行版，不要盲目安装不匹配包。也可以手动下载经校验的 amd64 Deb：

```bash
python3 tools/download_obsidian.py linux-deb-amd64 --output downloads
sudo apt install ./downloads/obsidian_1.14.5_amd64.deb
```

不使用 `--no-sandbox`，不以 root 启动 Obsidian。已有原生 Obsidian 可直接使用，不必再装 AppImage。

### 客户端自启动

```bash
mkdir -p "$HOME/.config/systemd/user"
cp "$MEMORY_ROOT/autostart/memory-share-client.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now memory-share-client.service
systemctl --user status memory-share-client.service
```

桌面默认登录后运行。若明确需要注销后继续运行，管理员可对该用户启用 linger；不要默认修改这项设置。

若发行版无 systemd，暂用 `"$MEMORY_PYTHON" -m memory_share --state "$MEMORY_ROOT" worker` 前台验证，再接入本机既有服务管理器，不假装 systemd 命令适用于所有 Linux。

## B. VPS 协调端（无桌面无需 Obsidian GUI）

把安装包复制至 VPS 独立目录。使用普通用户，不进入 Hermes venv，不运行 Hermes 更新命令。

```bash
cd "$HOME/Tools/memory-share-kit"
bash installers/install-server-linux.sh
SERVER_ROOT="$HOME/.local/share/memory-share-server"
SERVER_PYTHON="$SERVER_ROOT/venv/bin/python"
```

默认只绑定 `127.0.0.1:8731`。若你的现有连接安排要求绑定另一个地址，安装前设置 `MEMORY_SHARE_BIND_HOST` 为你已有的受限接口地址；不需要改成无认证公网服务。新服务所有数据接口始终要求令牌。

为每台设备分别发放令牌（同一设备重新执行会轮换令牌）：

```bash
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device win-main
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device mac-main
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device linux-main
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" issue-token --device vps-hermes
```

这是唯一有意输出令牌的命令。不要贴到聊天、日志或截图；分别在相应设备 configure 隐藏输入。撤销使用 `revoke-token --device ID`。

### 协调服务自动启动

```bash
mkdir -p "$HOME/.config/systemd/user"
cp "$SERVER_ROOT/autostart/memory-share-server.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now memory-share-server.service
systemctl --user status memory-share-server.service
```

服务器要在开机且无人登录时恢复，管理员执行 `sudo loginctl enable-linger 用户名`（替换真实服务用户）；随后确认 `loginctl show-user 用户名 -p Linger`。若使用系统级服务而非用户服务，应按现有运维规范设置普通用户，不要直接以 root 运行整个包。

### VPS 上的 Hermes 也用本地客户端

协调主库与客户端数据库分开。可以在同一台 VPS 再运行普通客户端安装脚本，设备 ID 为 `vps-hermes`。它通过 loopback 连接协调端，并用生成的 `hermes.config.yaml` 合并 MCP；不要让 Hermes 直接操作 authority.sqlite3。

### 每日备份与真实 OneDrive 上传

手动先验证：

```bash
"$SERVER_PYTHON" -m memory_share --state "$SERVER_ROOT" backup-upload --directory "$HOME/.local/share/memory-share-backups" --remote '你的remote:MemoryBridgeBackups'
```

命令生成一致性 SQLite 备份，`rclone copyto` 上传，再 `rclone cat` 读取远端字节核对 SHA256。只有 `uploaded:true, verified:true` 才表示远端验证成功。没有真实 remote 时去掉 `--remote` 只能生成本地备份。

为自动执行创建用户单元；下列绝对路径必须按实际用户名替换，不使用字面 `$HOME`：

```ini
# ~/.config/systemd/user/memory-share-backup.service
[Unit]
Description=Memory Share verified backup
[Service]
Type=oneshot
UMask=0077
ExecStart=/home/用户名/.local/share/memory-share-server/venv/bin/python -m memory_share --state /home/用户名/.local/share/memory-share-server backup-upload --directory /home/用户名/.local/share/memory-share-backups --remote 你的remote:MemoryBridgeBackups
```

```ini
# ~/.config/systemd/user/memory-share-backup.timer
[Unit]
Description=Daily Memory Share backup
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=300
[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now memory-share-backup.timer
systemctl --user list-timers
```

本版不自动删除备份，避免未确认远端恢复能力时清理唯一副本。至少保留 30 天，观察数据量后制定保留策略。远端故障时本地备份保留；下一次任务生成并上传新的完整备份，历史未传文件也应保留。见运维指南恢复步骤。
