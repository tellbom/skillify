# Skillify 引入 multi-agent-shogun 端侧 Team Runtime · 任务清单（task）

> 配套计划：`docs/2026-07-18-skillify-shogun-team-runtime-plan.md`
> 上游裁决：`docs/2026-07-18-skillify-shogun-team-runtime-integration-brief.md`
> 执行：Codex（主）。目标执行器：**Claude Code + OpenCode（仅此两者）**。上游 Shogun：`v5.2.0` / `431b86a`（MIT），端侧外部 Team Runtime，**不 fork / 不复制源码**。
> 环境：独立编码环境。按 2026-07-19 用户裁决，本轮只执行 Python 编译、模块静态装载、前端类型检查和 diff 校验；pytest、真实 CLI/tmux/网络及故障模型全部移交测试环境。`team` 模式在 [test-env] Go/No-Go 全过前**保持不可用**；`single/delegated` 不受影响。
> 每 Task：**依赖 / Owner / 文件 / 先失败测试 / 最小实现 / 删除项 / 验证命令 / 完成证据 / commit / Gate / 状态三层 / 指导意见**。
> 状态三层：`implemented`（合入）· `dev_verified`（离线门禁过）· `env_verified`（[test-env] 销账）。三者独立。**禁**在未真实验证 Shogun/CLI/tmux/内网模型时标 env_verified。

> 执行结果（2026-07-19）：S1–S5 `implemented=yes / compile_verified=yes / env_verified=pending`；S6/S7 验收清单已建立但未执行。由于用户明确跳过 pytest，本轮不把 compile-only 结果伪装成完整离线行为验证。

---

## 阶段 S1 · 协作契约（Owner: Codex）

### S1.1 execution/team_policy/work_package 契约 + Team 事件
- **依赖**：无
- **文件**：`src/skillify/workflows/pack_config.py`(增 `execution.{mode,collaboration_runtime,preferred_cli}` + `team_policy`)、`src/skillify/tasks/work_package.py`(增 `depends_on/read_only/verification`)、`src/skillify/agent/events.py`(增 Team EventType + `_DETAIL_KEYS` 的 worker_id/work_package_id/stage)、`+tests/test_team_contract.py`
- **先失败测试**：解析 `mode: single|delegated|team`、`collaboration_runtime: shogun`、`preferred_cli: opencode|claude-code`、`team_policy` 默认值、work_packages 依赖/只读/验收命令；Team 事件构造只允许闭合字段（拒绝秘密字段）→ 红。
- **最小实现**：增字段 + 校验；EventType 增 §3.2 全部成员；`_DETAIL_KEYS` 增三键。
- **删除项**：无。
- **验证**：`uv run pytest tests/test_team_contract.py -q` 绿；`compileall` 绿。
- **完成证据**：契约解析 + Team 事件闭合断言绿。
- **commit**：`feat(team): add execution mode, team policy and team events`
- **Gate**：三模式/事件未覆盖不推进 S2。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：`execution.mode`（哪个运行时执行）与既有 `delegation.mode`（工作包如何拆分）**是两个维度，勿混用**。Team 事件是闭合 schema 增量——**禁**把上游内部消息原样加字段；只加 §3.2 生命周期事件与三个可选 id/stage。

---

## 阶段 S2 · 离线制品与 Doctor（Owner: Codex）

### S2.1 shogun-manifest + 分发校验 + 依赖检查
- **依赖**：S1
- **文件**：`+infra/offline/shogun-manifest.json`、`+src/skillify/agent/shogun/__init__.py`、`+src/skillify/agent/shogun/distribution.py`、`src/skillify/cli/doctor_cmd.py`(增 shogun 检查)、`+tests/test_shogun_distribution.py`
- **先失败测试**：manifest sha256 匹配/篡改拒绝/version(v5.2.0)+commit(431b86a)+license(MIT) 校验；宿主依赖检查（`tmux/flock/inotify-tools/python3/od`+CLI）缺失时报明确 reason，**且不阻断 single/delegated**；断言**不调用** `first_setup.sh` → 红。
- **最小实现**：复用 codegraph manifest 校验原语；依赖探测；doctor 增非阻断 shogun 项。
- **验证**：`uv run pytest tests/test_shogun_distribution.py tests/test_cli_doctor.py -q` 绿；`compileall` 绿。
- **完成证据**：哈希/依赖/非阻断断言绿。
- **commit**：`build(team): pin offline shogun artifact and doctor checks`
- **Gate**：制品校验/依赖检查未过不推进 S3。
- **状态**：implemented / dev_verified / env_verified(真实制品内网拉取+宿主依赖)
- **指导意见**：制品须**内置预建 `.venv`（或 pyyaml wheel）+ 预生成 settings 模板**；**绝不**把 `first_setup.sh` 纳入安装路径（它联网）。bats 子模块、Android 不入制品。platform 固定 `linux-x86_64`。

