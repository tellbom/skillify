# Shogun Team Runtime · Git-Worktree 并行开发方向落地计划（plan）

> 类型：**实施落地计划**（配套 `docs/2026-07-20-shogun-team-git-worktree-task.md`）。
> 前置：`docs/2026-07-20-shogun-tp13-direction.md`（方向评估）、`docs/2026-07-18-skillify-shogun-team-runtime-integration-brief.md`（上游裁决）、`docs/2026-07-20-shogun-431b86a-source-findings.md`（源码取证）。
> 已裁决方向：**每 Worker 独立 Git worktree + 独立本地分支 + Integration 唯一集成**。放弃"共享工作树逐 Worker 强制 allowed_paths"。
> 红线：不 fork 上游、不换框架、不改上游归档、不启用 Team 开关、`installable` 保持 `false`、**不依赖 Linux UID/ACL/overlayfs/bind-mount/系统文件锁**、用户无 root。
> 每项设计对应真实文件/类/函数/表/事件；不写泛化架构文章。

---

## 0. 单一工作流与编排边界（本方案最高约束）

**本方案不是新增一套 Git Workflow Runtime。** Shogun 仍是**唯一**的 Team formation、角色、队列、通信、任务分配、生命周期与恢复编排系统。Git worktree/branch/commit/diff/merge **只作为 Shogun Team 执行过程中的工作区隔离、交付留痕与集成机制**，由 Shogun 现有阶段与现有 pane 调用。

**不得新增（硬约束）：**
- Git Task / Git Workflow 业务实体；
- 独立 Git Scheduler / Git Queue / Git Coordinator / Git Worker Runtime；
- 独立 Integration Agent 调度器 / 独立 Reviewer Agent 调度器；
- 第二套 Team 状态机；第二套数据库任务真相源；
- 独立于 Shogun recovery 的 Git 恢复工作流。

**组件定性（全部为无状态确定性工具/库，非 runtime/agent/scheduler）：**
- `WorktreeManager`、`ScopeGate`、`IntegrationEngine`、`ReviewGate`、`worker_delivery`、`git_guard` 都是**纯函数式 Git 工具**，由 `ShogunProvider`（适配层）在 Shogun 现有生命周期的固定点调用，或由 Shogun formation 中**现有 pane** 调用；它们**不领任务、不建 Agent、不管独立生命周期、不建队列/状态机**。
- **Integration 职责**由 Shogun formation 中**现有**的主将（shogun/lord）、家老（karo）或明确指定的**现有 pane** 承担；`IntegrationEngine` 只是该 pane 在 integration 阶段调用的确定性 Git 合并工具，**不额外启动脱离 formation 的 Integration Agent**。
- **Reviewer 复用**当前 Shogun formation 已有的**军师（gunshi）/Reviewer pane**；`ReviewGate` 只校验结构化审查结果并执行硬门禁，**不再启动独立 Reviewer Agent**。
- **恢复**并入现有 `ShogunProvider.recover`（`providers/shogun.py:190-263`），worktree/merge 状态只是其读取的附加运行期文件；**不新增独立 Git 恢复流程**。
- **真相源**：DM8 仍是唯一服务端任务真相源（brief §7.1）；`worktree-registry.json`/`merge-plan.json` 仅是 Shogun 运行目录内的运行期工作文件，不构成第二真相源。

**端侧数据库边界（核实结论，硬约束）：**
- **端侧不得直连 Skillify 项目的正式环境 DM 数据库。** 端侧（Bridge）只经 HTTP 与服务端交互（`src/skillify/cli/bridge_cmd.py:55-83`：`/api/endpoint/tasks/pull`、`/confirm`、事件上报），**端侧无任何 DM 驱动/连接**，服务端 DM8 作为真相源仅由服务端访问。
- DM 只读能力是**独立的按任务 MCP**（`src/skillify/mcp/db_readonly/connector.py:205-218 create_configured_server`），其连接目标**完全由环境变量/配置决定**（`SKILLIFY_MCP_DM8_HOST/PORT/USER/PASSWORD/TABLES`），**由用户在配置方案中选择连接哪一个数据库**，且**只能指向测试环境数据库**；不得隐式指向本项目正式 DM。凭据经 Credential Broker `credential_ref` 注入，不落配置/日志。
- 本方案（Git worktree）**不得**在端侧引入任何到 Skillify 正式 DM 的直连；Team 运行状态一律经既有 HTTP 事件/Outbox 上报，DM8 由服务端写入。

