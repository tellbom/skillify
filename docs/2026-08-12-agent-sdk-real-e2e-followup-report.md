# Agent SDK 真机闭环跟进报告（2026-08-12）

## 结论

- DeepSeek 的 OpenAI-compatible 与 Anthropic-compatible 入口在充值后均已真实返回 HTTP 200，余额不再是阻断项。
- OpenCode Team 已完成真实闭环：原生子 Agent 实际调用 Catalog 与 Forgejo MCP，Web 问题回答回到原 Session，两名 Worker 均形成提交，集成 Gate 通过。
- Claude Code Team 已完成真实闭环：原生子 Agent 实际调用 Catalog 与 Forgejo MCP，`AskUserQuestion` 从 Web 回到原 Session，两名 Worker 均形成提交与 Issue 评论，集成 Gate 通过。
- Web 强制取消已完成真实复核：Claude SDK Session 启动后由 Web 请求取消，端侧发出 `provider.aborted`，Task 与 Worker 均收敛为 `cancelled`，且无残留 Agent Host/Claude 进程。
- 功能验收已经闭环；宿主机 VMware 仍会同时对两台 VM 报 VMDK `errCode=1450`，这是独立的测试环境稳定性问题。

## OpenCode 成功证据

- Forgejo Issue：`196045/python-hello#6`
- Task：`49aeae2269f441fca3c8f08704409d5f`
- Worker：`opencode-a`、`opencode-b`
- 主 Session：`ses_00ae73a60ffeYeyMX5TV1YfxKY`
- 原生子 Agent Session：`ses_00ae7041dffe0YkPQwYhLdCpKb`
- 子 Agent 实际完成 `catalog_skills_search` 与 `forgejo_forgejo_get_issue` 调用；不是只检查配置名称。
- Web Interaction：`ai-1ba7419bd34b4cb685c6ea8f66f71e21`，选择 `alpha` 后状态依次到 `responded`、`delivered`、`applied`，原 Session 继续执行。
- 一个 Worker 等待用户时另一个 Worker 保持运行，验证 Team 决策不是全局阻塞。
- 集成提交：`94693d0`、`dbbedbf`、`355ab19`；Task 最终为 `succeeded`。

## 本轮阻断修正

1. Claude SDK 的 `subtype=thinking_tokens` 不再作为 `provider.event` 写入控制面时间线，避免每个思考增量形成 DM8 事件。
2. Claude 中断先由 Agent Host 本地 AbortController 终止进程并发出 `provider.aborted`，SDK `interrupt()` 只做有界的尽力通知，避免等待 SDK 回执而永久停在 `cancelling`。
3. Bridge 已确认向运行器交付取消后，如退出阶段发生控制面传输竞争，终态收敛为 `task.cancelled/user-cancelled`，不再误报 `provider-runtime-error`。

## 聚焦测试

- Windows Agent Host：`npm run build && npm test`，5/5 通过。
- 麒麟 Agent Host（Node 24）：`npm run build && npm test`，5/5 通过。
- 麒麟 Bridge：`pytest tests/test_bridge.py -q`，5/5 通过。
- Windows Python 测试仍受项目既有 POSIX `fcntl` 依赖限制；同一用例已在目标 Linux 通过。

## Claude Code Team 成功证据

- Forgejo Issue：`196045/python-hello#8`
- 成功 Task：`abc9112cf4f544cf9fb3558baca8a02f`
- `claude-a`、`claude-b` 的 `session.started` 均记录 Catalog、Forgejo MCP 为 `connected`，并记录同名 `nativeSubagentMcpServers`。
- `claude-a` 调用原生 `Agent` 后，子 Agent `a1e8ccaa1c73edf0c` 实际完成 Catalog `skills.search` 与 Forgejo `get-issue`；证据已写入 `skillify-claude-team-a.md`，不是只检查注入配置。
- `AskUserQuestion` Interaction `ai-63ee6e1e46cf4bb3a4dee5f51a1c1c03` 选择 `gamma`，状态到 `applied`，原 Session 随后继续写文件、评论 Issue 和提交。
- Worker A 分支提交 `3f3336e`，Worker B 分支提交 `561a12b`；集成工作区提交为 `3443003`、`2a0bf08`，工作区最终干净。
- Forgejo Issue 评论 ID 为 `44`、`45`，分别记录两名 Worker 的 MCP、文件、测试和提交证据。
- 两名 Worker 最终均为 `succeeded / gate passed`，Task 为 `succeeded`；Gate 的集成 head 为 `2a0bf089d161cc19518f5a2565300c67fe38057c`。
- 时间线共 142 条结构化事件，没有恢复被过滤的 `thinking_tokens` 噪声。

## Web 强制取消成功证据

- 取消 Task：`319c7d8b2c634946aaa780290de50c35`
- `interrupt-a` 已真实启动 Claude SDK Session `8859fa60-da77-4a87-ad31-3fec289e0f61` 后，Web 调用取消接口返回 HTTP 200。
- Task 状态由 `cancelling` 收敛为 `cancelled`，Worker 状态为 `cancelled`；未启动依赖 Worker `interrupt-b`。
- 运行时事件依次包含 `session.started` 与 `provider.aborted`，没有产生 `task.failed/provider-runtime-error`。
- 端侧 Bridge 保持运行，检查不到该 Task、Agent Host 或 Claude 子进程残留。

## 测试环境稳定性

宿主机/VMware 的问题仍然存在，但不再阻断上述功能证据：CentOS 控制台出现 `drm_atomic_helper` 与 NMI watchdog soft lockup；两台 VM 的 VMware 日志会在同一时间记录 VMDK 读写失败 `errCode=1450 / Insufficient system resources`。本轮仅通过宿主机命令控制 VM、隔离异常退出遗留的 `.lck` 目录并重新启动，没有修改 VMDK、快照、数据库或 VM 配置。试验性的 VM 3D 配置仍为原值 `mks.enable3d=TRUE`。

## 当前交接

- 最新提交 `c847038` 已同步到服务器和端侧；服务器已通过 `scripts/deployment/skillify-docker.sh deploy-code` 重建并运行，未使用 Docker Compose、未创建备份。
- 客户端麒麟 VM 与 `skillctl agent bridge` 最后检查为运行状态；当前 Bridge PID 为 `10102`。
- OpenCode 与 Claude Code 的 Team 功能闭环均已通过，Web 取消闭环也已通过；本任务没有剩余功能测试节点。
- 后续应把 VMware `errCode=1450` 作为宿主机运维问题单独处理，不应把 TCP 端口可连接视为 VM/应用健康。
