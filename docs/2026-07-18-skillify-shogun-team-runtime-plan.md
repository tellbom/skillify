# Skillify 引入 multi-agent-shogun 端侧 Team Runtime · 实施计划（plan）

> 日期：2026-07-18
> 上游裁决：`docs/2026-07-18-skillify-shogun-team-runtime-integration-brief.md`
> 关联：`docs/2026-07-16-skillify-agent-architecture-convergence-*.md`、`docs/2026-07-16-skillify-endpoint-mcp-and-agent-delegation-*.md`（均已由 Codex 落地）
> 配套任务：`docs/2026-07-18-skillify-shogun-team-runtime-task.md`
> 交付对象：Codex 二次评定并实施。目标执行器：**Claude Code + OpenCode（仅此两者）**。
> 结论：**条件接受**（见 §2）。当前独立编码环境，只保留离线门禁；`team` 模式在 [test-env] Go/No-Go 全过前**保持不可用**。三层状态 `implemented / dev_verified / env_verified` 分开标记。
>
> 执行状态（2026-07-19）：S1–S5 代码已实现；按用户裁决只完成编译、静态装载与前端类型检查，未执行 pytest 或真实环境验证。S6/S7 清单已输出，`team` 默认关闭，所有 `env_verified` 保持 pending。

---

## 0. 源码核实结论

### 0.1 Skillify 现状（已核实，前两轮已落地）
- 在线闭环存在：`runner.py` 按 `envelope.runtime` 选 Provider（`runner.py:61`）；`opencode`/`claudecode` 两 Provider 真实；Bridge→Runner→Provider 已通；Outbox 幂等；endpoint pull/claim/lease/events 已建。
- 委派与 MCP：`pack_config.py` 有 `DelegationConfig`（mode/user_approval/executor_managed，即工作包拆分的 adaptive/suggested/required）；`tasks/work_package.py` 工作包模型；`tasks/mcp_injection.py` 按任务 MCP 注入；`credentials/`（broker/identities/store）已建。
- **自研 Team 通讯早已删除**（`workflows/contract.py` 不存在，commit `a139a6f`）。**brief §11-q18 核实结论**：Skillify 此前"多 Agent"实为 FakeProvider 驱动的串行 workflow（已删）+ 真实单执行器 + `delegated`（执行器原生 Subagents，仅配置）；**从无真实 Team 协作**。故 `team` 是新增能力，不回退任何真实能力。
- **正交坐标澄清**：本轮 `execution.mode: single|delegated|team`（哪个运行时执行）与既有 `delegation.mode: adaptive|suggested|required`（工作包如何拆分/审批）是**两个不同维度**，不可混用。`team` 模式复用 `runner.py` 的"按 runtime 选 Provider"接缝：新增 `runtime="shogun"` → `ShogunProvider`。

### 0.2 multi-agent-shogun（本机 `~/Desktop/multi-agent-shogun`，`v5.2.0` / `431b86a`，已逐项核实真实源码）