---

## 1. 当前代码事实与上游限制（核实结论）

**已实现（Codex S9，读现行源码确认）：**
- `src/skillify/agent/shogun/config_gen.py:33-66 _project_runtime`：把只读 bundle 硬链接投影进 per-task `run_dir`（排除 `config/queue/logs/dashboard.md`），上游 `$SCRIPT_DIR` 落在隔离目录。`:198-218` per-task 隔离 `HOME`；`:226-229` `PATH` 前置 `.skillify-bin`。
- `src/skillify/agent/shogun/lifecycle.py:35-67 TeamHandle(session, run_dir)` 可序列化；`:115-124 is_alive` 用 `tmux has-session`；`:126-134 terminate`/`:139-158 cleanup_processes` 按 run_dir 内 `/proc/*/cwd` 结束进程；`:203-209` 单活守卫为 `O_CREAT|O_EXCL` 标记文件（**非 flock，无需 root**）。
- `src/skillify/agent/shogun/credentials.py:117-141 _write_launcher`：Python launcher 连 `0600` Unix Socket 取短期模型凭据后 `os.execve` 真实 CLI；`:87-115` 用 `SO_PEERCRED`+peer cwd 校验；`:126` launcher 已上报 `TMUX_PANE`。
- `src/skillify/agent/providers/shogun.py`：`start`（:92-151）建凭据通道+生成配置+启动；`recover`（:190-263）从 `team-handle.json`/`provider-state.json` 重认；`stream_events`（:265-292）扫队列映射事件。
- `src/skillify/agent/runner.py:63-143`：shogun 走 `recover()`；`:27-43 _reported_type` 透传 `team./worker./work_package./review.` 前缀事件。
- 数据层 `infra/dm8-init/09-team-tasks.sql`：`endpoint_team_tasks`、`endpoint_team_worker_events`（含 `event_id/worker_id/work_package_id/stage/summary`）、`endpoint_work_packages` 增列。
- `src/skillify/cli/bridge_cmd.py:270-284 start_spec`：team 的 `ProviderStartSpec` 由 `workspace`（仓库 alias 解析）、`config_dir=cache_dir/shogun/<task_id>` 构建。

**上游 `431b86a` 限制（findings 已核实）：**
- 入口 `shutsujin_departure.sh:16-28` 以脚本目录为根，`:551-552,578` 固定会话 `shogun`/`multiagent` 不可配置；starter 建会话后退出。
- pane 经 `tmux send-keys`（`:621-662,721-796`）启动 CLI；`lib/cli_adapter.sh:130-154` 渲染 per-agent `env` 为命令前缀（**可承载非密 worker 标识，不可承载秘密**）。
- `scripts/build_instructions.sh` 把所有 `ashigaruN` 折叠到单一 `ashigaru` 角色、只读 `read_allow/read_deny/edit_allow/edit_deny`——**上游权限模型无法表达 per-Worker 写隔离**。
- 无 `git worktree`；`scripts/auto_merge_short_lived.sh:92-118` 操作共享树，但主入口不调用它（findings Q4）。

## 2. 新方向 vs 旧方向

| 维度 | 旧（S9 隐含） | 新（本计划） |
|---|---|---|
| Worker 磁盘隔离 | 共享工作树 + 逐 Worker allowed_paths | **每 Worker 独立 worktree**（`git worktree add`） |
| 隔离依赖 | 上游权限渲染（已证不可行） | **Git 分支/worktree**，与上游权限无关 |
| 覆盖冲突 | 靠"不越界"约定 | 物理不同目录，杜绝磁盘覆盖 |
| 文本冲突 | 事后发现 | merge/cherry-pick 显式暴露 |
| 合并 | 主 Agent 看共享目录 | Skillify 确定性 merge 引擎 + Integration Agent 解语义冲突 |
| 越界检测 | 无强门禁 | 合并前 `git diff --name-status` ⊆ allowed_paths 强门禁 |
| allowed_paths 定性 | 声称文件系统隔离（错误） | 拆分/提示/合并前门禁/审计依据（**非硬安全边界**） |