---

## 阶段 S3 · Shogun Provider Adapter + FakeRuntime（Owner: Codex）

### S3.1 队列契约解析 + 配置生成
- **依赖**：S2
- **文件**：`+src/skillify/agent/shogun/contract.py`、`+src/skillify/agent/shogun/config_gen.py`、`+tests/test_shogun_contract.py`、`+tests/test_shogun_config_gen.py`
- **先失败测试**：解析 `queue/{tasks,reports,inbox}/*.yaml` + `shogun_to_karo.yaml`，**双读 status**（顶层+嵌套 legacy）、断言 canonical 文件名、容忍多余字段；`config_gen` 生成 all-OpenCode / all-Claude `settings.yaml` + OpenCode 声明式权限 + 入口 cmd + `SHOGUN_QUEUE_DIR` 运行目录，且 `--permission-mode` 非 dangerous、无 ntfy_topic、内网 endpoint 走 env → 红。
- **最小实现**：镜像 `slim_yaml.py:get_item_status` 双读；config 渲染最小集。
- **验证**：`uv run pytest tests/test_shogun_contract.py tests/test_shogun_config_gen.py -q` 绿。
- **完成证据**：契约解析 + 配置生成（含无 dangerous/无 ntfy 断言）绿。
- **commit**：`feat(team): add shogun queue contract and config generation`
- **Gate**：配置含 dangerous 或秘密即阻断。
- **状态**：implemented / dev_verified / env_verified(真实 CLI 读取生成配置生效)
- **指导意见**：解析**防御式**：状态双读、canonical 文件名断言、忽略未知字段（应对上游版本波动）。生成的 `settings.yaml`/权限/入口 cmd 里**只能出现 `credential_ref`，禁明文**。CLI 仅 claude/opencode 分支，其它一律拒绝。

### S3.2 生命周期（启动/取消/清理/单活跃守卫）+ FakeRuntime
- **依赖**：S3.1
- **文件**：`+src/skillify/agent/shogun/lifecycle.py`、`+src/skillify/agent/shogun/fake_runtime.py`、`+tests/test_shogun_lifecycle.py`
- **先失败测试**：FakeRuntime 按脚本写队列 YAML；启动建隔离运行目录；单活跃 Team 守卫（第二 Team 排队/拒绝）；cancel 序列（kill-session+杀 supervisor+pkill watchers+清 `/tmp/shogun_*`+清运行目录）无遗留；看门狗超时 kill → 红。
- **最小实现**：进程编排注入可替换（FakeRuntime 替 shell）；cleanup 幂等。
- **验证**：`uv run pytest tests/test_shogun_lifecycle.py -q` 绿。
- **完成证据**：启动/取消/清理/守卫全分支绿。
- **commit**：`feat(team): add shogun lifecycle and fake runtime`
- **Gate**：cancel 有遗留/守卫失效不推进 S3.3。
- **状态**：implemented / dev_verified(FakeRuntime) / env_verified(真实 tmux 无残留进程)
- **指导意见**：真实 tmux/进程杀由 [test-env] 验；离线用 FakeRuntime + 临时目录证明**编排逻辑与清理序列**正确。cancel 必须覆盖 supervisor 会 5s 重生 watcher → **先杀 supervisor 再 pkill**。