| # brief §11 问题 | 核实结论 | 证据 |
| --- | --- | --- |
| 1 tag/commit/LICENSE | v5.2.0（`431b86a`）；**MIT**（`LICENSE`），无 NOTICE、无 copyleft | `LICENSE:1-21` |
| 2 OpenCode 一级支持实现 | 真实一级：`get_cli_type` 分发、`build_cli_command` 组装，OpenCode 经 `--agent` 引用**声明式权限**定义（比 Claude 更干净） | `lib/cli_adapter.sh:173,236,279-300` |
| 3 非交互/后台 | **YES**，`nohup ./shutsujin_departure.sh -c &` 全程无交互 prompt | `shutsujin_departure.sh:149-259,552,722` |
| 4 Agent 数量/formation | **可配**：`config/settings.yaml` `cli.agents.<id>`；worker 数动态；all-Claude 默认 / all-OpenCode 设 `type: opencode` | `lib/cli_adapter.sh:1448-1468`；`README:592-606` |
| 5 空闲是否耗模型 | **否**：事件驱动 inotify/fswatch，仅 `unread>0` 才发模型 nudge；空闲=零模型调用 | `scripts/inbox_watcher.sh:1307-1359,1152` |
| 6 YAML 队列机器契约 | **稳定**：`queue/{tasks,reports,inbox}/*.yaml` + `queue/shogun_to_karo.yaml`；文件名/状态枚举硬编码 | `scripts/slim_yaml.py:18-24`；`instructions/shogun.md:120-131` |
| 7 inbox_write/锁/inotify | `scripts/inbox_write.sh`（mkdir+flock 锁、tmp+rename 原子写）；inotify 事件唤醒 | `inbox_write.sh:48-118`；`inbox_watcher.sh:80-90` |
| 8 可禁 Dashboard/ntfy/Tailscale | **可**：ntfy 默认关（需 `ntfy_topic`）；**无 Tailscale、无遥测**；Dashboard/saytask/Android 均可忽略 | `shutsujin_departure.sh:1008-1015`；grep 无 tailscale/telemetry |
| 9 按任务独立运行目录 | **部分**：`SHOGUN_QUEUE_DIR` 可迁移队列根，但 tmux 会话名（`shogun`/`multiagent`）与 `/tmp/shogun_*` 全局 → **单机仅一 Team** | `slim_yaml.py:59`；`shutsujin_departure.sh:552,578,697` |
| 10 安全取消/清理 | **部分**：无独立 teardown 脚本；取消=`kill-session` + 杀 supervisor + `pkill` watchers + 清 `/tmp/shogun_*`；`pkill -f` 进程名全局 | `shutsujin_departure.sh:339-340,904-906`；`watcher_supervisor.sh:89-92` |
| 11 worktree/互斥文件 | **无 worktree**；同文件安全仅靠 Karo(协调 LLM) 约定 + 队列 flock | grep 无 `git worktree`；`karo_role.md:150` |
| 12 最小权限满足度 | **仅 OpenCode 且仅文件路径**可声明（`config/opencode-permissions.yaml`→`.opencode/agents/*.md`）；**shell/命令、禁 push 无法表达**（兜底 `'*': allow`） | `opencode-permissions.yaml:100-102`；`.opencode/agents/ashigaru1.md:8` |
| 13 内网模型端点 | OpenCode 每 agent `env` 前缀（base URL/key）**支持**；Claude/Codex 不注入 per-agent，共享全局 shell env → **单一共享内网端点可用**，per-Claude 独立端点需改上游 | `lib/cli_adapter.sh:130-154,288,258-274` |
| 14 运行时下载/更新/遥测 | **无**（`first_setup.sh` 有网络安装，运行入口无） | grep `shutsujin_departure.sh`/`inbox_watcher.sh` 无网络 |
| 15 文件格式版本波动 | 4.x→5.x **增量**；风险在状态枚举/文件名（硬编码）；已发生一次 `task.status` 嵌套→顶层迁移，需双读 | `CHANGELOG.md`；`slim_yaml.py:63-80` |
| 16 需改上游的能力 | 见 §2.2 fork 边界 | — |
| 17 与 Skillify 重复应删/停用 | Skillify **不引入** Shogun 的 Dashboard/ntfy/saytask/Android；不复制 `scripts/queue/instructions`；Skillify Outbox/事件/审批仍为真相源 | brief §4.2 |
| 18 此前"多 Agent"真伪 | 见 0.1：无真实 Team | — |