## 3. 目标架构

**两套目录，职责分离：**
- **Shogun 运行投影** `run_dir = <cache>/shogun/<task_id>/`（现有 `config_gen._project_runtime`）：tmux/pane/queue/launcher/凭据 socket/隔离 HOME。
- **目标仓 worktree 集** `<state>/teams/<team_id>/worktrees/{integration,worker-1,worker-2}`：Worker 实际改码处，均从冻结 `base_commit` 创建，共享目标仓 `.git`。

```
<state>/teams/<team-id>/
├── worktrees/{integration, worker-1, worker-2}
├── metadata/{team-handle.json, worktree-registry.json, merge-plan.json, recovery-state.json}
└── logs/
```

**分支命名（冻结）：** `skillify/team/<team-id>/integration`、`skillify/team/<team-id>/worker/<worker-id>`。所有 Worker 与 integration 分支**均从同一 `base_commit`** 创建。

**pane→worktree 绑定：** `config_gen` 为每个 `ashigaruN` 写 per-agent 非密 env `SKILLIFY_WORKER_ID`/`SKILLIFY_WORKTREE`（经 `cli_adapter.sh:130-154` 渲染）；launcher 读取后 `os.chdir(worktree)` 并设局部 Git 身份，再 `execve` 真实 CLI。

## 4. Git 生命周期

1. **claim**：冻结 `base_commit = git -C <workspace> rev-parse HEAD`（若主工作区有未提交改动→按 §12 裁决默认拒绝启动）。
2. **prepare**（`ShogunProvider.start`，`generate_config` 后、`lifecycle.start` 前）：为 integration + 每个 Worker `git worktree add <path> -b <branch> <base_commit>`；写 `worktree-registry.json`。
3. **execute**：各 pane 在自己 worktree 内工作，Worker 本地 commit 到自己分支；禁 push（git wrapper）。
4. **deliver**：Worker 交付契约（§Worker）满足→进入待集成队列，记录 `worker_commit`。
5. **scope-gate**：`git diff --name-status base..worker_commit` ⊆ `allowed_paths`，越界→拒绝该 Worker。
6. **integrate**：Skillify 确定性引擎按序 merge/cherry-pick 到 integration 分支，冲突交 Integration Agent 解，禁 `ours/theirs` 全量覆盖。
7. **verify**：integration 分支跑全量测试/类型/lint/build/验收命令（发现语义冲突）。
8. **review**：独立 Reviewer 审最终集成 diff。
9. **finalize**：生成 `integration_commit`；阶段一**只出本地 integration commit，不自动 push**（§Git 凭据边界）。
10. **cleanup**：`git worktree remove`/`prune` + `git branch -D`（§清理）。

## 5. 状态模型

Team 状态（`endpoint_team_tasks.state`）：`pending → preparing → running → integrating → reviewing → (completed|failed|cancelled)`。
Worker 交付子状态（registry）：`assigned → running → committed → scope_rejected|delivered → merged|conflict|skipped`。
Merge 状态（`merge-plan.json`）：`pending → in_progress(worker=X) → (merged|conflict) → resolved`，支持中断恢复。

## 6. 数据模型变更（expand-only）

