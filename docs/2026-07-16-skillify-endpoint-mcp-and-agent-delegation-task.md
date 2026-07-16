# Skillify 端侧 MCP 与主子 Agent 委派 · 任务清单（task）

> 配套计划：`docs/2026-07-16-skillify-endpoint-mcp-and-agent-delegation-plan.md`
> 上游裁决：`docs/2026-07-16-skillify-endpoint-mcp-and-agent-delegation-design-brief.md`
> 执行：Codex（主）。目标执行器：OpenCode + Claude Code。
> 环境：独立编码环境，**只保留离线测试门禁**；Dev-DoD 在 Linux 跑（本 macOS 机 `dmpython` 无 wheel 不能 pytest）。
> 每 Task 含：**依赖 / 文件 / 先失败测试 / 最小实现 / 删除项 / 验证命令 / 完成证据 / commit / Gate / 状态 / 指导意见**。
> 状态三层：`implemented`（合入）· `dev_verified`（离线门禁过）· `env_verified`（[test-env] 销账）。三者独立，不可互推。
> 禁用表述：后续完善 / 适当处理 / 添加必要测试 / 类似上一任务 / 无路径无验证命令。
> **统一测试环境交付入口：** `docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`。测试窗口以该文档汇总范围和当前架构裁决为准。

> 执行结果（2026-07-16）：M1–M2、A1–A4、C1–C5、D1–D3 均为 `implemented=yes / dev_verified=yes / env_verified=pending`。E1 为 `env_verified=pending`，只在测试环境销账。

---

## 阶段 M · MCP 官方 SDK 替换手写协议（Owner: Codex）

### M1 固定官方 MCP SDK 离线制品
- **依赖**：无
- **文件**：`pyproject.toml`(+`mcp==<v1>`)、`uv.lock`、`+infra/offline/mcp-sdk-manifest.json`、`+tests/test_mcp_sdk_manifest.py`
- **先失败测试**：`test_mcp_sdk_manifest.py`——sha256 匹配/篡改拒绝/version 解析（复用 `codegraph.py:load_manifest/verify_artifact` 原语）→ 红。
- **最小实现**：manifest 记 version/sha256/license/sourceUrl/intranetUri；devpi 镜像；锁 uv.lock 哈希。
- **删除项**：无。
- **验证**：`uv run pytest tests/test_mcp_sdk_manifest.py -q` 绿；`uv run python -c "import mcp"`（Linux）。
- **完成证据**：manifest 校验绿 + `import mcp` 成功。
- **commit**：`build(mcp): pin official mcp python sdk offline`
- **Gate**：SDK 未固定不推进 M2。
- **状态**：implemented / dev_verified / env_verified(内网镜像真实拉取)
- **指导意见**：MCP SDK 是 pip 包不是二进制，固定走 pyproject+uv.lock+devpi 镜像；`mcp-sdk-manifest.json` 仅作离线来源与哈希登记，勿照搬 opencode 的多平台二进制字段。选精确 v1 稳定版，**禁 v2**。

### M2 删手写探测 + SDK client 封装
- **依赖**：M1
- **文件**：`src/skillify/mcp/registry.py`(删 645-897 及仅探测使用的常量/`_LineReader` 等)、`src/skillify/mcp/__init__.py`(删 probe 导出 13,27)、`+src/skillify/mcp/sdk_client.py`、`tests/test_mcp_remote_smoke.py`(重写为 SDK client 契约)、`tests/fixtures/mcp_echo_server.py`(改造为 SDK 参考 stdio server)、`+tests/test_mcp_sdk_client.py`
- **先失败测试**：`test_mcp_sdk_client.py`——对**本地 SDK 参考 server** 跑 initialize/tools.list/tools.call/cancel 往返 → 红。
- **最小实现**：`sdk_client.py` 用官方 SDK 完成握手与调用；删手写 `probe_stdio_mcp` 等；保留 `_MAX_ARG/_MAX_ARGS/_ENV_RE/_validate_timeout`。
- **删除项**：`registry.py:645-897` 探测段；`__init__.py` probe 导出。
- **验证**：`uv run pytest tests/test_mcp_sdk_client.py -q` 绿；`compileall` 绿；`rg "probe_stdio_mcp|select.select|_LineReader" src` 无残留。
- **完成证据**：SDK 往返测试绿 + `rg` 无残留。
- **commit**：`refactor(mcp): replace handwritten stdio probe with official sdk`
- **Gate G-M**：M1–M2 dev_verified；探测协议删净。
- **状态**：implemented / dev_verified / env_verified(真实内网 MCP server 往返)
- **指导意见**：**先确认 `probe_stdio_mcp` 无 `src/` 生产调用（已核实仅测试）再删**。SDK stdio 往返两端本机、无公网，属离线可测——把它作为 dev 硬门禁，不要标 `[test-env]`。治理层（`McpArtifact`/`load_mcp_artifact`/`render_opencode_mcp`）一行不动。

