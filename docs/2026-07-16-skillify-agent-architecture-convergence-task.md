# Skillify Agent 架构收敛 · 任务清单（task）

> 配套计划：`docs/2026-07-16-skillify-agent-architecture-convergence-plan.md`
> 上游裁决：`docs/2026-07-16-skillify-agent-architecture-convergence-review-brief.md`
> 执行：Codex（主）/ GPT / Sonnet。每 Task 含：**依赖 / 文件 / 失败测试 / 最小实现 / 验证 / 删除项 / 完成证据 / commit / Gate**。
> 环境前提：Dev-DoD 在 **Linux（Codex 环境）** 跑（本 macOS 机因 `dmpython` 无 macOS wheel 无法 `pytest`）。`[test-env]` 用例默认 `pytest.mark.skip`，接入测试环境销账。
> 图例：`- [ ]` 未完成 `- [x]` 完成。**禁用表述**：“后续完善/适当处理/添加必要测试/类似上一任务/无路径无验证命令的笼统任务”。

---

## 阶段 P0 · 基线固定（前置，Owner: Codex）

> 执行状态：按用户指示跳过基线全量测试；本轮仅执行与改动直接相关的开发期定向检查，P0 不作为开发阻塞 Gate。

### - [ ] T0.1 记录真实测试基线
- **依赖**：无
- **文件**：`+docs/assessments/2026-07-16-convergence-baseline.md`
- **步骤**：Linux 环境跑 `uv run python -m compileall -q src`、`uv run pytest -q`、`cd web && npm run type-check && npm test && npm run build`，逐项记录 pass/fail/skip 原始输出；标注既有失败（不得归因本轮）。
- **验证**：五命令原始输出入档；确认 codemap/workflow 相关测试当前为绿（删除前基线）。
- **完成证据**：assessment 文档含五命令原始输出块 + 基线计数。
- **commit**：`docs: record convergence baseline`
- **Gate**：基线未记录不得开始 P1。

---

## 阶段 P1 · Code Map 一刀切删除 + CodeGraph 接入（Owner: Codex + Claude Code）

### - [x] T1.1 删除自研 Code Map（前端 + 后端 + CLI + MCP + 解析存储）
- **依赖**：T0.1
- **文件（DELETE）**：`src/skillify/codemap/{__init__,pipeline,schema,store,query,mcp_server}.py`、`src/skillify/cli/map_cmd.py`、`web/src/views/CodeMapView.vue`、`tests/test_codemap_store.py`、`tests/test_codemap_pipeline.py`、`tests/test_codemap_interfaces.py`、`web/tests/codeMap.spec.js`
- **文件（MODIFY，外科）**：`src/skillify/cli/main.py`(删 line 32、35)、`src/skillify/web/schemas.py`(删 `codeMapReferences` line 31)、`src/skillify/web/service.py`(删填充 ~159/183)、`web/src/components/SkillGovernancePanel.vue`(删 line 27 Code Map 区块)、`web/tests/communityGovernance.spec.js`(删 codeMapReferences fixture+断言)、`docs/mcp/catalog.md`(删 line 10)、`workflows/{onboarding,feature,bugfix}/*`(措辞 Code Map→CodeGraph，移除 code-map tag)
- **失败测试/前置**：删除前确认反向引用只剩 `map_cmd.py`+被删测试（`rg -l "skillify.codemap|from .codemap|import codemap" src web tests` 仅命中被删文件）。
- **最小实现**：仅删归属行，不动共享基类（`cli/main.py` 的 Typer app、`schemas.py` 其他 DTO、`SkillGovernancePanel.vue` 其余治理项）。
- **验证**：`uv run python -m compileall -q src`(退出0)；`uv run pytest -q`(全绿，无 codemap 测试)；`cd web && npm run type-check && npm test && npm run build`(绿)；`rg -i "codemap|code-map" src web` 仅剩 workflow 已改措辞外无残留。
- **删除项**：见上 DELETE 清单（12 文件）。
- **完成证据**：三命令绿输出 + `rg` 无残留截图/输出。
- **commit**：`refactor(codemap): remove self-built code map`
- **Gate**：残留引用未清零、或任一命令红 → 不推进 T1.2。