- `src/skillify/agent/provider.py:63 ProviderStartSpec`：新增 `base_commit: str = ""`、`repository_root: Path | None = None`（默认取 `workspace`）；`__post_init__` 校验 team 模式下 `base_commit` 为 40 位 hex。
- `src/skillify/cli/bridge_cmd.py:270-284 start_spec`：team 分支冻结 `base_commit` 并传入；`:294-299` ShogunProvider 构造补 `credential_broker`（现缺，凭据通道会失败）。
- `src/skillify/tasks/work_package.py:18 WorkPackage`：新增可选 `forbidden_paths`、`required_tests`（复用 `verification`）、`expected_artifacts`、`completion_criteria`（均可选，向后兼容 `from_dict/to_dict`）。运行期 Git 状态（branch/worktree/commit）**不入 WorkPackage**，入 `worktree-registry.json`。
- `infra/dm8-init/10-team-git-worktree.sql`（新增，expand-only）：`endpoint_team_tasks` 增 `base_commit VARCHAR(64)`、`integration_branch VARCHAR(200)`、`integration_commit VARCHAR(64)`；`endpoint_team_worker_events` 增 `worker_commit VARCHAR(64)`、`changed_files_count INT`、`conflict_files_count INT`。

## 7. TaskEvent 变更

`src/skillify/agent/events.py`：
- `EventType`（:29-51）新增：`WORKTREE_CREATED="worktree.created"`、`WORKER_COMMITTED="worker.committed"`、`WORK_PACKAGE_SCOPE_REJECTED="work_package.scope_rejected"`、`INTEGRATION_STARTED="integration.started"`、`INTEGRATION_MERGE_CONFLICT="integration.merge_conflict"`、`INTEGRATION_MERGE_RESOLVED="integration.merge_resolved"`、`INTEGRATION_TESTED="integration.tested"`、`REVIEW_REJECTED="review.rejected"`、`WORKTREE_CLEANED="worktree.cleaned"`。
- `_DETAIL_KEYS`（:12-16）新增标量键：`base_commit`、`worker_commit`、`integration_commit`、`branch`、`changed_files_count`、`conflict_files_count`（均标量；**changed-files 明细不入 details（闭合标量 schema），走 artifact ref/summary**）。
- `src/skillify/agent/runner.py:27-43 _reported_type`：透传前缀增 `integration.`、`worktree.`。
- `src/skillify/tasks/reporting.py:87 build_task_event`：新增可选参数与 payload 键 `baseCommit/workerCommit/integrationCommit/branch/changedFilesCount/conflictFilesCount`；沿用 `_IDENTIFIER` 校验 SHA/分支名格式。
- `src/skillify/agent/shogun/events.py TeamEventMapper`：从 registry/merge-plan 变迁产出上述事件（保持幂等 `_seen`、脱敏）。

## 8. Bridge 重启恢复

扩展 `ShogunProvider.recover`（`providers/shogun.py:190-263`）+ 新 `WorktreeManager.inspect`：
- **Team 仍执行**：`is_alive` 真 + `git worktree list` 与 registry 一致 → 续报，不重建同名分支、不重执已 commit 工作包、不删在用 worktree。
- **Worker 已完成未集成**：读 `worker_commit`、校验 worktree 干净 → 入待集成队列，不重复执行。
- **合并中崩溃**：读 `merge-plan.json` + 检测 `.git/worktrees/<wt>/MERGE_HEAD`/`CHERRY_PICK_HEAD` → 安全续做或 `git merge --abort`/`cherry-pick --abort`，不重复应用同一 commit。
- **状态损坏**（分支/worktree/base/registry/tmux 不一致）→ 安全失败保留取证，不自动猜测重执整个 Team（发 `task.failed` reason_code=`team-state-corrupt`）。

## 9. Credential Broker 与 Git 凭据边界

- 模型凭据：沿用 `PaneCredentialInjector`（socket 注入，`credentials.py`），**扩展 launcher 同时做 chdir+Git 身份+argv 改写**，不改注入信道。
- Git 远程凭据：**Worker/Coordinator/Reviewer 环境一律不含** Forgejo/GitHub token、SSH key、`SSH_AUTH_SOCK`、`GIT_ASKPASS`、远程账号密码。
- 强制手段（非提示词）：`.skillify-bin/git` wrapper 拒 `push`/`remote set-url`/`remote add`/`config credential.*`，发安全审计事件；worktree remote 可选临时置为不可写占位。
- 仅 Integration 在通过全部门禁后，经**单独审批的最小权限凭据**才可远程 push；**阶段一默认只出本地 integration commit，由现有发布流程/人工确认后推送**。