---

## 阶段 A · Adapter 改造为 SDK stdio server（Owner: Codex）

### A1 SDK stdio server 框架 + skillctl mcp serve
- **依赖**：G-M
- **文件**：`+src/skillify/mcp/server/__init__.py`、`+src/skillify/cli/mcp_cmd.py`、`src/skillify/cli/main.py`(注册 mcp 组)、`+tests/test_mcp_serve.py`
- **先失败测试**：`skillctl mcp serve <name>` 启动 SDK stdio server，暴露注册工具，client 可 initialize/list/call → 红。
- **最小实现**：server 框架按 manifest 加载对应 Adapter 并注册工具；`mcp_cmd` 提供 serve/probe/list。
- **验证**：`uv run pytest tests/test_mcp_serve.py -q` 绿；`compileall` 绿。
- **完成证据**：serve 契约绿。
- **commit**：`feat(mcp): add sdk stdio server and skillctl mcp serve`
- **Gate**：框架未通不推进 A2。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：`runtime.command` 必须是 `skillctl`、`args:[mcp,serve,<name>]`（对应 manifest §7.1），不要让 Adapter 变成独立可执行随意启动。工具注册按任务最小集合（见 D3）。

### A2 三连接器改造为 SDK stdio server
- **依赖**：A1
- **文件**：`src/skillify/mcp/db_readonly/connector.py`、`src/skillify/mcp/forgejo/connector.py`、`src/skillify/mcp/docs/connector.py`（各加 SDK server 暴露层）、`tests/test_mcp_db_readonly.py`、`tests/test_mcp_development_connectors.py`（改经 SDK server 调用）
- **先失败测试**：经 SDK stdio 调用三连接器工具，断言只读/scope/行数/超时/脱敏仍生效 → 红。
- **最小实现**：策略引擎核心不变，仅加 SDK server 暴露层；工具原子化、读写分离。
- **删除项**：进程内直调路径若与 server 重复则收敛（保留策略引擎函数）。
- **验证**：`uv run pytest tests/test_mcp_db_readonly.py tests/test_mcp_development_connectors.py -q` 绿。
- **完成证据**：三连接器经 SDK 契约绿。
- **commit**：`refactor(mcp): expose connectors as sdk stdio servers`
- **Gate**：任一连接器安全策略回归则回退。
- **状态**：implemented / dev_verified / env_verified(真实 DM8/Forgejo/文档后端)
- **指导意见**：**保留** `validate_select`/scope/脱敏，别在 server 层重写。DM8 用 `SQLiteReadExecutor` 离线测；真实 DM8 executor（A4）单独，方言验证 `[test-env]`。

### A3 REST/OpenAPI 薄 Adapter（老系统包装）
- **依赖**：A1
- **文件**：`+src/skillify/mcp/rest/adapter.py`、`+tests/test_mcp_rest_adapter.py`
- **先失败测试**：对 **fake HTTP server** 端到端：MCP 参数→REST 调用→裁剪结构化返回；断言无任意 URL、network allowlist 生效、读写分离、错误不含 header/token/连接串 → 红。
- **最小实现**：薄映射 + Broker 取凭据（M 阶段 stub 或 C 阶段接入）+ scope/网络校验。
- **删除项**：无。
- **验证**：`uv run pytest tests/test_mcp_rest_adapter.py -q` 绿。
- **完成证据**：REST Adapter fake HTTP 端到端绿。
- **commit**：`feat(mcp): add thin rest adapter reference`
- **Gate**：薄约束契约不过则回退。
- **状态**：implemented / dev_verified / env_verified(真实内网 REST)
- **指导意见**：这是“包装老系统”的参考实现，**必须薄**：禁 `execute_anything`、禁任意目标 URL（只允许 manifest+本地策略共同允许的 host:port）。老系统权限/事务不在 Adapter 内重做。

