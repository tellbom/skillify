# Skillify 端侧 Agent 生态 · 任务节点

> **配套计划书：** `docs/2026-07-16-endpoint-agent-plan.md`（角色分工、S0 门禁、离线开发原则、校验模型）。
> **上游权威：** `docs/2026-07-15-skillify-endpoint-agent-ecosystem-master-plan.md`。
> **本文只放可勾选的任务节点。** 每个 Task 标注：**Owner** / **锚点路径**（真实=已存在，`+`=新增） /
> **Dev-DoD**（当前环境必须过：编译 + 离线单测） / **[test-env] 门禁**（延后到测试环境的真机验收） /
> **commit**。冲突时以上游主计划为准。

## 图例

- `- [ ]` Dev-DoD 未完成　`- [x]` Dev-DoD 已完成；各条 **[test-env]** 独立销账，不因 Dev 勾选而视为完成
- **Dev-DoD**：现在就要满足，工具见计划书 §0.1（`compileall` / `pytest` 离线 / `vue-tsc` / `vitest` / `build`）。
- **[test-env]**：需要真实 OpenCode / DM8 / Forgejo / 网络 / 目标 Linux；现在**只写代码 + 标 `skip`**，接入测试环境再销账。

---

## S0 · 仓库评定与计划固化

### - [x] Task 0.1 建立真实仓库基线 — Owner: Codex
- 锚点：`+docs/assessments/2026-07-16-endpoint-agent-repository-assessment.md`、`+docs/superpowers/plans/2026-07-16-s1-opencode-provider.md`
- 步骤：`rg --files` 清单 → 关键字矩阵（`skillctl|agent|opencode|claude|mcp|orchestration|runtime|permissions|devpi|Forgejo`）→ 跑测试基线 → 复用矩阵 → **离线可测性评估** → S1 精确计划。
- **Dev-DoD**：五份产出齐全；测试基线记录 `compileall`/`pytest`/`type-check`/`vitest`/`build` 的原始 pass/fail/skip；标出依赖真实服务需延后的用例。
- **[test-env]**：Linux/OpenCode/glibc/arch 离线安装、内网模型端点可调 —— 本 Task 只给草案，真机确认延后。
- commit：`docs: assess endpoint agent integration`

### - [x] Task 0.2 锁定 ADR 与协议版本 — Owner: Codex
- 锚点：`+docs/adr/ADR-xxx-endpoint-agent-runtime.md`
- 步骤：记录"扩展 skillctl 不新增重叠 CLI""OpenCode first + Provider 隔离""本地执行/服务端控制面/端侧主动连接""原生工具不 MCP 化"四项决策 + `task_protocol_version:1` + `provider_contract_version:1`。
- **Dev-DoD**：ADR 文件合入，四项决策 + 两个协议版本齐全。
- **[test-env]**：无。
- commit：`docs: record endpoint agent architecture decisions`

---

## S1 · 端侧基础与 OpenCode Provider

### - [x] Task 1.1 扩展 CLI 命令面 — Owner: Claude Code
- 锚点：`src/skillify/cli/main.py`、`+src/skillify/cli/agent_cmd.py`、`src/skillify/common/config.py`、`+tests/test_cli_agent.py`
- 命令：`agent doctor|init|run|status|stop|logs`；XDG 分区；稳定机器可读错误码。
- **Dev-DoD**：`compileall` 过；`test_cli_agent.py` 离线过（命令解析 / `--help` 快照 / 退出码 / 无服务器时 `doctor`、本地 `run` 逻辑分支可跑 / 未授权 workspace 失败）。
- **[test-env]**：`doctor` 对真实 OpenCode / 模型端点 / MCP runtime 的实际探测结果。
- commit：`feat(cli): add endpoint agent command group`

### - [x] Task 1.2 定义 Provider Adapter 契约 — Owner: Codex
- 锚点：`+src/skillify/agent/provider.py`、`+src/skillify/agent/events.py`、`+src/skillify/agent/fake_provider.py`、`+tests/test_provider_contract.py`
- 标准状态：`queued/awaiting_approval/running/blocked/succeeded/failed/cancelled`；标准事件：`task.accepted/plan.ready/tool.requested/tool.completed/test.completed/artifact.created/task.blocked/task.finished`；事件含 task/session/provider/version/timestamp，**不含** prompt/源码/secret。
- **Dev-DoD**：`FakeProvider` 可用；契约测试离线覆盖启动 / 事件顺序 / 取消 / 异常退出 / 清理；断言事件不含敏感字段。
- **[test-env]**：无（纯契约，离线即可完整验证）。
- commit：`feat(agent): define provider execution contract`

