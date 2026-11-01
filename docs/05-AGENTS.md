# Hermes、Codex、MiniMax Code 接入

三平台使用相同工具协议，区别仅在生成的绝对 Python 路径。先完成本机安装、configure 和 sync。配置生成器不修改原文件，也不自动设置宽泛权限。

生成片段包含本机绝对路径，只用于本机合并；不要把它们作为共享记忆同步，也不要未经检查提交到项目仓库。不同电脑分别生成自己的配置，项目事实仍用同一个稳定 project_id。

## 1. Codex CLI / 使用本机配置的 IDE

生成文件：私有状态目录下 `generated-config/codex.config.toml`。

1. 备份用户主目录的 `.codex/config.toml`（若设置 CODEX_HOME，使用该目录）。
2. 将生成的 `[mcp_servers.shared-memory]` 小节合并进去；若同名小节已经存在，先比较，不能再添加重复 TOML table。
3. 保留所有其他模型、权限和 MCP 配置。
4. 重启 Codex / IDE，运行 `codex mcp list` 或界面的 MCP 检查。
5. 让 Agent 实际执行 `memory_status`，不能仅看 configured。

也可通过官方 CLI 注册（参数使用实际绝对路径）：

```text
codex mcp add shared-memory -- ABSOLUTE_PYTHON -m memory_share --state ABSOLUTE_STATE mcp --agent codex
```

路径含空格时按当前 shell 引号规则处理，优先合并已生成 TOML，避免手工转义。

官方依据：https://developers.openai.com/codex/mcp/ 。本机 CLI/IDE 配置不等于云端执行环境能访问你的电脑；Codex 云任务需单独具备运行包和连接条件，不在本包默认接入范围。

## 2. Hermes

生成文件：`generated-config/hermes.config.yaml`。

1. 确认正在使用的 HERMES_HOME / profile。
2. 备份该 profile 的 `config.yaml`。
3. 在已有的 `mcp_servers:` 映射内增加 `shared-memory:` 子项。若已有顶层 `mcp_servers`，不要粘贴第二个顶层键。
4. 不改 `memory` 配置，不替换 MEMORY.md / USER.md，不共享 state.db。
5. 按当前安装方式重启 Hermes（CLI 重新启动；gateway 按现有服务方式重启，不猜服务名）。
6. 在新会话实际调用 memory_status、memory_search、memory_store。

当前包只接 MCP。保留未来通过官方 MemoryProvider 自动检索的空间，但没有提供或假装已安装 provider hook。

官方依据：https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp 。

## 3. MiniMax Code

这里指官方 MiniMax Code / MCode 的本地 Runtime，不是 MiniMax 媒体 API MCP，也不是把 MiniMax 模型接到其他宿主后的任意工具。

1. 核对 `mcode --version` 和实际客户端。桌面版先核对它是否使用支持项目 `.mcp.json` 的 Runtime。
2. 在**项目主工作目录**备份已有 `.mcp.json`。
3. 合并 `generated-config/minimax-code.mcp.json` 内 `mcpServers.shared-memory`，保留其他键。
4. stdio command 是私有 venv 的绝对 Python；args 中的 --agent 为 minimax-code。
5. 重启并使用 standard 模式，不使用会省略工具的 lightweight 模式。
6. TUI 执行 `/mcp`，再实际调用 memory_status 和 memory_search。配置列表本身不能证明工具成功执行。

官方配置支持 stdio；只读取 session 主项目目录，不向上查找 `.mcp.json`。不同项目需合并各自配置。不能假定在父目录放一次就覆盖全部项目。

依据：https://github.com/MiniMax-AI/minimax-code/blob/main/packages/local-runtime-v2/docs/project-mcp.md 。版本差异先核对，不编造桌面配置入口。

## 4. 其他 Agent

若支持 stdio MCP，使用 `generated-config/generic.mcp.json` 的 command/args 按其官方格式接入，并把 --agent 改为真实名称。若只支持远程 HTTP MCP，不能把本包 `/v1/events` REST 当成 MCP URL：**本包尚未提供远程 MCP 服务**。这类客户端需另行适配，不影响本地 stdio 核心。

## 5. 提示词与自动化边界

相关文件：

- `prompts/AGENT-COMMON.txt`：共享检索与保存规则，合并进项目 AGENTS.md。
- `prompts/AGENT-CODEX.txt`、`AGENT-HERMES.txt`、`AGENT-MINIMAX-CODE.txt`：对应工具补充规则。
- `prompts/INSTALL-WINDOWS.txt`、`INSTALL-MACOS.txt`、`INSTALL-LINUX.txt`：交给目标电脑 Agent 的安装执行任务。
- `prompts/NOEMA-OFFLINE.txt`：导入资料后使用的离线助手规则。

指令只提高调用一致性；MCP 发现不是自动记忆注入。不要承诺每轮、每个会话都能被提示词完整捕获。检查工具调用记录确认行为。

## 6. 统一工具验收提示词

```text
实际调用 memory_status。用 project:memory-share-acceptance 检索“共享记忆验收”。
若不存在，调用 memory_store，key 为 acceptance.shared-memory，标题“共享记忆验收”，
正文“这是跨电脑验收数据，不是用户长期偏好”，certainty=candidate，source=当前测试会话。
报告 event_id / fact_id 和 queued 或 server acknowledgement，不能把本地保存写成已同步。
调用 memory_sync，再次 memory_search，附实际工具结果摘要。
```

第二台电脑只先同步并检索，不先写同一条事实。确认 fact_id 相同后，再进行运维指南中的并发测试。