### S3.3 事件映射 + ShogunProvider + runner 接线
- **依赖**：S3.2
- **文件**：`+src/skillify/agent/shogun/events.py`、`+src/skillify/agent/providers/shogun.py`、`src/skillify/agent/runner.py`(execution.mode=team→runtime=shogun)、`+tests/test_shogun_events.py`、`+tests/test_shogun_provider_contract.py`
- **先失败测试**：队列状态迁移→标准 Team 事件（§3.2）映射 + 脱敏（断言无 Key/Token/env/原始对话/未脱敏 YAML）；ShogunProvider 经 FakeRuntime 跑 probe/start/create_session/stream_events/cancel/stop 全生命周期；runner 按 mode 选 shogun → 红。
- **最小实现**：ShogunProvider 实现 `AgentProvider`（薄壳，禁自分解/角色循环）；UI 名映射 Karo→Coordinator 等仅在事件展示层。
- **验证**：`uv run pytest tests/test_shogun_events.py tests/test_shogun_provider_contract.py -q` 绿；`rg "自分解|role loop" ...` 无角色循环。
- **完成证据**：事件映射脱敏 + Provider 契约全生命周期绿。
- **commit**：`feat(agent): add shogun team provider`
- **Gate G-S3**：S3.1–S3.3 dev_verified；Adapter 无禁做项（brief §5.2）。
- **状态**：implemented / dev_verified / env_verified
- **指导意见**：Provider 是**薄编排壳**：只读稳定输出文件、映射事件、幂等上报；**禁**在 Adapter 内分解任务/决定 Worker 消息/改队列/注入未验证 shell/管模型上下文/建第二套服务端编排状态机。写 inbox 只经 `inbox_write.sh` 语义。

---

## 阶段 S4 · 权限/凭据/网络接线（Owner: Codex）

### S4.1 角色最小权限 + Broker 引用 + 网络 allowlist + 并发治理
- **依赖**：G-S3
- **文件**：`src/skillify/agent/shogun/config_gen.py`(角色权限+MCP 最小注入+credential_ref+network allowlist)、`+src/skillify/agent/shogun/concurrency.py`、`+tests/test_shogun_permissions.py`、`+tests/test_shogun_concurrency.py`
- **先失败测试**：按角色生成 OpenCode 文件路径权限（Coordinator 读报告不写、Explorer 只读、Worker 仅工作包 allowed_paths 可写、Reviewer 只读、Integration 才可合并且默认禁 push）；每 Worker 只装其工作包声明 MCP；配置只含 `credential_ref`；network allowlist=Skillify 策略∩MCP Package 默认 deny；并发治理（max_active_workers/模型并发限流/喂任务节奏/时长上限/排队/429 退避）→ 红。
- **最小实现**：权限/MCP/网络渲染 + 并发限流纯逻辑。
- **验证**：`uv run pytest tests/test_shogun_permissions.py tests/test_shogun_concurrency.py -q` 绿。
- **完成证据**：权限/凭据/网络/并发离线断言绿 + **无秘密**快照断言。
- **commit**：`feat(team): generate minimal role permissions and concurrency governance`
- **Gate G-S4**：dev_verified；**任一配置/日志含秘密即阻断**。
- **状态**：implemented / dev_verified / env_verified(真实 CLI 权限生效)
- **指导意见**：**shell/命令与禁 push 上游无法表达**——用**工作区收敛**替代（文件路径权限 + workspace allowed_paths + 不发 push 凭据 + 网络 deny + Broker 不注入秘密到 worker env）。文档标注"Worker 内可执行任意 shell"为**阶段一已知残余风险**（用户已裁决接受，限受信内网本机）。互斥 allowed_paths 划分工作包（无 worktree），合并仅 Integration 角色。

---

## 阶段 S5 · Bridge 与 Web 接入（Owner: Codex + 前端）

### S5.1 DM8 team 表 + Bridge 隔离运行目录 + Web team 模式与工作包确认
- **依赖**：G-S4
- **文件**：`+infra/dm8-init/09-team-tasks.sql`、`src/skillify/index/models.py`、`src/skillify/web/endpoint_agent_api.py`、`src/skillify/cli/bridge_cmd.py`(team 建隔离运行目录)、`web/src/views/EndpointTasksView.vue`、`web/src/lib/api.js`、`+tests/test_team_api.py`、`web/tests/*`
- **先失败测试**：Web 选 `execution.mode=team` + `preferred_cli` + 确认工作包；服务端 fake Keycloak+SQLite；Bridge claim 后为 team 建隔离运行目录；Team/Worker 时间线（映射名）；重复 pull/event 幂等 → 红。
- **最小实现**：team 表(mode/collaboration_runtime/preferred_cli/team_policy)+worker/work_package 事件记录；前端模式选择+工作包确认+时间线。
- **验证**：`uv run pytest tests/test_team_api.py -q` 绿；`cd web && npm run type-check && npm test && npm run build` 绿。
- **完成证据**：API+UI+幂等绿。
- **commit**：`feat(team): wire team mode into bridge and web`
- **Gate G-S5**：S5.1 dev_verified；DM8 为真相源，Shogun 运行目录不直接覆盖服务端状态。
- **状态**：implemented / dev_verified / env_verified(真实 Keycloak/端侧联动)
- **指导意见**：UI **只显映射名**（Coordinator/Worker/Reviewer），不暴露武士主题词。Shogun 内部状态只经**合法事件**触发受控转换，DM8 唯一真相源。默认 `execution.mode=single`，team 未过门禁时前端置灰不可选。