### - [x] T1.2 CodeGraph 生命周期集成（离线可测部分）
- **依赖**：T1.1
- **文件**：`+src/skillify/agent/codegraph.py`、`+infra/offline/codegraph-manifest.json`、`src/skillify/cli/doctor_cmd.py`(增 codegraph 检查，失败为非阻断)、`+tests/test_codegraph_manifest.py`、`+tests/test_codegraph_config.py`
- **失败测试**：先写 `test_codegraph_manifest.py`（哈希匹配通过/篡改包拒绝/版本解析）与 `test_codegraph_config.py`（生成 `codegraph_explore` MCP 配置，幂等/dry-run/冲突拒绝，临时目录）→ 红。
- **最小实现**：`codegraph.py` 提供 version/兼容检查、构件哈希校验安装、workspace 索引 init/update、MCP 配置生成、关遥测/禁公网开关、任务前索引状态检查、失败诊断（返回“用原生检索继续”信号）。复用 `infra/offline/opencode-manifest.json` 校验模式。
- **验证**：两新测试转绿；`compileall` 绿；`doctor` 单测断言 codegraph 检查为可继续（不阻断）。
- **完成证据**：两测试绿 + manifest schema 校验通过。
- **commit**：`feat(codegraph): add offline codegraph lifecycle integration`
- **Gate**：manifest 校验/配置生成未离线通过 → 不推进 T1.3。

### - [x] T1.3 两执行器 CodeGraph MCP 配置生成
- **依赖**：T1.2
- **文件**：`src/skillify/agent/opencode_config.py`(增 codegraph MCP)、`+src/skillify/agent/claudecode_config.py`(Claude Code `.mcp.json`)、`tests/test_codegraph_config.py`(扩展双执行器断言)
- **失败测试**：断言 OpenCode 与 Claude Code 两种配置文件都含 `codegraph_explore`、关遥测、workspace 索引路径 → 红。
- **最小实现**：两生成器输出各自执行器的 MCP 配置片段；不改执行器原生工具。
- **验证**：`test_codegraph_config.py` 全绿（含双执行器）；`compileall` 绿。
- **完成证据**：测试绿。
- **commit**：`feat(codegraph): generate mcp config for opencode and claude code`
- **[test-env]（T1.smoke）**：`+tests/test_codegraph_smoke.py`（默认 skip）— 真实 CodeGraph 安装/建索引/两执行器调用/增量更新/关遥测无公网/构件校验升级回滚。
- **Gate G-P1**：T1.1–T1.3 Dev-DoD 全绿。`[test-env]` Go/No-Go 见 plan §8.1，上线前销账；未过则在线任务代码检索退回执行器原生 `grep/read`。

---

## 阶段 P2 · devpi 解耦（infra-only，Owner: Codex）

### - [x] T2.1 主栈剥离 devpi 生命周期
- **依赖**：无（可与 P1 并行）
- **文件**：`infra/docker-compose.yml`(删 devpi 服务/skillify-web depends_on/devpi-data 卷)、`+infra/devpi/docker-compose.yml`(独立栈)、`infra/devpi/Dockerfile`(迁入独立栈)、`scripts/deployment/start-test-server-docker.sh`(line 86 改 optional)、`tests/test_infra_compose.py`(更新断言)
- **失败测试**：改 `test_infra_compose.py`：断言主栈**无** devpi 服务/卷、skillify-web **无** depends_on devpi；独立 compose 含 devpi → 红。
- **最小实现**：主栈仅保留 `SKILLIFY_DEVPI_INDEX_URL` 环境消费；devpi 迁独立 compose。
- **验证**：`uv run pytest tests/test_infra_compose.py -q` 绿；`compileall` 绿（无代码改动预期）。
- **删除项**：主栈 compose 内 devpi 服务块/depends_on/卷。
- **完成证据**：测试绿 + compose diff。
- **commit**：`refactor(infra): decouple devpi into standalone stack`
- **Gate**：主栈仍强依赖 devpi → 不推进 T2.2。

