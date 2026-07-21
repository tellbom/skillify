# Shogun Team Runtime · Git-Worktree 并行开发任务清单（task）

> 配套：`docs/2026-07-20-shogun-team-git-worktree-plan.md`。执行：Codex（顺序）。
> 状态三层：`implemented`（合入）· `dev_verified`（FakeRuntime+临时 Git 仓离线门禁）· `env_verified`（[test-env] 真实 bundle/tmux/内网模型）。
> 全局红线（每 Task 继承）：不 fork/改上游归档；不 UID/ACL/overlayfs/bind-mount/OS 文件锁；Worker 无远程 Git 凭据；越界不入 integration；Integration 唯一合并；不启用 Team 开关；`installable` 保持 `false`；无 dangerous；凭据不落 YAML/日志/命令行/事件。
> **编排边界（硬约束）**：Shogun 是唯一 Team formation/角色/队列/通信/任务分配/生命周期/恢复编排系统。本清单所有 Git 组件（`WorktreeManager`/`ScopeGate`/`IntegrationEngine`/`ReviewGate`/`worker_delivery`/`git_guard`）均为**无状态确定性工具**，由 `ShogunProvider` 在既有生命周期固定点、或由 Shogun **现有 pane** 调用。**禁**新增：Git Task/Workflow 实体、独立 Git Scheduler/Queue/Coordinator/Worker Runtime、独立 Integration/Reviewer Agent 调度器、第二套 Team 状态机、第二套 DB 真相源、独立于 Shogun recovery 的 Git 恢复流程。Integration 由现有主将/家老/指定现有 pane 承担；Reviewer 复用现有军师 pane。
> **端侧 DB 边界（硬约束）**：端侧不得直连 Skillify 正式 DM；端侧只经 HTTP 与服务端交互（`bridge_cmd.py:55-83`）。DM 只读仅经用户配置选择的按任务 MCP（`db_readonly/connector.py:205-218`，连接由 `SKILLIFY_MCP_DM8_*` 环境变量决定），且只指向测试库。本清单不得在端侧引入任何到正式 DM 的直连。
> 依赖：S0→S1→S2→S3→S4→S5→S6→S7→S8→S9→(S10)→S11。

---

## S0 · 源码核对与契约冻结（[test-env] 前置，只读）

- **目标**：用真实 `431b86a` 构件确认 worktree 方向的三个关键机制，冻结命名/策略/事件/恢复语义。
- **修改文件**：追加至 `docs/2026-07-20-shogun-431b86a-source-findings.md`（新章"Git-Worktree 可行性"）；无代码改动。
- **前置**：批准离线 bundle（manifest `intranetUri`）。
- **实现要求**：逐条给源码行号回答——
  1. `lib/cli_adapter.sh:130-154` 是否把 per-agent `env` 渲染进各 pane 命令（承载 `SKILLIFY_WORKER_ID/SKILLIFY_WORKTREE`）；
  2. 上游启动 `opencode`/`claude` 的**确切 argv**（`shutsujin_departure.sh:721-796`）是否含显式 project/cwd 参数（决定 launcher 是否需剥离/改写）；
  3. `TMUX_PANE`→agent 名的稳定映射（pane 标题 `:621-662`），作为身份识别兜底；
  4. 确认主入口/队列**不触发** `auto_merge_short_lived.sh`；
  5. 冻结：分支命名 `skillify/team/<team-id>/{integration,worker/<worker-id>}`、merge 策略 `--no-ff`、事件集（plan §7）、恢复语义（plan §8）。
  6. **编排/DB 边界确认**：核对本方案不引入 Git Scheduler/Queue/Coordinator/独立 Integration/Reviewer Agent；Integration 由现有主将/家老 pane、Reviewer 由现有军师 pane 承担；确认端侧无到 Skillify 正式 DM 的直连（`bridge_cmd.py:55-83` 仅 HTTP），DM 只读 MCP 连接由 `SKILLIFY_MCP_DM8_*` 用户配置选择、只指向测试库。