## 10. allowed_paths 新定位

保留但**重定性为**：①工作拆分边界 ②Agent 提示/上下文约束 ③OpenCode per-pane 权限辅助（`config_gen.py:170-189` 保留为**辅助**，非唯一机制）④合并前 changed-files 强门禁（**真正强制点**）⑤Reviewer 审计依据 ⑥重叠提前告警。**不再宣称阻止 Worker 进程读写其他绝对路径**（本轮无 OS 沙箱）。重叠不必然禁建 Team，但需工作包确认阶段提示 + 标记同文件 + 调整合并顺序 + 加强 Reviewer + 必要时串行化。

## 11. 冲突分类与处理

1. **磁盘覆盖**：独立 worktree 从物理上消除。
2. **Git 文本冲突**：merge/cherry-pick 显式暴露 → Integration Agent 解，记录冲突文件/双方/结果到事件，禁 `ours/theirs` 全量覆盖。
3. **语义冲突**（Git 自动合并成功但组合不兼容）：必须由 integration 分支上的全量测试/类型/build/lint/API 契约/DB 迁移检查 + Reviewer 发现；**"Git 无冲突"≠"集成正确"**。

**merge 策略裁决：** 采用 **`git merge --no-ff`**（保留 Worker 分支历史与多 commit，冲突暴露清晰，`.git/MERGE_HEAD` 支持中断恢复，审计可追溯 caller 分支）。cherry-pick 仅在工作包声明"单原子 commit 交付"且无跨 commit 依赖时用于压平；默认 `--no-ff merge`。依据：现事件模型按 `work_package_id`/`worker_id` 归因，`--no-ff` 保留分支祖先便于 Reviewer 追溯，且恢复语义（`MERGE_HEAD` 存在性）比 cherry-pick 序列更易判定。

## 12. 清理与取证

- 正常/取消/失败/超时后清理：tmux 会话、凭据 socket、pane 短期凭据、Worker HOME、Agent 配置、临时日志、**Worker worktree、integration worktree、本地临时分支**。
- 清理前保证：最终结果/commit SHA/diff 摘要/审计事件已持久化；失败保留脱敏取证；**不误删用户原始仓库、不误删非 Skillify worktree**。
- 强制：`git worktree remove` + `git worktree prune` + `git branch -D`（**禁 `rm -rf` 遗留 worktree 元数据**）；删除前校验 owner marker + `team_id` + 目标仓 identity + 路径位于 `<state>/teams/` 内；禁按模糊路径递归删。
- **主工作区裁决（场景10）：** claim 时若 `git -C <workspace> status --porcelain` 非空 → 默认拒绝启动 Team（reason_code=`workspace-dirty`）；Team 全程只从冻结 `base_commit` 建独立 worktree，**绝不 stash/reset/commit 用户原有改动**。

## 13. 离线与供应链影响

- `src/skillify/agent/shogun/distribution.py:16 REQUIRED_HOST_DEPENDENCIES` 增 `git`（worktree 依赖）；doctor 相应增项。
- `infra/offline/shogun-manifest.json`：`installable` 保持 `false`；`hostDependencies` 增 `git`。无新公网依赖（worktree 全本地 Git）。
- CodeGraph（Q10）阶段一：只对 `integration` worktree 或 `base_commit` 建**共享只读索引**，Worker 用执行器原生检索；不为每 Worker 独立索引（避免 N×索引开销）。

## 14. 测试矩阵

离线（FakeRuntime + 临时 Git 仓，`dev_verified`）与 [test-env]（真实 bundle/tmux/内网模型，`env_verified`）分层。10 场景（§16 S10）：不同文件/同文件不同区/同行冲突/越界/push 拒绝/Worker 后重启/合并中重启/取消/语义冲突/主工作区脏。**必须用真实 Git 仓库**，禁纯临时假仓做最终结论。

## 15. 分阶段 Gate

