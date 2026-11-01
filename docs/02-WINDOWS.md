# Windows 安装

目标 Windows 10/11，PowerShell 5.1+，建议 Python 3.12。先将整个包解压到本机普通目录，例如 `C:\Tools\memory-share-kit`。不要只拷贝某个脚本。

## 1. 前置条件

普通 PowerShell：

```powershell
winget install --exact --id Python.Python.3.12
```

安装后重开终端，检查 `python --version`。若 Windows App Execution Alias 指向商店占位符，使用 `py -3.12 -c "import sys; print(sys.executable)"` 得到真实 Python 路径，传给下文的 `-PythonCommand`。不要因此升级全部 Python 环境。

无 winget 时使用官方 https://www.python.org/downloads/windows/ 安装 Python 3.12，并启用 pip；现有符合版本的 Python 可直接用。

## 2. 安装 Obsidian

```powershell
Set-Location 'C:\Tools\memory-share-kit'
powershell -NoProfile -ExecutionPolicy Bypass -File .\installers\install-obsidian-windows.ps1
```

Bypass 只作用于本次 PowerShell 进程，不修改全局执行策略。脚本先下载固定的官方 EXE、核对 SHA256，再打开 GUI 安装器。已有安装保持不动。

## 3. 安装本地记忆层

把路径替换为真实 Vault，脚本只补充缺少的目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installers\install-windows.ps1 -Device 'win-main' -Vault "$env:USERPROFILE\Documents\MyVault"
$MemoryRoot = Join-Path $env:LOCALAPPDATA 'MemoryShare'
$MemoryPython = Join-Path $MemoryRoot 'venv\Scripts\python.exe'
& $MemoryPython -m memory_share --state $MemoryRoot status
```

状态与凭据在 `%LOCALAPPDATA%\MemoryShare`，脚本限制目录 ACL。不要移到 OneDrive，不要把此目录复制给另一台电脑。

## 4. 配对与同步

选择本机当前可达的 VPS LAN 地址或 Tailscale 地址：

```powershell
& $MemoryPython -m memory_share --state $MemoryRoot configure --server 'http://<VPS_LAN_OR_TAILSCALE_ADDRESS>:8731' --allow-private-http --no-auth
& $MemoryPython -m memory_share --state $MemoryRoot sync
```

私网模式不提示输入令牌。VPS 会拒绝非私网来源；不要配置端口转发。MCP 配置仍需在 Codex 中合并一次，之后可直接使用本机队列。

`sync` 必须返回 `"ok":true`；不是仅检查 /healthz。

## 5. 合并 Agent 配置

生成文件在 `$MemoryRoot\generated-config`。按 [Agent 指南](05-AGENTS.md) 合并；其中已经写入正确的 Windows Python 绝对路径，无需手动转义反斜杠。不要把 JSON 直接粘贴为 TOML。

## 6. 登录自启动

先查看生成脚本，再执行：

```powershell
Get-Content (Join-Path $MemoryRoot 'autostart\enable-client-task.ps1')
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $MemoryRoot 'autostart\enable-client-task.ps1')
Get-ScheduledTask -TaskName 'MemoryShare-client'
```

任务以当前用户登录启动，不要求管理员权限，不要求网络可用才能启动；30 秒循环尝试同步并导出。注销/关机后停止，下次登录恢复。MCP 工具本身可按需启动，不依赖任务已运行。

停止和移除启动项：

```powershell
Stop-ScheduledTask -TaskName 'MemoryShare-client'
Unregister-ScheduledTask -TaskName 'MemoryShare-client' -Confirm:$false
```

这不会删除数据。不要在任务运行时删除虚拟环境。

## 7. 本机验收

```powershell
$env:PYTHONUTF8 = '1'
& $MemoryPython -m unittest discover -s .\tests -v
```

允许测试绑定本机临时 loopback 端口。完成跨电脑验收后记录 Windows 版本、CPU、Python 与 Agent 版本。