### 0.3 对 brief 的纠正（Codex 必须以此为准）
1. **`§4.1` 离线制品被低估**：不能只记 tarball。必须**禁用 `first_setup.sh`**（它 `apt/nvm/curl claude installer/npx` 联网，`first_setup.sh:113-496`）；制品须**内置预建 `.venv`（或 pyyaml wheel）+ 预生成 `settings.yaml`**；宿主机预置 `tmux/flock/inotify-tools/python3/od/CLI`（校验非安装）。runtime 入口 `shutsujin_departure.sh` 本身零联网。
2. **`§8.2` 角色受限 shell 无法仅靠上游配置实现**：OpenCode 权限矩阵**仅文件路径**、兜底 `'*': allow`；Claude/其它 CLI 无声明式矩阵；codex/copilot/kimi/cursor/antigravity **硬编码 bypass 标志**（`cli_adapter.sh:270-322`）改之即 fork。**用户裁决：接受此限制 + 工作区收敛**（见 §7.2），CLI 范围**收敛为 Claude+OpenCode**。
3. **`§9` Shogun 无任何并发/超时上限**：`max_active_workers/max_parallel_model_calls/team_timeout` 均不存在；须由 Skillify **外部治理**。利好：**空闲 worker 零模型调用**（事件驱动）。
4. **`§1/§6` 单机并发**：全局 tmux 会话名 + `/tmp/shogun_*` → **单机仅一 Team**；Adapter 强制"单端点单活跃 Team"，用 `SHOGUN_QUEUE_DIR` 把队列迁入每任务运行目录。
5. **`§8.4` per-Claude 独立端点不支持**：单一共享内网端点（启动前全局 env）可用；per-Claude 独立端点属后续/上游。

---

## 1. 接受/拒绝结论

**条件接受（CONDITIONAL ACCEPT）。** Shogun 作为端侧外部 Team Runtime，核心集成**无需 fork**。License(MIT)/Offline/机器契约(稳定 YAML)/headless/formation 可配/空闲零模型调用 均满足。接受以下**硬条件**（全部写入 task Gate）：

1. **CLI 仅 Claude + OpenCode**；禁 codex/copilot/kimi/cursor/antigravity（硬编码 bypass=fork）。OpenCode 优先（声明式权限）。
2. **禁用 `first_setup.sh`**；消费不可变制品（tree+预建 venv+settings）+ 宿主预置依赖校验；运行期零公网。
3. **单端点单活跃 Team**；`SHOGUN_QUEUE_DIR` 迁移队列；Adapter 排队其余 Team。
4. **权限**：Claude 恒传 `--permission-mode <受限>`、OpenCode 生成最小声明式权限；**永不用** `--dangerously-skip-permissions`。**shell/禁 push 无法上游表达** → 工作区收敛（§7.2）+ 文档标注残余风险（用户已裁决接受）。
5. **无 worktree** → 阶段一按**互斥 allowed_paths** 划分工作包；两 Worker 不碰同文件；合并仅一 Integration 角色；push 默认禁（不发 push 凭据）。
6. **Skillify 外部施加并发治理**（formation 大小=max_active_workers；模型并发经端点/网关限流+喂任务节奏；`max_team_duration` 由 Adapter 看门狗超时 kill）。
7. **单一共享内网模型端点**（启动前全局 env）。
8. **Adapter 只读稳定队列 YAML 契约**（防御式：双读 status、容忍多余字段、断言 canonical 文件名）；写 inbox 仅经 `scripts/inbox_write.sh`；映射标准 Team 事件；Outbox 幂等。
9. **固定 v5.2.0** 不可变制品；升级须过 schema-diff 测试与审批。
10. **Go/No-Go（brief §12）**：编码阶段只做 **Adapter 骨架 + FakeRuntime 契约**；`team` 上线前须在 [test-env] 过全部门禁；未过 `single/delegated` 不受影响，**不回退自研 Team**。

---

## 2. 目标架构与边界（略，见 brief §3；本计划边界补充）

### 2.1 Shogun Provider Adapter 契约（映射到既有 `AgentProvider`）
`runtime="shogun"`，实现 `probe/start/create_session/stream_events/cancel/stop`：
- `probe`：校验制品版本+SHA256；检查 `tmux/flock/inotify-tools/python3/od` + 目标 CLI；不可用→`ProviderProbe.available=False` + reason_code。
- `start`：为该 Task 建**隔离运行目录**（`SHOGUN_QUEUE_DIR=<run>/queue`），生成最小 `config/settings.yaml`（formation=preferred_cli、agents、内网 endpoint env、无 ntfy）+ OpenCode 声明式权限；headless 启动 `shutsujin_departure.sh -c --permission-mode <受限>`。强制单活跃 Team 守卫。
- `create_session`：把用户确认的 WorkPackage 转成入口任务写 `queue/shogun_to_karo.yaml`（经 `inbox_write.sh` 语义/原子写）。
- `stream_events`：inotify/fswatch 观察 `queue/{reports,inbox,tasks}`；双读 status；映射为标准 Team 事件（§3）。
- `cancel`/`stop`：kill-session(shogun,multiagent)+杀 supervisor+`pkill` watchers+清 `/tmp/shogun_*`+清运行目录+临时凭据；采集 report/diff/test/构件索引后归档。
- **禁**（brief §5.2）：自分解任务、决定 Worker 消息内容、重写队列/锁、向 pane 注入未验证 shell、解析人类 Dashboard 作机器接口、改队列伪造完成、Adapter 内实现角色循环、直接管模型上下文、把上游内部状态同步成第二套服务端编排状态机。