### A4 DM8 真实只读 executor
- **依赖**：A2
- **文件**：`+src/skillify/mcp/db_readonly/dm8_executor.py`、`+tests/test_mcp_dm8_executor_smoke.py`(默认 skip)
- **先失败测试**：`test_mcp_dm8_executor_smoke.py` 标 `[test-env]` skip；离线仍用 `SQLiteReadExecutor` 覆盖策略。
- **最小实现**：实现 `ReadExecutor` Protocol 的 DM8 版本（只读账号、SELECT/元数据、超时/行数）。
- **验证**：`compileall` 绿；离线策略测经 SQLite 绿。
- **完成证据**：executor 实现 + smoke 标 skip。
- **commit**：`feat(mcp): add dm8 readonly executor`
- **Gate G-A**：A1–A4 dev_verified（DM8 真实方言 [test-env]）。
- **状态**：implemented / dev_verified(SQLite 替身) / env_verified(真实 DM8 只读+方言)
- **指导意见**：DM8 无 macOS wheel，真实执行只能 `[test-env]`；离线以 SQLite 证明策略正确即可，别把 DM8 连接写进离线用例。

---

## 阶段 C · Credential Broker 与四身份（Owner: Codex）

### C1 McpArtifact manifest 扩展
- **依赖**：G-M
- **文件**：`src/skillify/mcp/registry.py`(McpArtifact +auth_profile/credential_ref/network allowlist(host+port+protocol)/scopes/tools(summary+context budget)/args)、`tests/test_mcp_registry.py`(或新增)
- **先失败测试**：加载含新字段的 manifest，旧 manifest 仍可加载（向后兼容），credential_ref 只允许引用不含明文 → 红。
- **最小实现**：`load_mcp_artifact` 增字段解析 + 校验；缺省安全。
- **验证**：`uv run pytest tests/test_mcp_registry.py -q` 绿；旧 fixture 仍绿。
- **完成证据**：新旧 manifest 均绿。
- **commit**：`feat(mcp): extend package manifest with auth and network fields`
- **Gate**：向后兼容破坏则回退。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：`credential_ref` 是**引用**（如 `local://orders/current-user`），manifest 里**禁**出现任何明文；network allowlist 结构化到 host+port+protocol，默认 deny。复用已有 `SKILLIFY_MCP_*` env 约束作为 credential_ref 的一种。

### C2 本机秘密存储 + 注入
- **依赖**：C1
- **文件**：`+src/skillify/credentials/store.py`、`+src/skillify/credentials/injection.py`、`+tests/test_credential_store.py`、`+tests/test_credential_injection.py`
- **先失败测试**：加密文件 0600/密钥密文分离/keyring 抽象；注入只经 env 或 Unix socket，**断言不进 CLI/`.mcp.json`/`opencode.json`** → 红。
- **最小实现**：store 抽象（keyring/Secret Service 优先，降级加密文件 0600）；injection 经 per-process env / 本机 Unix socket。
- **验证**：`uv run pytest tests/test_credential_store.py tests/test_credential_injection.py -q` 绿。
- **完成证据**：存储+注入离线绿，含“配置无秘密”快照断言。
- **commit**：`feat(credentials): add local secret store and injection`
- **Gate**：秘密进配置/CLI/日志任一 → 阻断。
- **状态**：implemented / dev_verified / env_verified(真实 keyring/TPM)
- **指导意见**：这是**安全硬门禁**（plan §1.1）：写静态断言扫 `.mcp.json`/`opencode.json`/argv/日志无秘密。加密文件仅在无 keyring 时用，密钥不与密文同文件。

### C3 Credential Broker 状态机（fake IdP）
- **依赖**：C2
- **文件**：`+src/skillify/credentials/broker.py`、`+src/skillify/credentials/identities.py`、`+tests/test_credential_broker.py`
- **先失败测试**：解析 auth_profile→credential_ref、检查用户已批准 scope、刷新短期 token、cancel/exit/timeout 清理、生成不含秘密审计（全 fake IdP）→ 红。
- **最小实现**：Broker 状态机 + 四身份抽象接口（web-user / endpoint / user-delegated(PKCE/Device/Token-Exchange) / service-account(Client Credentials)），真实 IdP 往返留接口。
- **验证**：`uv run pytest tests/test_credential_broker.py -q` 绿。
- **完成证据**：状态机全分支绿 + 审计脱敏断言。
- **commit**：`feat(credentials): add end-side credential broker`
- **Gate**：清理/脱敏未全覆盖不推进 C4。
- **状态**：implemented / dev_verified(fake IdP) / env_verified(真实 PKCE/Device/Token-Exchange/mTLS)
- **指导意见**：Broker 在 **Bridge 内**，不建集中秘密平台。四身份**不可混用**——接口层就分开，别用一个 token 兼四用。真实 IdP 登录/换取属 `[test-env]`，开发期用 fake IdP 打全状态机。