### - [x] T2.2 doctor 降级 + 安装链保护 + 运维文档拆分
- **依赖**：T2.1
- **文件**：`src/skillify/cli/doctor_cmd.py`(devpi-reachable `required=False`/WARN, ~137-151)、`+docs/operations-devpi-standalone.md`、`docs/operations-dm8-forgejo-devpi.md`(拆出 devpi 段，改引用)、`tests/test_cli_doctor.py`(断言 devpi 宕不致 doctor 整体失败)
- **失败测试**：`test_cli_doctor.py`：devpi 不可达时 doctor 仍 `all_ok`（WARN 非 required）→ 红。
- **最小实现**：仅改 devpi 检查的 `required` 标志；不动 `install/venv.py`/`installer.py`/`lock.py`/`extract.py`/`resolver.py`/`dependencies.py`（安装链保持）。
- **验证**：`uv run pytest tests/test_cli_doctor.py tests/test_installer_python_deps.py tests/test_venv_offline.py -q` 全绿（安装/离线/checksum 链未破坏）。
- **完成证据**：测试绿；运维文档拆分完成。
- **commit**：`refactor(devpi): make devpi check advisory and split runbook`
- **[test-env]（T2.smoke）**：真实独立 devpi 经 index URL 装依赖；主栈无 devpi 时非 Python Skill 安装正常。
- **Gate G-P2**：T2.1–T2.2 Dev-DoD 全绿且安装链测试未回归。

---

## 阶段 P3 · 删自研 Workflow 执行器 + 迁移 Pack 配置（Owner: Codex）

### - [x] T3.1 拆分 contract.py：删执行器、迁移配置
- **依赖**：T0.1
- **文件**：`src/skillify/workflows/contract.py`(删 `execute_workflow`/`WorkflowRole`/`WorkflowExecution`/角色解析/serial 约束)、`+src/skillify/workflows/pack_config.py`(迁 `WorkflowGate`/`approval_required`/`_safe_relative`/`_mapping`/`validate_skill_dir` 挂载/artifact 解析/mode)、`tests/test_workflow_{onboarding,bugfix,feature}.py`(改为测配置/门禁/artifact 解析，不驱动执行)
- **失败测试**：新 `pack_config` 测试：`runtime` 支持 `opencode|claude-code`，gate/approval/artifact/mode 解析与最严合并 → 先红。
- **最小实现**：把保留价值迁入 `pack_config.py`；`contract.py` 若清空则删文件并更新导入。禁止误删通用校验/权限/artifact 能力。
- **验证**：`uv run pytest tests/test_workflow_onboarding.py tests/test_workflow_bugfix.py tests/test_workflow_feature.py -q` 绿；`compileall` 绿；`rg "execute_workflow|WorkflowRole|WorkflowExecution" src` 无残留。
- **删除项**：`execute_workflow`、`WorkflowRole`、`WorkflowExecution` 及其解析。
- **完成证据**：测试绿 + `rg` 无残留。
- **commit**：`refactor(workflows): drop self-built role executor, keep pack config`
- **Gate G-P3**：执行器删净、Pack 配置解析测试绿；误删通用能力则回退重做。

---

## 阶段 P4 · 补齐在线控制面（服务端 API + 存储连通，Owner: Codex）

### - [x] T4.1 服务端 claim/lease/heartbeat 纯逻辑
- **依赖**：T0.1
- **文件**：`+src/skillify/tasks/lease.py`、`src/skillify/index/models.py`(EndpointTaskRecord 增 `runtime`/`lease_owner`/`lease_expires_at`/`heartbeat_at`；EndpointTaskEventRecord `event_id` 唯一)、`+infra/dm8-init/07-endpoint-task-runtime-lease.sql`、`+tests/test_task_lease.py`
- **失败测试**：`test_task_lease.py`（SQLite）：claim compare-and-set、lease 发放/续租/过期回收、重复 claim 幂等、越权 endpoint 拒绝 → 红。
- **最小实现**：纯函数 + SQLite 存储操作；expand 迁移（新列可空/默认）。
- **验证**：`uv run pytest tests/test_task_lease.py -q` 绿；`compileall` 绿。
- **完成证据**：六类用例绿。
- **commit**：`feat(tasks): add claim/lease/heartbeat state machine`
- **Gate**：状态机未离线全覆盖 → 不推进 T4.2。