### 2.2 需改上游才能实现的能力（fork 边界，本阶段一律不做）
- 命令级/shell 权限、禁 push（上游无法表达）→ 工作区收敛替代。
- 同机多 Team、硬文件隔离(worktree)、per-Claude 独立端点、并发上限 → 外部治理/后续/上游贡献，不本地改源码。

---

## 3. WorkPackage 与事件 Schema

### 3.1 中立输入（brief §6，Skillify 不暴露武士主题词）
`execution.{mode: team, collaboration_runtime: shogun, preferred_cli: opencode|claude-code}` + `team_policy.{min_workers,max_active_workers,max_parallel_model_calls,max_team_duration_minutes,require_independent_review}` + `work_packages[].{id,objective,allowed_paths,depends_on,read_only,verification[]}`。UI 名称映射：Karo→Coordinator、Ashigaru→Worker、Gunshi→Reviewer（仅展示，不改上游标识）。

### 3.2 标准 Team 事件（brief §7）
`team.preparing/started`、`worker.started`、`work_package.assigned/blocked/started/completed`、`review.started/completed`、`team.waiting_approval/cancelling/cancelled/completed/failed`。字段：`event_id/task_id/runtime=shogun/worker_id?/work_package_id?/stage/summary(脱敏)/artifact_refs[]/occurred_at`。**禁上报**：模型 Key、Keycloak Token、MCP 凭据、完整环境变量、CLI 原始对话、老系统敏感数据、未脱敏上游 YAML。

---

## 4. KEEP / DELETE / MIGRATE / CREATE

### 4.1 DELETE
无（team 为纯增量）。**禁**复制 Shogun 源码；**禁**恢复自研 Team 通讯；**禁**用旧自研 Workflow Runtime 兜底。

### 4.2 KEEP（复用，禁破坏）
`runner.py` 选 Provider 接缝、`AgentProvider` 契约、`permissions.py`、`credentials/`（broker/identities/store）、`tasks/work_package.py`、`tasks/mcp_injection.py`、Outbox、endpoint pull/claim/lease/events。