- **明确不做**：不改上游任何文件；不写代码；不引入第二套编排/队列/状态机/DB 真相源。
- **单元测试**：无（取证）。
- **Linux 集成测试**：在 test-env 解压只读副本核对。
- **失败条件**：机制 1 与 3 **均**不可用 → 标 `upstream-contribution-or-blocker`，停止后续、`installable` 保持 `false`、escalate。
- **完成证据**：findings 新章六问带行号；身份通道选定（主/备）。
- **commit**：`docs(team): freeze git-worktree contract from shogun source`

## S1 · TeamHandle 与持久化模型扩展

- **目标**：持久化模型承载 worktree registry、Worker branch/commit、integration/merge 状态，向后兼容现有 `TeamHandle`。
- **修改文件**：`src/skillify/agent/shogun/lifecycle.py:35-67`（`TeamHandle` 增可选 `team_id`、`base_commit`，保持 `from_dict` 对旧字段兼容）；`+src/skillify/agent/shogun/registry.py`（`WorktreeRegistry`、`MergePlan` dataclass + 原子读写）；`+tests/test_shogun_registry.py`。
- **前置**：S0。
- **实现要求**：`WorktreeRegistry{team_id, base_commit, repository_root, integration_branch, integration_worktree, workers:[{worker_id, branch, worktree, work_package_id, allowed_paths, worker_commit|None, state}]}`；`MergePlan{order:[worker_id], current|None, merged:[], conflict:bool, integration_head|None}`；原子写（`os.replace` + `0600`，参照 `lifecycle.py:55-60`）。
- **明确不做**：运行期 Git 状态不塞进 `WorkPackage`。
- **单元测试**：registry/merge-plan roundtrip；旧 `team-handle.json`（仅 session/run_dir）仍可 `read`。
- **Linux 集成测试**：无（纯数据）。
- **失败条件**：旧句柄不可读；写非原子。
- **完成证据**：roundtrip + 兼容断言绿。
- **commit**：`feat(team): add worktree and merge persistence model`

## S2 · WorktreeManager

- **目标**：确定性创建/校验/注册/恢复/清理 Worker 与 integration worktree，路径与分支防护。
- **修改文件**：`+src/skillify/agent/shogun/worktree.py`（`WorktreeManager`）；`+tests/test_shogun_worktree.py`。
- **前置**：S1。
- **实现要求**：`create(repository_root, base_commit, team_id, workers)`→对 integration+每 Worker `git -C <repo> worktree add <path> -b <branch> <base_commit>`，路径固定 `<state>/teams/<team_id>/worktrees/<name>`；写 owner marker（`.skillify-team-owner` 含 team_id+repo identity）；`inspect()` 对 `git worktree list --porcelain` 与 registry 核对；`cleanup()` 用 `git worktree remove --force` + `git worktree prune` + `git branch -D`，删前校验 owner marker+team_id+路径在 `<state>/teams/` 内。
- **明确不做**：禁 `rm -rf` worktree；禁触碰主工作区与非 Skillify worktree；禁 chmod/chown。
- **单元测试**（临时真 Git 仓）：两 worktree 独立目录+独立分支同 base；同名分支冲突拒绝；cleanup 后 `git worktree list` 无残留、无 `.git/worktrees` 元数据；owner-marker 不符时拒绝清理。
- **Linux 集成测试**：真仓 `worktree add/remove/prune` 无残留。
- **失败条件**：cleanup 遗留元数据；误删仓外路径；分支从非冻结 base 创建。
- **完成证据**：创建/校验/清理/防护全绿。
- **commit**：`feat(team): add git worktree manager`

## S3 · Pane Launcher 接入 worktree

