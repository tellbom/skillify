# Skillify 端侧 Agent 生态 · 计划书（执行契约）

> **上游目标文档（唯一权威）：** `docs/2026-07-15-skillify-endpoint-agent-ecosystem-master-plan.md`
> **配套任务节点：** `docs/2026-07-16-endpoint-agent-tasks.md`（本计划书只讲"怎么执行、按什么规矩"，
> 逐 Task 的可勾选清单在任务节点文件里）。
> **交付对象：** Codex（后端 + 仓库评定）、Claude Code（计划编写 + Provider/CLI）。执行方 GPT / Sonnet。
> **日期：** 2026-07-16　**状态：** 待评审。冲突时以上游主计划为准。

---

## 0. 本阶段执行约束（最重要，先读）

**现实：** 当前开发环境**没有目标服务器**（无真实 OpenCode / DM8 / Forgejo / Keycloak / devpi / 内网模型端点），
只能做**编译 / 类型检查 / 离线单测**。真实联调在开发完成后接入**测试环境**再做。

**由此产生的两处关键裁决（覆盖主计划的对应表述）：**

1. **真机门禁整体延后。** 主计划要求"每个 G0–G8 至少在目标 Linux 真机执行一次"。本阶段裁决：
   **G1–G8 的真机验收全部延后到测试环境**；开发阶段以"编译 + 离线单测"作为准入。每个门禁在
   任务节点里拆成两层：**Dev-DoD（现在必须过）** 与 **[test-env] 门禁（延后，接入测试环境补跑）**。

2. **代码必须"可离线编译 + 可离线单测"，这是硬性架构约束，不是可选项。** 因为没有真实服务，
   凡涉及外部系统的代码都必须做成**依赖注入 / 可替换 Fake**：Provider 用 `FakeProvider`、HTTP 用
   fake server、DB 用 SQLite/临时库、文件用临时目录、时间/随机可注入。**任何"不接真实服务就没法验证"
   的写法都算设计缺陷**，退回重构。主计划本身已按此思路设计（Task 1.2 要求 FakeProvider、Task 1.3
   要求先 Fake HTTP 契约测试再真机 smoke），本阶段把它从"推荐"提升为"强制"。

### 0.1 本阶段唯一有效的校验手段（Dev-DoD 工具箱）

| 层 | 命令 | 作用 |
| --- | --- | --- |
| 后端编译 | `uv run python -m compileall -q src` | 语法/导入可编译（**准入下限**） |
| 后端单测 | `uv run pytest -q` | 逻辑正确性，**仅限可离线用例**（Fake/临时目录/SQLite） |
| 前端类型 | `cd web && npm run type-check` | `vue-tsc --noEmit` |
| 前端单测 | `cd web && npm test`（vitest） | 组件/纯函数逻辑 |
| 前端构建 | `cd web && npm run build` | 打包可通过 |

> 后端当前**未配置 mypy/ruff**，所以后端"类型检查"= `compileall`；如需更强静态检查，S0 可评估是否引入（须锁版本、离线）。
> 需要真实 OpenCode/DM8/Forgejo/网络的用例，一律 `pytest.mark.skip(reason="requires test-env: ...")`，
> 与仓库现有 `tests/test_installer_python_deps.py` 的做法一致，**不得留成 flaky，也不得伪造通过**。

### 0.2 诚实边界

- 编译 + 离线单测**能证明**：契约形状、状态机流转、事件序列、权限合并、锁文件生成、协议序列化、错误码。
- **不能证明**：OpenCode 真能被 SDK 拉起、只绑 localhost、进程无残留、内网模型端点可调、DM8 方言兼容、
  断网重连真幂等。这些**必须**在 `[test-env]` 门禁补验，开发阶段不得宣称"已验收"。

---

## 1. 角色分工与执行模型