### - [x] Task 1.3 实现 OpenCode Provider — Owner: Claude Code
- 锚点：`+src/skillify/agent/providers/opencode.py`、`+tests/test_opencode_provider_contract.py`、`+tests/test_opencode_provider_smoke.py`
- 用官方 OpenCode Server/OpenAPI/SDK；`127.0.0.1`+随机空闲端口+临时强密码+超时+进程组清理；每 workspace 隔离配置；不持久化明文密钥；映射五条路径（正常结束/取消/超时/崩溃/SIGTERM）。
- **Dev-DoD**：`compileall` 过；用 **fake HTTP server** 离线验证会话/消息/工具事件→标准事件的映射、五条生命周期分支、密钥不落盘/日志。
- **[test-env]**：`test_opencode_provider_smoke.py`（默认 `pytest.mark.skip`）——真实 OpenCode 拉起、只绑 localhost、停止后无残留进程。
- commit：`feat(agent): add opencode provider`

### - [x] Task 1.4 离线安装与版本锁定 — Owner: Codex
- 锚点：`src/skillify/cli/doctor_cmd.py`、`+infra/offline/opencode-manifest.json`、用户文档
- 复用现有分发方式，不 `curl|sh`；记录 OpenCode/skillctl 的版本/平台/哈希/许可/内网位置；兼容矩阵写入 doctor 规则。
- **Dev-DoD**：`compileall` 过；manifest schema + 校验逻辑（哈希比对 / 损坏包拒绝 / 版本解析）离线单测过。
- **[test-env]**：真机断网安装 / 升级 / 降级。
- commit：`build(agent): add offline opencode distribution`

> **门禁 G1** — Dev：1.1–1.4 全部 Dev-DoD 过。**[test-env] G1**：目标 Linux + 示例仓库完成"分析文件→改一处→跑测试→输出 diff 摘要"，OpenCode 仅 localhost，停止无残留进程。
> **状态（2026-07-16）**：Dev G1 已通过；**[test-env] G1 待执行**。

---

## S2 · Skill/Workflow/MCP 分发与权限

### - [x] Task 2.1 OpenCode 配置适配器 — Owner: Claude Code
- 锚点：复用 `install/agent_defaults.py`、`install/projector.py`；`+src/skillify/agent/opencode_config.py`
- 从 Skillify manifest 生成 OpenCode skills/agents/commands/plugin/MCP；user/project scope；install/update/rollback/dry-run；安装前预览、安装后 lockfile、卸载只删归属条目；冲突不静默覆盖。
- **Dev-DoD**：生成逻辑对临时目录离线单测；幂等 / dry-run / 冲突拒绝覆盖。
- **[test-env]**：真实 OpenCode 读取生成的配置并生效。
- commit：`feat(agent): install skillify capabilities into opencode`

### - [x] Task 2.2 能力锁文件 — Owner: Codex
- 锚点：复用 `install/lock.py`、`install/resolver.py`；`+src/skillify/agent/capability_lock.py`
- 字段：`schema_version`/构件类型/名称/版本/Forgejo release/commit/checksum/依赖/作用域/生成文件/时间；禁止漂移 latest；安装校验 checksum、回滚不重解析。
- **Dev-DoD**：可复现 lockfile 生成 + 四类测试（依赖冲突/循环/缺包/篡改）离线过（用 fake release 元数据）。
- **[test-env]**：对真实 Forgejo release 的 checksum 校验。
- commit：`feat(agent): lock installed capabilities`