### 4.3 CREATE / MIGRATE（精确路径）
```
+infra/offline/shogun-manifest.json                 # name/source(yohey-w/multi-agent-shogun)/version v5.2.0/commit 431b86a/license MIT/sha256/platform[linux-x86_64]；含"预建 venv + settings + 宿主依赖"清单
+src/skillify/agent/providers/shogun.py             # ShogunProvider 实现 AgentProvider（薄编排壳）
+src/skillify/agent/shogun/__init__.py
+src/skillify/agent/shogun/distribution.py          # 制品哈希校验 + 宿主依赖检查（禁 first_setup）
+src/skillify/agent/shogun/config_gen.py            # 生成 settings.yaml + opencode 声明式权限 + 入口 cmd + SHOGUN_QUEUE_DIR 运行目录
+src/skillify/agent/shogun/contract.py              # 队列 YAML 解析（双读 status、canonical 文件名、容忍多余字段）
+src/skillify/agent/shogun/lifecycle.py             # headless 启动 / cancel / cleanup（kill-session+supervisor+pkill+清/tmp）/ 单活跃 Team 守卫 / 看门狗超时
+src/skillify/agent/shogun/events.py                # 队列状态迁移 → 标准 Team 事件映射 + 脱敏
+src/skillify/agent/shogun/fake_runtime.py          # 离线 FakeRuntime：按脚本写队列 YAML，驱动契约测试
+src/skillify/agent/shogun/concurrency.py           # 外部并发治理：max_active_workers/模型并发限流/喂任务节奏/时长上限
 src/skillify/agent/runner.py                        # execution.mode=team → runtime=shogun 选 ShogunProvider，透传 team_policy/work_packages/preferred_cli
 src/skillify/agent/events.py                        # 新增 Team EventType + _DETAIL_KEYS 扩展(worker_id/work_package_id/stage)（增量、闭合 schema）
 src/skillify/workflows/pack_config.py               # 增 execution/collaboration_runtime/team_policy；work_packages 增 depends_on/read_only/verification
 src/skillify/tasks/work_package.py                  # 增 depends_on/read_only/verification 字段
 src/skillify/cli/doctor_cmd.py                      # 增 shogun 检查（版本/哈希/tmux/flock/inotify/python3），失败非阻断（team 不可用，single/delegated 继续）
+infra/dm8-init/09-team-tasks.sql                    # team 任务字段(mode/collaboration_runtime/preferred_cli/team_policy) + worker/work_package 事件记录；SQLite 镜像离线
 src/skillify/index/models.py                        # TeamTask/WorkerEvent 记录
 src/skillify/web/endpoint_agent_api.py              # team 模式创建 + 工作包确认 + Team/Worker 时间线接口
 web/src/views/EndpointTasksView.vue                 # 执行模式(single/delegated/team)选择 + 工作包确认 + Team/Worker 时间线(用 UI 映射名)
 web/src/lib/api.js                                  # team 字段 + 事件时间线
```
测试：`+tests/test_shogun_distribution.py`、`+tests/test_shogun_config_gen.py`、`+tests/test_shogun_contract.py`、`+tests/test_shogun_events.py`、`+tests/test_shogun_lifecycle.py`、`+tests/test_shogun_concurrency.py`、`+tests/test_shogun_provider_contract.py`（FakeRuntime 驱动）、`+tests/test_shogun_smoke.py`（[test-env]，默认 skip）。

---

## 5. 离线分发
- `shogun-manifest.json` 记 version/commit/sha256/license/platform；外网审核区下 tag tarball → 许可/依赖/shell 脚本/供应链审查 → 传 Forgejo Release → Skillify 只装批准版本。
- **制品内含**预建 `.venv`（或 pyyaml wheel）+ 预生成 `settings.yaml` 模板；**不含** `first_setup.sh` 执行路径、bats 子模块、Android。
- 运行期禁 `git clone/curl/npm/pip`；升级重走兼容+审批；不跟 `main`。

## 6. tmux / 进程生命周期
- 启动：headless `nohup shutsujin_departure.sh -c --permission-mode <受限>`（设 `SHOGUN_QUEUE_DIR`、内网 endpoint env、无 ntfy）。
- 取消/清理：kill-session(shogun,multiagent)→杀 `watcher_supervisor`→`pkill -f inbox_watcher.sh`/`ntfy_listener.sh`→清 `/tmp/shogun_*`→清运行目录。
- 恢复：Bridge 重启后经 `tmux has-session` + 读运行目录 `queue/` 重建状态，续报或安全终止（无单一 resume 命令，Adapter 重建）。
- 单活跃 Team 守卫：全局 tmux 名冲突 → 拒绝并发，排队。

## 7. 权限 / 凭据 / 网络
### 7.1 凭据（复用既有 Broker）
`settings.yaml`/任务 YAML/tmux 命令只出现 `credential_ref`；Token 由端侧 Broker 取；Adapter **不转发** Skillify Web Token 给上游；每 Worker 只装其工作包声明的 MCP；DB/业务 MCP 不默认全注入；CodeGraph 按需。
### 7.2 工作区收敛（shell 缺口的替代，用户已裁决接受）
OpenCode 声明式文件路径权限 + workspace `allowed_paths` 限可写 + 不发 push 凭据 + 网络 allowlist 默认 deny + Broker 不注入秘密到 worker env。**残余风险**：Worker 内可执行任意 shell（Shogun/CLI 固有）——文档明示，阶段一仅限受信内网用户本机；如需硬 shell 沙箱属后续 OS 级方案。
### 7.3 网络
禁 ntfy/Tailscale/公网通知；禁安装脚本联网；仅内网模型地址+Skillify 地址+工作包声明 MCP/API 目标；遥测/更新/插件自动安装关闭；allowlist=Skillify 策略 ∩ MCP Package。

