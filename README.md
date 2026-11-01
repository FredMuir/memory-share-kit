# 多电脑 Agent 共享记忆安装包 v0.1.3

核心：Windows / macOS / Linux 上的 Hermes、Codex、MiniMax Code 等工具，通过**本机 stdio MCP**共用本机 SQLite；后台同步进程把事件提交到 VPS。VPS 故障不影响本机记忆工具。Obsidian 是人可读视图；Noema 是边缘离线辅助。

## 开发目标

让同一个用户在不同电脑、不同 Agent 之间延续项目知识和工作经验，无需反复介绍背景，也无需日常手工导入导出或处理 Git 同步。

- **跨工具共享**：Hermes、Codex、MiniMax Code 等使用统一记忆协议，保留各自原生记忆与会话。
- **本地优先**：每台电脑可读取已有快照、持久保存新增；VPS 故障期间继续工作，恢复后自动补传。
- **可靠一致**：事件 ID 幂等、稳定事实标识、版本检查、撤销记录和显式冲突处理，避免重复同步与静默覆盖。
- **一个 Vault**：Obsidian 阅读和整理长期知识；OneDrive 同步普通笔记、保存导出与备份，不同步运行数据库。
- **低维护与可扩展**：复用现有网络与免费工具，提供三平台安装、自启动、测试、故障排查和回滚；以后可接入更多 Agent。
- **移动端补充**：Noema 利用已导入的本机资料和记忆离线检索、分析，并在实际可用工具范围内行动；不把未验证接口作为核心依赖。

完整的目标、验收标准、当前进度与分阶段路线见 [开发目标与路线图](docs/00-DEVELOPMENT-GOALS.md)。这里描述的是开发方向，完成情况以该文档和实际测试记录为准。

这是可运行的源码安装包，不是架构示意或接口桩。当前已在 Linux CPython 3.12 测试真实 HTTP、SQLite 和 MCP SDK。Windows、macOS 的安装器和自启动文件已提供，**尚未在对应系统实机执行**；不得据此声称三平台已经部署。没有访问生产 VPS。

## 从这里开始

1. 阅读 [精确行动指南](docs/01-ACTION-GUIDE.md)，先配置 VPS，再安装一台电脑试运行。
   若需在局域网部署协调端，按 [局域网部署模板](docs/LAN-DEPLOYMENT.md) 操作，并替换其中的占位符。
2. 系统安装：[Windows](docs/02-WINDOWS.md)、[macOS](docs/03-MACOS.md)、[Linux 桌面与 VPS](docs/04-LINUX.md)。
3. 连接 Agent：[Hermes / Codex / MiniMax Code](docs/05-AGENTS.md)。
4. 配置 [Obsidian OneDrive Sync 与 Noema](docs/06-OBSIDIAN-NOEMA.md)。
5. 执行 [验收、故障排查与回滚](docs/07-OPERATIONS.md)。
6. 可复制的 [平台安装提示词](prompts) 和 [Agent 共享记忆规则](prompts/AGENT-COMMON.txt)。

## 优化后的实现

- 不为每台电脑额外开放 HTTP 服务。Agent 各自启动 stdio MCP 进程，共用一个本机 SQLite 文件。
- 多进程 SQLite WAL 处理本机并发；同步使用操作系统文件锁，同一时间只有一个同步任务。进程退出或被杀后操作系统释放锁。
- MCP 活跃时每 30 秒尝试同步。原生自启动 worker 让 Agent 关闭后也能补传；电脑关机或休眠期间不运行。
- 权威事实的版本使用事件 UUID，不使用会在数据库恢复后重复的简单整数。
- 同事件重试幂等；稳定 scope+key 识别同一事实；语义相似内容不擅自合并。
- 每电脑存储确认快照、本地事件和确认回执。恢复旧备份时更换 epoch，客户端重放保留事件。
- v0.1 保留全部事件/回执，不自动清理。日志压缩与摘要属于后续版本，不能先删除恢复所需记录。
- 个人 global、项目 project:ID、设备 local 三种范围；local 永不上载。
- 中文搜索采用确定性子串匹配，支持短词；目前没有向量检索、FTS 索引或自动 LLM 摘要。后续按规模增加，不冒充已实现。
- Hermes 原生记忆不变。本版统一走 MCP；原生 MemoryProvider 自动镜像不在本版实现范围。
- 所有检索文字是资料，不是授权或可执行指令。

## 安装文件

- `installers/install-windows.ps1`：Windows 本机安装。
- `installers/install-unix.sh`：macOS / Linux 本机安装。
- `installers/install-server-linux.sh`：VPS 独立目录安装，不自动启动。
- `installers/install-obsidian-*.{ps1,sh}`：获取并校验官方 Obsidian 安装文件，再安装。
- `installers/obsidian-assets.json`：Obsidian 1.14.5 官方下载资产与 SHA256。
- `tools/autostart.py`：生成 Windows 计划任务、macOS launchd、Linux systemd 用户单元。
- `requirements.lock`：固定本次已验证依赖，包含 Windows 条件依赖。
- `dist/memory_share_kit-0.1.3-py3-none-any.whl`：三平台通用的本包 Python 安装文件；依赖另从固定清单安装。
- `memory_share/`：完整 Python 程序；`tests/`：自动化测试。

Obsidian 安装器从官方 GitHub 下载，未打包重新分发的大体积 EXE/DMG。第一次安装需要网络和 Python 3.11+，建议 3.12。Agent 自身与模型账号不由此安装包安装或收费。

解压后先运行 `python tools/verify_bundle.py` 检查包内文件一致性。CHECKSUMS 是校验清单，不是发布者数字签名。

## 两条硬性配置

1. **私有状态目录不得放在 Vault、OneDrive、iCloud 或任何同步目录。** 不要同步 `client.sqlite3`、`authority.sqlite3` 或令牌。
2. **每台 Obsidian 的 Remotely Save 排除 `40-Agent-Memory/` 整个目录。** 这是各电脑自己渲染的视图；普通笔记继续同步。不要把同一目录再交给其他同步器。

首次 MVP 先用测试 Vault。正式迁入现有 Vault 前先备份，并保留已有目录和文件。脚本不覆盖已有 Agent 配置，不自动安装 Obsidian 社区插件，不操作现有 rclone 授权。

## 验证与边界

运行：`python -m unittest discover -s tests -v`（使用已安装依赖的 Python，允许本机 loopback 端口）。

MCP 工具存在不等于 Agent 会自动调用。用项目 `AGENTS.md` 规则引导，验证实际工具记录。没有跨产品通用的可靠会话结束 hook，故不承诺抓取所有对话。宿主模型不可用时，记忆层不能代替模型推理。

Noema 的导入资料可离线用；自动关联 Vault、自动更新索引和离线记忆自动回流尚未验证。不要把资料包生成成功当成 Noema 已导入成功。

所有用户属于同一信任域，设备令牌授予整个共享空间读写权限。本版不实现多人隔离、角色权限、公开互联网防护或认证反向代理。服务器默认 loopback，沿用你已有的受限访问入口；所有记忆接口要求设备令牌。