### - [x] Task 2.3 权限 Manifest 与本地确认 — Owner: Codex
- 锚点：复用 manifest `permissions`；`+src/skillify/agent/permissions.py`
- 合并 Skill/Workflow/MCP/任务权限取最严；运行前摘要；`rm`/提权/凭据/DB 写/越界写 拒绝或二次确认；Web 任务首版禁无人值守写码；脱敏审计。
- **Dev-DoD**：权限合并 / 最严规则 / 危险操作判定 纯函数离线全覆盖；审计记录脱敏断言。
- **[test-env]**：真实端侧二次确认交互。
- commit：`feat(agent): enforce local capability permissions`

### - [x] Task 2.4 MCP 构件分发 — Owner: Codex
- 锚点：`+src/skillify/mcp/registry.py`、复用 `packaging/pack.py`、`publish/`
- MCP 作为并列构件元数据；本地 stdio / 远程 Streamable HTTP；安装前命令/来源/网络/权限预览；本地 stdio 仅允许构件内经审查的直接服务二进制，参数仅限安全选项闭集和显式凭据引用，环境必须精确等于命令实际消费且符合 `SKILLIFY_MCP_[A-Z0-9]+(?:_[A-Z0-9]+)*` 规范分段的凭据引用集合，从正向边界排除 loader/runtime 控制变量；禁止解释器包装脚本、自由位置参数及子命令，预览必须显示执行、参数与环境约束；**S0 给出 runtime 复用与许可结论**。
- **Dev-DoD**：元数据模型 + 预览生成 + 本地 echo MCP 契约（stdio）离线单测。
- **[test-env]**：内网远程 MCP smoke。
- commit：`feat(mcp): distribute governed mcp configurations`

> **门禁 G2** — Dev：2.1–2.4 Dev-DoD 过。**[test-env] G2**：从 Skillify 安装一个 Workflow Pack，其 Skill、OpenCode agent/command、本地 MCP 均可离线安装/更新/回滚，用户配置不被破坏。
> **状态（2026-07-16）**：Dev G2 离线夹具已通过；**[test-env] G2 待真实 Linux/OpenCode/Forgejo/内网 MCP 环境执行**。

---

## S3 · Code Map 本地代码智能

### - [x] Task 3.1 语言无关索引管线（复用 OSS） — Owner: Codex
- 锚点：`+src/skillify/codemap/pipeline.py`
- ripgrep 发现 + Tree-sitter/Ctags 符号 + Repomix 摘要；排除 secret/二进制/vendor/生成物；首批 Python→JS/TS→Java→Go；版本化 `code-map.json`（解析器版本+内容哈希）。
- **Dev-DoD**：对仓库内**固定小样本**离线跑通；增量/删除/重命名/语法错误/超大仓 测试过（可用 fixture 仓）。
- **[test-env]**：真实中型仓库性能预算。
- commit：`feat(codemap): build evidence-linked repository index`

### - [x] Task 3.2 Code Map 数据模型 — Owner: Codex
- 锚点：`+src/skillify/codemap/schema.py`、`+src/skillify/codemap/store.py`
- 节点：repository/module/file/symbol/API endpoint/data entity/test/entrypoint；边：contains/imports/calls/implements/reads-writes/tests/routes-to；推断关系标 confidence/source；生成失败不阻塞普通任务。
- **Dev-DoD**：稳定节点 ID + 增量重建 + confidence 标注 离线单测。
- **[test-env]**：无（离线可完整验证）。
- commit：`feat(codemap): define graph schema and incremental store`

### - [x] Task 3.3 CLI/MCP/只读视图 — Owner: Claude Code
- 锚点：`+src/skillify/cli/map_cmd.py`、`+src/skillify/codemap/mcp_server.py`、`web/`（**Mermaid/markmap/Vue Flow，禁止把 React Flow 引入 Vue 项目**）
- `skillctl map build/status/query/export`；MCP 返回证据位置非整仓源码；Web 首版只读。
- **Dev-DoD**：`compileall` + `vue-tsc` + `vitest`/`build` 过；五类查询对样本仓离线返回证据位置；前端视图对固定 `code-map.json` 渲染单测。
- **[test-env]**：真机中型仓库查询跳转真实证据 + 降级路径。
- commit：`feat(codemap): expose cli mcp and read-only views`

> **门禁 G3** — Dev：3.1–3.3 Dev-DoD 过。**[test-env] G3**：真实中型仓库首次+增量索引达 S0 性能预算；五类查询跳真实代码证据；解析失败有降级。
> **状态（2026-07-16）**：Dev G3 固定仓库索引、图模型、六类证据查询、CLI/MCP 与只读视图已通过；**[test-env] G3 待真实中型仓库性能与证据跳转验证**。