| 角色 | 主责 | 不做 |
| --- | --- | --- |
| **Codex** | S0 仓库二次评定；后端 TDD（Provider 契约、任务协议、锁文件、DB/MCP、扫描/评测）；离线依赖与兼容矩阵 | 不擅自改 CLI 语言；S0 未过不写功能代码 |
| **Claude Code** | 用 `superpowers:writing-plans` 产出各阶段精确计划；`skillctl agent` CLI、OpenCode Provider、Code Map 视图、Web 前端 | 不 fork OpenCode；不重写其 Agent loop/工具 |
| **GPT / Sonnet** | 按任务节点逐 Task 执行、过 Dev-DoD、登记 `[test-env]` 待验项 | 不静默降指标；不合并未过 Dev-DoD 的 Task |

**执行铁律：**

- [ ] **OpenCode first**：只做 OpenCode Provider；Claude Code Provider 在 `[test-env]` G1 通过前不并行。
- [ ] **阶段串行**：S0→…→S8，每阶段独立可编译、独立可回滚、独立可演示（演示=离线单测跑通）。
- [ ] **可离线优先**：所有外部交互依赖注入 + Fake；见 §0 与 §6。
- [ ] **信任边界不因缺服务而松动**：服务端不主动连端侧、OpenCode 只绑 `127.0.0.1`——即使现在无法真机验证，
      代码与配置也必须落成这样，留给 `[test-env]` 验收。

---

## 2. 硬约束红线自检（每次提交前逐条确认，对应主计划 §8）

- [ ] 新命令进 `skillctl agent ...`，无与现有 `skillctl` 重叠的用户入口。
- [ ] 没有重写 OpenCode Agent loop / 工具系统；原生 文件/Shell/Git/测试 仍用 OpenCode 内置。
- [ ] 没有把所有本地工具强行 MCP 化（MCP 只用于外部系统 / 可复用能力）。
- [ ] 没有把服务器沙箱当执行前置；服务器不可用时本地 CLI 仍能工作。
- [ ] 没有让服务端访问本机路径或监听端侧入站端口。
- [ ] 没有默认上传 prompt / 源码 / secret / 环境变量 / 数据库结果。
- [ ] 每个任务绑定明确 workspace 与允许路径；不默认扫描整机。
- [ ] 新 OSS 均记录版本 / 许可证 / 来源 / 哈希 / 内网镜像策略，运行时不隐式出网。
- [ ] Skill 仍走 Forgejo 不可变构件 + checksum + 每 Skill 独立 `uv` venv + devpi。
- [ ] **（本阶段新增）** 改动可 `compileall` 通过；新增逻辑有离线单测；需真实服务的验收已标 `[test-env]`。

---

## 3. S0 强制门禁：先评定，后编码（Go / No-Go）

**任何功能代码前先过 G0。** §5 的"预置基线"只是草稿，Task 0.1 必须逐条复核修正，禁止照抄。

### 3.1 Codex 首条指令（可粘贴）

```text
只执行主计划的 S0，不写功能代码。扫描现有 Skillify 仓库，优先识别并复用 skillctl、agent 投影
适配层、manifest/lock 解析、Forgejo 构件链、doctor、telemetry 上报、权限与配置生成能力。产出：
1) 复用矩阵（需求→现有模块/OSS→缺口→裁决）；
2) 真实文件地图（每个 Task 的 Create/Modify/Test 精确路径，真实存在或明确标注新增）；
3) 测试基线（跑 compileall + 现有 pytest + 前端 type-check/build/vitest，记录原始 pass/fail/skip，
   禁止把旧失败归因新代码；标注哪些用例依赖真实服务需延后）；
4) 离线可测性评估（每个后端模块能否用 Fake/临时目录/SQLite 离线单测；不能的给出重构方案）；
5) Linux/OpenCode 离线兼容矩阵（延后到测试环境，但先给出目标发行版/glibc/arch/离线安装方式草案）；
6) ADR 草案（主计划 Task 0.2 四项决策 + 协议版本）；
7) S1 精确 TDD 计划（测试代码、运行命令、预期失败/通过输出、commit 边界，且所有验收以离线为准）。
输出到 docs/assessments/2026-07-16-endpoint-agent-repository-assessment.md 与
docs/superpowers/plans/2026-07-16-s1-opencode-provider.md。任何与现有模块重叠的新组件都要给出
“不复用现有实现”的证据。完成后停下等待评审。
```

### 3.2 Claude Code 首条指令（可粘贴）