### - [x] T4.2 连通两套存储（envelope 签名 + 幂等）
- **依赖**：T4.1
- **文件**：`src/skillify/tasks/web_store.py`(dispatch 增 runtime；pull/claim/event 落库)、`src/skillify/tasks/protocol.py`(TaskEnvelope 签名/nonce 应用到 DM8 记录，SQLiteTaskStore 保留为测试替身)、`+tests/test_task_store_bridge.py`
- **失败测试**：下发签名 envelope、回传校验 nonce/`state_version`、重放拒绝、revoke 生效 → 红。
- **最小实现**：DM8 记录为真相源，协议签名/幂等挂上去；不新增第二生产存储。
- **验证**：`uv run pytest tests/test_task_store_bridge.py -q` 绿。
- **完成证据**：测试绿。
- **commit**：`feat(tasks): bind signed envelope protocol to web task store`
- **Gate**：两存储未连通/重放未防 → 不推进 T4.3。

### - [x] T4.3 缺失服务端路由（pull/events/confirm/cancel/heartbeat）
- **依赖**：T4.2
- **文件**：`+src/skillify/web/endpoint_agent_api.py`、`src/skillify/web/app.py`(注册路由)、`+tests/test_endpoint_agent_api.py`
- **失败测试**：fake Keycloak + SQLite：`GET /api/endpoint/tasks/pull`(claim+lease)、`POST /api/endpoint/tasks/{id}/{heartbeat,confirm,cancel}`、`POST /api/endpoint/events`(按 event_id 幂等)；覆盖重复 pull、重复 event、越权 endpoint、lease 过期 → 红。
- **最小实现**：路由沿用 `require_keycloak_user` + endpoint 归属校验；调用 T4.1/T4.2 逻辑。
- **验证**：`uv run pytest tests/test_endpoint_agent_api.py -q` 绿；`compileall` 绿。
- **完成证据**：全部 HTTP 契约用例绿。
- **commit**：`feat(web): implement endpoint pull/events/lifecycle routes`
- **Gate G-P4**：T4.1–T4.3 Dev-DoD 全绿。`[test-env]`：真实 DM8 并发 compare-and-set。

---

## 阶段 P5 · 打通 Bridge→Runner→Provider + 双 Provider（Owner: Claude Code + Codex）

### - [x] T5.1 执行器无关 Task Runner + Bridge 接线
- **依赖**：G-P4、G-P3
- **文件**：`+src/skillify/agent/runner.py`、`src/skillify/cli/bridge_cmd.py`(pull→确认→交 Runner，不再只写 task.received)、`src/skillify/cli/agent_cmd.py`(抽出可复用 provider 驱动)、`src/skillify/tasks/reporting.py`(幂等 event_id 对齐)、`+tests/test_bridge_runner.py`
- **失败测试**：FakeProvider 驱动全链路：pull→确认→start→stream_events→Outbox→幂等上传；断网补传去重、重复事件不重复执行 → 红。
- **最小实现**：Runner 按 `task.runtime` 选 Provider；复用 `_run_local_task` 逻辑；Outbox 先写后传。
- **验证**：`uv run pytest tests/test_bridge_runner.py -q` 绿；`rg "task.received" src/skillify/cli/bridge_cmd.py` 不再是唯一动作。
- **删除项**：bridge 中“仅写 task.received 即结束”的逻辑。
- **完成证据**：全链路事件序列测试绿。
- **commit**：`feat(agent): wire bridge pull to provider task runner`
- **Gate**：Bridge 仍不调 Provider → 不推进 T5.2。

### - [x] T5.2 Claude Code Provider（离线契约）
- **依赖**：T5.1
- **文件**：`+src/skillify/agent/providers/claudecode.py`、`+tests/test_claudecode_provider_contract.py`、`+tests/test_claudecode_provider_smoke.py`(默认 skip)
- **失败测试**：fake `claude` 子进程：`stream-json`→标准 TaskEvent 映射、五条生命周期（正常/取消/超时/崩溃/SIGTERM）、密钥不落盘/日志、仅 workspace+allowed_paths → 红。
- **最小实现**：实现 `AgentProvider` 契约；无头 `claude -p --output-format stream-json`（或 Agent SDK），ModelRuntimeConfig 注入端点/凭据，进程组清理。
- **验证**：`uv run pytest tests/test_claudecode_provider_contract.py tests/test_provider_contract.py -q` 绿（双 Provider 共用契约）。
- **完成证据**：契约测试绿。
- **commit**：`feat(agent): add claude code provider`
- **[test-env]（T5.2.smoke）**：真实 Claude Code 拉起、仅绑 localhost、停止无残留进程。
- **Gate**：契约五分支未离线覆盖 → 不推进 T5.3。

