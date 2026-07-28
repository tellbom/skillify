# Agent SDK 托管与 Web 决策闭环阶段报告（2026-07-28）

## 当前结论

本轮代码已补齐 OpenCode 与 Claude Agent SDK 的结构化事件、用户问题回传、原会话回答、子 Agent MCP 继承、运行失败归一化和 Web 时间线展示。当前不能给出真机完成结论：客户端和服务器的 NAT 端口可建立 TCP 连接，但 SSH 在 banner exchange 阶段超时，Skillify、Forgejo、Keycloak 也未返回 HTTP 响应，因此最新代码尚未重新部署，OpenCode/Claude Team 两条真实 Issue 链路也尚未重跑。

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

- Windows 仅用于不依赖 POSIX 的 Agent Host/Web 聚焦验证：
  - `agent-host npm run build`：通过。
  - `agent-host npm test`：4/4 通过，覆盖 OpenCode 与 Claude 单问题和多问题回答映射。
  - Web 聚焦测试：5/5 通过（在本轮前次改动后执行）。
  - Web production build：通过（在本轮前次改动后执行）。
- 最新问题映射改动之前，客户端 Linux 已执行 Agent Host build 和 Python 聚焦测试，结果为 15 passed。由于虚拟机随后冻结，最新差异尚未在 Linux 重跑。

## 既有真实链路证据

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

2026-07-28 当前观测：

- `192.168.124.2:2222` 与 `:2223`：TCP 可连接，SSH 在 banner exchange 超时。
- `:18090`、`:3000`、`:18085`：TCP 可连接，但 8 秒内无 HTTP 响应。
- 尚未把本轮最新代码部署到服务器，也未提交或推送本轮未验证差异。

虚拟机恢复后只执行以下必要步骤：

1. 同步差异到客户端，运行 Agent Host build/4 个测试及 Python 桥接、MCP 注入、worktree 聚焦测试。
2. 使用 Docker CLI 部署脚本更新服务器代码，不使用 Compose、不做备份。
3. 验证 RBAC、Keycloak、Forgejo 和 Skillify API。
4. 分别以 Issue 6、Issue 7 创建 OpenCode Team、Claude Team 最小任务，验证子 Agent MCP、Web 决策、原 Session 恢复、commit/integration/Gate。
5. 若模型仍返回 402，记录为供应商阻断，不伪造完成结论；余额恢复后再完成两条闭环。
6. 真机证据完成后提交并推送当前 Git 工作区。

