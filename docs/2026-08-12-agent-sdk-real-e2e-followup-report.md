# Agent SDK 真机闭环跟进报告（2026-08-12）

## 结论

- DeepSeek 的 OpenAI-compatible 与 Anthropic-compatible 入口在充值后均已真实返回 HTTP 200，余额不再是阻断项。
- OpenCode Team 已完成真实闭环：原生子 Agent 实际调用 Catalog 与 Forgejo MCP，Web 问题回答回到原 Session，两名 Worker 均形成提交，集成 Gate 通过。
- Claude Code 已验证官方 Agent SDK 启动、MCP 注入、Web 权限请求与回答；但完整 Team Gate 被 CentOS/VMware 的宿主机 I/O 与 UI 异常中断，不能宣称 Claude 真机闭环完成。

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

## Claude 实机证据与剩余阻断

- Forgejo Issue：`196045/python-hello#8`
- 当前最小 Team Task：`ad7e81abfbbe41a0ad86acc92d732e61`
- `claude-a` 的 `session.started` 记录了 Catalog、Forgejo MCP 及同名 `nativeSubagentMcpServers`。
- 修正后真实运行的时间线不再出现 `thinking_tokens`；启动后的首轮仅产生 12 条结构化事件。
- Claude 发出 Bash 权限 Interaction，Web 回答 `allow` 返回 HTTP 200，证明决策请求已进入 Web API。
- 尚未取得 Claude 原生子 Agent 实际调用 MCP、`AskUserQuestion` 回答恢复、两个 Worker 提交及最终 Gate 证据。

阻断来自宿主机/VMware，而非模型或 Skillify 代码：CentOS 控制台出现 `drm_atomic_helper` soft lockup；VMware 日志随后记录 VMDK 写入失败 `errCode=1450 / Insufficient system resources`，并弹出 UI thread / desktop composition 异常。多次继续后仍复现。为避免继续异常断电 DM8，停止重复强制复位。试验性的 VM 3D 配置已恢复为原值 `mks.enable3d=TRUE`，没有把未验证的虚拟机调整留给用户。

## 当前交接

- 客户端麒麟 VM 和 `skillctl agent bridge` 在最后一次检查时仍运行。
- CentOS VM 当前需要用户在 VMware Workstation 图形界面中点击启动，并在 I/O 异常框选择用户此前确认可用的“继续”。
- CentOS 恢复后使用项目脚本 `scripts/deployment/skillify-docker.sh start` 启动，不使用 Docker Compose、不创建备份。
- 服务恢复后只需继续 Issue 8 / Claude Task 的最小路径；OpenCode 不需要重跑。