---

## S4 · 代码开发 Workflow Packs（全 Owner: Claude Code）

### - [x] Task 4.1 Project Onboarding Pack
- 锚点：`+workflows/onboarding/`
- 串行角色（分析→架构摘要→风险/测试入口）；只读；输出 `project-brief.md`+Code Map 引用。
- **Dev-DoD**：Pack 结构过 Skillify validator；三仓 golden tests **离线** 跑通（FakeProvider 驱动）。
- **[test-env]**：真实 OpenCode 执行产出质量。
- commit：`feat(workflows): add project onboarding pack`

### - [x] Task 4.2 Bugfix Pack
- 锚点：`+workflows/bugfix/`
- 串行角色（复现→根因→实现→测试→Review）；无可复现证据不改码；产物含复现命令/失败测试/补丁/通过测试/剩余风险。
- **Dev-DoD**：Pack 结构 + 角色编排定义离线校验；golden tests（Fake）过。
- **[test-env]**：真实 bug 仓端到端。
- commit：`feat(workflows): add evidence-driven bugfix pack`

### - [x] Task 4.3 Feature Pack
- 锚点：`+workflows/feature/`
- 串行角色（澄清→定位→计划→TDD→Review）；计划审批为可配置门禁（Web 任务默认审批后写码）。
- **Dev-DoD**：Pack 结构 + 审批门禁开关逻辑离线单测。
- **[test-env]**：真实特性开发端到端。
- commit：`feat(workflows): add feature development pack`

### - [x] Task 4.4 Review/Refactor Pack
- 锚点：`+workflows/review/`、`+workflows/refactor/`
- Review 只报有证据问题；Refactor 先记录基线不改外部行为；报告等级同现有团队规范。
- **Dev-DoD**：Pack 结构 + 报告 schema 离线校验。
- **[test-env]**：真实仓库 review/refactor 产出。
- commit：`feat(workflows): add review and refactor packs`

> **门禁 G4** — Dev：四 Pack 结构 + golden tests（Fake）离线过。**[test-env] G4**：四 Pack 可从 Skillify 安装、CLI 执行、产出结构化结果，串行、可恢复。
> **状态（2026-07-16）**：Dev G4 四类 Pack 的结构、串行角色、证据/审批门禁、Fake golden 与报告 schema 已通过；**[test-env] G4 待真实安装与 OpenCode 执行质量验证**。

---

## S5 · Bridge、Web 任务与可信上报

### - [x] Task 5.1 定义任务协议 — Owner: Codex
- 锚点：`+src/skillify/tasks/protocol.py`、`+infra/dm8-init/06-endpoint-tasks.sql`
- TaskEnvelope（workspace **alias** 非绝对路径）；签名/过期/重放/撤销/幂等；状态 compare-and-set。
- **Dev-DoD**：协议序列化 + 状态机 + 幂等/重放/撤销 逻辑对 **SQLite** 离线全覆盖。
- **[test-env]**：DM8 上的 `06-endpoint-tasks.sql` 建表与并发 compare-and-set。
- commit：`feat(tasks): define endpoint task protocol`

### - [x] Task 5.2 Bridge/daemon 模式 — Owner: Claude Code
- 锚点：`+src/skillify/cli/bridge_cmd.py`
- `agent connect|bridge start|status|stop`；复用 skillctl 认证；出站拉取+指数退避+本地 outbox；默认前台，systemd user service 可选不需 root。
- **Dev-DoD**：拉取循环 / 退避 / outbox 入队 对 fake HTTP 离线单测；`compileall` 过。
- **[test-env]**：真实服务端长轮询 + 断网重连。
- commit：`feat(agent): add opt-in endpoint bridge`

### - [x] Task 5.3 事件与构件上报 — Owner: Codex
- 锚点：复用 `common/telemetry.py`、`index/events.py`；`+src/skillify/tasks/reporting.py`
- 只报标准事件/测试摘要/diff 统计/版本/构件引用；prompt/源码/secret 默认不传；outbox 幂等补传；UI 无虚构百分比。
- **Dev-DoD**：上报载荷构造（脱敏断言）+ outbox 幂等（按 event_id）对 fake 端点离线单测。
- **[test-env]**：真实服务端接收入库。
- commit：`feat(agent): report verifiable endpoint events`