- **目标**：每 Worker pane 在自己 worktree 内运行真实 CLI（独立 cwd/HOME/CLI 配置），保留凭据注入，不改上游归档。
- **修改文件**：`src/skillify/agent/shogun/credentials.py:117-141`（launcher 增 `os.chdir(SKILLIFY_WORKTREE)` + 设局部 Git 身份 + 按 S0 剥离/改写 project argv，再 `execve`）；`src/skillify/agent/shogun/config_gen.py:127-135,215-229`（per-agent 非密 env `SKILLIFY_WORKER_ID`/`SKILLIFY_WORKTREE`；credentials socket 应答按 pane→worker 返回该 Worker worktree 时同理）；`tests/test_shogun_credentials.py`、`tests/test_shogun_config_gen.py`。
- **前置**：S2、S0（身份通道）。
- **实现要求**：launcher 读 `SKILLIFY_WORKTREE`→`chdir`；`git config --local user.name/user.email`（`<worker-id>@skillify.local.invalid`）；socket 应答仍只含模型凭据（`credentials.py:78-85`），worktree 走非密 env，不混入 socket 明文。身份通道按 S0：主=per-agent env，备=socket 用 `TMUX_PANE`→worker 映射返回。
- **明确不做**：不把 worktree 路径当秘密；不改上游 send-keys；launcher 不引入远程 Git 凭据。
- **单元测试**：launcher 脚本含 chdir+局部 Git 身份+argv 改写；env dict 有 `SKILLIFY_WORKER_ID/WORKTREE` 且无秘密；无秘密快照断言仍绿。
- **Linux 集成测试**：真 tmux 下两 pane 分别落在各自 worktree（`pwd`/`git rev-parse --show-toplevel` 不同）。
- **失败条件**：pane 落在共享根；worktree 路径进日志/命令行以外的落盘文件混入秘密。
- **完成证据**：cwd 隔离 + 身份 + 无秘密断言绿。
- **commit**：`feat(team): route each worker pane into its worktree`

## S4 · Worker Git 交付协议

- **目标**：Worker 交付以本地 commit 为准，含 clean-worktree 门禁与 changed-files，禁 push。
- **修改文件**：`+src/skillify/agent/shogun/worker_delivery.py`（`collect_delivery(worktree, base_commit, branch)`）；`+src/skillify/agent/shogun/git_guard.py`（`.skillify-bin/git` wrapper 生成器）；`config_gen.py:226-229`（PATH 已前置 `.skillify-bin`，git wrapper 落此）；`+tests/test_shogun_worker_delivery.py`、`+tests/test_shogun_git_guard.py`。
- **前置**：S3。
- **实现要求**：交付要求（plan §Worker）——有效 commit、base 一致、worktree 干净（`git status --porcelain` 空或明确记为失败）、返回 `worker_commit`+changed-files（`git diff --name-status base..HEAD`）+测试摘要+已知风险；不改 integration 分支、不合并他人分支。git wrapper 拒 `push`/`remote set-url`/`remote add`/`config credential.*`（非零退出+审计事件），放行本地操作。
- **明确不做**：不靠提示词禁 push；不给远程凭据；不自动 push。
- **单元测试**：无 commit/base 不一致/worktree 不干净→交付判失败；git wrapper 拒远程写、放行本地 commit；changed-files 解析正确。
- **Linux 集成测试**：真仓 Worker commit→交付含 SHA/changed-files；`git push` 被 wrapper 拒。
- **失败条件**：脏 worktree 判成功；push 未被拒。
- **完成证据**：交付门禁 + push 拒绝 + 审计事件绿。
- **commit**：`feat(team): enforce worker local commit delivery and push denial`

## S5 · Allowed-path Diff Gate