---

## 阶段 S6/S7 · [test-env] formation 验收（默认 skip）

### S6.1 全 OpenCode formation 真机 E2E
- **依赖**：G-S5
- **文件**：`+tests/test_shogun_smoke.py`(标 skip)、`+docs/testing/2026-shogun-team-e2e-checklist.md`
- **[test-env] 覆盖**：真实制品离线安装（无 first_setup、无公网）→ 全 OpenCode 2~3 Worker + 独立 Reviewer → 真实内网模型 → 真实代码任务完成 → 事件幂等 → 无 dangerous、凭据不落 YAML/日志 → Worker 不互覆盖文件 → cancel/超时/崩溃/Bridge 重启可恢复或安全终止 → tmux/子进程全清。
- **完成证据**：checklist 逐项销账 + 无秘密日志审计。
- **commit**：`test(team): opencode formation e2e checklist`
- **Gate**：brief §12 门禁全过方可标 team 可用。
- **状态**：env_verified

### S7.1 全 Claude Code formation 真机 E2E
- **依赖**：S6.1
- **文件**：`docs/testing/2026-shogun-team-e2e-checklist.md`(Claude 段)
- **[test-env] 覆盖**：全 Claude 2~3 Worker + 独立 Reviewer；`--permission-mode` 非 dangerous；单一共享内网端点（全局 env）；其余同 S6。
- **完成证据**：Claude formation 销账。
- **状态**：env_verified
- **指导意见**：per-Claude 独立端点上游不支持——用**单一共享内网端点**（启动前全局 `ANTHROPIC_BASE_URL` 等）；勿尝试 per-Claude env。

### S8（延后）混合 formation
- 仅 S6/S7 分别稳定后评估；非第一阶段门禁。

---

## Go/No-Go 门禁（brief §12，全部 [test-env]，team 上线前必过）
| 门禁 | 必须结果 |
|---|---|
| License | MIT 确认（已核实），NOTICE 无 |
| Offline | 运行期无公网下载/更新/遥测（禁 first_setup） |
| Linux | 目标发行版/CPU/glibc 可用 |
| OpenCode | 全 OpenCode formation 可启动并完成任务 |
| Claude Code | 全 Claude formation 可启动并完成任务 |
| Lifecycle | 启停/取消/超时/崩溃/清理无遗留进程 |
| Security | 不用 dangerous；凭据不落日志/YAML |
| Events | 稳定转 Skillify 事件，重复幂等 |
| Workspace | Worker 不互覆盖文件（互斥 allowed_paths） |
| Concurrency | 最大活动 Worker 与模型并发可限 |
| Recovery | Bridge 重启后识别已有 Team 续报或安全终止 |

> 任一未过：`single/delegated` 继续；`team` 不可用；**不恢复自研 Team 通讯**；**不以旧自研 Workflow Runtime 兜底**。

---

## 执行看板
### 开发期编译门禁（用户裁决：不执行 pytest/真实环境验证）
- [x] S1(契约)　- [x] S2(制品+Doctor)　- [x] G-S3(Adapter+FakeRuntime)　- [x] G-S4(权限/凭据/网络/并发)　- [x] G-S5(Bridge+Web)
### [test-env]（brief §12 全门禁 + S6/S7）
- [ ] 全 OpenCode formation　- [ ] 全 Claude formation　- [ ] Lifecycle/Security/Events/Workspace/Concurrency/Recovery

> 依赖：S1→S2→S3→S4→S5→(S6,S7)→S8。安全不变量（无 dangerous、凭据不落 YAML/日志/命令行/事件、Adapter 不改队列伪造、脱敏、单活跃守卫、cancel 清理）为 dev_verified 硬门禁。`team` 未过 [test-env] 门禁前保持不可用。