### - [x] Task 5.4 Web 任务下达与审批 — Owner: Claude Code
- 锚点：`src/skillify/web/app.py`、`web/src/views/`（复用 Keycloak/RBAC）
- 只能向自己绑定且在线 endpoint 下达；固定 Workflow 表单，无任意 prompt/shell 输入框；展示确认状态/事件时间线/构件/失败原因。
- **Dev-DoD**：后端接口对 fake Keycloak + SQLite 离线单测；前端 `vue-tsc`/`vitest`/`build` 过。
- **[test-env]**：真实 Keycloak/RBAC + 端侧联动。
- commit：`feat(web): dispatch governed endpoint tasks`

> **门禁 G5** — Dev：5.1–5.4 Dev-DoD 过。**[test-env] G5**：浏览器建 Bugfix 任务→端侧拉取确认→OpenCode 本地完成→断网重连事件无重复且可审计；服务端从未连端侧入站端口。
> **状态（2026-07-16）**：Dev G5 协议、出站 Bridge、可信事件 outbox 与固定 Workflow Web 表单已通过；**[test-env] G5 待真实 Keycloak/长轮询/OpenCode/断网重连联动**。

---

## S6 · 数据库与业务 MCP（全 Owner: Codex）

### - [ ] Task 6.1 MCP 接入评定与目录
- 锚点：`+docs/mcp/catalog.md`
- 盘点现有 API/CLI/SDK/DB；优先官方/成熟 MCP；记录 owner/版本/数据分类/权限/网络/维护/smoke。
- **Dev-DoD**：目录文档合入，字段齐全。
- **[test-env]**：各连接器真机 smoke。
- commit：`docs(mcp): catalog approved internal connectors`

### - [ ] Task 6.2 只读数据库 MCP（DM8）
- 锚点：`+src/skillify/mcp/db_readonly/`
- 复用成熟 SQL MCP + DM8 兼容层；只读账号；仅 SELECT/元数据，拒绝多语句/DDL/DML/存储过程；allowlist+超时+行数+字节上限+审计 ID；字段脱敏。
- **Dev-DoD**：SQL 安全策略（注释绕过/CTE/子查询/超时/超行/敏感列 六类）对 **SQLite** 离线过；脱敏逻辑单测。
- **[test-env]**：真实 DM8 只读账号 + 方言兼容。
- commit：`feat(mcp): add governed read-only database connector`

### - [ ] Task 6.3 Forgejo/文档/CI MCP
- 锚点：`+src/skillify/mcp/forgejo/` 等
- 优先级 Forgejo→文档搜索→CI；默认只读，写操作逐项授权；最小 scope，不下发管理员 token。
- **Dev-DoD**：工具 scope 定义 + 只读默认 + 写授权门禁 对 fake Forgejo 离线单测。
- **[test-env]**：真实 Forgejo/CI。
- commit：`feat(mcp): add approved development connectors`

> **门禁 G6** — Dev：6.1–6.3 Dev-DoD 过。**[test-env] G6**：一个代码任务经 Code Map 找代码 + 只读 DB MCP 查 schema + Forgejo MCP 读 issue，端侧权限界面清楚展示三类边界。

---

## S7 · 非技术 Agent Apps

### - [ ] Task 7.1 Agent App 模板契约 — Owner: Codex
- 锚点：`+src/skillify/apps/contract.py`
- 固定输入表单+锁定 Workflow/Skill+权限模板+结构化输出；输入/输出 JSON Schema；只允许已发布版本。
- **Dev-DoD**：契约 schema + 校验（拒草稿脚本）离线单测。
- **[test-env]**：无。
- commit：`feat(apps): define governed agent app contract`

### - [ ] Task 7.2 本地文件检索 App — Owner: Claude Code
- 锚点：`+apps/local-doc-search/`
- 端侧选目录生成 alias，服务端不枚举本机；文件名/元数据/全文检索，默认不整盘向量化；内容上传需再确认。
- **Dev-DoD**：检索逻辑 + ignore/大小/敏感目录规则 对临时目录离线单测。
- **[test-env]**：真实端侧目录 + Web 表单联动。
- commit：`feat(apps): add local document search app`