- **目标**：合并前用 changed-files 强制越界拒绝，重叠告警。
- **修改文件**：`+src/skillify/agent/shogun/scope_gate.py`（`check(worker_commit, base_commit, allowed_paths, forbidden_paths)`）；`+tests/test_shogun_scope_gate.py`。
- **前置**：S4。
- **实现要求**：`actual = git diff --name-status base..worker_commit`；规范化路径（拒绝绝对路径、`..` 逃逸、symlink 逃逸）；`actual ⊆ allowed_paths` 且 ∩`forbidden_paths`=∅，否则 `scope_rejected`（**不静默删越界改动**）；跨 Worker changed-files 交集→高风险合并标记（进 merge-plan 顺序调整）。
- **明确不做**：不修改 Worker 分支内容；越界不"删掉后继续"。
- **单元测试**：越界文件→拒绝；干净子集→通过；两 Worker 同文件→高风险标记；绝对/逃逸路径→拒绝。
- **Linux 集成测试**：真仓越界 commit 被拒、integration 分支不受污染。
- **失败条件**：越界进入集成；路径逃逸未拦。
- **完成证据**：越界拒绝 + 重叠告警绿。
- **commit**：`feat(team): add changed-files scope gate`

## S6 · Integration Engine（现有 pane 调用的确定性 Git 工具）

- **目标**：为 Shogun **现有 integration 阶段**提供确定性 Git 合并工具（`--no-ff` 默认），冲突检测/恢复/abort，integration commit。**不新增 Integration Agent/调度器/生命周期。**
- **修改文件**：`+src/skillify/agent/shogun/integration.py`（`IntegrationEngine`，纯函数式，无自调度）；`+tests/test_shogun_integration.py`。
- **前置**：S5。
- **实现要求**：`IntegrationEngine` 是**无状态工具**，由 Shogun formation 中承担 integration 职责的**现有 pane**（主将 shogun / 家老 karo / 明确指定的现有 pane）在进入 integration 阶段时调用（经 Skill/命令），或由 `ShogunProvider` 在检测到 integration 阶段就绪时确定性执行并上报事件；**它不领任务、不建 Agent、不管队列/状态机**。逻辑：确认 base 未变→所有待合并分支基于该 base→按 `merge-plan.json` 顺序 `git merge --no-ff <worker-branch>`（声明单原子时 `cherry-pick`）；冲突→记录冲突文件/双方、置 `conflict`、交**该现有 integration pane** 解（**禁 `-X ours/theirs` 全量覆盖**）；每步更新 merge-plan（中断恢复）；合并后跑工作包/项目验收命令；产 `integration_commit`。
- **明确不做**：不启动脱离 formation 的 Integration Agent；不建独立 Integration 调度器/状态机；不让主 Agent"看目录没问题就结束"；不 `ours/theirs` 绕冲突；不跳验收。
- **单元测试**（临时真仓）：不同文件→自动合并；同行→冲突被记录且不静默选边；合并后验收命令被调用；merge-plan 每步落盘；`IntegrationEngine` 无任何任务领取/Agent 创建接口（结构断言：仅暴露纯合并方法）。
- **Linux 集成测试**：现有 integration pane 调用引擎完成三 Worker 真合并，冲突可解，integration commit 生成。
- **失败条件**：出现独立 Integration Agent/调度器；`ours/theirs` 覆盖；冲突未记录；验收被跳过。
- **完成证据**：合并/冲突/恢复/验收全绿 + 无独立调度断言绿。
- **commit**：`feat(team): add deterministic integration engine for shogun integration phase`

## S7 · Reviewer Gate（复用现有军师 pane）