```text
使用 superpowers:writing-plans，基于已批准的 S0 评定，产出 S1 逐文件实施计划：skillctl agent
命令组、AgentProvider 契约、FakeProvider、OpenCode Provider。严格 TDD 且以离线校验为准：先写
失败的离线单测（用 FakeProvider / fake HTTP server，不连真实 OpenCode）、给出运行命令与预期
输出、标 commit 边界；真实 OpenCode smoke 单独标 [test-env] 延后。复用现有 CLI 日志/HTTP/认证/
配置设施。不实现 Claude Code Provider。完成计划后等待评审。
```

### 3.3 G0 通过条件（Dev 可完成，无需真机）

- [ ] 复用矩阵 + 真实文件地图 + 测试基线 + 离线可测性评估 + S1 精确计划齐全。
- [ ] Linux/OpenCode 离线兼容矩阵给出**草案**（真机确认标 `[test-env]`）。
- [ ] ADR 记录四项决策 + `task_protocol_version:1` + `provider_contract_version:1`。
- [ ] 提交 `docs: assess endpoint agent integration`、`docs: record endpoint agent architecture decisions`。

---

## 4. 预置仓库基线（初步只读扫描 · 供 Task 0.1 校验，勿照抄）

> 关键信号：`mcp` 与 `provider` 关键字在 `src/` 命中 **0 文件** → 全新建设；
> `opencode` 目前仅作为**技能投影目标**（`install/agent_defaults.py`），非执行器 Provider。

| 主计划需求 | 现有可复用点（真实路径） | 缺口 | 初判 |
| --- | --- | --- | --- |
| 统一 CLI 入口 | `src/skillify/cli/main.py`（Typer） | 无 `agent` 命令组 | 扩展 |
| 环境诊断 | `src/skillify/cli/doctor_cmd.py` | 未查 OpenCode/模型端点/MCP | 扩展 |
| Agent 目录适配 | `install/agent_defaults.py`、`install/projector.py` | 是"投影"非"Provider" | 部分复用（S2）+ 新建 Provider |
| manifest/依赖/锁 | `install/lock.py`、`install/dependencies.py`、`install/resolver.py`、`validator/`、`spec/` | 无能力 lockfile | 复用解析器 + 新 schema |
| 不可变构件链 | `publish/publisher.py`、`publish/forgejo_client.py`、`packaging/pack.py` | 无 MCP 构件类型 | 复用 + 并列 MCP |
| 权限声明 | manifest `permissions` | 无运行时合并/本地确认 | 新增 |
| 上报/遥测 | `common/telemetry.py`、`index/events.py` | 无 TaskEvent/outbox | 复用隐私边界 + 新协议 |
| 配置/XDG | `common/config.py`、`~/.skillify/` | 无 agent 配置/状态/日志分离 | 扩展 |
| 身份/权限 | `web/auth.py`（Keycloak）+ 前端 RBAC 桥接 | 无端侧设备绑定 | 复用 + 新增 |
| 业务库 | DM8（`infra/dm8-init/`）、`index/` ORM | 无任务控制面表 | 扩展（先 expand 后 contract） |
| MCP 分发/runtime | **无** | 全部 | 新建（S0 评定 ToolHive/ContextForge 复用与许可） |
| Provider 执行契约 | **无** | 全部 | 新建 AgentProvider + FakeProvider |
| Code Map | **无** | 全部 | 新建（复用 Tree-sitter/Ctags/ripgrep/Repomix） |

**未落地目录（本计划将创建）：** `docs/adr/`、`docs/assessments/`、`AGENTS.md`。

---

## 5. S1 精确文件级骨架（Claude Code 用 `superpowers:writing-plans` 细化）

> 严格 TDD 且**以离线单测为准入**：先写失败的离线单测 → 实现 → `compileall` + `pytest` 过 → commit。
> 真实 OpenCode smoke 标 `[test-env]` 延后。

