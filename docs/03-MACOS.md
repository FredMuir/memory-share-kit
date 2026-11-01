# macOS 安装

支持 Apple Silicon / Intel，建议 Python 3.12；实际依赖轮子需适配系统版本。源码位于普通本机目录，例如 `~/Tools/memory-share-kit`。

## 1. Python

若已使用 Homebrew：`brew install python@3.12`。不要为了本项目强制安装 Homebrew；也可从 https://www.python.org/downloads/macos/ 安装 Python 3.12。

检查 `python3 --version`。如需指定 Homebrew Python：

```bash
export MEMORY_SHARE_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
```

脚本使用此变量选择解释器，不依赖 GUI App 的 PATH。

## 2. Obsidian 与本地服务

```bash
cd "$HOME/Tools/memory-share-kit"
bash installers/install-obsidian-unix.sh
bash installers/install-unix.sh mac-main "$HOME/Documents/MyVault"
```

Obsidian 官方通用 DMG 经 SHA256 校验后安装到 `~/Applications`；已有 `/Applications/Obsidian.app` 或用户安装保持不动。没有关闭 Gatekeeper、没有修改系统安全策略。

打开 Obsidian，选择实际 Vault。按 [同步设置](06-OBSIDIAN-NOEMA.md) 排除生成视图。

## 3. 配对

```bash
MEMORY_ROOT="$HOME/Library/Application Support/MemoryShare"
MEMORY_PYTHON="$MEMORY_ROOT/venv/bin/python"
"$MEMORY_PYTHON" -m memory_share --state "$MEMORY_ROOT" configure --server 'http://<VPS_LAN_OR_TAILSCALE_ADDRESS>:8731' --allow-private-http --no-auth
"$MEMORY_PYTHON" -m memory_share --state "$MEMORY_ROOT" sync
```

LAN/Tailscale 模式不需要设备令牌。确认服务仅限私网来源，不配置公网转发。

## 4. Agent 接入

`$MEMORY_ROOT/generated-config` 中是已展开绝对路径的片段。合并方式见 [Agent 指南](05-AGENTS.md)。即使从 Finder 启动 IDE，也不依赖终端 PATH。

## 5. 登录自启动

```bash
mkdir -p "$HOME/Library/LaunchAgents"
cp "$MEMORY_ROOT/autostart/org.memoryshare.client.plist" "$HOME/Library/LaunchAgents/"
plutil -lint "$HOME/Library/LaunchAgents/org.memoryshare.client.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/org.memoryshare.client.plist"
launchctl print "gui/$(id -u)/org.memoryshare.client"
```

同名任务已载入时先 `launchctl bootout "gui/$(id -u)/org.memoryshare.client"`，再 bootstrap，不能重复载入。LaunchAgent 在用户登录后工作，电脑睡眠时不承诺运行。

日志是 `$MEMORY_ROOT/client.err.log` 和 `client.out.log`，长期使用需定期轮换；状态以 `memory_share status` 为准。此版本日志不输出记忆正文或令牌。

停用：

```bash
launchctl bootout "gui/$(id -u)/org.memoryshare.client"
rm "$HOME/Library/LaunchAgents/org.memoryshare.client.plist"
```

仅删除自启动文件，保留 SQLite 和队列。

## 6. 本机测试

在包根目录执行：

```bash
"$MEMORY_PYTHON" -m unittest discover -s tests -v
```

需要实际 Mac 与本机 loopback；当前交付时尚未运行 macOS 真机测试。