### - [x] T5.3 OpenCode session 恢复（断线重连）
- **依赖**：T5.1
- **文件**：`src/skillify/agent/providers/opencode.py`(增 resume)、`tests/test_opencode_provider_contract.py`(增 resume 分支)
- **失败测试**：断线后按 session id 恢复事件流、不重复执行 → 红。
- **最小实现**：仅补 resume 路径，不改现有映射。
- **验证**：`uv run pytest tests/test_opencode_provider_contract.py -q` 绿。
- **完成证据**：resume 分支绿。
- **commit**：`feat(agent): support opencode session resume`
- **Gate G-P5**：T5.1–T5.3 Dev-DoD 全绿。`[test-env]`：两执行器真实拉起 + 断网重连幂等。

---

## 阶段 P6 · Web 前端闭环展示 + 执行器选择（Owner: Claude Code）

### - [x] T6.1 任务表单执行器选择 + 真实事件时间线
- **依赖**：G-P4
- **文件**：`web/src/views/EndpointTasksView.vue`、`web/src/lib/api.js`、`+web/tests/endpointTasks.spec.js`(或扩展现有)
- **失败测试**：`vitest` 对 fake 数据：执行器下拉(OpenCode/Claude Code)、固定 Workflow 表单、事件时间线/测试摘要/diff 摘要/构件/失败原因渲染；无任意 prompt/shell 输入框；无虚构百分比 → 红。
- **最小实现**：表单增 runtime 字段透传；时间线读服务端事件。
- **验证**：`cd web && npm run type-check && npm test && npm run build` 绿。
- **完成证据**：三命令绿 + 渲染快照。
- **commit**：`feat(web): select executor and show real task timeline`
- **[test-env]（T6.smoke）**：真实 Keycloak/RBAC + 端侧联动展示真实阶段。
- **Gate G-P6**：Dev-DoD 全绿。

---

## 阶段 P7 · 全链路 [test-env] 验收（接入测试环境后销账）

### - [ ] T7.1 真实 Linux Web→Bridge→执行器→Web E2E
- **依赖**：G-P1、G-P2、G-P5、G-P6
- **文件**：`+docs/testing/2026-convergence-e2e-checklist.md`
- **[test-env] 覆盖分支**：正常完成 / 用户拒绝 / 等待计划审批 / 用户取消 / 执行器异常退出 / 网络中断补传 / 重复 pull+重复事件 / lease 过期 / workspace 越权 / CodeGraph/devpi 不可用降级或阻塞。两执行器各跑一遍。
- **信任边界**：服务端从未连端侧入站端口；执行器仅绑 `127.0.0.1`；停止无残留；devpi 独立服务经 index URL 接入；CodeGraph 关遥测无公网。
- **完成证据**：E2E checklist 逐项销账 + 事件审计导出。
- **Gate G-P7（终验）**：plan §8 与 brief §11 全部满足；未销账不得宣称上线可用。

---

## 执行看板

### Dev-DoD（本轮按用户裁决采用编译 + 定向单测 + 前端类型检查/构建）
- [ ] G-P0（用户指示跳过）　- [x] G-P1(CodeGraph)　- [x] G-P2(devpi)　- [x] G-P3(删执行器)　- [x] G-P4(服务端 API)　- [x] G-P5(双 Provider 闭环)　- [x] G-P6(前端)

### [test-env] 待验收
- [ ] G-P1 Go/No-Go　- [ ] G-P2 devpi smoke　- [ ] G-P5 双执行器+断网　- [ ] G-P6 Keycloak/端侧　- [ ] G-P7 全链路 E2E

> 规则：任一 Gate 未过禁止推进下一阶段；Dev 全绿只代表“编译通过 + 离线逻辑正确”，`[test-env]` 未销账前不得对外宣称该域上线可用。并行关系：P1、P2、P3 无相互依赖可并行；P4 依赖 P3；P5 依赖 P3+P4；P6 依赖 P4；P7 依赖全部。