- **目标**：为 Shogun **现有军师（gunshi）/Reviewer pane** 提供结构化审查校验与硬门禁；**不新增独立 Reviewer Agent/调度器**。
- **修改文件**：`+src/skillify/agent/shogun/review.py`（`ReviewGate`，只校验+硬门禁）；`src/skillify/agent/shogun/config_gen.py:179`（Reviewer 只读全仓保留）；`+tests/test_shogun_review.py`。
- **前置**：S6。
- **实现要求**：审查动作由现有 gunshi pane 执行并产出结构化结果；`ReviewGate` 只**校验该结构化审查结果并执行硬门禁**（plan §Reviewer 检查项：工作包 vs 实际改动一致、无越界 changed-files、同文件已处理、无遗漏 Worker、无 `ours/theirs`、最终 diff 无无关改动、测试覆盖、无未提交/生成物/Token/env/临时文件、integration commit 含全部批准改动、无远程凭据泄露），产 pass/reject/rework，不自绕门禁。Reviewer 与 Integration 分离**角色/pane**（沿用 formation 既有分工），非新增进程。
- **明确不做**：不启动独立 Reviewer Agent/调度器；ReviewGate 不改码、不合并、不再次拉起审查 Agent。
- **单元测试**：遗漏 Worker→reject；`ours/theirs` 痕迹→reject；干净集成→pass；产 `review.rejected`/`review.completed`；`ReviewGate` 结构断言：无 Agent 启动接口。
- **Linux 集成测试**：现有 gunshi pane 产出审查结果→ReviewGate 校验产正确结论。
- **失败条件**：出现独立 Reviewer Agent；Reviewer 兼任合并；reject 项被放行。
- **完成证据**：审查校验 + pass/reject 事件 + 无独立 Agent 断言绿。
- **commit**：`feat(team): add reviewer gate over existing gunshi pane`

## S8 · Bridge Recovery

- **目标**：重启后区分 live Team/已完成 Worker/合并中/损坏，防重复执行与重复合并。
- **修改文件**：`src/skillify/agent/providers/shogun.py:190-263 recover`（并入 worktree/merge 恢复）；`src/skillify/cli/bridge_cmd.py`（team 恢复接线）；`+tests/test_shogun_recovery.py`。
- **前置**：S2、S6。
- **实现要求**：按 plan §8——live（`is_alive`+worktree 一致→续报，不重建分支/不重执已 commit/不删在用 worktree）；completed-uncommitted-integration（读 `worker_commit`→入待集成，不重执）；merge-interrupted（读 merge-plan + 检 `.git/worktrees/<wt>/MERGE_HEAD`/`CHERRY_PICK_HEAD`→续或 abort，不重复 apply）；corrupt→安全失败保留取证（`task.failed` reason_code=`team-state-corrupt`）。
- **明确不做**：不自动猜测重执整个 Team；不重复 apply commit；**不新增独立于 Shogun recover 的 Git 恢复工作流**——worktree/merge 恢复必须并入现有 `ShogunProvider.recover`。
- **单元测试**：Worker 后重启不重执；合并中重启检测 `MERGE_HEAD` 并安全续/abort；损坏→failed 保留取证。
- **Linux 集成测试**：真 tmux+真仓四场景恢复。
- **失败条件**：重复执行/重复合并；损坏时乱猜重执。
- **完成证据**：四恢复分支绿。
- **commit**：`feat(team): recover worktree and merge state on restart`

## S9 · 清理与取证