`S0 契约冻结 → S1 持久化模型 → S2 WorktreeManager → S3 Launcher 接 worktree → S4 Worker 交付协议 → S5 Scope Gate → S6 Integration 引擎 → S7 Reviewer Gate → S8 Recovery → S9 清理取证 → S10 真机 formation → S11 Gate 更新`。安全不变量（无 dangerous、凭据不落 YAML/日志/命令行/事件、Worker 无远程凭据、越界不入 integration、Integration 唯一合并、Bridge 不重复执行/合并、结束无残留）为 `dev_verified` 硬门禁。

## 16. 不做事项

不 fork/改上游归档；不换框架；不 UID/GID/ACL/overlayfs/bind-mount/OS 文件锁；不改现有仓文件 owner/group/chmod；不建 per-Worker Linux 用户；不给 Worker 远程 push 凭据；不自动 push（阶段一）；不 stash/reset 用户工作区；不启用 Team 开关；不置 `installable=true`；不恢复自研 Team 通讯/旧 Workflow Runtime；不追求对恶意本地 shell 的强安全沙箱。

**编排边界（见 §0）：** 不新增 Git Task/Workflow 实体、Git Scheduler/Queue/Coordinator/Worker Runtime、独立 Integration/Reviewer Agent 调度器、第二套 Team 状态机、第二套 DB 真相源、独立于 Shogun 的 Git 恢复工作流。`IntegrationEngine`/`ReviewGate` 只作为现有 pane（karo/gunshi 等）在既有阶段调用的确定性工具，不自行领任务/建 Agent/管生命周期。

**端侧 DB 边界（见 §0）：** 不在端侧引入到 Skillify 正式 DM 的任何直连；DM 只读只经用户配置选择的 MCP、且只指向测试库。

## 17. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| worker 身份注入通道不可用 | S0 主(per-agent env)+备(`TMUX_PANE`→worker 映射，socket 已收 pane) | 若均失败→NO-GO 保持 `installable=false` |
| 上游传显式 project 目录 argv | S0 抓确切 argv，launcher 改写/剥离 | 同上 |
| 上游 auto_merge 被触发 | S0 确认主入口/队列不触发；工作包不下发合并指令 | 禁用相关队列消息 |
| worktree 元数据残留 | `git worktree prune` + registry 校验 + owner marker | 人工 `git worktree repair` |
| 语义冲突漏检 | 强制全量测试/类型/build + Reviewer | Team 标 failed，不标成功 |
| 部署主机残留 `setup_cron.sh --install` 定时任务，`auto_merge_short_lived.sh` 每 6 小时对共享工作树自动合并，与 Integration 唯一合并假设冲突（S0 实测发现，`crontab -l` 本轮为空但机制客观存在） | S2/S11 doctor 增 `crontab -l` 探测 `auto_merge_short_lived` 关键字，命中即告警 | 人工 `crontab -e` 移除该行 |

回滚总原则：任一门禁未过→`single/delegated` 继续可用，`team` 不可用，两开关关闭，`installable=false`。

## 18. 对 S1–S9 的复用与修改

**直接复用：** 制品/manifest 校验、queue 契约（`contract.py`）、TeamHandle+is_alive+cleanup（`lifecycle.py`）、凭据 socket 注入信道（`credentials.py` 的 socket/broker 部分）、run_dir 投影+HOME（`config_gen._project_runtime`）、recover 骨架、DM8 team 表、bridge/web team 接线。
**需修改：** ①`config_gen` 增 per-agent `SKILLIFY_WORKER_ID/WORKTREE` env，`opencode-permissions` 降为辅助；②`credentials._write_launcher` 增 chdir+Git 身份+argv 改写；③`events`/`reporting`/DM8 增事件类型/详情键/列；④`provider.start` 建 worktree、`recover` 重建 worktree/merge 状态、`stream_events`/mapper 产新事件；⑤`ProviderStartSpec`/envelope/`start_spec` 增 `base_commit`/`repository_root`；⑥`distribution` 增 `git` 依赖；⑦bridge 构造 ShogunProvider 补 `credential_broker`。
**新增：** `WorktreeManager`、git wrapper、`IntegrationEngine`、`ScopeGate`、worktree/merge registries。