## 8. 并发与内网模型保护（§9）
Adapter 外部施加：单端点最大并行 Team=1（阶段一）；单 Team 最大活动 Worker（=formation 大小）；单模型端点最大并发（端点/网关限流 + 喂任务节奏）；单用户并发任务；排队而非超限；429/503 退避；Worker 超时/失联检测；协调 Agent 提前结束的失败检测；空闲 Worker 零模型调用（上游天然）。**不得**演变成第二套编排器。

## 9. Bridge / Web / DM8 接线
Web 选 `team` + 确认工作包 → Bridge claim + 建隔离运行目录 → ShogunProvider 校验/生成配置/启动 → 事件转 Outbox 幂等上传 → Web 展示 Team/Worker 时间线(映射名)/测试/diff/构件。DM8 `09-team-tasks.sql` 为服务端真相源；Shogun 运行目录只经合法事件触发受控状态转换，**不得**直接覆盖服务端状态。

## 10. 失败路径（§10.2，尽量离线可测）
制品缺失/哈希不符、依赖缺失、CLI 未装/不兼容、内网模型不可达、Worker 未启动、Worker 卡死、依赖长期阻塞、两 Worker 文件冲突、拒权限、审批超时、Bridge 断网、重复 pull/event、取消、SIGTERM、遗留 tmux、Adapter 崩溃恢复、上游显示完成但验收命令失败、脱敏失败——每条产生明确事件；FakeRuntime + 临时目录 + SQLite 离线覆盖可测部分，真实进程/tmux/模型 → [test-env]。

## 11. 回滚
每 CREATE/MIGRATE 独立 commit 可单独 revert；`shogun-manifest.json`、`ShogunProvider`、DM8 `09` 独立；team 事件为 EventType 增量，回退不破坏既有事件；`execution.mode` 缺省 `single`，回退即 team 不可选。

## 12. Dev 验证与 [test-env] 门禁
- **本轮裁决覆盖**：2026-07-19 用户明确要求开发环境只做编译安全校验，因此本轮实际门禁为 Python `compileall`、关键模块静态装载、前端 `vue-tsc --noEmit` 与 `git diff --check`。下述 pytest/FakeRuntime 行为验证与所有真实环境门禁统一移交测试环境，不据此降低实现边界或提前启用 `team`。
- **Dev-DoD（Linux/Codex 离线）**：`uv run python -m compileall -q src`；`uv run pytest -q`（FakeRuntime/临时目录/SQLite）；`cd web && npm run type-check && npm test && npm run build`。安全不变量（凭据不落 YAML/日志/命令行/事件、Adapter 不改队列伪造、脱敏、单活跃守卫、cancel 清理逻辑）为 **dev_verified 硬门禁**。
- **[test-env]（brief §12 Go/No-Go）**：License/Offline/Linux/OpenCode formation/Claude formation/Lifecycle 无残留/Security 无 dangerous+凭据不泄/Events 幂等/Workspace 无互覆盖/Concurrency 可限/Recovery 重启续报。`team` 上线前全过；未过 `single/delegated` 继续，team 不可用，不回退自研 Team。

## 13. Non-Goals（brief §14）
不 fork/复制/重写 Shogun；不做服务器集群/沙箱；不引 LangGraph/CrewAI/AutoGen/Temporal/Ruflo/Metaswarm；不并存自研 Team Runtime；不把 Claude Agent Teams 作 team 第二实现；不让 OpenCode 伪装点对点；不强制所有任务升 team；不给所有 Worker 全 MCP；不启 ntfy/Tailscale；不暴露武士主题词；阶段一不支持任意数量/任意 CLI/任意模型混编；不 codex/copilot/kimi/cursor/antigravity。