```
Create:
  src/skillify/cli/agent_cmd.py              # skillctl agent doctor/init/run/status/stop/logs
  src/skillify/agent/__init__.py
  src/skillify/agent/provider.py             # AgentProvider 抽象：probe/start/create_session/stream_events/cancel/stop
  src/skillify/agent/events.py               # TaskEvent 标准事件 + 状态枚举
  src/skillify/agent/fake_provider.py        # 离线单测唯一执行器，事件顺序可控
  src/skillify/agent/providers/opencode.py   # OpenCode Server/SDK，127.0.0.1+随机端口+临时凭据
  tests/test_cli_agent.py                    # 命令解析/help 快照/退出码/无服务器可跑（离线）
  tests/test_provider_contract.py            # 用 FakeProvider 跑：启动/事件顺序/取消/异常/清理（离线）
  tests/test_opencode_provider_contract.py   # 用 fake HTTP server 跑映射逻辑（离线）
  tests/test_opencode_provider_smoke.py      # [test-env] 真实 OpenCode，pytest.mark.skip 默认跳过
Modify:
  src/skillify/cli/main.py                   # app.add_typer 注册 agent 组
  src/skillify/cli/doctor_cmd.py             # 扩展检查项（OpenCode/模型端点/MCP/workspace）——检测逻辑可离线单测
  src/skillify/common/config.py              # XDG：agent 配置/状态/缓存/日志分离
  pyproject.toml                             # 若引入 OpenCode SDK/HTTP 依赖：锁版本+许可+内网镜像
Dev-DoD 命令：
  uv run python -m compileall -q src
  uv run pytest tests/test_cli_agent.py tests/test_provider_contract.py tests/test_opencode_provider_contract.py -q
[test-env] 门禁：
  uv run pytest tests/test_opencode_provider_smoke.py -q   # 接入测试环境后解除 skip
Commit 边界：1.1 CLI → 1.2 契约+Fake → 1.3 OpenCode Provider → 1.4 离线分发
```

---

## 6. 可离线开发原则（把"无服务器"变成设计规范）

1. **依赖边界即 Fake 边界**：每个外部系统（OpenCode/Forgejo/DM8/MCP/模型端点/网络）后面都要有一个抽象接口
   与一个 Fake 实现；业务逻辑只依赖接口。
2. **纯逻辑与 I/O 分离**：事件映射、状态机、权限合并、锁文件生成、协议序列化——写成纯函数，直接单测。
3. **副作用可注入**：进程启动、文件写、时间、随机端口、UUID 都从参数/工厂注入，测试可替换。
4. **错误路径优先测**：取消、超时、崩溃、断网、篡改、越权——这些恰恰是离线最好测、真机最难复现的，优先覆盖。
5. **`[test-env]` 清单是一等产物**：每个 Task 结束时，把"无法离线验证、需真机补验"的点写进任务节点的
   `[test-env]` 门禁，接入测试环境时逐条销账。

---

## 7. 协作与发布规范

- **TDD 全程**：先失败的离线单测后实现；不得先实现后补测试。
- **门禁两层**：Dev-DoD（编译 + 离线单测）现在过；`[test-env]` 门禁（真机）接入测试环境补跑，**未补跑不得标"验收完成"**。
- **协议分别版本化**：Provider / Workflow / MCP / Code Map schema / task protocol 各自版本，端侧至少兼容当前与前一版本。
- **数据库迁移先 expand 后 contract**；沿用 DM8 + Alembic 基线（就绪度前置项）。真实 DM8 方言兼容标 `[test-env]`。
- **发布策略**：每阶段独立版本 / 迁移 / 回滚说明；S1–S4 面向开发者 CLI，S5 起邀请 Web 用户，S7 起面向非技术用户——**灰度节奏以测试环境验收为准**。
- **离线依赖**：新 OSS 锁版本+许可+哈希+来源+内网镜像；运行时不隐式出网。
- **事件隐私**：默认不上传 prompt/源码/secret/环境变量/数据库结果；纯本地 CLI 场景可关上报。

---

## 附：与就绪度计划的衔接

本计划假设"就绪度地基"（完整部署包、Alembic/DM8、发布可恢复、Web 上传进 Git、版本中心）按
`docs/review-test-production-readiness-...` 与 `next-direction-community-growth-2026-07-15.md` 的 P0 前置项推进。
**S0 的 Task 0.1 必须确认这些遗留项是否阻塞 S1**；若阻塞，先清障再开 S1。就绪度项的真机验收同样标 `[test-env]`。
