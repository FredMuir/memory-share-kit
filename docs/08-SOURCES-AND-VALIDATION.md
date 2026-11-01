# 来源与验证记录

核对日期：2026-10-31。安装和产品能力会变化，配置异常先核对实际版本。

| 内容 | 官方来源 | 本包使用方式 |
|---|---|---|
| Obsidian 下载 | https://obsidian.md/download | 官方链接指向 obsidianmd/obsidian-releases |
| Obsidian 资产 | https://github.com/obsidianmd/obsidian-releases/releases/tag/v1.14.5 | 读取 GitHub release asset SHA256，固定下载，不重分发 EXE/DMG |
| Codex MCP | https://developers.openai.com/codex/mcp/ | 本机 stdio、config.toml 配置 |
| Hermes MCP | https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp | mcp_servers 配置，不修改原生记忆 |
| MiniMax Code | https://github.com/MiniMax-AI/minimax-code/blob/main/packages/local-runtime-v2/docs/project-mcp.md | 项目 .mcp.json，stdio 支持 |
| MCP Python SDK | https://pypi.org/project/mcp/1.30.0/ | 固定到已测 v1 API；没有声称使用最新主版本 |
| Remotely Save | https://github.com/remotely-save/remotely-save | 唯一负责普通笔记同步 |
| OneDrive App Folder | https://github.com/remotely-save/remotely-save/blob/master/docs/remote_services/onedrive/README.md | 按真实授权目录，不假定任意根目录 |
| Noema 数据集 | https://noemaai.com/docs/dataset-integration | 本地导入/索引，自动刷新待实测 |
| Noema 同步范围 | https://noemaai.com/docs/constellation | 数据集/索引留在设备，不等于聊天同步 |
| Obsidian Mobile 开发 | https://docs.obsidian.md/Plugins/Getting%20started/Mobile%20development | 不将桌面 Node 插件当作 iOS 服务器 |

## 本地已执行

- Linux CPython 3.12，安装固定 MCP SDK，运行真实 stdio ClientSession initialize/list_tools/call_tool。
- 真实 ThreadingHTTPServer + SQLite 集成测试，包含重复提交、离线持久队列、并发更新、备份恢复。
- bash 语法检查、Python 编译、JSON/TOML 配置解析。
- 对安装脚本、自启动模板与导出行为进行检查；具体测试结果另见 TEST-RESULTS.txt。

## 尚未执行

- Windows/macOS 实机安装、原生计划任务/launchd 执行、各自 Agent 的 UI 验收。
- 生产 VPS 部署与现有 Hermes gateway 重启。
- 实际 OneDrive remote 上传和恢复（本会话未提供授权环境）。
- Noema 真机导入、离线索引与工具执行。
- 官方 Obsidian EXE/DMG/AppImage 安装操作；下载器使用已核对官方资产哈希，安装发生在用户目标电脑。

这些边界必须保留在对外说明里，不能用测试客户端或脚本语法检查冒充目标产品的实际部署成功。