### C4 修复 Endpoint 机器身份混用
- **依赖**：C3
- **文件**：`+src/skillify/web/endpoint_auth.py`、`src/skillify/web/endpoint_agent_api.py`(改 33-38 用独立依赖)、`src/skillify/cli/bridge_cmd.py`(端点凭据来源)、`tests/test_endpoint_agent_api.py`
- **先失败测试**：端点鉴权用独立 Endpoint 机器身份（device token/mTLS 抽象），Web 用户 token **不能**充当端点身份 → 红。
- **最小实现**：独立依赖校验端点凭据；离线用 fake device token。
- **删除项**：`endpoint_agent_api.py` 对 `require_keycloak_user` 的端点鉴权复用。
- **验证**：`uv run pytest tests/test_endpoint_agent_api.py -q` 绿。
- **完成证据**：端点/Web 身份分离测试绿。
- **commit**：`refactor(web): separate endpoint machine identity from web user`
- **Gate**：身份仍混用则回退。
- **状态**：implemented / dev_verified / env_verified(真实 device token/mTLS)
- **指导意见**：这是 brief §4.2 明令的缺陷修复。当前项目测试阶段，允许破坏现有端点鉴权路径；离线用 fake 端点凭据验证分离即可，真实 mTLS/device token `[test-env]`。

### C5 credential CLI + doctor 报告
- **依赖**：C2
- **文件**：`+src/skillify/cli/credential_cmd.py`、`src/skillify/cli/main.py`(注册)、`src/skillify/cli/doctor_cmd.py`(凭据存在/过期)、`+tests/test_credential_cli.py`
- **先失败测试**：`credential add/list/status/revoke`，`list` 不显秘密；`doctor` 只报存在/过期不报内容 → 红。
- **最小实现**：CLI 走 store；doctor 增只读报告。
- **验证**：`uv run pytest tests/test_credential_cli.py tests/test_cli_doctor.py -q` 绿。
- **完成证据**：CLI+doctor 绿 + list/status 无秘密断言。
- **commit**：`feat(cli): add credential management commands`
- **Gate G-C**：C1–C5 dev_verified。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：`list`/`status` 输出做无秘密断言；doctor 凭据检查为非阻断 WARN（缺凭据不应阻断无凭据任务）。

---

## 阶段 D · 委派、工作包与按任务 MCP 注入（Owner: Codex + 前端）

### D1 Workflow Pack delegation + 工作包模型
- **依赖**：G-M
- **文件**：`src/skillify/workflows/pack_config.py`(+delegation/一等 mcp/命名 gate)、`+src/skillify/tasks/work_package.py`、`+infra/dm8-init/08-work-packages.sql`、`src/skillify/index/models.py`(WorkPackageRecord)、`+tests/test_work_package.py`、`tests/test_workflow_*.py`
- **先失败测试**：解析 `delegation:{mode,user_approval,executor_managed}`（默认 suggested）；工作包字段（objective/allowed_paths/deps/read-write scope/推荐 skill+mcp/acceptance/parallelizable）校验；`required` 只约束结果 → 红。
- **最小实现**：pack 增字段 + 工作包模型（对 SQLite 离线）；最严权限合并复用 `permissions.py`。
- **验证**：`uv run pytest tests/test_work_package.py tests/test_workflow_onboarding.py tests/test_workflow_bugfix.py tests/test_workflow_feature.py -q` 绿。
- **完成证据**：delegation+工作包解析绿。
- **commit**：`feat(workflows): add delegation and work-package model`
- **Gate**：未覆盖三模式不推进 D2。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：工作包按**模块/上下文边界**拆，**禁**固化“架构师→开发→测试→评审”角色链。`required` 只约束结果，不得让 Skillify 逐轮发提示词。allowed_paths 复用 `ProviderStartSpec.allowed_paths`。