### - [ ] Task 7.3 文本/表格批处理 App — Owner: Claude Code
- 锚点：`+apps/file-processing/`（复用 `examples/excel`、`examples/text`）
- 核心转换用版本锁定可测 Python Skill；不原地覆盖；deterministic fixture tests；依赖只从 devpi。
- **Dev-DoD**：每脚本 deterministic fixture tests **离线** 过（本地包/`--find-links`，同 `test_venv_offline.py` 思路）；输出进新目录+变更清单断言。
- **[test-env]**：真实 devpi 装依赖 + Web 表单端到端。
- commit：`feat(apps): add deterministic file processing apps`

> **门禁 G7** — Dev：7.1–7.3 Dev-DoD 过。**[test-env] G7**：非技术用户仅经 Web 表单下达本地 CSV 汇总任务，端侧确认后用锁定 Skill 生成新文件+预览+审计，原文件未改。

---

## S8 · 质量、安全与社区增长

### - [ ] Task 8.1 供应链与静态扫描 — Owner: Codex
- 锚点：`+src/skillify/security/scan.py`、发布链路
- 复用 Cisco Skill Scanner/NVIDIA SkillSpector/Syft/Grype/Cosign；发布生成 SBOM+扫描+签名/来源；阻断与警告分离。
- **Dev-DoD**：扫描规则 + 阻断/警告分级 对样本构件离线单测；SBOM 生成逻辑单测。
- **[test-env]**：真实 Syft/Grype/Cosign 工具链 + 签名验证。
- commit：`feat(security): scan and attest agent capabilities`

### - [ ] Task 8.2 评测与可观测性 — Owner: Codex
- 锚点：`+src/skillify/evals/`
- 基于真实 TaskEvent 的成功率/拒绝率/回滚率/测试通过率/阻塞原因；Promptfoo/Phoenix；新版本回放固定用例达基线才 stable。
- **Dev-DoD**：指标聚合 对样本 TaskEvent 离线单测；回放门禁逻辑单测。
- **[test-env]**：真实运行数据 + Promptfoo/Phoenix trace。
- commit：`feat(evals): gate workflow releases with evidence`

### - [ ] Task 8.3 社区分发与反馈闭环 — Owner: Claude Code
- 锚点：`web/src/views/SkillDetailView.vue`、`LeaderboardView.vue`
- 详情页展示兼容执行器/所需 MCP/权限/扫描/示例/Code Map/验收数据；团队精选 Pack；收集安装/成功/卸载/反馈，任务内容不作默认遥测；**以真实数据决定是否做 Claude Code Provider 与可视化执行画布**。
- **Dev-DoD**：前端 `vue-tsc`/`vitest`/`build` 过；聚合展示对 fake 数据渲染单测。
- **[test-env]**：真实运行数据驱动的展示与反馈。
- commit：`feat(community): expose governed workflow catalog`

> **门禁 G8** — Dev：8.1–8.3 Dev-DoD 过。**[test-env] G8**：能回答"哪个 Workflow 在什么 Linux/OpenCode/模型版本、以何权限、完成什么任务、失败原因"，不依赖采集源码/完整 prompt。

---

## 执行看板

### Dev 完成度（当前环境，编译 + 离线单测）
- [x] G0 Dev　- [x] G1 Dev　- [x] G2 Dev　- [x] G3 Dev　- [x] G4 Dev　- [x] G5 Dev　- [ ] G6 Dev　- [ ] G7 Dev　- [ ] G8 Dev

### 测试环境待验收（接入后销账）
- [ ] G1 [test-env]　- [ ] G2 [test-env]　- [ ] G3 [test-env]　- [ ] G4 [test-env]　- [ ] G5 [test-env]　- [ ] G6 [test-env]　- [ ] G7 [test-env]　- [ ] G8 [test-env]

> 规则：Dev 全绿只代表"编译通过 + 离线逻辑正确"，**不等于验收完成**；每个阶段的 `[test-env]` 未销账前，不得对外宣称该阶段已上线可用。
