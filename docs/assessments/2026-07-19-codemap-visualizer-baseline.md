# Skillify 人用 Code Map 可视化 · P0 基线

> 日期：2026-07-19
> 仓库基线：`main@88683b4`
> 状态：T0.1、T0.2 `implemented=yes / dev_verified=yes / env_verified=no`

## 1. 已确认边界

- Agent 使用的 CodeGraph 固定为 `colbymchenry/codegraph v0.9.6`，来源和 Linux x64/arm64 构件位于 `infra/offline/codegraph-manifest.json`。
- `src/skillify/agent/codegraph.py` 只负责 manifest、checksum、安装、版本、`init/sync` 和降级状态。
- OpenCode 在 `src/skillify/agent/opencode_config.py`、Claude Code 在 `src/skillify/agent/claudecode_config.py` 中通过 `codegraph serve --mcp` 注册 `codegraph_explore`。
- 当前 `web/package.json` 没有图谱渲染依赖，`web/src` 没有 Code Map 页面。
- 本轮 Visualizer 必须保持独立索引、独立进程和独立状态目录，不能进入 Agent、MCP 或 Workflow。

## 2. 禁止触碰的核心

| 文件/行为 | 基线 SHA256 或约束 |
| --- | --- |
| `src/skillify/agent/codegraph.py` | `f2ca25a62599d0e0f0cc33053bea1413bed118f99fbcadaef409a82419d2cede` |
| `infra/offline/codegraph-manifest.json` | `7752ce85c49ef3d805c8209e0c0022327f8d078da3ab071d3a50c8f5b4074aaa` |
| `src/skillify/agent/opencode_config.py` | `d191f710601ec97d0d09a28dbbfb91ebd66e1b6abce4fb3c3ff4ab4fe2196466` |
| `src/skillify/agent/claudecode_config.py` | `4232f43de8ae7c57bcb5cbf1190e3d41007198a03621fbb14d8be9513211cfb9` |
| CodeGraph 行为 | 不改变 `init/sync/serve --mcp`、`codegraph_explore`、环境变量和降级语义 |

交付前必须重新计算以上四个文件的 SHA256；Visualizer 代码和索引不得被上述文件、Agent Runner、MCP 选择器或 Workflow 引用。

## 3. Endpoint 通讯链

现有准确链路：

```text
Web EndpointTasksView.vue
  -> web/src/lib/api.js
  -> POST /api/endpoint-tasks
  -> src/skillify/tasks/web_store.py::dispatch_task
  -> src/skillify/index/models.py::EndpointTaskRecord / WorkPackageRecord
  -> 用户确认工作包
  -> src/skillify/tasks/lease.py::claim_next_task
  -> GET /api/endpoint/tasks/pull
  -> src/skillify/cli/bridge_cmd.py::BridgeLoop
  -> POST /api/endpoint/tasks/{id}/confirm
  -> TaskRunner
  -> LocalOutbox / TaskEventReporter
  -> POST /api/endpoint/events
  -> EndpointTaskEventRecord
  -> GET /api/endpoint-tasks
  -> Web 时间线
```

服务端 Endpoint 机器接口集中在 `src/skillify/web/endpoint_agent_api.py`，已经提供 pull、confirm、heartbeat、cancel 和事件接收。租约 compare-and-set 与过期回收位于 `src/skillify/tasks/lease.py`，事件通过 `event_id` 幂等，端侧 Outbox 位于 `src/skillify/cli/bridge_cmd.py`。

## 4. T4.1 需要补齐的最小缺口

- 当前 Web 任务只接受 `WORKFLOW_FORMS` 中的 Agent Workflow；没有 `codemap.visualization.start|stop|open|status` 固定动作。
- 当前 Bridge 只将已确认 Envelope 交给 Agent `TaskRunner`；没有 Visualizer Launcher dispatch。
- 当前任务输出没有 Visualizer 状态摘要；需要复用现有事件记录和 Web 时间线，不增加第二套轮询或事件协议。
- Visualizer 动作必须使用 workspace alias 和动作 allowlist，不能把绝对路径、localhost URL、Shell 或任意参数放进服务端 payload。

## 5. 数据、CLI、Web 与迁移位置

- ORM：`src/skillify/index/models.py`
- DM8：`infra/dm8-init/06-endpoint-tasks.sql`、`07-endpoint-task-runtime-lease.sql`、`08-work-packages.sql`、`09-team-tasks.sql`
- Web API：`src/skillify/web/app.py`、`src/skillify/web/endpoint_agent_api.py`
- Endpoint 身份：`src/skillify/web/endpoint_auth.py`
- Bridge/Outbox：`src/skillify/cli/bridge_cmd.py`
- 事件：`src/skillify/tasks/reporting.py`、`src/skillify/tasks/web_store.py`
- CLI 注册：`src/skillify/cli/main.py`
- 前端任务页：`web/src/views/EndpointTasksView.vue`
- 前端 API：`web/src/lib/api.js`
- 动态路由：`web/src/router/dynamicRoutes.js`，菜单来源由后端 RBAC 管理
- 前端测试：`web/tests/endpointTasks.spec.js`

## 6. 基线验证

通过命令：

```text
.venv/bin/pytest -q tests/test_codegraph_manifest.py tests/test_codegraph_config.py \
  tests/test_task_protocol.py tests/test_task_store_bridge.py tests/test_bridge.py \
  tests/test_task_reporting.py tests/test_web_endpoint_tasks.py \
  tests/test_endpoint_agent_api.py tests/test_task_lease.py tests/test_bridge_runner.py
```

结果：`31 passed, 1 warning`。warning 是现有 Starlette/httpx 兼容弃用提示。

直接执行 `uv run pytest` 在解析阶段失败，因为当前 macOS 无法安装仅提供 Linux/Windows wheel 的 `dmpython==2.5.32`；仓库现有 `.venv` 可执行上述测试，因此不构成 P0 阻断。

## 7. 工作树基线

P0 开始时只有用户提供的以下未跟踪文档：

- `docs/2026-07-19-skillify-codemap-visualization-direction-brief.md`
- `docs/2026-07-19-skillify-codemap-visualization-plan.md`
- `docs/2026-07-19-skillify-codemap-visualization-task.md`

后续实现保留这些输入，不覆盖无关用户改动。
