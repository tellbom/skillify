# Agent SDK 托管与 Web 决策闭环阶段报告（更新至 2026-08-12）

## 当前结论

代码、Linux 聚焦测试、Docker CLI 部署、Keycloak 登录及真实 OpenCode/Claude Team Session 启动均已通过。两种 Provider 的 Session 启动事件都证明 Catalog、Forgejo MCP 已注入 Worker，并投影到原生子 Agent；Claude 还实证两个 MCP Server 均为 `connected`。当前仍不能给出完整闭环结论：两个模型入口都返回 HTTP 402 `Insufficient Balance`，因此模型没有机会实际调用 MCP、提出 Web Question、恢复原 Session、形成 Worker commit 或进入成功 Gate。

## 本轮修复

- OpenCode：
  - 使用与端侧 OpenCode 1.17.18 匹配的官方 SDK。
  - 使用 v2 Question API 接收 `question.asked` 并把回答送回原 request/session。
  - 单选、多选、自由文本和多问题回答保持各自问题边界。
  - 每个 Worker 的 MCP 配置由其本地 Server 继承到原生子 Agent。
  - Provider 错误优先于后续 idle，避免 402 等错误被误判为成功。
- Claude：
  - 使用 Agent SDK 的 `canUseTool` 决策回调，不依赖 TUI 字节流。
  - `AskUserQuestion` 的真实问题与选项进入 Web，多个问题分别映射回原始 question key。
  - 子 Agent 定义显式携带当前 Worker 的 MCP Server 名单。
  - SDK `result.is_error=true` 被识别为失败，不再形成假成功。
- skillctl/运行器：
  - Agent Host 启动 PATH 包含配置的 Provider 可执行文件目录。
  - Provider 运行异常形成可审计的 `task.failed`，不向 Web 泄露原始异常细节。
  - 重试时仅复用任务自己的 branch/worktree，拒绝错配工作区。
  - 最终成功仍由 commit、integration、测试和 Gate 决定。
- Web：
  - 展示归一化 Agent 文本、工具状态和安全错误摘要，不直接 JSON 展开 Provider 原始载荷。
  - 页面刷新后读取终态运行记录。
  - 决策卡仍通过 API/skillctl 回到对应 Provider Session，不提供可输入终端。

## MCP 与子 Agent

MCP 不参与修改模型推理，也不负责替代 Team 调度；它向当前 Worker 暴露受限工具。当前实现中，OpenCode 原生子 Agent 继承所在 Worker Server 的 MCP 工具集，Claude 子 Agent 通过 Agent Definition 显式继承同一名单。因此“派发给子 Agent 后 MCP 不起作用”的缺口已在代码上补齐，但仍需真机任务证明实际工具调用。

## 已完成的聚焦验证

- 客户端 Kylin Linux（2026-08-12）：
  - Agent Host `npm run build`：通过。
  - Agent Host `npm test`：4/4 通过，覆盖 OpenCode 与 Claude 单问题和多问题回答映射。
  - Python 桥接、MCP 注入、Agent Host PATH 与 worktree 聚焦测试：15/15 通过。
  - Web `endpointTasks.spec.js`：5/5 通过。
  - Web production build：通过。
- 验收过程中修正 Agent Host 测试命令：将 Linux 默认 shell 不支持的 `dist/**/*.test.js` 改为实际输出目录 `dist/*.test.js`，Windows 与 Linux 均通过。
- 服务器使用 `scripts/deployment/skillify-docker.sh deploy-code` 部署，不使用 Compose、不创建备份、不修改状态卷。部署后：
  - `skillify-skillify-web-1`、`skillify-frontend-1`：healthy。
  - 容器内确认 `first_terminal_outcome`、`host_environment`、`provider-runtime-error` 均来自新源码。
  - Skillify `/healthz`、Forgejo API、Keycloak OIDC discovery：HTTP 200。
  - Keycloak 用户令牌可访问受保护的 Endpoint/Task API：HTTP 200。

## 2026-08-12 真实链路证据

- OpenCode Team / Forgejo Issue 6：
  - Task Run：`a51bf046ed5c45979f18030c0924f6df`
  - Worker `opencode-a` Session：`ses_00af2d793ffeJcn2OCFK5w3IEQ`
  - Worker `opencode-b` Session：`ses_00af2cfa8ffeDjI4HNUhM9rC0c`
  - 两个 `session.started` 均记录 `mcpServers=[catalog, forgejo]` 和 `nativeSubagentMcpServers=[catalog, forgejo]`。
  - 两个 Session 均收到 HTTP 402，Task Gate 为 `provider-failed`；无 Interaction、commit 或实际 MCP 调用证据。
- Claude Team / Forgejo Issue 7：
  - Task Run：`52c612d708644e98820b0dfcaeb0098a`
  - Worker `claude-a` Session：`f07f3401-de5a-465e-83b0-851a8253815f`
  - Worker `claude-b` Session：`1f3ca680-7576-44f2-bbce-c6fe1e847516`
  - 两个 `session.started` 均记录 Catalog、Forgejo 为 `connected`，具有对应 MCP 工具名单，且 `nativeSubagentMcpServers=[catalog, forgejo]`。
  - Claude SDK 返回 `subtype=success` 但同时 `isError=true`、`apiErrorStatus=402`；当前 Adapter 正确生成 `provider.failed`，Task Gate 为 `provider-failed`，没有假成功。

## 历史真实链路证据

- OpenCode Task Run：
  - `16ad8a9564f34025abea6ccd55302267`
  - `dd698dd4bf7c4728a6e4ba25d78b6b56`
  - Forgejo Issue 6
- Claude Task Run：
  - `a251d57f5dfa491b931a3f2ef77cb452`
  - Forgejo Issue 7
  - Session 启动事件已显示 Catalog、Forgejo MCP 和子 Agent MCP 名单。

以上真实任务均被模型供应商 HTTP 402（余额不足）终止，不能作为成功闭环证据。代码已修正为明确失败，不再以 idle 或 Agent 文本冒充 Gate 成功。

## 当前阻断与恢复后最小步骤

当前唯一业务阻断是模型供应商余额。VM、SSH、客户端 bridge、DM8、Keycloak、Forgejo、Skillify 及部署版本已经恢复。余额或可用模型凭据恢复后只需：

1. 复用 Issue 6、Issue 7，重新创建两条最小 Team 任务。
2. 观察子 Agent 实际调用 Catalog/Forgejo MCP，而不只检查配置名单。
3. 分别触发 OpenCode Question 与 Claude `AskUserQuestion`，在 Web 回答后确认原 Session 继续。
4. 验证一个 Worker `waiting_user` 时另一个继续运行。
5. 保存 Interaction ID、回答、恢复事件、Worker commit、integration commit 和最终 Gate 结果。

模型继续返回 402 时必须保持 `provider.failed/gate.failed`，不得将 Session 启动、MCP connected、Provider idle 或 Agent 文本当作完成。