- **目标**：Team 结束清理全部资源，先持久化结果与取证，保护用户仓。
- **修改文件**：`src/skillify/agent/shogun/lifecycle.py:228-243`（`cancel/stop/_release` 并入 worktree 清理）；`src/skillify/agent/providers/shogun.py:294-312`；`+tests/test_shogun_cleanup.py`。
- **前置**：S2、S8。
- **实现要求**：清理 tmux/socket/短期凭据/Worker HOME/Agent 配置/临时日志/**worktree（`git worktree remove/prune` + `git branch -D`）**；清理前确保 commit SHA/diff 摘要/审计事件已落盘；失败保留脱敏取证（可配置保留期）；owner marker+team_id+repo identity+路径校验后才删；worktree 清理失败→记录 `worktree.cleaned` 失败事件供人工恢复。
- **明确不做**：不 `rm -rf` worktree；不删用户仓/非 Skillify worktree。
- **单元测试**：清理后无 worktree/分支/socket 残留；owner 不符不删;清理失败有事件。
- **Linux 集成测试**：真仓取消后 `git worktree list`/`tmux ls`/`pgrep` 全净，主工作区未变。
- **失败条件**：残留 worktree 元数据/进程/凭据；误删仓。
- **完成证据**：清理无残留 + 仓保护绿。
- **commit**：`feat(team): clean up worktrees and forensics on team end`

## S10 · 真实 formation 测试（[test-env]，默认 skip 占位）

- **目标**：真机十场景验收。
- **修改文件**：`tests/test_shogun_smoke.py`（解 skip）；`docs/testing/2026-shogun-team-e2e-checklist.md`（Git-Worktree 段）。
- **前置**：S1–S9。
- **[test-env] 覆盖**（真实 Git 仓，禁假仓最终结论）：①不同文件→独立 worktree+自动合并+全测过；②同文件不同区→无磁盘覆盖+高风险提示+集成过；③同行→冲突显式+记录进 TaskEvent+不静默选边；④越界→分支留证+Gate 拒+integration 不污染；⑤push→wrapper 拒+本地 commit 不受影响+审计事件；⑥Worker 后重启→恢复 worktree/branch/commit 不重执；⑦合并中重启→检测未完成 merge 安全续/abort 不重复 apply；⑧取消→停 Agent+清 tmux/凭据+留 Git 取证+worktree 元数据清+主工作区不变；⑨语义冲突→Git 自动合并但全测失败→不标成功；⑩主工作区脏→默认拒启+不 stash/reset。
- **完成证据**：checklist 逐项 + 无秘密日志审计 + 无残留证据。
- **commit**：`test(team): git-worktree formation e2e checklist`
- **状态**：env_verified

## S11 · TP-13 Gate 更新

- **目标**：门禁与文档收敛，明确启用前置。
- **修改文件**：`docs/2026-07-20-shogun-tp13-direction.md`（记录采纳 worktree 方向与结论）；`docs/testing/2026-07-17-post-ba3-test-environment-handoff.md` 6.4（更新 TP-13 下一步）；`infra/offline/shogun-manifest.json`（`hostDependencies` 增 `git`；`installable` 仍 `false`）；`src/skillify/agent/shogun/distribution.py:16`（增 `git`）。
- **前置**：S10。
- **实现要求**：只有 brief §12 全门禁 + Workspace（worktree 隔离）+ 新增（越界/冲突/恢复/清理/push 拒绝）真机通过 + 集中 hardening 后，才由负责人评估 `installable=true` 与两开关。
- **明确不做**：Codex 不擅自置 `installable=true`/开开关。
- **单元测试**：`distribution` git 依赖检查项。
- **Linux 集成测试**：doctor 显示 git 依赖状态。
- **失败条件**：门禁未过即翻转 installable/开关。
- **完成证据**：文档/manifest/依赖更新 + 门禁清单挂接证据。
- **commit**：`docs(team): update tp-13 gates for git-worktree runtime`

---

## 执行看板
- [x] S0 契约冻结　- [x] S1 持久化　- [x] S2 WorktreeManager　- [x] S3 Launcher 接 worktree　- [x] S4 Worker 交付　- [x] S5 Scope Gate
- [x] S6 Integration　- [x] S7 Reviewer　- [x] S8 Recovery　- [x] S9 清理　- [x] S10 真机 formation（主干路径，详见 plan §19；10 场景未全覆盖）　- [ ] S11 Gate 更新

> 安全不变量（dev_verified 硬门禁）：无 dangerous；凭据/远程 Git 凭据不落 YAML/日志/命令行/事件；Worker 独立 worktree 无磁盘覆盖；越界不入 integration；Integration 唯一合并；Bridge 不重复执行/合并；结束无 worktree/tmux/凭据/进程残留；主工作区不被修改。`team` 未过 [test-env] 门禁前保持不可用，`installable=false`，两开关关闭。