### D2 工作包确认/编辑 API + Web UI
- **依赖**：D1
- **文件**：`src/skillify/web/endpoint_agent_api.py`(工作包确认/编辑路由)、`src/skillify/tasks/web_store.py`、`web/src/views/EndpointTasksView.vue`、`web/src/lib/api.js`、`+tests/test_work_package_api.py`、`web/tests/*`
- **先失败测试**：suggested 模式生成拆分建议、用户编辑/确认工作包后落库；后端 fake Keycloak+SQLite；前端 `vitest` 渲染工作包编辑 → 红。
- **最小实现**：确认/编辑 API + Web 工作包卡片（objective/allowed_paths/scope/parallel）；无任意 prompt/shell 框。
- **验证**：`uv run pytest tests/test_work_package_api.py -q` 绿；`cd web && npm run type-check && npm test && npm run build` 绿。
- **完成证据**：API+UI 绿。
- **commit**：`feat(web): confirm and edit delegation work packages`
- **Gate**：用户确认后执行器原生调度（[test-env]）。
- **状态**：implemented / dev_verified / env_verified(执行器原生子 Agent 调度)
- **指导意见**：用户确认的是**工作包不是角色**。执行器原生管理子 Agent；控制面只记已暴露标准事件——**不要**为委派新增依赖执行器内部子会话事件（OpenCode SSE 已丢子会话事件）。

### D3 按任务最小 MCP 注入
- **依赖**：G-A、D1
- **文件**：`+src/skillify/tasks/mcp_injection.py`、`src/skillify/agent/opencode_config.py`(task-scoped)、`src/skillify/agent/claudecode_config.py`(task-scoped)、`src/skillify/agent/runner.py`(接入)、`+tests/test_mcp_injection.py`
- **先失败测试**：按任务声明只生成最小 MCP 集合到 **task-scoped** 配置；未声明的社区 MCP 不注入；不支持执行器回退全局+allowlist 并 `log` 降级 → 红。
- **最小实现**：注入选择器 + task-scoped 配置生成（OpenCode project `opencode.json` / Claude Code `--mcp-config`）。
- **验证**：`uv run pytest tests/test_mcp_injection.py -q` 绿。
- **完成证据**：按任务子集注入绿 + 降级路径断言。
- **commit**：`feat(tasks): inject minimal per-task mcp set`
- **Gate G-D**：D1–D3 dev_verified。
- **状态**：implemented / dev_verified / env_verified(执行器 per-task MCP 实际生效)
- **指导意见**：每 MCP Package 必须声明 tools 摘要与上下文预算；**禁**把社区全部 MCP 注入执行器。执行器是否支持 per-task 配置属 `[test-env]` 兼容风险，回退方案必须实现并 `log`。

---

## 阶段 E · [test-env] 内网 E2E 清单（接入后销账）

### E1 全链路真实验收
- **依赖**：G-M、G-A、G-C、G-D
- **文件**：`+docs/testing/2026-mcp-delegation-e2e-checklist.md`
- **[test-env] 覆盖**（brief §11）：Web 选 OpenCode/Claude Code 下达 → Bridge 端侧领取确认 → suggested 工作包用户确认 → 执行器原生调度 → 只加载声明最小 MCP → Adapter 用官方 SDK 调真实内网服务 → Broker 取/刷新 Keycloak 及其他凭据（服务端任务无秘密）→ Token audience/scope 目标服务校验 → 读写不同 scope、写操作审批 → 取消/超时/Token 过期/403/网络不通/Adapter 崩溃均有明确事件 → 两执行器各完成一次真实 E2E → Agent/MCP/凭据/API 日志无秘密 → 全程无公网。
- **完成证据**：checklist 逐项销账 + 无秘密日志审计导出。
- **Gate G-E（终验）**：brief §11 全满足；未销账不得宣称上线可用。
- **状态**：env_verified
- **指导意见**：这是唯一“上线可用”判据。每条失败路径都要真机复现一次并留事件证据；两执行器分别跑。

---

## 执行看板

### Dev-DoD（Linux 离线硬门禁）
- [x] G-M(SDK 替换)　- [x] G-A(Adapter×4)　- [x] G-C(Broker+四身份)　- [x] G-D(委派+工作包+按任务 MCP)

### [test-env] 待验收
- [ ] SDK 真实 server 往返　- [ ] DM8 方言 + 内网 REST/Forgejo/文档　- [ ] 真实 PKCE/Device/Token-Exchange/mTLS　- [ ] 执行器 per-task MCP 与子 Agent 行为　- [ ] G-E 全链路

> 依赖：M→(A,C,D)；A3/A4 依赖 A1；D3 依赖 A 与 D1；E 依赖全部。
> 规则：任一 Gate 未过禁止推进；`dev_verified` 只代表离线正确，`env_verified` 未销账前不得宣称该向上线可用。安全不变量（秘密隔离/Adapter 薄/注入路径）是 `dev_verified` **硬门禁**，不得延后。
